"""Pydantic models for the public API.

Validation is deliberately strict: every field is bounded, enums are closed
sets and unknown fields are rejected. The only free-text field is ``city`` and
it is restricted to letters and a few punctuation marks.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CommuteMode = Literal[
    "wfh", "walk", "cycle", "two_wheeler", "auto_rickshaw", "bus", "metro", "car"
]
CookingFuel = Literal["electric", "lpg", "biomass"]
HeatingType = Literal["none", "electric", "gas", "biomass"]
CostTier = Literal["free", "low", "medium", "high"]
RiskLevel = Literal[
    "good",
    "moderate",
    "unhealthy_sensitive",
    "unhealthy",
    "very_unhealthy",
    "hazardous",
]

_ALLOWED_CITY_PUNCTUATION = frozenset(" .,'-")


# ----------------------------------------------------------------- requests
class Household(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adults: int = Field(1, ge=0, le=10)
    children: int = Field(0, ge=0, le=10)
    seniors: int = Field(0, ge=0, le=10)
    respiratory_condition: bool = False

    @model_validator(mode="after")
    def _at_least_one_person(self) -> "Household":
        if self.adults + self.children + self.seniors < 1:
            raise ValueError("household must include at least one person")
        return self


class AdviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    city: str = Field(min_length=2, max_length=80)
    household: Household = Field(default_factory=Household)
    commute_mode: CommuteMode = "wfh"
    commute_minutes_each_way: int = Field(0, ge=0, le=240)
    cooking_fuel: CookingFuel = "lpg"
    heating: HeatingType = "none"
    has_purifier: bool = False
    outdoor_exercise_minutes: int = Field(0, ge=0, le=240)
    neighbourhood_households: int = Field(50, ge=1, le=10_000)
    # Optional reading from the user's own monitor or a local station.
    pm25_override: float | None = Field(None, ge=0, le=1000)

    @field_validator("city")
    @classmethod
    def _city_is_plain_text(cls, value: str) -> str:
        value = " ".join(value.split())
        allowed = all(c.isalpha() or c in _ALLOWED_CITY_PUNCTUATION for c in value)
        if len(value) < 2 or not allowed:
            raise ValueError("city may contain only letters, spaces and . , ' -")
        return value


# ---------------------------------------------------------------- responses
class Place(BaseModel):
    name: str
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    verified: bool = False


class AirInfo(BaseModel):
    pm25: float
    aqi: int
    category: RiskLevel
    category_label: str
    times_who_guideline: float
    source: str
    observed_at: str | None = None
    user_supplied: bool = False


class Risk(BaseModel):
    level: RiskLevel
    label: str
    headline: str


class Dose(BaseModel):
    total_ug: float
    home_ug: float
    commute_ug: float
    exercise_ug: float


class Action(BaseModel):
    id: str
    title: str
    detail: str
    cost_tier: CostTier
    exposure_reduction_ug: float
    exposure_reduction_pct: float
    co2e_kg_saved_per_day: float
    note: str | None = None


class CleanWindow(BaseModel):
    hour: int | None
    pm25: float | None
    advice: str


class MemberNote(BaseModel):
    group: str
    advice: str


class Community(BaseModel):
    households: int
    co2e_kg_saved_per_day: float
    pledges: list[str]


class Explanation(BaseModel):
    summary: str
    source: Literal["gemini", "rules"]


class AdviceResponse(BaseModel):
    place: Place
    air: AirInfo
    risk: Risk
    dose: Dose
    actions: list[Action]
    combined_reduction_pct: float
    clean_window: CleanWindow
    member_notes: list[MemberNote]
    community: Community
    explanation: Explanation
    disclaimer: str
