"""Tests for the Google Maps Routes city-leg enrichment."""
# pylint: disable=attribute-defined-outside-init,too-few-public-methods
# pylint: disable=unnecessary-lambda,protected-access,unused-argument
# Rationale: standard pytest idioms — setup_method fixtures, minimal stub
# collaborators, and monkeypatch lambdas are intentional in test code.

from __future__ import annotations

import pytest

from app.services.city_routes import CityRoutesService
from tests.conftest import build_assistant


class _KeyVault:
    """Secret vault stub returning a fixed key."""

    def __init__(self, key: str) -> None:
        self.key = key

    def get(self, name: str, default: str = "") -> str:
        """Return the configured key regardless of name."""
        del name, default
        return self.key


class TestCityRoutesFallback:
    """Deterministic behaviour without a Maps API key."""

    def test_no_key_yields_estimate(self):
        """No key yields estimate."""
        service = CityRoutesService(secrets=_KeyVault(""))
        leg = service.city_leg("Stadium", "City Centre", 6.0)
        assert leg["provider"] == "estimate"
        assert leg["duration_minutes"] == pytest.approx(12.0)
        assert leg["distance_km"] == pytest.approx(6.0)

    def test_estimate_shape_is_stable(self):
        """Estimate shape is stable."""
        leg = CityRoutesService(secrets=_KeyVault("")).city_leg("A", "B", 3.0)
        assert set(leg) == {
            "provider",
            "origin",
            "destination",
            "distance_km",
            "duration_minutes",
        }

    def test_upstream_failure_falls_back_to_estimate(self, monkeypatch):
        """Upstream failure falls back to estimate."""
        service = CityRoutesService(secrets=_KeyVault("real-key"))
        monkeypatch.setattr(
            service,
            "_fetch_route",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("api down")),
        )
        leg = service.city_leg("Stadium", "City Centre", 6.0)
        assert leg["provider"] == "estimate"

    def test_key_resolved_once(self):
        """Key resolved once."""
        vault = _KeyVault("")
        service = CityRoutesService(secrets=vault)
        service.city_leg("A", "B", 1.0)
        vault.key = "late-key"
        leg = service.city_leg("A", "B", 1.0)
        assert leg["provider"] == "estimate"

    def test_is_healthy(self):
        """Is healthy."""
        assert CityRoutesService(secrets=_KeyVault("")).is_healthy() is True


class TestCityRoutesApiPath:
    """Routes API request/response handling with a stubbed fetch."""

    def test_api_route_used_when_key_present(self, monkeypatch):
        """Api route used when key present."""
        service = CityRoutesService(secrets=_KeyVault("real-key"))
        monkeypatch.setattr(
            service,
            "_fetch_route",
            lambda origin, destination, key: {
                "provider": "routes_api",
                "origin": origin,
                "destination": destination,
                "distance_km": 7.4,
                "duration_minutes": 21.0,
            },
        )
        leg = service.city_leg("Stadium", "City Centre", 6.0)
        assert leg["provider"] == "routes_api"
        assert leg["duration_minutes"] == 21.0

    def test_duration_parsing(self):
        """Duration parsing."""
        assert CityRoutesService._parse_duration_minutes("1260s") == 21.0

    def test_response_body_parsing(self, monkeypatch):
        """Response body parsing."""
        service = CityRoutesService(secrets=_KeyVault("real-key"))

        class _StubResponse:
            """Minimal urlopen response."""

            def read(self):
                """Return a canned Routes API body."""
                return (
                    b'{"routes":[{"distanceMeters":7400,"duration":"1260s"}]}'
                )

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(
            "urllib.request.urlopen", lambda req, timeout: _StubResponse()
        )
        leg = service.city_leg("Stadium", "City Centre", 6.0)
        assert leg["provider"] == "routes_api"
        assert leg["travel_mode"] == "transit"
        assert leg["distance_km"] == pytest.approx(7.4)
        assert leg["duration_minutes"] == pytest.approx(21.0)

    def test_drive_retry_when_transit_empty(self, monkeypatch):
        """Drive retry when transit empty."""
        service = CityRoutesService(secrets=_KeyVault("real-key"))
        calls: list[str] = []

        def fake_request(origin, destination, key, mode):
            calls.append(mode)
            if mode == "TRANSIT":
                return []
            return [{"distanceMeters": 12000, "duration": "900s"}]

        monkeypatch.setattr(service, "_request_routes", fake_request)
        leg = service.city_leg("MetLife Stadium", "Times Square", 10.0)
        assert calls == ["TRANSIT", "DRIVE"]
        assert leg["provider"] == "routes_api"
        assert leg["travel_mode"] == "drive"
        assert leg["duration_minutes"] == pytest.approx(15.0)

    def test_all_modes_empty_falls_back(self, monkeypatch):
        """All modes empty falls back."""
        service = CityRoutesService(secrets=_KeyVault("real-key"))
        monkeypatch.setattr(
            service, "_request_routes", lambda *a, **k: []
        )
        assert service.city_leg("A", "B", 4.0)["provider"] == "estimate"

    def test_empty_routes_falls_back(self, monkeypatch):
        """Empty routes falls back."""
        service = CityRoutesService(secrets=_KeyVault("real-key"))

        class _StubResponse:
            """Empty-route response."""

            def read(self):
                """Return an empty routes list."""
                return b'{"routes":[]}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(
            "urllib.request.urlopen", lambda req, timeout: _StubResponse()
        )
        assert service.city_leg("A", "B", 2.0)["provider"] == "estimate"

    def test_city_leg_uses_configured_addresses(self):
        """City leg uses configured addresses."""
        assistant = build_assistant()
        plan = assistant.transit_plan("north", 6.0, 1)
        assert "MetLife Stadium" in plan["city_leg"]["origin"]
        assert "Times Square" in plan["city_leg"]["destination"]


class TestTransitIntegration:
    """The transit plan carries the city leg end-to-end."""

    def test_transit_plan_includes_city_leg(self):
        """Transit plan includes city leg."""
        assistant = build_assistant()
        plan = assistant.transit_plan("north", 6.0, 1)
        assert plan["city_leg"]["provider"] == "estimate"
        assert plan["city_leg"]["duration_minutes"] > 0

    def test_health_includes_maps_routes(self, client):
        """Health includes maps routes."""
        body = client.get("/api/health").get_json()
        assert "maps_routes" in body
