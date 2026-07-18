"""Deterministic crowd-density scoring and wait-time estimation per zone.

Crowd reports arrive as coarse levels (``low`` … ``critical``).  The registry
converts them to numeric scores, applies exponential time decay so stale
reports fade, and derives queue wait-times from documented service-rate
constants.  No generative model participates in these numbers.

Constants and their basis:

* Level scores (0–100 scale): low=20, moderate=50, high=80, critical=95 —
  an ordinal mapping chosen so the midpoint of adjacent levels is distinct.
* Decay half-life: 600 seconds.  Crowd conditions at stadium pinch points
  change on a ~10 minute cadence between event phases.
* Service rates (people/min per lane): concession=3, security lane=8,
  restroom=10 — planning-order figures consistent with published queueing
  guidance for event venues (e.g. ~4–10 persons/min per security lane in
  Safe and Secure event guidance, UEFA/stadium ops literature).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

LEVEL_SCORES = {"low": 20.0, "moderate": 50.0, "high": 80.0, "critical": 95.0}

DECAY_HALF_LIFE_SECONDS = 600.0

#: People served per minute per lane, by amenity kind.
SERVICE_RATES = {"concession": 3.0, "security": 8.0, "restroom": 10.0}

#: Assumed queue length (people) at density 100 for a single lane.
FULL_QUEUE_PEOPLE = 40.0

#: Density thresholds for the traffic-light status shown to organizers.
STATUS_THRESHOLDS = ((75.0, "critical"), (55.0, "busy"), (30.0, "steady"))


@dataclass(frozen=True)
class CrowdReport:
    """A single observation of crowd level in a zone."""

    zone: str
    level: str
    timestamp: float

    @property
    def score(self) -> float:
        """Numeric density score for the reported level."""
        return LEVEL_SCORES[self.level]


@dataclass
class ZoneLoadRegistry:
    """Aggregates crowd reports into decayed density scores per zone."""

    reports: dict[str, list[CrowdReport]] = field(default_factory=dict)
    max_reports_per_zone: int = 50

    @staticmethod
    def normalise_level(level: str) -> str:
        """Validate and canonicalise a crowd level word."""
        key = level.strip().lower()
        aliases = {"medium": "moderate", "mid": "moderate", "packed": "critical"}
        key = aliases.get(key, key)
        if key not in LEVEL_SCORES:
            raise ValueError(f"Unknown crowd level '{level}'.")
        return key

    def record(self, zone: str, level: str, timestamp: float | None = None) -> CrowdReport:
        """Store a report and return the canonical record."""
        canonical = self.normalise_level(level)
        report = CrowdReport(
            zone=zone.strip().lower(),
            level=canonical,
            timestamp=timestamp if timestamp is not None else time.time(),
        )
        bucket = self.reports.setdefault(report.zone, [])
        bucket.append(report)
        del bucket[: -self.max_reports_per_zone]
        return report

    def density(self, zone: str, now: float | None = None) -> float:
        """Time-decayed weighted density score (0–100) for a zone.

        Weight for a report of age ``t`` seconds is ``0.5 ** (t / half_life)``;
        the density is the weighted mean of report scores.  Zones without
        reports return 0.0 (unknown ≈ unloaded, surfaced as ``quiet``).
        """
        moment = now if now is not None else time.time()
        bucket = self.reports.get(zone.strip().lower(), [])
        weighted = 0.0
        weights = 0.0
        for report in bucket:
            age = max(0.0, moment - report.timestamp)
            weight = math.pow(0.5, age / DECAY_HALF_LIFE_SECONDS)
            weighted += report.score * weight
            weights += weight
        if weights == 0.0:
            return 0.0
        return min(100.0, max(0.0, weighted / weights))

    @staticmethod
    def status_for(density: float) -> str:
        """Map a density score to a traffic-light status word."""
        for threshold, label in STATUS_THRESHOLDS:
            if density >= threshold:
                return label
        return "quiet"

    @staticmethod
    def wait_minutes(density: float, amenity: str = "concession", lanes: int = 1) -> float:
        """Deterministic queue wait estimate for an amenity at a density.

        Queue length scales linearly with density; service follows the
        documented per-lane rates.  ``lanes`` must be at least 1.
        """
        rate = SERVICE_RATES.get(amenity, SERVICE_RATES["concession"])
        effective_lanes = max(1, lanes)
        queue_people = FULL_QUEUE_PEOPLE * (density / 100.0)
        return round(queue_people / (rate * effective_lanes), 1)

    def heatmap(self, zones: list[str], now: float | None = None) -> list[dict]:
        """Density snapshot for a list of zones, sorted busiest first."""
        snapshot: list[dict] = []
        for zone in zones:
            score = self.density(zone, now=now)
            snapshot.append(
                {
                    "zone": zone,
                    "density": round(score, 1),
                    "status": self.status_for(score),
                    "estimated_concession_wait_min": self.wait_minutes(score),
                }
            )
        snapshot.sort(key=lambda item: float(item["density"]), reverse=True)
        return snapshot
