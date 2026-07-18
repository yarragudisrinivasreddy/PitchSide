"""Free-text interpretation: Gemini parses, heuristics guarantee an answer.

The interpreter converts a persona's natural-language message into one of
four structured intents (``route_request``, ``crowd_report``,
``incident_report``, ``transit_query``).  Gemini performs the parsing with a
strict JSON contract; any upstream or parsing failure falls back to a
deterministic keyword heuristic so the endpoint never fails on model issues.
"""

from __future__ import annotations

import json
import logging
import re

from app.services.gateway import UPSTREAM_FAILURES, VertexGateway

LOGGER = logging.getLogger(__name__)

INTENTS = ("route_request", "crowd_report", "incident_report", "transit_query")

_PROMPT_TEMPLATE = """You are the intent parser for a stadium operations copilot.
Classify the message and extract fields. Respond with ONLY a JSON object,
no markdown fences, using this schema:
{{"intent": "route_request|crowd_report|incident_report|transit_query",
 "origin": string|null, "destination": string|null,
 "accessible": boolean, "zone": string|null,
 "level": "low|moderate|high|critical"|null,
 "category": "medical|security|crowd|facility|lost_item"|null,
 "description": string|null, "mode": string|null}}
Persona: {persona}
Message: {message}
"""

_ROUTE_WORDS = ("how do i get", "route", "way to", "navigate", "reach", "find my seat")
_TRANSIT_WORDS = ("metro", "shuttle", "parking", "leave", "train", "bus", "depart")
_INCIDENT_WORDS = ("hurt", "injured", "fight", "fire", "broken", "lost", "unconscious",
                   "medical", "help needed", "emergency")
_CROWD_WORDS = ("queue", "crowded", "packed", "busy", "line", "full", "empty")

_LEVEL_WORDS = {
    "critical": ("packed", "crush", "dangerous", "overflowing"),
    "high": ("huge", "very busy", "long queue", "crowded"),
    "moderate": ("busy", "filling", "moderate"),
    "low": ("empty", "quiet", "no queue", "clear"),
}

_ZONE_PATTERN = re.compile(
    r"\b(gate\s+[a-d]|north|south|east|west|section\s+\d+|food court|metro|"
    r"parking|shuttle)\b",
    re.IGNORECASE,
)


class IntentInterpreter:
    """Parses free text into structured intents with guaranteed output."""

    def __init__(self, gateway: VertexGateway | None = None) -> None:
        self._gateway = gateway or VertexGateway()

    def parse(self, message: str, persona: str) -> dict:
        """Interpret a message, falling back to heuristics on any failure."""
        try:
            raw = self._gateway.generate(
                _PROMPT_TEMPLATE.format(persona=persona, message=message)
            )
            parsed = self._coerce(raw)
            parsed["source"] = "gemini"
            return parsed
        except (*UPSTREAM_FAILURES, json.JSONDecodeError, KeyError, TypeError) as exc:
            LOGGER.warning("Interpreter fallback engaged: %s", exc)
            fallback = self._heuristic(message)
            fallback["source"] = "heuristic"
            return fallback

    @staticmethod
    def _coerce(raw: str) -> dict:
        """Validate the model's JSON output against the intent contract."""
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise TypeError("Model output was not a JSON object.")
        if data.get("intent") not in INTENTS:
            raise KeyError("Model output missing a valid intent.")
        data.setdefault("accessible", False)
        for field in ("origin", "destination", "zone", "level", "category",
                      "description", "mode"):
            data.setdefault(field, None)
        return data

    @classmethod
    def _heuristic(cls, message: str) -> dict:
        """Deterministic keyword classification used as the safety net."""
        lowered = message.lower()
        intent = cls._classify(lowered)
        zone_match = _ZONE_PATTERN.search(message)
        zone = zone_match.group(0).lower() if zone_match else None
        result: dict = {
            "intent": intent,
            "origin": None,
            "destination": zone if intent == "route_request" else None,
            "accessible": any(
                word in lowered for word in ("wheelchair", "step-free", "stroller",
                                             "accessible")
            ),
            "zone": zone,
            "level": cls._level(lowered) if intent == "crowd_report" else None,
            "category": cls._category(lowered) if intent == "incident_report" else None,
            "description": message if intent == "incident_report" else None,
            "mode": "metro" if "metro" in lowered else None,
        }
        return result

    @staticmethod
    def _classify(lowered: str) -> str:
        """Pick the most likely intent from keyword families."""
        if any(word in lowered for word in _INCIDENT_WORDS):
            return "incident_report"
        if any(word in lowered for word in _ROUTE_WORDS):
            return "route_request"
        if any(word in lowered for word in _TRANSIT_WORDS):
            return "transit_query"
        if any(word in lowered for word in _CROWD_WORDS):
            return "crowd_report"
        return "route_request"

    @staticmethod
    def _level(lowered: str) -> str:
        """Extract a crowd level word from the message."""
        for level, words in _LEVEL_WORDS.items():
            if any(word in lowered for word in words):
                return level
        return "moderate"

    @staticmethod
    def _category(lowered: str) -> str:
        """Extract an incident category from the message."""
        if any(word in lowered for word in ("hurt", "injured", "medical",
                                            "unconscious", "bleeding")):
            return "medical"
        if any(word in lowered for word in ("fight", "weapon", "threat")):
            return "security"
        if "lost" in lowered:
            return "lost_item"
        if any(word in lowered for word in ("broken", "leak", "spill")):
            return "facility"
        return "crowd"
