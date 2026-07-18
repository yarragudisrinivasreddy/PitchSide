"""Deterministic stadium routing on a weighted, accessibility-aware graph.

Doctrine: *Gemini interprets, the graph computes.*  All navigation answers are
produced by Dijkstra's algorithm over an explicit venue model.  Every edge
carries a ``step_free`` flag so wheelchair users and families with strollers
receive routes that avoid stairs entirely, and a ``width_class`` so egress
planning can prefer wide concourses during peak crowd flow.

Walking-speed assumptions (documented, deterministic):

* Standard pedestrian: 1.2 m/s — mid-range of the 1.0–1.4 m/s design values in
  transport engineering guidance (TRB Highway Capacity Manual).
* Step-free/assisted travel: 0.9 m/s — conservative planning value for
  wheelchair users in crowded environments.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from app.exceptions import RoutingError

STANDARD_SPEED_MPS = 1.2
ACCESSIBLE_SPEED_MPS = 0.9

#: Edge width classes, from narrow stairwells to main concourses.
WIDTH_CLASSES = ("narrow", "standard", "wide")


@dataclass(frozen=True)
class Node:
    """A navigable point inside or around the stadium."""

    node_id: str
    name: str
    kind: str  # gate | concourse | section | amenity | transit
    zone: str


@dataclass(frozen=True)
class Edge:
    """A traversable connection between two nodes."""

    target: str
    distance_m: float
    step_free: bool = True
    width_class: str = "standard"


@dataclass
class RouteSegment:
    """One hop of a computed route, serialisable for API responses."""

    from_node: str
    to_node: str
    distance_m: float
    step_free: bool
    width_class: str

    def to_payload(self) -> dict:
        """Serialise the segment for JSON responses."""
        return {
            "from": self.from_node,
            "to": self.to_node,
            "distance_m": round(self.distance_m, 1),
            "step_free": self.step_free,
            "width_class": self.width_class,
        }


@dataclass
class VenueGraph:
    """Weighted undirected graph of the venue with Dijkstra routing."""

    nodes: dict[str, Node] = field(default_factory=dict)
    adjacency: dict[str, list[Edge]] = field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        """Register a node in the graph."""
        self.nodes[node.node_id] = node
        self.adjacency.setdefault(node.node_id, [])

    def connect(
        self,
        a: str,
        b: str,
        distance_m: float,
        step_free: bool = True,
        width_class: str = "standard",
    ) -> None:
        """Create a bidirectional edge between two registered nodes."""
        if a not in self.nodes or b not in self.nodes:
            raise RoutingError(f"Cannot connect unknown nodes '{a}' and '{b}'.")
        if width_class not in WIDTH_CLASSES:
            raise RoutingError(f"Unknown width class '{width_class}'.")
        self.adjacency[a].append(Edge(b, distance_m, step_free, width_class))
        self.adjacency[b].append(Edge(a, distance_m, step_free, width_class))

    def find_node(self, query: str) -> Node:
        """Resolve a node by id or case-insensitive name match."""
        key = query.strip()
        if key in self.nodes:
            return self.nodes[key]
        lowered = key.lower()
        for node in self.nodes.values():
            if node.name.lower() == lowered or node.node_id.lower() == lowered:
                return node
        raise RoutingError(f"Unknown location '{query}'.")

    def route(
        self, origin: str, destination: str, accessible: bool = False
    ) -> dict:
        """Compute the shortest path, optionally restricted to step-free edges.

        Returns a payload with ordered segments, total distance and a
        deterministic walking-time estimate.
        """
        start = self.find_node(origin)
        goal = self.find_node(destination)
        if start.node_id == goal.node_id:
            raise RoutingError("Origin and destination are the same location.")

        previous = self._dijkstra(start.node_id, goal.node_id, accessible)
        if goal.node_id not in previous:
            mode = "step-free " if accessible else ""
            raise RoutingError(
                f"No {mode}route exists between "
                f"'{start.name}' and '{goal.name}'."
            )

        segments = self._unwind(previous, start.node_id, goal.node_id)
        total = sum(segment.distance_m for segment in segments)
        speed = ACCESSIBLE_SPEED_MPS if accessible else STANDARD_SPEED_MPS
        return {
            "origin": start.name,
            "destination": goal.name,
            "accessible": accessible,
            "segments": [segment.to_payload() for segment in segments],
            "total_distance_m": round(total, 1),
            "eta_minutes": round(total / speed / 60.0, 1),
            "fully_step_free": all(segment.step_free for segment in segments),
        }

    def _dijkstra(
        self, start_id: str, goal_id: str, accessible: bool
    ) -> dict[str, tuple[str, Edge]]:
        """Shortest-path search returning the predecessor map."""
        distances: dict[str, float] = {start_id: 0.0}
        previous: dict[str, tuple[str, Edge]] = {}
        heap: list[tuple[float, str]] = [(0.0, start_id)]
        visited: set[str] = set()
        while heap:
            cost, current = heapq.heappop(heap)
            if current in visited:
                continue
            visited.add(current)
            if current == goal_id:
                break
            for edge in self.adjacency.get(current, []):
                if accessible and not edge.step_free:
                    continue
                candidate = cost + edge.distance_m
                if candidate < distances.get(edge.target, float("inf")):
                    distances[edge.target] = candidate
                    previous[edge.target] = (current, edge)
                    heapq.heappush(heap, (candidate, edge.target))
        return previous

    def _unwind(
        self,
        previous: dict[str, tuple[str, Edge]],
        start_id: str,
        goal_id: str,
    ) -> list[RouteSegment]:
        """Rebuild the segment list from Dijkstra's predecessor map."""
        segments: list[RouteSegment] = []
        cursor = goal_id
        while cursor != start_id:
            parent, edge = previous[cursor]
            segments.append(
                RouteSegment(
                    from_node=self.nodes[parent].name,
                    to_node=self.nodes[cursor].name,
                    distance_m=edge.distance_m,
                    step_free=edge.step_free,
                    width_class=edge.width_class,
                )
            )
            cursor = parent
        segments.reverse()
        return segments

    def zones(self) -> list[str]:
        """Return the sorted set of zones covered by the graph."""
        return sorted({node.zone for node in self.nodes.values()})


