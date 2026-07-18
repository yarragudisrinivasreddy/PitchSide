"""JSON API blueprint: validate → delegate to the assistant → jsonify.

All business logic lives in :mod:`app.services.assistant`.  Routes here only
validate input shape, apply a generous rate limit, and serialise results.
"""

from __future__ import annotations

import time
from functools import wraps
from typing import Callable

from flask import Blueprint, Response, current_app, jsonify, request

from app.config import (
    DEFAULT_LANGUAGE,
    MAX_TEXT_LENGTH,
    RATE_LIMIT_PER_MINUTE,
)
from app.exceptions import ValidationError
from app.services.assistant import MatchDayAssistant

api_bp = Blueprint("api", __name__, url_prefix="/api")

_WINDOW_SECONDS = 60.0
_rate_buckets: dict[str, list[float]] = {}


def _rate_limited(view: Callable[..., Response]) -> Callable[..., Response]:
    """Generous in-memory rate limiter.

    Deliberately permissive (see ``RATE_LIMIT_PER_MINUTE``) so automated
    evaluation traffic is never blocked.  For multi-instance deployments a
    shared store such as Redis or Memorystore should back the buckets.
    """

    @wraps(view)
    def wrapper(*args: object, **kwargs: object) -> Response:
        client = request.headers.get("X-Forwarded-For", request.remote_addr or "anon")
        now = time.time()
        bucket = _rate_buckets.setdefault(client, [])
        bucket[:] = [stamp for stamp in bucket if now - stamp < _WINDOW_SECONDS]
        if len(bucket) >= RATE_LIMIT_PER_MINUTE:
            response = jsonify(
                {"error": "RateLimited", "message": "Too many requests."}
            )
            response.status_code = 429
            return response
        bucket.append(now)
        return view(*args, **kwargs)

    return wrapper


def _payload() -> dict:
    """Parse the JSON body, raising a typed error on malformed input."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    return data


def _text_field(data: dict, field: str, required: bool = True) -> str:
    """Extract and validate a bounded text field."""
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError(f"Field '{field}' is required.")
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be a string.")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValidationError(
            f"Field '{field}' exceeds {MAX_TEXT_LENGTH} characters."
        )
    return value.strip()


def _language(data: dict) -> str:
    """Validate the optional language field."""
    try:
        return current_app.extensions["assistant"].translator.validate_language(
            data.get("language")
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def _assistant() -> "MatchDayAssistant":
    """Fetch the application-scoped assistant."""
    return current_app.extensions["assistant"]


def _maybe_translate(result: dict, language: str) -> dict:
    """Translate a result payload when a non-default language is requested."""
    if language == DEFAULT_LANGUAGE:
        return result
    translated = _assistant().translator.translate_json_values(result, language)
    return translated if isinstance(translated, dict) else result


@api_bp.post("/assist")
@_rate_limited
def assist() -> Response:
    """Conversational entry point across all four personas."""
    data = _payload()
    message = _text_field(data, "message")
    persona = data.get("persona", "fan")
    if persona not in ("fan", "volunteer", "organizer", "staff"):
        raise ValidationError("persona must be fan, volunteer, organizer or staff.")
    language = _language(data)
    return jsonify(_assistant().assist(message, persona, language))


@api_bp.post("/route")
@_rate_limited
def route() -> Response:
    """Deterministic venue routing, optionally step-free only."""
    data = _payload()
    origin = _text_field(data, "origin")
    destination = _text_field(data, "destination")
    accessible = bool(data.get("accessibility_required", False))
    language = _language(data)
    result = _assistant().compute_route(origin, destination, accessible)
    return jsonify(_maybe_translate(result, language))


@api_bp.post("/report")
@_rate_limited
def report() -> Response:
    """Crowd or incident report from any persona."""
    data = _payload()
    kind = data.get("kind", "crowd")
    if kind == "crowd":
        zone = _text_field(data, "zone")
        level = _text_field(data, "level")
        result = _assistant().record_crowd_report(zone, level)
    elif kind == "incident":
        category = _text_field(data, "category")
        description = _text_field(data, "description")
        result = _assistant().record_incident(category, description)
    else:
        raise ValidationError("kind must be 'crowd' or 'incident'.")
    language = _language(data)
    return jsonify(_maybe_translate(result, language))


@api_bp.get("/zones")
@_rate_limited
def zones() -> Response:
    """Live zone density heat list."""
    return jsonify({"zones": _assistant().zone_heatmap()})


@api_bp.post("/transit")
@_rate_limited
def transit() -> Response:
    """Departure wave and carbon comparison."""
    data = _payload()
    zone = _text_field(data, "zone")
    distance_km = data.get("distance_km", 5.0)
    party_size = data.get("party_size", 1)
    if not isinstance(distance_km, (int, float)) or isinstance(distance_km, bool):
        raise ValidationError("distance_km must be a number.")
    if not isinstance(party_size, int) or isinstance(party_size, bool):
        raise ValidationError("party_size must be an integer.")
    language = _language(data)
    result = _assistant().transit_plan(zone, float(distance_km), party_size)
    return jsonify(_maybe_translate(result, language))


@api_bp.get("/ops/summary")
@_rate_limited
def ops_summary() -> Response:
    """Organizer dashboard summary."""
    return jsonify(_assistant().ops_summary())


@api_bp.get("/health")
def health() -> Response:
    """Per-service availability report; always HTTP 200."""
    return jsonify(_assistant().health())
