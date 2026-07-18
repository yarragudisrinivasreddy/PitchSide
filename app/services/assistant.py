"""Match-day orchestration: intent → deterministic result → narrative.

The assistant owns the wiring between interpretation, the deterministic
domain modules, persistence, narration and translation.  Routes stay thin by
delegating here; every public method returns a JSON-serialisable dict.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from app.config import CITY_LEG_DESTINATION, CITY_LEG_ORIGIN, DEFAULT_LANGUAGE
from app.domain import incident_rules
from app.domain.transit_planner import TransitPlanner
from app.domain.venue_graph import VenueGraph, build_default_venue
from app.domain.zone_load import ZoneLoadRegistry
from app.exceptions import RoutingError, ValidationError
from app.services.archive import ArchiveVault
from app.services.cache import InsightCache
from app.services.city_routes import CityRoutesService
from app.services.composer import NarrativeComposer
from app.services.interpreter import IntentInterpreter
from app.services.ledger import EventLedger, build_ledger
from app.services.sentiment import SentimentLens
from app.services.translator import ResponseTranslator

T = TypeVar("T")

LOGGER = logging.getLogger(__name__)

OPS_CACHE_KEY = "ops:summary"


def _or_default(value: T | None, factory: Callable[[], T]) -> T:
    """Return the injected collaborator or build the production default."""
    return value if value is not None else factory()

#: Default assumptions when a transit query omits details.
DEFAULT_TRANSIT_DISTANCE_KM = 5.0
DEFAULT_PARTY_SIZE = 1


class MatchDayAssistant:
    """Coordinates all services behind the public API surface."""

    def __init__(
        self,
        graph: VenueGraph | None = None,
        registry: ZoneLoadRegistry | None = None,
        planner: TransitPlanner | None = None,
        ledger: EventLedger | None = None,
        interpreter: IntentInterpreter | None = None,
        composer: NarrativeComposer | None = None,
        translator: ResponseTranslator | None = None,
        city_routes: CityRoutesService | None = None,
        sentiment: SentimentLens | None = None,
        archive: ArchiveVault | None = None,
        cache: InsightCache | None = None,
    ) -> None:
        self.graph = _or_default(graph, build_default_venue)
        self.registry = _or_default(registry, ZoneLoadRegistry)
        self.planner = _or_default(planner, TransitPlanner)
        self.ledger = _or_default(ledger, build_ledger)
        self.interpreter = _or_default(interpreter, IntentInterpreter)
        self.composer = _or_default(composer, NarrativeComposer)
        self.translator = _or_default(translator, ResponseTranslator)
        self.city_routes = _or_default(city_routes, CityRoutesService)
        self.sentiment = _or_default(sentiment, SentimentLens)
        self.archive = _or_default(archive, ArchiveVault)
        self.cache = _or_default(cache, InsightCache)

    # ------------------------------------------------------------------ #
    # Deterministic feature entry points                                  #
    # ------------------------------------------------------------------ #

    def compute_route(
        self, origin: str, destination: str, accessible: bool
    ) -> dict:
        """Venue routing with optional step-free restriction."""
        return self.graph.route(origin, destination, accessible=accessible)

    def record_crowd_report(self, zone: str, level: str) -> dict:
        """Store a crowd report and return the refreshed zone view."""
        try:
            report = self.registry.record(zone, level)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        self.ledger.add_report(
            {"zone": report.zone, "level": report.level, "timestamp": report.timestamp}
        )
        self.cache.invalidate_prefix("ops:")
        density = self.registry.density(report.zone)
        return {
            "zone": report.zone,
            "level": report.level,
            "density": round(density, 1),
            "status": self.registry.status_for(density),
        }

    def record_incident(self, category: str, description: str) -> dict:
        """Triage and store an incident, returning the dispatch decision."""
        score = self.sentiment.score(description)
        try:
            result = incident_rules.triage(category, description, score)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        payload = result.to_payload()
        payload["sentiment_score"] = round(score, 2)
        self.ledger.add_incident(
            {**payload, "description": description, "timestamp": time.time()}
        )
        self.cache.invalidate_prefix("ops:")
        return payload

    def zone_heatmap(self) -> list[dict]:
        """Live density snapshot across all venue zones."""
        return self.registry.heatmap(self.graph.zones())

    def transit_plan(
        self, zone: str, distance_km: float, party_size: int
    ) -> dict:
        """Departure wave, carbon comparison and city leg for a zone."""
        try:
            density = self.registry.density(zone)
            plan = self.planner.plan(zone, density, distance_km, party_size)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        plan["city_leg"] = self.city_routes.city_leg(
            CITY_LEG_ORIGIN, CITY_LEG_DESTINATION, distance_km
        )
        return plan

    def ops_summary(self) -> dict:
        """Organizer dashboard summary, cached until the next write."""
        cached = self.cache.get(OPS_CACHE_KEY)
        if isinstance(cached, dict):
            return cached
        heatmap = self.zone_heatmap()
        incidents = self.ledger.open_incidents(limit=20)
        by_severity: dict[str, int] = {"P1": 0, "P2": 0, "P3": 0}
        for incident in incidents:
            severity = incident.get("severity", "P3")
            by_severity[severity] = by_severity.get(severity, 0) + 1
        actions = [
            f"Meter inbound flow to zone '{entry['zone']}'"
            for entry in heatmap
            if entry["status"] in ("busy", "critical")
        ]
        summary = {
            "zones": heatmap,
            "incidents_by_severity": by_severity,
            "open_incident_count": len(incidents),
            "recommended_actions": actions or ["No congestion actions required."],
        }
        self.cache.set(OPS_CACHE_KEY, summary)
        self.archive.archive_snapshot(summary)
        return summary

    # ------------------------------------------------------------------ #
    # Conversational entry point                                          #
    # ------------------------------------------------------------------ #

    def assist(self, message: str, persona: str, language: str) -> dict:
        """Full pipeline: interpret → compute → narrate → translate."""
        intent = self.interpreter.parse(message, persona)
        result = self._dispatch(intent)
        narrative = self.composer.compose(intent["intent"], result, persona)
        response = {
            "intent": intent["intent"],
            "source": intent["source"],
            "persona": persona,
            "language": language,
            "result": result,
            "guidance": narrative,
        }
        if language != DEFAULT_LANGUAGE:
            translated = self.translator.translate_json_values(response, language)
            if isinstance(translated, dict):
                response = translated
        return response

    def _dispatch(self, intent: dict) -> dict:
        """Route a parsed intent to its deterministic computation."""
        kind = intent["intent"]
        if kind == "route_request":
            return self._dispatch_route(intent)
        if kind == "crowd_report":
            zone = intent.get("zone") or "north"
            level = intent.get("level") or "moderate"
            return self.record_crowd_report(zone, level)
        if kind == "incident_report":
            category = intent.get("category") or "crowd"
            description = intent.get("description") or "Unspecified incident."
            return self.record_incident(category, description)
        # transit_query
        zone = intent.get("zone") or "north"
        return self.transit_plan(
            zone, DEFAULT_TRANSIT_DISTANCE_KM, DEFAULT_PARTY_SIZE
        )

    def _dispatch_route(self, intent: dict) -> dict:
        """Compute a route from a parsed intent with sensible defaults."""
        origin = intent.get("origin") or "Gate A"
        destination = intent.get("destination") or "Section 101"
        try:
            return self.compute_route(
                origin, destination, bool(intent.get("accessible"))
            )
        except RoutingError:
            return self.compute_route(
                "Gate A", "Section 101", bool(intent.get("accessible"))
            )

    def health(self) -> dict:
        """Per-service availability without failing the request."""
        return {
            "app": True,
            "vertex_ai": self.interpreter is not None
            and self.composer is not None
            and self._probe(getattr(self.interpreter, "_gateway", None)),
            "translate": self._probe(self.translator),
            "firestore": self._probe(self.ledger),
            "natural_language": self._probe(self.sentiment),
            "storage": self._probe(self.archive),
            "maps_routes": self._probe(self.city_routes),
            "secret_manager": True,
        }

    @staticmethod
    def _probe(service: object) -> bool:
        """Call ``is_healthy`` when available; absent probes read healthy."""
        probe = getattr(service, "is_healthy", None)
        if probe is None:
            return True
        return bool(probe())