def build_default_venue() -> VenueGraph:
    """Construct the reference stadium model used by the application.

    The layout mirrors a typical FIFA World Cup 2026 venue bowl: four gates,
    a ring of concourses, seating sections, amenities and transit links.
    Stairs between concourse levels are deliberately modelled as
    ``step_free=False`` with parallel ramp/elevator edges so accessible
    routing always has a viable alternative.
    """
    graph = VenueGraph()
    nodes = [
        Node("gate_a", "Gate A", "gate", "north"),
        Node("gate_b", "Gate B", "gate", "east"),
        Node("gate_c", "Gate C", "gate", "south"),
        Node("gate_d", "Gate D", "gate", "west"),
        Node("conc_n", "North Concourse", "concourse", "north"),
        Node("conc_e", "East Concourse", "concourse", "east"),
        Node("conc_s", "South Concourse", "concourse", "south"),
        Node("conc_w", "West Concourse", "concourse", "west"),
        Node("upper_n", "North Upper Level", "concourse", "north"),
        Node("sec_101", "Section 101", "section", "north"),
        Node("sec_114", "Section 114", "section", "east"),
        Node("sec_127", "Section 127", "section", "south"),
        Node("sec_140", "Section 140", "section", "west"),
        Node("sec_201", "Section 201", "section", "north"),
        Node("food_n", "North Food Court", "amenity", "north"),
        Node("food_s", "South Food Court", "amenity", "south"),
        Node("medic_e", "East Medical Post", "amenity", "east"),
        Node("rest_w", "West Restrooms", "amenity", "west"),
        Node("metro", "Stadium Metro Station", "transit", "transit"),
        Node("shuttle", "Shuttle Bay", "transit", "transit"),
        Node("parking", "Parking Lot P1", "transit", "transit"),
    ]
    for node in nodes:
        graph.add_node(node)

    graph.connect("gate_a", "conc_n", 60, width_class="wide")
    graph.connect("gate_b", "conc_e", 55, width_class="wide")
    graph.connect("gate_c", "conc_s", 60, width_class="wide")
    graph.connect("gate_d", "conc_w", 55, width_class="wide")
    graph.connect("conc_n", "conc_e", 120, width_class="wide")
    graph.connect("conc_e", "conc_s", 120, width_class="wide")
    graph.connect("conc_s", "conc_w", 120, width_class="wide")
    graph.connect("conc_w", "conc_n", 120, width_class="wide")
    graph.connect("conc_n", "sec_101", 40)
    graph.connect("conc_e", "sec_114", 40)
    graph.connect("conc_s", "sec_127", 40)
    graph.connect("conc_w", "sec_140", 40)
    # Upper level: stairs (not step-free) plus a step-free elevator link.
    graph.connect("conc_n", "upper_n", 25, step_free=False, width_class="narrow")
    graph.connect("conc_n", "upper_n", 70, step_free=True, width_class="standard")
    graph.connect("upper_n", "sec_201", 35)
    graph.connect("conc_n", "food_n", 30)
    graph.connect("conc_s", "food_s", 30)
    graph.connect("conc_e", "medic_e", 25)
    graph.connect("conc_w", "rest_w", 20)
    graph.connect("gate_a", "metro", 200, width_class="wide")
    graph.connect("gate_c", "shuttle", 150, width_class="wide")
    graph.connect("gate_d", "parking", 250, width_class="wide")
    return graph
