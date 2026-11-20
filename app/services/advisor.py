"""Orchestrates one advice request: air data -> exposure model -> rules -> narrative."""

from __future__ import annotations

from app.schemas import (
    AdviceRequest,
    AdviceResponse,
    AirInfo,
    CleanWindow,
    Community,
    Dose,
    Explanation,
    Household,
    Place,
    Risk,
)
from app.services import rules
from app.services.aqi_client import AirQualityClient, AirReading
from app.services.exposure import (
    WHO_PM25_24H,
    Lifestyle,
    aqi_category,
    clean_hour_ratio,
    cleanest_hour,
    daily_dose,
    pm25_to_aqi,
)
from app.services.llm import Explainer, build_facts, clean_summary

DISCLAIMER = (
    "Estimates for comparing choices, not medical advice. Numbers come from a "
    "simplified exposure model and a forecast. If anyone has breathing "
    "difficulty, follow their doctor's plan or seek medical care."
)


def _household_summary(h: Household) -> str:
    parts = []
    if h.adults:
        parts.append(f"{h.adults} adult(s)")
    if h.children:
        parts.append(f"{h.children} child(ren)")
    if h.seniors:
        parts.append(f"{h.seniors} older adult(s)")
    if h.respiratory_condition:
        parts.append("someone with a respiratory or heart condition")
    return ", ".join(parts)


async def _resolve_air(
    req: AdviceRequest, air: AirQualityClient
) -> tuple[Place, AirReading, str, bool]:
    """Return (place, reading, source label, user_supplied)."""
    if req.pm25_override is not None:
        place = Place(name=req.city)
        reading = AirReading(pm25=req.pm25_override, observed_at=None)
        return place, reading, "Your own reading", True

    geo = await air.geocode(req.city)
    reading = await air.air_quality(geo)
    place = Place(
        name=geo.name,
        country=geo.country,
        latitude=geo.latitude,
        longitude=geo.longitude,
        verified=True,
    )
    return place, reading, "Open-Meteo CAMS air-quality model", False


async def build_advice(
    req: AdviceRequest, air: AirQualityClient, explainer: Explainer
) -> AdviceResponse:
    place, reading, source, user_supplied = await _resolve_air(req, air)

    pm25 = round(reading.pm25, 1)
    aqi = pm25_to_aqi(pm25)
    category = aqi_category(aqi)
    level = rules.household_risk(category, req.household)

    best = cleanest_hour(reading.hourly)
    ratio = clean_hour_ratio(reading.hourly, best[1]) if best else 1.0

    lifestyle = Lifestyle.from_request(req)
    baseline = daily_dose(pm25, lifestyle, ratio)
    plan = rules.build_plan(pm25, lifestyle, ratio, has_hourly=best is not None)

    place_label = place.name if not place.country else f"{place.name}, {place.country}"
    top = plan.actions[0] if plan.actions else None
    summary = rules.template_summary(
        place_label,
        pm25,
        aqi,
        rules.RISK_LABELS[category],
        pm25 / WHO_PM25_24H,
        top,
        plan.combined_reduction_pct,
    )
    source_tag = "rules"
    if explainer.enabled and plan.actions:
        facts = build_facts(
            place_label,
            pm25,
            aqi,
            rules.RISK_LABELS[level],
            _household_summary(req.household),
            [a.model_dump() for a in plan.actions],
            plan.combined_reduction_pct,
        )
        generated = clean_summary(await explainer.summarise(facts))
        if generated:
            summary, source_tag = generated, "gemini"

    return AdviceResponse(
        place=place,
        air=AirInfo(
            pm25=pm25,
            aqi=aqi,
            category=category,
            category_label=rules.RISK_LABELS[category],
            times_who_guideline=round(pm25 / WHO_PM25_24H, 1),
            source=source,
            observed_at=reading.observed_at,
            user_supplied=user_supplied,
        ),
        risk=Risk(
            level=level,
            label=rules.RISK_LABELS[level],
            headline=rules.RISK_HEADLINES[level],
        ),
        dose=Dose(
            total_ug=round(baseline.total, 1),
            home_ug=round(baseline.home, 1),
            commute_ug=round(baseline.commute, 1),
            exercise_ug=round(baseline.exercise, 1),
        ),
        actions=plan.actions,
        combined_reduction_pct=plan.combined_reduction_pct,
        clean_window=CleanWindow(
            hour=best[0] if best else None,
            pm25=round(best[1], 1) if best else None,
            advice=rules.clean_window_advice(
                best[0] if best else None, best[1] if best else None
            ),
        ),
        member_notes=rules.member_notes(req.household, level),
        community=Community(
            households=req.neighbourhood_households,
            co2e_kg_saved_per_day=round(
                plan.co2e_kg_saved_per_day * req.neighbourhood_households, 1
            ),
            pledges=list(rules.COMMUNITY_PLEDGES),
        ),
        explanation=Explanation(summary=summary, source=source_tag),  # type: ignore[arg-type]
        disclaimer=DISCLAIMER,
    )
