"""Pure multi-parameter assessment and best-time selection policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.domain.contracts import HeatMetricName
from app.domain.heat_policy import classify_heat
from app.domain.environmental_parameters import ENVIRONMENT_PARAMETERS


@dataclass(frozen=True)
class ParameterThreshold:
    elevated: float
    high: float
    unit: str
    source: str


PARAMETER_THRESHOLDS: dict[str, ParameterThreshold] = {
    "heat_index_celsius": ParameterThreshold(26.7, 40.6, "C", "noaa"),
    "apparent_temperature_celsius": ParameterThreshold(30.0, 40.0, "C", "product"),
    "wet_bulb_temperature_celsius": ParameterThreshold(28.0, 32.0, "C", "published_physiology"),
    "air_quality:idx": ParameterThreshold(51.0, 101.0, "index", "epa_aqi"),
    "air_quality_pm2p5:idx": ParameterThreshold(51.0, 101.0, "index", "epa_aqi"),
    "air_quality_pm10:idx": ParameterThreshold(51.0, 101.0, "index", "epa_aqi"),
    "air_quality_no2:idx": ParameterThreshold(51.0, 101.0, "index", "epa_aqi"),
    "air_quality_o3:idx": ParameterThreshold(51.0, 101.0, "index", "epa_aqi"),
    "air_quality_so2:idx": ParameterThreshold(51.0, 101.0, "index", "epa_aqi"),
    "aqi_us_co": ParameterThreshold(51.0, 101.0, "index", "epa_aqi"),
    "relative_humidity_percent": ParameterThreshold(60.0, 80.0, "%", "product"),
    "precipitation_mm": ParameterThreshold(0.1, 5.0, "mm", "product"),
    "solar_irradiance": ParameterThreshold(400.0, 600.0, "W/m2", "product"),
}

_INFORMATIONAL_UNITS = {
    "cloud_cover_octas": "octas",
    "elevation": "m",
    "methane_ppb": "ppb",
    "co2_ppm": "ppm",
}


@dataclass(frozen=True)
class ParameterConcern:
    parameter: str
    value: float | None
    unit: str
    available: bool
    concern_level: str
    threshold: float | None
    threshold_source: str | None


@dataclass(frozen=True)
class HourlyConcernProfile:
    hour: int
    concerns: tuple[ParameterConcern, ...]
    elevated_count: int
    high_count: int
    not_reported_count: int
    primary_thermal_value: float
    primary_thermal_metric: HeatMetricName


@dataclass(frozen=True)
class BestTimeDecision:
    hour: int
    reason: str
    profile: HourlyConcernProfile


def assess_hour(
    hour: int,
    *,
    tcm_celsius: float,
    parameters: Mapping[str, float | None],
) -> HourlyConcernProfile:
    """Assess all requested environmental parameters for one available TCM hour."""
    concerns = tuple(
        _assess_parameter(name, parameters.get(name)) for name in ENVIRONMENT_PARAMETERS
    )
    heat_index = parameters.get("heat_index_celsius")
    primary_value = heat_index if heat_index is not None else tcm_celsius
    primary_metric = (
        HeatMetricName.HEAT_INDEX_CELSIUS if heat_index is not None else HeatMetricName.TCM
    )
    return HourlyConcernProfile(
        hour=hour,
        concerns=concerns,
        elevated_count=sum(concern.concern_level == "elevated" for concern in concerns),
        high_count=sum(concern.concern_level == "high" for concern in concerns),
        not_reported_count=sum(not concern.available for concern in concerns),
        primary_thermal_value=float(primary_value),
        primary_thermal_metric=primary_metric,
    )


def select_best_time(
    profiles: tuple[HourlyConcernProfile, ...], *, cautious: bool
) -> BestTimeDecision:
    """Select the least-concerning available hour with deterministic ties."""
    if not profiles:
        raise ValueError("at least one hourly concern profile is required")
    selected = min(profiles, key=lambda profile: _selection_sort_key(profile, cautious))
    return BestTimeDecision(selected.hour, _recommendation_reason(selected, profiles), selected)


def _assess_parameter(name: str, value: float | None) -> ParameterConcern:
    threshold = PARAMETER_THRESHOLDS.get(name)
    unit = threshold.unit if threshold is not None else _INFORMATIONAL_UNITS[name]
    if value is None:
        return ParameterConcern(name, None, unit, False, "not_reported", None, None)
    if threshold is None:
        return ParameterConcern(name, value, unit, True, "none", None, None)
    level = (
        "high" if value >= threshold.high else "elevated" if value >= threshold.elevated else "none"
    )
    compared_threshold = (
        threshold.high
        if level == "high"
        else threshold.elevated
        if level == "elevated"
        else threshold.elevated
    )
    return ParameterConcern(
        name,
        value,
        unit,
        True,
        level,
        compared_threshold,
        threshold.source,
    )


def _selection_sort_key(
    profile: HourlyConcernProfile, cautious: bool
) -> tuple[int, bool, int, float, int]:
    interpretation = classify_heat(
        profile.primary_thermal_value,
        metric=profile.primary_thermal_metric,
        cautious=cautious,
    )
    return (
        profile.high_count,
        interpretation.action_required,
        profile.elevated_count,
        profile.primary_thermal_value,
        profile.hour,
    )


def _recommendation_reason(
    selected: HourlyConcernProfile, profiles: tuple[HourlyConcernProfile, ...]
) -> str:
    if selected.high_count == 0 and selected.elevated_count == 0:
        if (
            len({profile.primary_thermal_value for profile in profiles}) == 1
            and len({profile.concerns for profile in profiles}) == 1
        ):
            return "flat environmental profile; earliest equally suitable period"
        return "coolest period with no environmental concerns"
    if all(profile.high_count or profile.elevated_count for profile in profiles):
        return (
            f"all periods show elevated conditions; {selected.hour:02d}:00 has the fewest concerns"
        )
    return f"lowest overall environmental concern at {selected.hour:02d}:00"
