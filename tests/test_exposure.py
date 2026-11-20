import math

import pytest

from app.services.exposure import (
    Lifestyle,
    aqi_category,
    clean_hour_ratio,
    cleanest_hour,
    commute_emissions_kg,
    daily_dose,
    pm25_to_aqi,
)


@pytest.mark.parametrize(
    "pm25, expected",
    [(0, 0), (9.0, 50), (35.4, 100), (55.4, 150), (125.4, 200), (225.4, 300), (500, 500)],
)
def test_pm25_to_aqi_breakpoints(pm25, expected):
    assert pm25_to_aqi(pm25) == expected


def test_pm25_to_aqi_is_capped_above_scale():
    assert pm25_to_aqi(900) == 500


def test_pm25_to_aqi_is_monotonic():
    values = [pm25_to_aqi(x / 2) for x in range(0, 1001)]
    assert values == sorted(values)


@pytest.mark.parametrize("bad", [-1, float("nan")])
def test_pm25_to_aqi_rejects_invalid(bad):
    with pytest.raises(ValueError):
        pm25_to_aqi(bad)


@pytest.mark.parametrize(
    "aqi, label",
    [(0, "good"), (50, "good"), (51, "moderate"), (150, "unhealthy_sensitive"),
     (151, "unhealthy"), (250, "very_unhealthy"), (301, "hazardous"), (500, "hazardous")],
)
def test_aqi_category(aqi, label):
    assert aqi_category(aqi) == label


def test_dose_is_zero_with_clean_air_and_no_sources():
    style = Lifestyle(cooking_fuel="electric", heating="none")
    dose = daily_dose(0.0, style)
    # electric cooking still has a small indoor source
    assert dose.commute == 0 and dose.exercise == 0
    assert dose.home > 0


def test_dose_increases_with_pollution():
    style = Lifestyle(commute_mode="walk", commute_minutes_each_way=30)
    assert daily_dose(200, style).total > daily_dose(50, style).total


def test_wfh_has_no_commute_dose():
    assert daily_dose(150, Lifestyle(commute_mode="wfh", commute_minutes_each_way=60)).commute == 0


def test_mask_reduces_open_commute_but_not_car():
    walk = Lifestyle(commute_mode="walk", commute_minutes_each_way=30)
    masked = walk.with_changes(mask_on_commute=True)
    assert daily_dose(150, masked).commute == pytest.approx(daily_dose(150, walk).commute * 0.5)
    car = Lifestyle(commute_mode="car", commute_minutes_each_way=30)
    assert daily_dose(150, car.with_changes(mask_on_commute=True)).commute == daily_dose(150, car).commute


def test_purifier_and_sealing_reduce_home_dose():
    base = Lifestyle()
    home = daily_dose(150, base).home
    assert daily_dose(150, base.with_changes(purifier="hepa")).home < home
    assert daily_dose(150, base.with_changes(purifier="diy")).home < home
    assert daily_dose(150, base.with_changes(sealed_home=True)).home < home
    assert daily_dose(150, base.with_changes(purifier="hepa")).home < daily_dose(
        150, base.with_changes(purifier="diy")
    ).home


def test_biomass_cooking_dominates_and_venting_helps():
    biomass = Lifestyle(cooking_fuel="biomass")
    lpg = Lifestyle(cooking_fuel="lpg")
    assert daily_dose(50, biomass).home > daily_dose(50, lpg).home
    assert daily_dose(50, biomass.with_changes(vented_cooking=True)).home < daily_dose(50, biomass).home


def test_indoor_exercise_beats_outdoor_on_smoggy_day():
    style = Lifestyle(exercise_minutes=45)
    outdoor = daily_dose(200, style).exercise
    indoor = daily_dose(200, style.with_changes(exercise="indoor")).exercise
    assert indoor < outdoor


def test_clean_hour_exercise_uses_ratio():
    style = Lifestyle(exercise_minutes=45)
    normal = daily_dose(100, style).exercise
    clean = daily_dose(100, style.with_changes(exercise="clean_hour"), clean_hour_ratio=0.5).exercise
    assert clean == pytest.approx(normal * 0.5)


def test_time_budget_never_negative():
    style = Lifestyle(commute_mode="bus", commute_minutes_each_way=240, exercise_minutes=240)
    dose = daily_dose(100, style)
    assert dose.home >= 0 and not math.isnan(dose.total)


def test_commute_emissions_ordering_and_carpool():
    assert commute_emissions_kg("walk", 30) == 0
    assert commute_emissions_kg("car", 30) > commute_emissions_kg("metro", 30)
    assert commute_emissions_kg("car", 30, occupants=2) == pytest.approx(
        commute_emissions_kg("car", 30) / 2
    )


def test_cleanest_hour_picks_minimum_in_waking_window():
    hourly = [100.0] * 24
    hourly[3] = 1.0  # outside 8-20 window, ignored
    hourly[15] = 40.0
    assert cleanest_hour(hourly) == (15, 40.0)


def test_cleanest_hour_handles_missing_data():
    assert cleanest_hour([]) is None
    assert cleanest_hour([None] * 24) is None
    assert cleanest_hour([None] * 10 + [30.0] + [None] * 13) == (10, 30.0)


def test_clean_hour_ratio_is_bounded():
    assert clean_hour_ratio([], 10) == 1.0
    assert clean_hour_ratio([100.0] * 24, 1.0) == 0.2
    assert clean_hour_ratio([100.0] * 24, 500.0) == 1.0
    assert clean_hour_ratio([0.0] * 24, 5.0) == 1.0
