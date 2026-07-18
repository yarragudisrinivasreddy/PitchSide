"""Deterministic post-match departure planning with carbon-aware guidance.

Two responsibilities, both computed without any generative model:

1. **Departure waves** — staggered egress recommendations per stadium zone so
   50,000 people do not hit the metro platform simultaneously.  Wave
   assignment is a fixed zone→wave table modulated by live density: a zone
   already congested is asked to wait one wave longer.
2. **Carbon comparison** — per-passenger-km emission factors for each travel
   mode, with sources cited below, so fans see the sustainability cost of
   their choice and organizers can report modal-shift impact.

Emission factors (grams CO2e per passenger-km):

* Metro/rail: 30 — order of magnitude for electrified urban rail, IPCC AR5
  WGIII Chapter 8 (Transport) and UITP averages.
  https://www.ipcc.ch/report/ar5/wg3/
* Shuttle bus (high occupancy): 80 — urban bus mid-range, IPCC AR5 WGIII.
  https://www.ipcc.ch/report/ar5/wg3/
* Private car (average occupancy 1.5): 171 — UK DEFRA/BEIS 2023 average car
  factor per vehicle-km scaled to passenger-km.
  https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2023
* Walking: 0 — direct emissions.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Mode → (grams CO2e per passenger-km, cruise speed km/h, source URL).
MODES: dict[str, tuple[float, float, str]] = {
    "metro": (30.0, 35.0, "https://www.ipcc.ch/report/ar5/wg3/"),
    "shuttle": (80.0, 25.0, "https://www.ipcc.ch/report/ar5/wg3/"),
    "car": (
        171.0,
        30.0,
        "https://www.gov.uk/government/publications/"
        "greenhouse-gas-reporting-conversion-factors-2023",
    ),
    "walk": (0.0, 4.5, "https://www.ipcc.ch/report/ar5/wg3/"),
}

#: Fixed egress wave per stadium zone (minutes after final whistle).
ZONE_BASE_WAVE = {
    "north": 0,
    "east": 15,
    "south": 15,
    "west": 30,
    "transit": 0,
}

WAVE_LENGTH_MINUTES = 15
MAX_WAVE_START = 45

#: Density above which a zone's departure is deferred by one wave.
CONGESTION_DEFERRAL_THRESHOLD = 75.0


@dataclass(frozen=True)
class ModePlan:
    """Deterministic travel plan for one mode."""

    mode: str
    duration_minutes: float
    co2_grams: float
    source: str

    def to_payload(self) -> dict:
        """Serialise the plan for JSON responses."""
        return {
            "mode": self.mode,
            "duration_minutes": self.duration_minutes,
            "co2_grams": self.co2_grams,
            "source": self.source,
        }


class TransitPlanner:
    """Computes departure waves and per-mode carbon comparisons."""

    @staticmethod
    def available_modes() -> list[str]:
        """Modes the planner understands."""
        return sorted(MODES)

    @staticmethod
    def mode_plan(mode: str, distance_km: float, party_size: int) -> ModePlan:
        """Deterministic duration and emissions for one mode of travel."""
        key = mode.strip().lower()
        if key not in MODES:
            raise ValueError(f"Unknown travel mode '{mode}'.")
        if distance_km <= 0:
            raise ValueError("distance_km must be positive.")
        if party_size < 1:
            raise ValueError("party_size must be at least 1.")
        factor, speed_kmh, source = MODES[key]
        duration = distance_km / speed_kmh * 60.0
        co2 = factor * distance_km * party_size
        return ModePlan(
            mode=key,
            duration_minutes=round(duration, 1),
            co2_grams=round(co2, 1),
            source=source,
        )

    @staticmethod
    def departure_wave(zone: str, density: float) -> dict:
        """Egress wave for a zone, deferred one wave when congested."""
        base = ZONE_BASE_WAVE.get(zone.strip().lower(), MAX_WAVE_START)
        if density >= CONGESTION_DEFERRAL_THRESHOLD:
            base = min(MAX_WAVE_START, base + WAVE_LENGTH_MINUTES)
        return {
            "zone": zone.strip().lower(),
            "wave_start_minutes_after_final_whistle": base,
            "wave_end_minutes_after_final_whistle": base + WAVE_LENGTH_MINUTES,
            "deferred_due_to_congestion": density >= CONGESTION_DEFERRAL_THRESHOLD,
        }

    def plan(
        self,
        zone: str,
        density: float,
        distance_km: float,
        party_size: int,
    ) -> dict:
        """Full departure plan: wave + all mode options, greenest flagged."""
        options = [
            self.mode_plan(mode, distance_km, party_size).to_payload()
            for mode in self.available_modes()
        ]
        options.sort(key=lambda item: item["co2_grams"])
        greenest = options[0]["mode"]
        practical = [
            option for option in options if option["mode"] != "walk"
        ]
        lowest_carbon_transit = practical[0]["mode"] if practical else greenest
        return {
            "departure": self.departure_wave(zone, density),
            "options": options,
            "greenest_mode": greenest,
            "lowest_carbon_transit_mode": lowest_carbon_transit,
        }
