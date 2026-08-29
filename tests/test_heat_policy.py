import pytest

from app.domain.contracts import HeatMetricName
from app.domain.heat_policy import HeatBand, GuidancePolicy, classify_heat
from app.conversion import fahrenheit_to_celsius


@pytest.mark.parametrize(  # type: ignore[misc]
    ("fahrenheit", "celsius"),
    [(80, 26.6666666667), (90, 32.2222222222), (105, 40.5555555556), (130, 54.4444444444)],
)
def test_noaa_boundaries_convert_to_celsius(fahrenheit: float, celsius: float) -> None:
    assert fahrenheit_to_celsius(fahrenheit) == pytest.approx(celsius)


@pytest.mark.parametrize(  # type: ignore[misc]
    ("value", "band"),
    [
        (26.6, HeatBand.BELOW_CAUTION),
        (26.7, HeatBand.CAUTION),
        (32.2, HeatBand.EXTREME_CAUTION),
        (40.6, HeatBand.DANGER),
        (54.4, HeatBand.DANGER),
        (54.5, HeatBand.EXTREME_DANGER),
    ],
)
def test_actual_heat_index_uses_noaa_bands(value: float, band: HeatBand) -> None:
    result = classify_heat(value, metric=HeatMetricName.HEAT_INDEX_CELSIUS)
    assert result.band is band
    assert result.is_actual_heat_index is True


def test_provider_tcm_never_uses_noaa_category() -> None:
    result = classify_heat(38, metric=HeatMetricName.TCM)
    assert result.band is HeatBand.PROVIDER_HIGHER
    assert result.is_actual_heat_index is False
    assert result.band_label == "Higher provider temperature"


def test_missing_heat_index_is_explicit() -> None:
    result = classify_heat(None, metric=HeatMetricName.HEAT_INDEX_CELSIUS)
    assert result.band is None
    assert result.band_label == "NOAA Heat Index unavailable"


def test_cautious_guidance_moves_action_band_one_band_earlier() -> None:
    result = classify_heat(38, metric=HeatMetricName.HEAT_INDEX_CELSIUS, cautious=True)
    assert result.band is HeatBand.EXTREME_CAUTION
    assert result.action_band is HeatBand.CAUTION
    assert result.guidance_policy is GuidancePolicy.CAUTIOUS
    assert result.policy_applied == "cautious_guidance_one_band_earlier"


def test_cautious_guidance_does_not_change_provider_value() -> None:
    result = classify_heat(38, metric=HeatMetricName.TCM, cautious=True)
    assert result.value_celsius == 38
    assert result.action_band is HeatBand.PROVIDER_MODERATE
