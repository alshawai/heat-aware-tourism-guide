"""Centralized temperature unit conversion with full provenance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TemperatureConversion:
    """Result of a temperature unit normalization."""

    original_value: float
    original_unit: str
    normalized_value: float
    normalized_unit: str
    converted: bool
    unit_provenance: str  # "explicit" or "inferred"


def fahrenheit_to_celsius(value: float) -> float:
    """Convert Fahrenheit to Celsius without changing numerical precision."""
    return (value - 32) * 5 / 9


def normalize_temperature(
    value: float,
    *,
    source_unit: str,
    unit_provenance: str,
) -> TemperatureConversion:
    """Normalize a temperature value to Celsius, preserving original provenance."""
    if source_unit == "F":
        return TemperatureConversion(
            original_value=value,
            original_unit="F",
            normalized_value=fahrenheit_to_celsius(value),
            normalized_unit="C",
            converted=True,
            unit_provenance=unit_provenance,
        )
    if source_unit == "C":
        return TemperatureConversion(
            original_value=value,
            original_unit="C",
            normalized_value=value,
            normalized_unit="C",
            converted=False,
            unit_provenance=unit_provenance,
        )
    raise ValueError(f"unsupported temperature unit: {source_unit}")
