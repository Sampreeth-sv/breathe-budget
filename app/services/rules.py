"""Rule engine: turns the exposure model into ranked, explainable actions.

Each intervention is a small counterfactual. We re-run the exposure model with
one habit changed and report the difference, so every "you would breathe X%
less" claim comes from the same deterministic model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.schemas import Action, CostTier, Household, MemberNote
from app.services.exposure import (
    WHO_PM25_24H,
    Lifestyle,
    commute_emissions_kg,
    daily_dose,
)

MAX_ACTIONS = 6
MIN_REDUCTION_PCT = 1.0
MIN_CO2E_KG = 0.2

# ------------------------------------------------------------------- risk
RISK_ORDER = (
    "good",
    "moderate",
    "unhealthy_sensitive",
    "unhealthy",
    "very_unhealthy",
    "hazardous",
)
RISK_LABELS = {
    "good": "Good",
    "moderate": "Moderate",
    "unhealthy_sensitive": "Unhealthy for sensitive groups",
    "unhealthy": "Unhealthy",
    "very_unhealthy": "Very unhealthy",
    "hazardous": "Hazardous",
}
RISK_HEADLINES = {
    "good": "Air is clean today. Keep your low-emission habits going.",
    "moderate": "Air is acceptable, but sensitive family members may notice it.",
    "unhealthy_sensitive": "Children, older adults and anyone with lung or heart conditions should cut outdoor time.",
    "unhealthy": "Everyone should reduce time and effort outdoors today.",
    "very_unhealthy": "Stay indoors as much as you can and keep indoor air as clean as possible.",
    "hazardous": "Emergency-level smog. Stay in, seal up and run air cleaning.",
}


def household_risk(category: str, household: Household) -> str:
    """Escalate one level when the household includes sensitive members."""
    index = RISK_ORDER.index(category)
    sensitive = household.children or household.seniors or household.respiratory_condition
    if sensitive and index >= 1:
        index = min(index + 1, len(RISK_ORDER) - 1)
    return RISK_ORDER[index]


# -------------------------------------------------------------- interventions
@dataclass(frozen=True)
class Intervention:
    id: str
    group: str  # mutually exclusive alternatives share a group
    cost_tier: CostTier
    title: str
    detail: str
    needs_poor_air: bool
    eligible: Callable[[Lifestyle, float, bool], bool]
    apply: Callable[[Lifestyle], Lifestyle]
    co2e_kg: Callable[[Lifestyle], float] = lambda s: 0.0


_OPEN_TO_TRAFFIC = {"two_wheeler", "auto_rickshaw", "bus"}
_SEVERE_PM25 = 55.5  # "unhealthy" and above
_SENSITIVE_PM25 = 35.5


def _transit_co2e(s: Lifestyle) -> float:
    before = commute_emissions_kg(s.commute_mode, s.commute_minutes_each_way)
    after = commute_emissions_kg("metro", s.commute_minutes_each_way)
    return before - after


INTERVENTIONS: tuple[Intervention, ...] = (
    Intervention(
        id="hepa_purifier",
        group="air_cleaner",
        cost_tier="high",
        title="Run a HEPA air purifier in the room you use most",
        detail=(
            "Pick one rated for your room size (look for CADR), keep doors and "
            "windows shut while it runs, and use it overnight in the bedroom."
        ),
        needs_poor_air=True,
        eligible=lambda s, pm, hourly: s.purifier == "none",
        apply=lambda s: s.with_changes(purifier="hepa"),
    ),
    Intervention(
        id="diy_air_cleaner",
        group="air_cleaner",
        cost_tier="low",
        title="Build a DIY box-fan air cleaner (Corsi-Rosenthal box)",
        detail=(
            "Tape four MERV-13 filters around a box fan. It removes fine "
            "particles for a fraction of a purifier's price. Run it where the "
            "family spends the evening."
        ),
        needs_poor_air=True,
        eligible=lambda s, pm, hourly: s.purifier == "none",
        apply=lambda s: s.with_changes(purifier="diy"),
    ),
    Intervention(
        id="seal_home",
        group="seal",
        cost_tier="low",
        title="Keep windows shut at peak hours and seal the draughty gaps",
        detail=(
            "Add door sweeps or weather-strip to the leakiest gaps. Open "
            "windows only for a short time in the cleanest hour of the day."
        ),
        needs_poor_air=True,
        eligible=lambda s, pm, hourly: not s.sealed_home,
        apply=lambda s: s.with_changes(sealed_home=True),
    ),
    Intervention(
        id="vent_cooking",
        group="cooking",
        cost_tier="low",
        title="Vent the kitchen while you cook",
        detail=(
            "Switch on the chimney or exhaust fan, crack the kitchen window and "
            "keep the kitchen door closed so smoke doesn't spread through the home."
        ),
        needs_poor_air=False,
        eligible=lambda s, pm, hourly: s.cooking_fuel != "electric" and not s.vented_cooking,
        apply=lambda s: s.with_changes(vented_cooking=True),
    ),
    Intervention(
        id="clean_cooking",
        group="cooking",
        cost_tier="medium",
        title="Move from wood, dung or coal cooking to LPG or induction",
        detail=(
            "Biomass cookstoves are a large source of indoor smoke. Clean fuel "
            "also reduces what the neighbourhood breathes."
        ),
        needs_poor_air=False,
        eligible=lambda s, pm, hourly: s.cooking_fuel == "biomass",
        apply=lambda s: s.with_changes(cooking_fuel="lpg"),
    ),
    Intervention(
        id="clean_heating",
        group="heating",
        cost_tier="medium",
        title="Replace wood, coal or charcoal heating with an electric heater and layers",
        detail=(
            "Indoor burning adds smoke exactly when outdoor air is worst. Use "
            "insulation, warm layers and a low-wattage electric heater instead."
        ),
        needs_poor_air=False,
        eligible=lambda s, pm, hourly: s.heating == "biomass",
        apply=lambda s: s.with_changes(heating="electric"),
    ),
    Intervention(
        id="transit_switch",
        group="commute",
        cost_tier="free",
        title="Take the metro or a closed, air-conditioned bus instead",
        detail=(
            "Rail and enclosed transit keep you out of tailpipe-heavy air and "
            "cut commute emissions per person."
        ),
        needs_poor_air=False,
        eligible=lambda s, pm, hourly: s.commutes and s.commute_mode in _OPEN_TO_TRAFFIC,
        apply=lambda s: s.with_changes(commute_mode="metro"),
        co2e_kg=_transit_co2e,
    ),
    Intervention(
        id="smog_day_transit",
        group="commute",
        cost_tier="free",
        title="On the worst smog days, swap walking or cycling for the metro",
        detail=(
            "Hard breathing in heavy traffic multiplies your dose. Save active "
            "commuting for cleaner days."
        ),
        needs_poor_air=True,
        eligible=lambda s, pm, hourly: (
            s.commutes and s.commute_mode in {"walk", "cycle"} and pm >= _SEVERE_PM25
        ),
        apply=lambda s: s.with_changes(commute_mode="metro"),
    ),
    Intervention(
        id="carpool",
        group="commute",
        cost_tier="free",
        title="Share the ride with one or more neighbours",
        detail=(
            "Carpooling halves per-person emissions. Keep windows closed and "
            "recirculate the air on smoggy days."
        ),
        needs_poor_air=False,
        eligible=lambda s, pm, hourly: s.commutes and s.commute_mode == "car",
        apply=lambda s: s,
        co2e_kg=lambda s: commute_emissions_kg("car", s.commute_minutes_each_way)
        - commute_emissions_kg("car", s.commute_minutes_each_way, occupants=2),
    ),
    Intervention(
        id="mask_commute",
        group="mask",
        cost_tier="low",
        title="Wear a well-fitted N95 or FFP2 mask on open commutes",
        detail=(
            "Fit matters more than the label: it should seal around the nose and "
            "chin with no gaps. Cloth and surgical masks filter far less."
        ),
        needs_poor_air=True,
        eligible=lambda s, pm, hourly: s.commutes and not s.mask_on_commute,
        apply=lambda s: s.with_changes(mask_on_commute=True),
    ),
    Intervention(
        id="exercise_indoors",
        group="exercise",
        cost_tier="free",
        title="Move today's workout indoors",
        detail=(
            "Brisk exercise multiplies how much air you breathe. Do a lighter "
            "home workout with windows shut until the air improves."
        ),
        needs_poor_air=True,
        eligible=lambda s, pm, hourly: (
            s.exercise_minutes > 0 and s.exercise == "outdoor" and pm >= _SENSITIVE_PM25
        ),
        apply=lambda s: s.with_changes(exercise="indoor"),
    ),
    Intervention(
        id="exercise_clean_hour",
        group="exercise",
        cost_tier="free",
        title="Exercise outdoors in the cleanest hour of the day",
        detail=(
            "Forecast PM2.5 changes a lot through the day. Pick the hour shown "
            "under 'Cleanest time today' instead of the early-morning or evening peak."
        ),
        needs_poor_air=True,
        eligible=lambda s, pm, has_hourly: (
            has_hourly
            and s.exercise_minutes > 0
            and s.exercise == "outdoor"
            and pm < _SEVERE_PM25
        ),
        apply=lambda s: s.with_changes(exercise="clean_hour"),
    ),
)


@dataclass(frozen=True)
class Plan:
    actions: list[Action]
    combined_reduction_pct: float
    co2e_kg_saved_per_day: float


def _pct(reduction: float, baseline: float) -> float:
    return 100.0 * reduction / baseline if baseline > 0 else 0.0


def build_plan(
    pm25: float,
    lifestyle: Lifestyle,
    clean_ratio: float = 1.0,
    has_hourly: bool = False,
) -> Plan:
    """Rank interventions by how much exposure they remove."""
    baseline = daily_dose(pm25, lifestyle, clean_ratio).total
    poor_air = pm25 >= WHO_PM25_24H
    scored: list[tuple[Intervention, Action]] = []

    for item in INTERVENTIONS:
        if item.needs_poor_air and not poor_air:
            continue
        if not item.eligible(lifestyle, pm25, has_hourly):
            continue
        after = daily_dose(pm25, item.apply(lifestyle), clean_ratio).total
        reduction = baseline - after
        pct = _pct(reduction, baseline)
        co2e = item.co2e_kg(lifestyle)
        if pct < MIN_REDUCTION_PCT and co2e < MIN_CO2E_KG:
            continue
        scored.append(
            (
                item,
                Action(
                    id=item.id,
                    title=item.title,
                    detail=item.detail,
                    cost_tier=item.cost_tier,
                    exposure_reduction_ug=round(max(reduction, 0.0), 1),
                    exposure_reduction_pct=round(max(pct, 0.0), 1),
                    co2e_kg_saved_per_day=round(max(co2e, 0.0), 2),
                ),
            )
        )

    scored.sort(
        key=lambda pair: (
            pair[1].exposure_reduction_ug,
            pair[1].co2e_kg_saved_per_day,
        ),
        reverse=True,
    )
    top = scored[:MAX_ACTIONS]

    # Combined effect: best option per mutually exclusive group, applied together.
    combined = lifestyle
    chosen_groups: set[str] = set()
    co2e_total = 0.0
    for item, action in scored:
        if item.group in chosen_groups:
            continue
        chosen_groups.add(item.group)
        combined = item.apply(combined)
        co2e_total += action.co2e_kg_saved_per_day
    combined_dose = daily_dose(pm25, combined, clean_ratio).total
    combined_pct = _pct(baseline - combined_dose, baseline)

    return Plan(
        actions=[action for _, action in top],
        combined_reduction_pct=round(min(max(combined_pct, 0.0), 100.0), 1),
        co2e_kg_saved_per_day=round(co2e_total, 2),
    )


# ------------------------------------------------------------ household notes
_BANDS = ("low", "mid", "high")


def _band(level: str) -> str:
    index = RISK_ORDER.index(level)
    if index <= 1:
        return "low"
    return "mid" if index <= 3 else "high"


_MEMBER_GUIDANCE: dict[str, dict[str, str]] = {
    "Children": {
        "low": "Normal outdoor play is fine. Keep an eye on anyone who coughs or wheezes.",
        "mid": "Shorten outdoor play, skip sports practice outside and choose indoor games.",
        "high": "Keep children indoors with windows shut. Walk or cycle to school only if there is no alternative, and wear a child-sized fitted mask if your doctor agrees.",
    },
    "Older adults": {
        "low": "Usual routines are fine. Stay hydrated and take your regular medication.",
        "mid": "Take walks in the cleanest hour or indoors, and avoid busy roads.",
        "high": "Stay in the cleanest room, limit errands and ask a neighbour or family member to help.",
    },
    "Anyone with asthma, COPD or heart disease": {
        "low": "Carry your reliever as usual and follow your doctor's action plan.",
        "mid": "Reduce exertion outdoors, keep medication within reach and follow your doctor's action plan.",
        "high": "Stay indoors with filtered air, follow your doctor's plan and seek medical help for wheezing, chest pain or breathlessness.",
    },
    "Adults": {
        "low": "No special restrictions. Take clean-air habits you can keep all winter.",
        "mid": "Cut back on hard outdoor exercise and travel in enclosed transport where possible.",
        "high": "Avoid outdoor exertion, work from home if you can and wear a fitted N95 if you must go out.",
    },
}


def member_notes(household: Household, level: str) -> list[MemberNote]:
    band = _band(level)
    groups: list[str] = []
    if household.children:
        groups.append("Children")
    if household.seniors:
        groups.append("Older adults")
    if household.respiratory_condition:
        groups.append("Anyone with asthma, COPD or heart disease")
    if household.adults:
        groups.append("Adults")
    return [MemberNote(group=g, advice=_MEMBER_GUIDANCE[g][band]) for g in groups]


# ---------------------------------------------------------- windows & community
def clean_window_advice(hour: int | None, pm25: float | None) -> str:
    if hour is None or pm25 is None:
        return "Hourly forecast isn't available. Ventilate briefly in the afternoon, when air is usually cleaner."
    if pm25 >= _SEVERE_PM25:
        return "There is no truly clean window today. Keep windows closed and rely on air cleaning."
    if pm25 >= _SENSITIVE_PM25:
        return f"The cleanest hour is around {hour:02d}:00. Open windows for no more than 10 minutes, then close them."
    return f"The cleanest hour is around {hour:02d}:00. Open windows for 10 to 15 minutes to refresh the home."


COMMUNITY_PLEDGES = (
    "Agree as a building or street not to burn leaves, waste or wood, and report open burning to the local pollution control authority.",
    "Share rides to school and work, and keep engines off while waiting.",
    "Set up one shared clean-air room with a purifier for older neighbours and young children.",
    "Stagger or avoid diesel generator use, and service generators before winter.",
    "Wet-mop or damp-dust instead of dry sweeping to keep dust down.",
    "Check in on neighbours with breathing problems on severe smog days.",
)


def template_summary(
    place: str | None,
    pm25: float,
    aqi: int,
    level_label: str,
    who_multiple: float,
    top: Action | None,
    combined_pct: float,
) -> str:
    where = place or "your area"
    text = (
        f"In {where}, PM2.5 is about {pm25:.0f} µg/m³ (AQI {aqi}, {level_label.lower()}), "
        f"roughly {who_multiple:.1f} times the WHO daily guideline."
    )
    if top is not None:
        text += (
            f" Your biggest single win is to {top.title[0].lower()}{top.title[1:]}"
            f", which could cut your daily exposure by about {top.exposure_reduction_pct:.0f}%."
        )
    if combined_pct >= 1:
        text += f" Together, the steps below could lower it by around {combined_pct:.0f}%."
    return text
