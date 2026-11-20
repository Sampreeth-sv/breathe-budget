import pytest

from app.schemas import Household
from app.services import rules
from app.services.exposure import Lifestyle


def ids(plan):
    return [a.id for a in plan.actions]


def test_clean_air_suggests_no_smog_actions():
    plan = rules.build_plan(
        8.0, Lifestyle(commute_mode="walk", commute_minutes_each_way=20, cooking_fuel="electric")
    )
    assert plan.actions == []
    assert plan.combined_reduction_pct == 0


def test_kitchen_venting_is_advised_even_on_clean_days():
    plan = rules.build_plan(8.0, Lifestyle(cooking_fuel="lpg"))
    assert ids(plan) == ["vent_cooking"]


def test_smoggy_day_ranks_by_exposure_reduction():
    style = Lifestyle(commute_mode="two_wheeler", commute_minutes_each_way=40, exercise_minutes=30)
    plan = rules.build_plan(180.0, style, has_hourly=True)
    reductions = [a.exposure_reduction_ug for a in plan.actions]
    assert reductions == sorted(reductions, reverse=True)
    assert 0 < len(plan.actions) <= rules.MAX_ACTIONS
    assert all(a.exposure_reduction_pct >= 1.0 or a.co2e_kg_saved_per_day >= 0.2 for a in plan.actions)


def test_every_action_reduction_matches_the_model():
    from app.services.exposure import daily_dose

    style = Lifestyle(commute_mode="two_wheeler", commute_minutes_each_way=40)
    plan = rules.build_plan(150.0, style)
    baseline = daily_dose(150.0, style).total
    mask = next(a for a in plan.actions if a.id == "mask_commute")
    after = daily_dose(150.0, style.with_changes(mask_on_commute=True)).total
    assert mask.exposure_reduction_ug == pytest.approx(baseline - after, abs=0.1)


def test_combined_never_double_counts_alternatives():
    plan = rules.build_plan(200.0, Lifestyle())
    both_cleaners = {"hepa_purifier", "diy_air_cleaner"} <= set(ids(plan))
    assert both_cleaners  # both are offered as options...
    assert 0 < plan.combined_reduction_pct < 100  # ...but combined effect is bounded


def test_existing_purifier_is_not_recommended_again():
    plan = rules.build_plan(200.0, Lifestyle(purifier="hepa"))
    assert not {"hepa_purifier", "diy_air_cleaner"} & set(ids(plan))


def test_biomass_household_gets_clean_fuel_advice():
    plan = rules.build_plan(60.0, Lifestyle(cooking_fuel="biomass", heating="biomass"))
    assert {"clean_cooking", "clean_heating"} <= set(ids(plan))


def test_electric_cooking_has_no_vent_advice():
    plan = rules.build_plan(150.0, Lifestyle(cooking_fuel="electric"))
    assert "vent_cooking" not in ids(plan)


def test_commute_actions_need_a_commute():
    plan = rules.build_plan(150.0, Lifestyle(commute_mode="wfh"))
    assert not {"mask_commute", "transit_switch", "carpool"} & set(ids(plan))


def test_carpool_reports_emissions_saved():
    plan = rules.build_plan(150.0, Lifestyle(commute_mode="car", commute_minutes_each_way=45))
    carpool = next(a for a in plan.actions if a.id == "carpool")
    assert carpool.co2e_kg_saved_per_day > 0
    assert plan.co2e_kg_saved_per_day > 0


def test_exercise_moves_indoors_when_air_is_bad():
    plan = rules.build_plan(120.0, Lifestyle(exercise_minutes=40), has_hourly=True)
    assert "exercise_indoors" in ids(plan)
    assert "exercise_clean_hour" not in ids(plan)  # a "clean hour" is not clean enough at this level


def test_clean_hour_only_offered_with_hourly_data():
    style = Lifestyle(exercise_minutes=40)
    with_data = rules.build_plan(40.0, style, clean_ratio=0.5, has_hourly=True)
    without = rules.build_plan(40.0, style, clean_ratio=1.0, has_hourly=False)
    assert "exercise_clean_hour" in ids(with_data)
    assert "exercise_clean_hour" not in ids(without)


def test_risk_escalates_for_sensitive_households():
    plain = Household(adults=2)
    sensitive = Household(adults=1, children=1)
    assert rules.household_risk("moderate", plain) == "moderate"
    assert rules.household_risk("moderate", sensitive) == "unhealthy_sensitive"
    assert rules.household_risk("good", sensitive) == "good"
    assert rules.household_risk("hazardous", sensitive) == "hazardous"


def test_member_notes_cover_each_group_and_band():
    household = Household(adults=1, children=1, seniors=1, respiratory_condition=True)
    notes = rules.member_notes(household, "unhealthy")
    assert [n.group for n in notes] == [
        "Children", "Older adults", "Anyone with asthma, COPD or heart disease", "Adults",
    ]
    assert all(n.advice for n in notes)
    assert rules.member_notes(Household(adults=1), "good")[0].group == "Adults"


def test_clean_window_advice_cases():
    assert "isn't available" in rules.clean_window_advice(None, None)
    assert "no truly clean window" in rules.clean_window_advice(14, 90.0).lower()
    assert "10 minutes" in rules.clean_window_advice(14, 40.0)
    assert "10 to 15" in rules.clean_window_advice(14, 20.0)


def test_template_summary_mentions_key_facts():
    plan = rules.build_plan(150.0, Lifestyle(commute_mode="two_wheeler", commute_minutes_each_way=30))
    text = rules.template_summary("Delhi", 150.0, 200, "Unhealthy", 10.0, plan.actions[0], plan.combined_reduction_pct)
    assert "Delhi" in text and "150" in text and "10.0" in text
