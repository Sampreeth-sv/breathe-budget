"""Deterministic PM2.5 exposure model.

Everything here is a pure function: no network, no clock, no randomness. That
makes the "direct impact" numbers reproducible and unit-testable. The LLM never
computes them; it only explains them.

The model is intentionally simple and every constant below is an *assumption*
drawn from typical ranges in the exposure literature. Results are estimates for
comparing choices against each other, not clinical measurements.

    dose (ug/day) = sum over micro-environments of
                    concentration (ug/m3) x breathing rate (m3/h) x hours
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal, Sequence

from app.schemas import AdviceRequest, CommuteMode, CookingFuel, HeatingType

WHO_PM25_24H = 15.0  # ug/m3, WHO 2021 24-hour guideline

# (pm2.5 low, pm2.5 high, aqi low, aqi high), US EPA 2024 PM2.5 breakpoints.
_PM25_BREAKPOINTS: tuple[tuple[float, float, int, int], ...] = (
    (0.0, 9.0, 0, 50),
    (9.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 125.4, 151, 200),
    (125.5, 225.4, 201, 300),
    (225.5, 500.0, 301, 500),
)
_AQI_CATEGORY_LIMITS: tuple[tuple[int, str], ...] = (
    (50, "good"),
    (100, "moderate"),
    (150, "unhealthy_sensitive"),
    (200, "unhealthy"),
    (300, "very_unhealthy"),
)


def pm25_to_aqi(pm25: float) -> int:
    """Convert a PM2.5 concentration (ug/m3) to a US AQI value (0-500)."""
    if math.isnan(pm25) or pm25 < 0:
        raise ValueError("pm25 must be a non-negative number")
    truncated = math.floor(min(pm25, 500.0) * 10) / 10  # EPA truncates to 0.1
    for c_low, c_high, i_low, i_high in _PM25_BREAKPOINTS:
        if truncated <= c_high:
            c = max(truncated, c_low)
            return round((i_high - i_low) / (c_high - c_low) * (c - c_low) + i_low)
    return 500


def aqi_category(aqi: int) -> str:
    for limit, name in _AQI_CATEGORY_LIMITS:
        if aqi <= limit:
            return name
    return "hazardous"


# ------------------------------------------------------------ model constants
BREATHING_REST = 0.5  # m3/h, adult at rest or light indoor activity
BREATHING_EXERCISE_OUTDOOR = 2.0
BREATHING_EXERCISE_INDOOR = 1.5  # shorter, gentler indoor session
BASE_INFILTRATION = 0.6  # indoor/outdoor ratio for a typical leaky winter home
SEALED_INFILTRATION_FACTOR = 0.75  # closing windows, sealing gaps
MASK_FACTOR = 0.5  # realistic N95 benefit after fit leakage
VENTED_COOKING_FACTOR = 0.4

PURIFIER_INFILTRATION_FACTOR = {"none": 1.0, "diy": 0.6, "hepa": 0.4}
PURIFIER_SOURCE_FACTOR = {"none": 1.0, "diy": 0.7, "hepa": 0.5}

# Extra indoor PM2.5 (ug/m3) while the source is active, and hours per day.
COOKING_SOURCE: dict[str, tuple[float, float]] = {
    "electric": (5.0, 2.0),
    "lpg": (25.0, 2.0),
    "biomass": (150.0, 3.0),
}
HEATING_SOURCE: dict[str, tuple[float, float]] = {
    "none": (0.0, 0.0),
    "electric": (0.0, 0.0),
    "gas": (10.0, 5.0),
    "biomass": (80.0, 5.0),
}


@dataclass(frozen=True)
class Transport:
    exposure_factor: float  # in-vehicle concentration / ambient concentration
    breathing_m3_h: float
    speed_kmh: float
    gco2e_per_passenger_km: float
    mask_helps: bool


TRANSPORT: dict[str, Transport] = {
    "wfh": Transport(0.0, 0.0, 0.0, 0.0, False),
    "walk": Transport(1.1, 1.0, 4.5, 0.0, True),
    "cycle": Transport(1.2, 1.6, 14.0, 0.0, True),
    "two_wheeler": Transport(1.3, 0.7, 25.0, 60.0, True),
    "auto_rickshaw": Transport(1.3, 0.6, 20.0, 80.0, True),
    "bus": Transport(1.1, 0.6, 18.0, 70.0, True),
    "metro": Transport(0.7, 0.6, 32.0, 30.0, False),
    "car": Transport(0.6, 0.6, 22.0, 170.0, False),  # windows closed, recirculating
}

Purifier = Literal["none", "diy", "hepa"]
ExerciseMode = Literal["outdoor", "clean_hour", "indoor"]


@dataclass(frozen=True)
class Lifestyle:
    """Everything the model needs to know about a typical day."""

    commute_mode: CommuteMode = "wfh"
    commute_minutes_each_way: int = 0
    cooking_fuel: CookingFuel = "lpg"
    heating: HeatingType = "none"
    purifier: Purifier = "none"
    exercise_minutes: int = 0
    exercise: ExerciseMode = "outdoor"
    sealed_home: bool = False
    vented_cooking: bool = False
    mask_on_commute: bool = False

    @classmethod
    def from_request(cls, req: AdviceRequest) -> "Lifestyle":
        return cls(
            commute_mode=req.commute_mode,
            commute_minutes_each_way=req.commute_minutes_each_way,
            cooking_fuel=req.cooking_fuel,
            heating=req.heating,
            purifier="hepa" if req.has_purifier else "none",
            exercise_minutes=req.outdoor_exercise_minutes,
        )

    @property
    def commutes(self) -> bool:
        return self.commute_mode != "wfh" and self.commute_minutes_each_way > 0

    @property
    def commute_hours(self) -> float:
        return 2 * self.commute_minutes_each_way / 60 if self.commutes else 0.0

    def with_changes(self, **changes: object) -> "Lifestyle":
        return replace(self, **changes)


@dataclass(frozen=True)
class DoseBreakdown:
    home: float
    commute: float
    exercise: float

    @property
    def total(self) -> float:
        return self.home + self.commute + self.exercise


def daily_dose(pm25: float, lifestyle: Lifestyle, clean_hour_ratio: float = 1.0) -> DoseBreakdown:
    """Estimated PM2.5 inhaled per day (ug) for one typical adult."""
    transport = TRANSPORT[lifestyle.commute_mode]
    commute_h = lifestyle.commute_hours
    exercise_h = lifestyle.exercise_minutes / 60
    home_h = max(0.0, 24.0 - commute_h - exercise_h)

    infiltration = BASE_INFILTRATION
    if lifestyle.sealed_home:
        infiltration *= SEALED_INFILTRATION_FACTOR
    infiltration *= PURIFIER_INFILTRATION_FACTOR[lifestyle.purifier]
    indoor_background = pm25 * infiltration

    cook_conc, cook_hours = COOKING_SOURCE[lifestyle.cooking_fuel]
    heat_conc, heat_hours = HEATING_SOURCE[lifestyle.heating]
    cook_factor = VENTED_COOKING_FACTOR if lifestyle.vented_cooking else 1.0
    source_ug_h = cook_conc * cook_hours * cook_factor + heat_conc * heat_hours
    source_ug_h *= PURIFIER_SOURCE_FACTOR[lifestyle.purifier]

    home = BREATHING_REST * (home_h * indoor_background + source_ug_h)

    mask = MASK_FACTOR if lifestyle.mask_on_commute and transport.mask_helps else 1.0
    commute = (
        transport.breathing_m3_h * commute_h * pm25 * transport.exposure_factor * mask
    )

    if lifestyle.exercise == "indoor":
        exercise = BREATHING_EXERCISE_INDOOR * exercise_h * indoor_background
    elif lifestyle.exercise == "clean_hour":
        exercise = BREATHING_EXERCISE_OUTDOOR * exercise_h * pm25 * clean_hour_ratio
    else:
        exercise = BREATHING_EXERCISE_OUTDOOR * exercise_h * pm25

    return DoseBreakdown(home=home, commute=commute, exercise=exercise)


def commute_emissions_kg(mode: str, minutes_each_way: int, occupants: int = 1) -> float:
    """Approximate CO2e (kg/day) for a round-trip commute, per passenger."""
    transport = TRANSPORT[mode]
    distance_km = transport.speed_kmh * (2 * minutes_each_way / 60)
    return distance_km * transport.gco2e_per_passenger_km / 1000 / max(1, occupants)


# --------------------------------------------------------------- hourly data
def cleanest_hour(
    hourly: Sequence[float | None], start: int = 8, end: int = 20
) -> tuple[int, float] | None:
    """Hour of day (local) with the lowest forecast PM2.5 between start and end."""
    candidates = [
        (value, hour)
        for hour, value in enumerate(hourly)
        if start <= hour <= end and value is not None
    ]
    if not candidates:
        return None
    value, hour = min(candidates)
    return hour, value


def clean_hour_ratio(hourly: Sequence[float | None], best_pm25: float) -> float:
    """How much cleaner the best hour is than the daily mean (bounded 0.2-1.0)."""
    values = [v for v in hourly if v is not None]
    if not values:
        return 1.0
    mean = sum(values) / len(values)
    if mean <= 0:
        return 1.0
    return min(1.0, max(0.2, best_pm25 / mean))
