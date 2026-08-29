"""Metric-specific heat interpretation and cautious-guidance policy."""

from __future__ import annotations

import math

from app.conversion import fahrenheit_to_celsius
from app.domain.contracts import (
    GuidancePolicy,
    HEAT_BAND_LABELS,
    HeatBand,
    HeatInterpretation,
    HeatMetricName,
)

HeatBand = HeatBand
GuidancePolicy = GuidancePolicy
HeatInterpretation = HeatInterpretation


NOAA_BOUNDARIES_FAHRENHEIT = (80.0, 90.0, 105.0, 130.0)
NOAA_BOUNDARIES_CELSIUS = tuple(
    fahrenheit_to_celsius(value) for value in NOAA_BOUNDARIES_FAHRENHEIT
)
# Product TCM bands are deliberately separate from NOAA Heat Index boundaries.
PROVIDER_TCM_BOUNDARIES_CELSIUS = (30.0, 35.0, 40.0)

_NOAA_ORDER = (
    HeatBand.BELOW_CAUTION,
    HeatBand.CAUTION,
    HeatBand.EXTREME_CAUTION,
    HeatBand.DANGER,
    HeatBand.EXTREME_DANGER,
)
_PROVIDER_ORDER = (
    HeatBand.PROVIDER_LOWER,
    HeatBand.PROVIDER_MODERATE,
    HeatBand.PROVIDER_HIGHER,
    HeatBand.PROVIDER_VERY_HIGH,
)


def classify_heat(
    value_celsius: float | None,
    *,
    metric: HeatMetricName,
    cautious: bool = False,
    noaa_heat_index_available: bool | None = None,
) -> HeatInterpretation:
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
    noaa_available = (
        metric is HeatMetricName.HEAT_INDEX_CELSIUS and value_celsius is not None
        if noaa_heat_index_available is None
        else noaa_heat_index_available
    )
    if not isinstance(noaa_available, bool):
        raise ValueError("NOAA Heat Index availability must be a boolean")
    if metric is HeatMetricName.HEAT_INDEX_CELSIUS and noaa_available and value_celsius is None:
        raise ValueError("available NOAA Heat Index requires a value")
    actual_heat_index = (
        metric is HeatMetricName.HEAT_INDEX_CELSIUS and value_celsius is not None and noaa_available
    )
    if value_celsius is None:
        return HeatInterpretation(
            metric=metric,
            value_celsius=None,
            band=None,
            band_label="NOAA Heat Index unavailable"
            if metric is HeatMetricName.HEAT_INDEX_CELSIUS
            else "Provider temperature unavailable",
            action_threshold_band=None,
            guidance_policy=policy,
            is_actual_heat_index=False,
            noaa_heat_index_available=noaa_available,
            action_required=False,
            policy_applied="no_heat_index_available"
            if metric is HeatMetricName.HEAT_INDEX_CELSIUS
            else "metric_unavailable",
        )

    if actual_heat_index:
        band = _noaa_band(value_celsius)
        order: tuple[HeatBand, ...] = _NOAA_ORDER
    else:
        band = _provider_band(value_celsius)
        order = _PROVIDER_ORDER
    index = order.index(band)
    default_threshold = 2
    threshold_index = max(default_threshold - 1, 0) if cautious else default_threshold
    action_threshold_band = order[threshold_index]
    action_required = index >= threshold_index
    return HeatInterpretation(
        metric=metric,
        value_celsius=float(value_celsius),
        band=band,
        band_label=HEAT_BAND_LABELS[band],
        action_threshold_band=action_threshold_band,
        guidance_policy=policy,
        is_actual_heat_index=actual_heat_index,
        noaa_heat_index_available=noaa_available,
        action_required=action_required,
        policy_applied=(
            "cautious_guidance_one_band_earlier" if cautious else "standard_heat_guidance"
        ),
    )


def _noaa_band(value: float) -> HeatBand:
    first, second, third, fourth = NOAA_BOUNDARIES_CELSIUS
    if value < first:
        return HeatBand.BELOW_CAUTION
    if value < second:
        return HeatBand.CAUTION
    if value < third:
        return HeatBand.EXTREME_CAUTION
    if value < fourth:
        return HeatBand.DANGER
    return HeatBand.EXTREME_DANGER


def _provider_band(value: float) -> HeatBand:
    first, second, third = PROVIDER_TCM_BOUNDARIES_CELSIUS
    if value < first:
        return HeatBand.PROVIDER_LOWER
    if value < second:
        return HeatBand.PROVIDER_MODERATE
    if value < third:
        return HeatBand.PROVIDER_HIGHER
    return HeatBand.PROVIDER_VERY_HIGH
