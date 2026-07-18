"""Unit tests for the deterministic domain modules."""
# pylint: disable=attribute-defined-outside-init,too-few-public-methods
# pylint: disable=unnecessary-lambda,protected-access,unused-argument
# Rationale: standard pytest idioms — setup_method fixtures, minimal stub
# collaborators, and monkeypatch lambdas are intentional in test code.


from __future__ import annotations

import pytest

from app.domain import incident_rules
from app.domain.transit_planner import MODES, TransitPlanner
from app.domain.venue_graph import Node, VenueGraph, build_default_venue
from app.domain.zone_load import LEVEL_SCORES, ZoneLoadRegistry
from app.exceptions import RoutingError


# --------------------------------------------------------------------- #
# VenueGraph                                                             #
# --------------------------------------------------------------------- #


class TestVenueGraph:
    """Routing behaviour of the venue graph."""

    def setup_method(self) -> None:
        """Fresh default venue for each test."""
        self.graph = build_default_venue()

    def test_default_venue_has_expected_nodes(self):
        """Default venue has expected nodes."""
        assert "gate_a" in self.graph.nodes
        assert self.graph.nodes["sec_201"].kind == "section"

    def test_zones_are_sorted_and_unique(self):
        """Zones are sorted and unique."""
        zones = self.graph.zones()
        assert zones == sorted(set(zones))
        assert "north" in zones

    def test_find_node_by_id(self):
        """Find node by id."""
        assert self.graph.find_node("gate_a").name == "Gate A"

    def test_find_node_by_name_case_insensitive(self):
        """Find node by name case insensitive."""
        assert self.graph.find_node("gate a").node_id == "gate_a"

    def test_find_node_unknown_raises(self):
        """Find node unknown raises."""
        with pytest.raises(RoutingError):
            self.graph.find_node("Narnia")

    def test_route_basic_path(self):
        """Route basic path."""
        result = self.graph.route("Gate A", "Section 101")
        assert result["total_distance_m"] == pytest.approx(100.0)
        assert result["segments"][0]["from"] == "Gate A"
        assert result["segments"][-1]["to"] == "Section 101"

    def test_route_eta_uses_standard_speed(self):
        """Route eta uses standard speed."""
        result = self.graph.route("Gate A", "Section 101")
        assert result["eta_minutes"] == pytest.approx(100.0 / 1.2 / 60.0, abs=0.1)

    def test_accessible_route_uses_slower_speed(self):
        """Accessible route uses slower speed."""
        standard = self.graph.route("Gate A", "Section 101")
        accessible = self.graph.route("Gate A", "Section 101", accessible=True)
        assert accessible["eta_minutes"] > standard["eta_minutes"]

    def test_upper_level_standard_route_takes_stairs(self):
        """Upper level standard route takes stairs."""
        result = self.graph.route("North Concourse", "Section 201")
        assert result["fully_step_free"] is False
        assert result["total_distance_m"] == pytest.approx(60.0)

    def test_upper_level_accessible_route_avoids_stairs(self):
        """Upper level accessible route avoids stairs."""
        result = self.graph.route(
            "North Concourse", "Section 201", accessible=True
        )
        assert result["fully_step_free"] is True
        assert all(seg["step_free"] for seg in result["segments"])
        assert result["total_distance_m"] == pytest.approx(105.0)

    def test_same_origin_destination_raises(self):
        """Same origin destination raises."""
        with pytest.raises(RoutingError):
            self.graph.route("Gate A", "gate_a")

    def test_no_accessible_path_raises(self):
        """No accessible path raises."""
        graph = VenueGraph()
        graph.add_node(Node("a", "A", "gate", "z"))
        graph.add_node(Node("b", "B", "section", "z"))
        graph.connect("a", "b", 10, step_free=False)
        with pytest.raises(RoutingError):
            graph.route("a", "b", accessible=True)

    def test_connect_unknown_node_raises(self):
        """Connect unknown node raises."""
        graph = VenueGraph()
        graph.add_node(Node("a", "A", "gate", "z"))
        with pytest.raises(RoutingError):
            graph.connect("a", "ghost", 10)

    def test_connect_invalid_width_class_raises(self):
        """Connect invalid width class raises."""
        graph = VenueGraph()
        graph.add_node(Node("a", "A", "gate", "z"))
        graph.add_node(Node("b", "B", "gate", "z"))
        with pytest.raises(RoutingError):
            graph.connect("a", "b", 10, width_class="gigantic")

    def test_segments_expose_width_class(self):
        """Segments expose width class."""
        result = self.graph.route("Gate A", "North Food Court")
        assert {seg["width_class"] for seg in result["segments"]} <= {
            "narrow",
            "standard",
            "wide",
        }

    def test_route_prefers_shorter_path(self):
        """Route prefers shorter path."""
        result = self.graph.route("Gate A", "Gate B")
        assert result["total_distance_m"] == pytest.approx(235.0)


