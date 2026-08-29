from app.domain.best_time import assess_hour, select_best_time
from app.domain.contracts import HeatMetricName


def test_selects_coolest_when_no_concerns() -> None:
    profiles = (
        assess_hour(8, tcm_celsius=31.0, parameters={}),
        assess_hour(9, tcm_celsius=29.0, parameters={}),
    )

    decision = select_best_time(profiles, cautious=False)

    assert decision.hour == 9
    assert decision.reason == "coolest period with no environmental concerns"
    assert decision.profile.primary_thermal_metric is HeatMetricName.TCM


def test_bad_aqi_penalizes_cool_hour() -> None:
    profiles = (
        assess_hour(8, tcm_celsius=28.0, parameters={"air_quality:idx": 125.0}),
        assess_hour(9, tcm_celsius=30.0, parameters={"air_quality:idx": 25.0}),
    )

    decision = select_best_time(profiles, cautious=False)

    assert decision.hour == 9
    aqi = next(
        concern for concern in profiles[0].concerns if concern.parameter == "air_quality:idx"
    )
    assert (aqi.concern_level, aqi.threshold, aqi.threshold_source) == (
        "high",
        101.0,
        "epa_aqi",
    )


def test_concern_profile_is_complete_and_missing_values_are_not_penalized() -> None:
    missing = assess_hour(8, tcm_celsius=29.0, parameters={})
    available = assess_hour(
        9,
        tcm_celsius=29.0,
        parameters={"precipitation_mm": 0.2, "wet_bulb_temperature_celsius": 32.0},
    )

    decision = select_best_time((available, missing), cautious=False)

    assert len(missing.concerns) == 17
    assert missing.not_reported_count == 17
    assert missing.elevated_count == missing.high_count == 0
    assert decision.hour == 8
    wet_bulb = next(
        concern
        for concern in available.concerns
        if concern.parameter == "wet_bulb_temperature_celsius"
    )
    assert (wet_bulb.concern_level, wet_bulb.threshold_source) == (
        "high",
        "published_physiology",
    )


def test_cautious_guidance_prefers_below_action_threshold_before_temperature() -> None:
    profiles = (
        assess_hour(8, tcm_celsius=33.0, parameters={}),
        assess_hour(9, tcm_celsius=29.0, parameters={"relative_humidity_percent": 65.0}),
    )

    assert select_best_time(profiles, cautious=False).hour == 8
    assert select_best_time(profiles, cautious=True).hour == 9


def test_equal_temperature_with_different_concerns_is_not_described_as_flat() -> None:
    profiles = (
        assess_hour(8, tcm_celsius=29.0, parameters={}),
        assess_hour(9, tcm_celsius=29.0, parameters={"air_quality:idx": 75.0}),
    )

    decision = select_best_time(profiles, cautious=False)

    assert decision.hour == 8
    assert "flat environmental profile" not in decision.reason
