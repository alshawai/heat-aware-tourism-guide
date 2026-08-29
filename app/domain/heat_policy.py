"""Metric-specific heat interpretation and cautious-guidance policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from app.domain.contracts import HeatMetricName


class HeatBand(str, Enum):
    BELOW_CAUTION = "below_caution"
    CAUTION = "caution"
    EXTREME_CAUTION = "extreme_caution"
    DANGER = "danger"
    EXTREME_DANGER = "extreme_danger"
    PROVIDER_LOWER = "provider_lower"
    PROVIDER_MODERATE = "provider_moderate"
    PROVIDER_HIGHER = "provider_higher"
    PROVIDER_DANGER = "provider_danger"


class GuidancePolicy(str, Enum):
    STANDARD = "standard"
    CAUTIOUS = "cautious"


@dataclass(frozen=True)
class HeatClassification:
    metric: HeatMetricName
    value_celsius: float | None
    band: HeatBand | None
    band_label: str
    action_band: HeatBand | None
    guidance_policy: GuidancePolicy
    is_actual_heat_index: bool
    policy_applied: str


_NOAA_BANDS = (
    (26.7, HeatBand.CAUTION),
    (32.2, HeatBand.EXTREME_CAUTION),
    (40.6, HeatBand.DANGER),
    (54.4, HeatBand.EXTREME_DANGER),
)
_NOAA_LABELS = {
    HeatBand.BELOW_CAUTION: "Below NOAA caution",
    HeatBand.CAUTION: "Caution",
    HeatBand.EXTREME_CAUTION: "Extreme caution",
    HeatBand.DANGER: "Danger",
    HeatBand.EXTREME_DANGER: "Extreme danger",
}
_PROVIDER_LABELS = {
    HeatBand.PROVIDER_LOWER: "Lower provider temperature",
    HeatBand.PROVIDER_MODERATE: "Moderate provider temperature",
    HeatBand.PROVIDER_HIGHER: "Higher provider temperature",
    HeatBand.PROVIDER_DANGER: "Very high provider temperature",
}


def classify_heat(
    value_celsius: float | None,
    *,
    metric: HeatMetricName,
    cautious: bool = False,
) -> HeatClassification:
    """Classify a Celsius value without conflating provider data with NOAA data."""
    if not isinstance(metric, HeatMetricName):
        raise ValueError("metric must be a HeatMetricName value")
    if value_celsius is not None and (
        isinstance(value_celsius, bool)
        or not isinstance(value_celsius, (int, float))
        or not math.isfinite(value_celsius)
    ):
        raise ValueError("heat value must be finite or None")
    policy = GuidancePolicy.CAUTIOUS if cautious else GuidancePolicy.STANDARD
    if value_celsius is None:
        return HeatClassification(
            metric,
            None,
            None,
            "NOAA Heat Index unavailable"
            if metric is HeatMetricName.HEAT_INDEX_CELSIUS
            else "Provider temperature unavailable",
            None,
            policy,
            metric is HeatMetricName.HEAT_INDEX_CELSIUS,
            "no_heat_index_available"
            if metric is HeatMetricName.HEAT_INDEX_CELSIUS
            else "metric_unavailable",
        )

    if metric is HeatMetricName.HEAT_INDEX_CELSIUS:
        band = _noaa_band(value_celsius)
        action_band = _shift_band(band) if cautious else band
        return HeatClassification(
            metric,
            float(value_celsius),
            band,
            _NOAA_LABELS[band],
            action_band,
            policy,
            True,
            "cautious_guidance_one_band_earlier" if cautious else "standard_noaa_guidance",
        )

    band = _provider_band(value_celsius)
    return HeatClassification(
        metric,
        float(value_celsius),
        band,
        _PROVIDER_LABELS[band],
        _shift_provider_band(band) if cautious else band,
        policy,
        False,
        "cautious_guidance_one_band_earlier" if cautious else "standard_provider_guidance",
    )


def _noaa_band(value: float) -> HeatBand:
    if value < _NOAA_BANDS[0][0]:
        return HeatBand.BELOW_CAUTION
    if value < 32.2:
        return HeatBand.CAUTION
    if value < 40.6:
        return HeatBand.EXTREME_CAUTION
    if value <= 54.4:
        return HeatBand.DANGER
    return HeatBand.EXTREME_DANGER


def _shift_band(band: HeatBand) -> HeatBand:
    order = (
        HeatBand.BELOW_CAUTION,
        HeatBand.CAUTION,
        HeatBand.EXTREME_CAUTION,
        HeatBand.DANGER,
        HeatBand.EXTREME_DANGER,
    )
    return order[max(order.index(band) - 1, 0)]


def _provider_band(value: float) -> HeatBand:
    if value < 26.7:
        return HeatBand.PROVIDER_LOWER
    if value < 32.2:
        return HeatBand.PROVIDER_MODERATE
    if value < 40.6:
        return HeatBand.PROVIDER_HIGHER
    return HeatBand.PROVIDER_DANGER


def _shift_provider_band(band: HeatBand) -> HeatBand:
    order = (
        HeatBand.PROVIDER_LOWER,
        HeatBand.PROVIDER_MODERATE,
        HeatBand.PROVIDER_HIGHER,
        HeatBand.PROVIDER_DANGER,
    )
    return order[max(order.index(band) - 1, 0)]