# --------------------------------------------------------------------- #
# ZoneLoadRegistry                                                       #
# --------------------------------------------------------------------- #


class TestZoneLoad:
    """Density scoring and wait-time behaviour."""

    def setup_method(self) -> None:
        """Fresh registry for each test."""
        self.registry = ZoneLoadRegistry()

    @pytest.mark.parametrize("level", sorted(LEVEL_SCORES))
    def test_levels_round_trip(self, level):
        """Levels round trip."""
        report = self.registry.record("north", level, timestamp=1000.0)
        assert report.level == level
        assert report.score == LEVEL_SCORES[level]

    def test_alias_levels_normalised(self):
        """Alias levels normalised."""
        assert self.registry.normalise_level("Medium") == "moderate"
        assert self.registry.normalise_level("PACKED") == "critical"

    def test_unknown_level_raises(self):
        """Unknown level raises."""
        with pytest.raises(ValueError):
            self.registry.normalise_level("apocalyptic")

    def test_density_unreported_zone_is_zero(self):
        """Density unreported zone is zero."""
        assert self.registry.density("nowhere") == 0.0

    def test_density_single_fresh_report(self):
        """Density single fresh report."""
        self.registry.record("north", "high", timestamp=1000.0)
        assert self.registry.density("north", now=1000.0) == pytest.approx(80.0)

    def test_density_decays_toward_newer_reports(self):
        """Density decays toward newer reports."""
        self.registry.record("north", "critical", timestamp=0.0)
        self.registry.record("north", "low", timestamp=1200.0)
        blended = self.registry.density("north", now=1200.0)
        assert 20.0 < blended < 50.0

    def test_density_equal_weights_average(self):
        """Density equal weights average."""
        self.registry.record("east", "low", timestamp=1000.0)
        self.registry.record("east", "high", timestamp=1000.0)
        assert self.registry.density("east", now=1000.0) == pytest.approx(50.0)

    def test_zone_names_are_normalised(self):
        """Zone names are normalised."""
        self.registry.record("  North  ", "high", timestamp=1000.0)
        assert self.registry.density("north", now=1000.0) > 0.0

    def test_report_cap_enforced(self):
        """Report cap enforced."""
        for index in range(80):
            self.registry.record("west", "low", timestamp=float(index))
        assert len(self.registry.reports["west"]) == 50

    @pytest.mark.parametrize(
        "density,expected",
        [(0.0, "quiet"), (30.0, "steady"), (55.0, "busy"), (90.0, "critical")],
    )
    def test_status_thresholds(self, density, expected):
        """Status thresholds."""
        assert self.registry.status_for(density) == expected

    def test_wait_minutes_known_answer(self):
        """Wait minutes known answer."""
        # density 50 -> 20 people; concession 3/min -> 6.7 minutes.
        assert self.registry.wait_minutes(50.0) == pytest.approx(6.7)

    def test_wait_minutes_scales_with_lanes(self):
        """Wait minutes scales with lanes."""
        single = self.registry.wait_minutes(80.0, "security", lanes=1)
        double = self.registry.wait_minutes(80.0, "security", lanes=2)
        assert double == pytest.approx(single / 2)

    def test_wait_minutes_unknown_amenity_uses_concession(self):
        """Wait minutes unknown amenity uses concession."""
        assert self.registry.wait_minutes(50.0, "mystery") == pytest.approx(6.7)

    def test_heatmap_sorted_busiest_first(self):
        """Heatmap sorted busiest first."""
        self.registry.record("north", "low", timestamp=1000.0)
        self.registry.record("south", "critical", timestamp=1000.0)
        heat = self.registry.heatmap(["north", "south"], now=1000.0)
        assert heat[0]["zone"] == "south"
        assert heat[0]["status"] == "critical"


# --------------------------------------------------------------------- #
# TransitPlanner                                                         #
# --------------------------------------------------------------------- #


