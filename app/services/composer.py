"""Narrative composition: deterministic results, persona-appropriate words.

The composer receives the *already computed* deterministic result (a route,
a triage decision, a departure plan) and asks Gemini to phrase it for the
requesting persona.  On any upstream failure a deterministic template
produces the narrative instead, so responses always include guidance text.
"""

from __future__ import annotations

import json
import logging

from app.services.gateway import UPSTREAM_FAILURES, VertexGateway

LOGGER = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """You are PitchSide, a stadium copilot at FIFA World Cup 2026.
Write 2-3 concise sentences of guidance for a {persona} based ONLY on this
computed result. Do not invent numbers; use only values present in the JSON.
Result JSON: {payload}
"""

_TEMPLATES = {
    "route_request": (
        "Your route from {origin} to {destination} covers about "
        "{total_distance_m} metres and should take {eta_minutes} minutes."
    ),
    "crowd_report": (
        "Thanks for the report. {zone} is now tracked at density "
        "{density} ({status})."
    ),
    "incident_report": (
        "Your report is logged as {severity}. Recommended action: "
        "{recommended_action}"
    ),
    "transit_query": (
        "Your zone departs {wave_start_minutes_after_final_whistle} minutes "
        "after the final whistle. Lowest-carbon transit option: "
        "{lowest_carbon_transit_mode}."
    ),
}


class NarrativeComposer:
    """Turns deterministic results into short persona-aware narratives."""

    def __init__(self, gateway: VertexGateway | None = None) -> None:
        self._gateway = gateway or VertexGateway()

    def compose(self, intent: str, result: dict, persona: str) -> str:
        """Compose a narrative, falling back to templates on failure."""
        try:
            text = self._gateway.generate(
                _PROMPT_TEMPLATE.format(
                    persona=persona, payload=json.dumps(result, default=str)
                ),
                temperature=0.4,
            )
            return text.strip()
        except UPSTREAM_FAILURES as exc:
            LOGGER.warning("Composer fallback engaged: %s", exc)
            return self._template(intent, result)

    @staticmethod
    def _template(intent: str, result: dict) -> str:
        """Deterministic narrative built from the result payload."""
        template = _TEMPLATES.get(intent)
        if template is None:
            return "Your request has been processed."
        flat = dict(result)
        for nested in ("departure", "triage"):
            if isinstance(result.get(nested), dict):
                flat.update(result[nested])
        try:
            return template.format(**flat)
        except KeyError:
            return "Your request has been processed."
