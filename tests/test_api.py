"""API endpoint tests: happy paths and boundary validation."""
# pylint: disable=attribute-defined-outside-init,too-few-public-methods
# pylint: disable=unnecessary-lambda,protected-access,unused-argument
# Rationale: standard pytest idioms — setup_method fixtures, minimal stub
# collaborators, and monkeypatch lambdas are intentional in test code.


from __future__ import annotations


class TestAssistEndpoint:
    """POST /api/assist."""

    def test_route_message_happy_path(self, client):
        """Route message happy path."""
        response = client.post(
            "/api/assist",
            json={"message": "How do I get from Gate A to Section 114?"},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["intent"] == "route_request"
        assert body["result"]["segments"]

    def test_accessible_route_message(self, client):
        """Accessible route message."""
        response = client.post(
            "/api/assist",
            json={"message": "Wheelchair route from Gate A to Section 201"},
        )
        body = response.get_json()
        assert body["result"]["fully_step_free"] is True

    def test_crowd_report_message(self, client):
        """Crowd report message."""
        response = client.post(
            "/api/assist",
            json={"message": "huge queue at gate b", "persona": "volunteer"},
        )
        body = response.get_json()
        assert body["intent"] == "crowd_report"
        assert body["result"]["status"] in ("quiet", "steady", "busy", "critical")

    def test_incident_message(self, client):
        """Incident message."""
        response = client.post(
            "/api/assist",
            json={"message": "someone is injured at the east concourse",
                  "persona": "staff"},
        )
        body = response.get_json()
        assert body["intent"] == "incident_report"
        assert body["result"]["severity"] in ("P1", "P2", "P3")

    def test_transit_message(self, client):
        """Transit message."""
        response = client.post(
            "/api/assist", json={"message": "when should I leave for the metro"}
        )
        body = response.get_json()
        assert body["intent"] == "transit_query"
        assert body["result"]["departure"]

    def test_translated_response_is_fully_translated(self, client):
        """Translated response is fully translated."""
        response = client.post(
            "/api/assist",
            json={
                "message": "How do I get from Gate A to Section 114?",
                "language": "es",
            },
        )
        body = response.get_json()
        assert body["guidance"].startswith("[es]")
        assert body["result"]["origin"].startswith("[es]")

    def test_missing_message_is_400(self, client):
        """Missing message is 400."""
        response = client.post("/api/assist", json={})
        assert response.status_code == 400
        assert response.get_json()["error"] == "ValidationError"

    def test_non_json_body_is_400(self, client):
        """Non json body is 400."""
        response = client.post(
            "/api/assist", data="plain text", content_type="text/plain"
        )
        assert response.status_code == 400

    def test_overlong_message_is_400(self, client):
        """Overlong message is 400."""
        response = client.post("/api/assist", json={"message": "x" * 2001})
        assert response.status_code == 400

    def test_invalid_persona_is_400(self, client):
        """Invalid persona is 400."""
        response = client.post(
            "/api/assist", json={"message": "hello", "persona": "alien"}
        )
        assert response.status_code == 400

    def test_invalid_language_is_400(self, client):
        """Invalid language is 400."""
        response = client.post(
            "/api/assist", json={"message": "hello", "language": "xx"}
        )
        assert response.status_code == 400


class TestRouteEndpoint:
    """POST /api/route."""

    def test_route_happy_path(self, client):
        """Route happy path."""
        response = client.post(
            "/api/route", json={"origin": "Gate A", "destination": "Section 101"}
        )
        assert response.status_code == 200
        assert response.get_json()["total_distance_m"] == 100.0

    def test_accessible_route_only_step_free_segments(self, client):
        """Accessible route only step free segments."""
        response = client.post(
            "/api/route",
            json={
                "origin": "North Concourse",
                "destination": "Section 201",
                "accessibility_required": True,
            },
        )
        body = response.get_json()
        assert body["fully_step_free"] is True
        assert all(segment["step_free"] for segment in body["segments"])

    def test_unknown_location_is_422(self, client):
        """Unknown location is 422."""
        response = client.post(
            "/api/route", json={"origin": "Narnia", "destination": "Gate A"}
        )
        assert response.status_code == 422
        assert response.get_json()["error"] == "RoutingError"

    def test_missing_destination_is_400(self, client):
        """Missing destination is 400."""
        response = client.post("/api/route", json={"origin": "Gate A"})
        assert response.status_code == 400

    def test_translated_route(self, client):
        """Translated route."""
        response = client.post(
            "/api/route",
            json={"origin": "Gate A", "destination": "Section 101",
                  "language": "hi"},
        )
        assert response.get_json()["origin"].startswith("[hi]")


class TestReportEndpoint:
    """POST /api/report."""

    def test_crowd_report_happy_path(self, client):
        """Crowd report happy path."""
        response = client.post(
            "/api/report", json={"kind": "crowd", "zone": "north", "level": "high"}
        )
        assert response.status_code == 200
        assert response.get_json()["density"] > 0

    def test_incident_report_happy_path(self, client):
        """Incident report happy path."""
        response = client.post(
            "/api/report",
            json={
                "kind": "incident",
                "category": "medical",
                "description": "fan is unconscious",
            },
        )
        body = response.get_json()
        assert body["severity"] == "P1"
        assert "paramedic" in body["recommended_action"].lower()

    def test_invalid_kind_is_400(self, client):
        """Invalid kind is 400."""
        response = client.post("/api/report", json={"kind": "gossip"})
        assert response.status_code == 400

    def test_invalid_level_is_400(self, client):
        """Invalid level is 400."""
        response = client.post(
            "/api/report", json={"kind": "crowd", "zone": "north",
                                 "level": "apocalyptic"}
        )
        assert response.status_code == 400

    def test_invalid_category_is_400(self, client):
        """Invalid category is 400."""
        response = client.post(
            "/api/report",
            json={"kind": "incident", "category": "weather",
                  "description": "rain"},
        )
        assert response.status_code == 400


class TestZonesTransitOps:
    """GET /api/zones, POST /api/transit, GET /api/ops/summary."""

    def test_zones_snapshot(self, client):
        """Zones snapshot."""
        response = client.get("/api/zones")
        assert response.status_code == 200
        zones = response.get_json()["zones"]
        assert {"zone", "density", "status"} <= set(zones[0])

    def test_transit_happy_path(self, client):
        """Transit happy path."""
        response = client.post(
            "/api/transit", json={"zone": "north", "distance_km": 7, "party_size": 2}
        )
        body = response.get_json()
        assert body["greenest_mode"] == "walk"
        assert body["lowest_carbon_transit_mode"] == "metro"

    def test_transit_defaults_applied(self, client):
        """Transit defaults applied."""
        response = client.post("/api/transit", json={"zone": "east"})
        assert response.status_code == 200

    def test_transit_bad_distance_is_400(self, client):
        """Transit bad distance is 400."""
        response = client.post(
            "/api/transit", json={"zone": "north", "distance_km": "far"}
        )
        assert response.status_code == 400

    def test_transit_bad_party_size_is_400(self, client):
        """Transit bad party size is 400."""
        response = client.post(
            "/api/transit", json={"zone": "north", "party_size": 1.5}
        )
        assert response.status_code == 400

    def test_transit_negative_distance_is_400(self, client):
        """Transit negative distance is 400."""
        response = client.post(
            "/api/transit", json={"zone": "north", "distance_km": -2}
        )
        assert response.status_code == 400

    def test_ops_summary_shape(self, client):
        """Ops summary shape."""
        client.post(
            "/api/report", json={"kind": "crowd", "zone": "south",
                                 "level": "critical"}
        )
        response = client.get("/api/ops/summary")
        body = response.get_json()
        assert body["open_incident_count"] == 0
        assert any("south" in action for action in body["recommended_actions"])

    def test_ops_summary_counts_incidents(self, client):
        """Ops summary counts incidents."""
        client.post(
            "/api/report",
            json={"kind": "incident", "category": "security",
                  "description": "someone has a knife"},
        )
        response = client.get("/api/ops/summary")
        body = response.get_json()
        assert body["incidents_by_severity"]["P1"] == 1

    def test_unknown_path_is_json_404(self, client):
        """Unknown path is json 404."""
        response = client.get("/api/nothing-here")
        assert response.status_code == 404
        assert response.get_json()["error"] == "NotFound"


class TestBoundaryPaths:
    """Rate limiting, translated writes and non-string fields."""

    def test_rate_limit_kicks_in_after_configured_ceiling(self, client, monkeypatch):
        """Rate limit kicks in after configured ceiling."""
        monkeypatch.setattr("app.routes.api.RATE_LIMIT_PER_MINUTE", 3)
        monkeypatch.setattr("app.routes.api._rate_buckets", {})
        for _ in range(3):
            assert client.get("/api/zones").status_code == 200
        assert client.get("/api/zones").status_code == 429

    def test_non_string_field_is_400(self, client):
        """Non string field is 400."""
        response = client.post(
            "/api/route", json={"origin": 42, "destination": "Gate A"}
        )
        assert response.status_code == 400

    def test_translated_report_response(self, client):
        """Translated report response."""
        response = client.post(
            "/api/report",
            json={"kind": "crowd", "zone": "north", "level": "high",
                  "language": "fr"},
        )
        assert response.get_json()["zone"] == "north"

    def test_translated_transit_response(self, client):
        """Translated transit response."""
        response = client.post(
            "/api/transit", json={"zone": "north", "language": "pt"}
        )
        assert response.status_code == 200