class TestTransitPlanner:
    """Departure waves and carbon comparison."""

    def setup_method(self) -> None:
        """Fresh planner for each test."""
        self.planner = TransitPlanner()

    def test_available_modes_sorted(self):
        """Available modes sorted."""
        assert self.planner.available_modes() == sorted(MODES)

    def test_mode_plan_metro_known_answer(self):
        """Mode plan metro known answer."""
        plan = self.planner.mode_plan("metro", 7.0, 2)
        assert plan.co2_grams == pytest.approx(420.0)
        assert plan.duration_minutes == pytest.approx(12.0)

    def test_mode_plan_walk_zero_emissions(self):
        """Mode plan walk zero emissions."""
        assert self.planner.mode_plan("walk", 2.0, 1).co2_grams == 0.0

    def test_mode_plan_unknown_mode_raises(self):
        """Mode plan unknown mode raises."""
        with pytest.raises(ValueError):
            self.planner.mode_plan("teleport", 5.0, 1)

    def test_mode_plan_invalid_distance_raises(self):
        """Mode plan invalid distance raises."""
        with pytest.raises(ValueError):
            self.planner.mode_plan("metro", 0.0, 1)

    def test_mode_plan_invalid_party_raises(self):
        """Mode plan invalid party raises."""
        with pytest.raises(ValueError):
            self.planner.mode_plan("metro", 5.0, 0)

    def test_mode_plans_carry_source_urls(self):
        """Mode plans carry source urls."""
        plan = self.planner.mode_plan("car", 5.0, 1)
        assert plan.source.startswith("https://")

    def test_departure_wave_base_assignment(self):
        """Departure wave base assignment."""
        wave = self.planner.departure_wave("west", density=10.0)
        assert wave["wave_start_minutes_after_final_whistle"] == 30
        assert wave["deferred_due_to_congestion"] is False

    def test_departure_wave_deferred_when_congested(self):
        """Departure wave deferred when congested."""
        wave = self.planner.departure_wave("north", density=90.0)
        assert wave["wave_start_minutes_after_final_whistle"] == 15
        assert wave["deferred_due_to_congestion"] is True

    def test_departure_wave_unknown_zone_uses_last_wave(self):
        """Departure wave unknown zone uses last wave."""
        wave = self.planner.departure_wave("moonbase", density=0.0)
        assert wave["wave_start_minutes_after_final_whistle"] == 45

    def test_plan_orders_options_by_carbon(self):
        """Plan orders options by carbon."""
        plan = self.planner.plan("north", 10.0, 5.0, 1)
        emissions = [option["co2_grams"] for option in plan["options"]]
        assert emissions == sorted(emissions)
        assert plan["greenest_mode"] == "walk"

    def test_plan_flags_lowest_carbon_transit(self):
        """Plan flags lowest carbon transit."""
        plan = self.planner.plan("north", 10.0, 5.0, 1)
        assert plan["lowest_carbon_transit_mode"] == "metro"


# --------------------------------------------------------------------- #
# Incident rules                                                         #
# --------------------------------------------------------------------- #


class TestIncidentRules:
    """Severity matrix and dispatch actions."""

    def test_categories_have_full_action_matrix(self):
        """Categories have full action matrix."""
        for category in incident_rules.CATEGORY_BASE:
            for severity in ("P1", "P2", "P3"):
                assert (category, severity) in incident_rules.DISPATCH_ACTIONS

    def test_medical_baseline_is_p2(self):
        """Medical baseline is p2."""
        result = incident_rules.triage("medical", "a fan feels dizzy")
        assert result.severity == "P2"

    def test_medical_unconscious_is_p1(self):
        """Medical unconscious is p1."""
        result = incident_rules.triage("medical", "person is unconscious near gate")
        assert result.severity == "P1"
        assert "unconscious" in result.matched_keywords

    def test_security_weapon_is_p1(self):
        """Security weapon is p1."""
        result = incident_rules.triage("security", "someone has a knife")
        assert result.severity == "P1"

    def test_crowd_stampede_is_p1(self):
        """Crowd stampede is p1."""
        result = incident_rules.triage("crowd", "possible stampede forming")
        assert result.severity == "P1"

    def test_lost_item_baseline_is_p3(self):
        """Lost item baseline is p3."""
        result = incident_rules.triage("lost_item", "lost my scarf")
        assert result.severity == "P3"

    def test_facility_baseline_is_p3(self):
        """Facility baseline is p3."""
        result = incident_rules.triage("facility", "tap dripping slowly")
        assert result.severity == "P3"

    def test_negative_sentiment_escalates(self):
        """Negative sentiment escalates."""
        calm = incident_rules.triage("crowd", "queue building", 0.0)
        upset = incident_rules.triage("crowd", "queue building", -0.8)
        assert upset.score == calm.score + 10.0

    def test_positive_sentiment_never_escalates(self):
        """Positive sentiment never escalates."""
        calm = incident_rules.triage("crowd", "queue building", 0.9)
        assert calm.score == incident_rules.CATEGORY_BASE["crowd"]

    def test_score_capped_at_100(self):
        """Score capped at 100."""
        result = incident_rules.triage(
            "medical", "unconscious, not breathing, cardiac, bleeding child", -1.0
        )
        assert result.score == 100.0

    def test_alias_categories(self):
        """Alias categories."""
        assert incident_rules.normalise_category("Lost") == "lost_item"
        assert incident_rules.normalise_category("safety") == "security"

    def test_unknown_category_raises(self):
        """Unknown category raises."""
        with pytest.raises(ValueError):
            incident_rules.normalise_category("weather")

    def test_payload_shape(self):
        """Payload shape."""
        payload = incident_rules.triage("medical", "bleeding hand").to_payload()
        assert set(payload) == {
            "category",
            "severity",
            "score",
            "recommended_action",
            "matched_keywords",
        }
