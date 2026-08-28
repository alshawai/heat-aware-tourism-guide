import math

import pytest

from app.conversion import TemperatureConversion, fahrenheit_to_celsius, normalize_temperature


def test_fahrenheit_to_celsius_known_values() -> None:
    assert fahrenheit_to_celsius(32) == pytest.approx(0.0)
    assert fahrenheit_to_celsius(212) == pytest.approx(100.0)
    assert fahrenheit_to_celsius(95) == pytest.approx(35.0)


def test_fahrenheit_to_celsius_preserves_precision() -> None:
    result = fahrenheit_to_celsius(98.6)
    assert math.isfinite(result)
    assert result == pytest.approx(37.0, abs=0.01)


def test_normalize_temperature_celsius_passthrough() -> None:
    conv = normalize_temperature(35.0, source_unit="C", unit_provenance="explicit")
    assert conv == TemperatureConversion(35.0, "C", 35.0, "C", False, "explicit")
    assert not conv.converted
    assert conv.unit_provenance == "explicit"


def test_normalize_temperature_fahrenheit_conversion() -> None:
    conv = normalize_temperature(95.0, source_unit="F", unit_provenance="explicit")
    assert conv.original_value == 95.0
    assert conv.original_unit == "F"
    assert conv.normalized_value == pytest.approx(35.0)
    assert conv.normalized_unit == "C"
    assert conv.converted is True
    assert conv.unit_provenance == "explicit"


def test_normalize_temperature_inferred_provenance() -> None:
    conv = normalize_temperature(35.0, source_unit="C", unit_provenance="inferred")
    assert conv.unit_provenance == "inferred"
    assert not conv.converted


def test_normalize_temperature_rejects_unsupported_unit() -> None:
    with pytest.raises(ValueError, match="unsupported temperature unit"):
        normalize_temperature(300.0, source_unit="K", unit_provenance="explicit")
