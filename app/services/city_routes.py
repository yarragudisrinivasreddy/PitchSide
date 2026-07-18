"""City-side transit legs via the Google Maps Platform Routes API.

The venue graph covers the stadium precinct; the journey home continues into
the host city.  When a Maps Platform API key is available (resolved through
Secret Manager with an environment fallback), the planner enriches transit
plans with a live city leg — distance, duration and transit guidance — from
the Routes API (``routes.googleapis.com``).  Without a key or on any
upstream failure, a deterministic estimate keeps the plan complete.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from google.api_core import exceptions as gapi_exceptions
from google.auth import exceptions as gauth_exceptions

from app.services.secrets import SecretVault

LOGGER = logging.getLogger(__name__)

UPSTREAM_FAILURES = (
    gapi_exceptions.GoogleAPIError,
    gauth_exceptions.GoogleAuthError,
    urllib.error.URLError,
    ValueError,
    RuntimeError,
    KeyError,
    TimeoutError,
)

ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
MAPS_KEY_SECRET = "maps-api-key"
REQUEST_TIMEOUT_SECONDS = 5

#: Deterministic fallback speed for city transit (km/h) when Routes API is
#: unavailable — urban rail scheduled-speed planning value.
FALLBACK_TRANSIT_SPEED_KMH = 30.0


class CityRoutesService:
    """Optional Routes API enrichment with a deterministic fallback."""

    def __init__(self, secrets: SecretVault | None = None) -> None:
        self._secrets = secrets or SecretVault()
        self._api_key: str | None = None

    def _resolve_key(self) -> str:
        """Resolve the Maps Platform key once per instance."""
        if self._api_key is None:
            self._api_key = self._secrets.get(MAPS_KEY_SECRET, default="")
        return self._api_key

    def city_leg(
        self, origin: str, destination: str, distance_km: float
    ) -> dict:
        """City transit leg via Routes API, or a deterministic estimate.

        The response always contains ``provider`` (``routes_api`` or
        ``estimate``), ``duration_minutes`` and ``distance_km`` so callers
        and tests can rely on a stable shape.
        """
        key = self._resolve_key()
        if key:
            try:
                return self._fetch_route(origin, destination, key)
            except UPSTREAM_FAILURES as exc:
                LOGGER.warning("Routes API fallback engaged: %s", exc)
        return {
            "provider": "estimate",
            "origin": origin,
            "destination": destination,
            "distance_km": round(distance_km, 1),
            "duration_minutes": round(
                distance_km / FALLBACK_TRANSIT_SPEED_KMH * 60.0, 1
            ),
        }

    def _fetch_route(self, origin: str, destination: str, key: str) -> dict:
        """Routes API lookup: TRANSIT first, DRIVE retry if no transit route."""
        for mode in ("TRANSIT", "DRIVE"):
            routes = self._request_routes(origin, destination, key, mode)
            if routes:
                return self._leg_from_route(origin, destination, mode, routes[0])
        raise RuntimeError("Routes API returned no routes for any mode.")

    def _request_routes(
        self, origin: str, destination: str, key: str, mode: str
    ) -> list[dict]:
        """One computeRoutes call for a single travel mode."""
        payload = {
            "origin": {"address": origin},
            "destination": {"address": destination},
            "travelMode": mode,
        }
        request = urllib.request.Request(
            ROUTES_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "routes.distanceMeters,routes.duration",
            },
            method="POST",
        )
        with urllib.request.urlopen(  # nosec B310 - fixed https endpoint
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
        return list(body.get("routes") or [])

    def _leg_from_route(
        self, origin: str, destination: str, mode: str, route: dict
    ) -> dict:
        """Build the city-leg payload from one Routes API route."""
        return {
            "provider": "routes_api",
            "travel_mode": mode.lower(),
            "origin": origin,
            "destination": destination,
            "distance_km": round(float(route["distanceMeters"]) / 1000.0, 1),
            "duration_minutes": self._parse_duration_minutes(route["duration"]),
        }

    @staticmethod
    def _parse_duration_minutes(duration: str) -> float:
        """Convert a Routes API duration string (e.g. ``'1234s'``) to minutes."""
        seconds = float(duration.rstrip("s"))
        return round(seconds / 60.0, 1)

    def is_healthy(self) -> bool:
        """The service is healthy when key resolution succeeds (key may be empty)."""
        try:
            self._resolve_key()
            return True
        except Exception:  # pragma: no cover  # pylint: disable=broad-exception-caught
            return False
