"""Deterministic incident triage: severity matrix and dispatch actions.

Staff and volunteers report incidents in free text.  Gemini (elsewhere) only
extracts the category and normalised description; the *severity decision* is
made here by an auditable rule matrix so that dispatch recommendations are
reproducible and explainable to venue command.

Severity model:

* Base score by category (medical=60, security=55, crowd=50, facility=30,
  lost_item=15).
* Keyword escalators add fixed increments for terms indicating danger to
  life or mass-casualty risk.
* Negative sentiment (score < -0.25 from Cloud Natural Language) adds a
  small increment — distressed language correlates with urgency but never
  outweighs explicit danger keywords.
* P1 ≥ 80, P2 ≥ 50, else P3.
"""

from __future__ import annotations

from dataclasses import dataclass

CATEGORY_BASE = {
    "medical": 60.0,
    "security": 55.0,
    "crowd": 50.0,
    "facility": 30.0,
    "lost_item": 15.0,
}

#: Keyword → escalation increment.  Matched case-insensitively as substrings.
ESCALATORS = {
    "unconscious": 30.0,
    "not breathing": 40.0,
    "cardiac": 35.0,
    "weapon": 35.0,
    "knife": 35.0,
    "fire": 30.0,
    "smoke": 20.0,
    "stampede": 40.0,
    "crush": 35.0,
    "collapse": 25.0,
    "child": 15.0,
    "bleeding": 20.0,
}

NEGATIVE_SENTIMENT_THRESHOLD = -0.25
NEGATIVE_SENTIMENT_BONUS = 10.0

P1_THRESHOLD = 80.0
P2_THRESHOLD = 50.0

DISPATCH_ACTIONS = {
    ("medical", "P1"): "Dispatch on-site paramedic team and alert nearest hospital.",
    ("medical", "P2"): "Send first-aid responder from the nearest medical post.",
    ("medical", "P3"): "Direct reporter to the nearest medical post.",
    ("security", "P1"): "Dispatch security response team and notify police liaison.",
    ("security", "P2"): "Send nearest steward pair to assess and de-escalate.",
    ("security", "P3"): "Log for CCTV review and monitor the area.",
    ("crowd", "P1"): "Open auxiliary gates and pause inbound flow to the zone.",
    ("crowd", "P2"): "Deploy stewards to meter flow at the zone entry points.",
    ("crowd", "P3"): "Update signage and app guidance to redistribute footfall.",
    ("facility", "P1"): "Close the facility and dispatch maintenance immediately.",
    ("facility", "P2"): "Dispatch maintenance within the current event phase.",
    ("facility", "P3"): "Queue for scheduled maintenance after the event.",
    ("lost_item", "P1"): "Escort reporter to guest services immediately.",
    ("lost_item", "P2"): "Log item description and notify guest services.",
    ("lost_item", "P3"): "Log item description for lost-and-found matching.",
}


@dataclass(frozen=True)
class TriageResult:
    """Outcome of the deterministic triage matrix."""

    category: str
    severity: str
    score: float
    action: str
    matched_keywords: tuple[str, ...]

    def to_payload(self) -> dict:
        """Serialise the triage result for JSON responses."""
        return {
            "category": self.category,
            "severity": self.severity,
            "score": round(self.score, 1),
            "recommended_action": self.action,
            "matched_keywords": list(self.matched_keywords),
        }


def normalise_category(category: str) -> str:
    """Validate and canonicalise an incident category."""
    key = category.strip().lower().replace(" ", "_")
    aliases = {"lost": "lost_item", "safety": "security", "queue": "crowd"}
    key = aliases.get(key, key)
    if key not in CATEGORY_BASE:
        raise ValueError(f"Unknown incident category '{category}'.")
    return key


def triage(category: str, description: str, sentiment_score: float = 0.0) -> TriageResult:
    """Apply the severity matrix to a categorised incident description."""
    canonical = normalise_category(category)
    lowered = description.lower()
    matched = tuple(
        keyword for keyword in sorted(ESCALATORS) if keyword in lowered
    )
    score = CATEGORY_BASE[canonical]
    score += sum(ESCALATORS[keyword] for keyword in matched)
    if sentiment_score < NEGATIVE_SENTIMENT_THRESHOLD:
        score += NEGATIVE_SENTIMENT_BONUS
    score = min(100.0, score)
    if score >= P1_THRESHOLD:
        severity = "P1"
    elif score >= P2_THRESHOLD:
        severity = "P2"
    else:
        severity = "P3"
    return TriageResult(
        category=canonical,
        severity=severity,
        score=score,
        action=DISPATCH_ACTIONS[(canonical, severity)],
        matched_keywords=matched,
    )
