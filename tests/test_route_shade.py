"""OSM building-height and deterministic shadow geometry behavior."""

from datetime import datetime
import math
from zoneinfo import ZoneInfo

import pytest
from shapely.geometry import LineString, Polygon

from app.domain.route_shade import (
    BuildingFootprint,
    BuildingHeightQuality,
    SolarPosition,
    classify_building_height,
    parse_height,
    route_shade_percent,
    solar_position,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12", 12.0),
        ("12 m", 12.0),
        ("40 ft", 12.192),
        ("10'6\"", 3.2004),
    ],
)
def test_parse_height_accepts_supported_osm_forms(raw: str, expected: float) -> None:
    assert parse_height(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "0", "-2", "10;12", "10-12", "ten"])
def test_parse_height_rejects_missing_ambiguous_or_nonpositive_values(raw: object) -> None:
    assert parse_height(raw) is None


def test_explicit_height_precedes_levels_and_invalid_height_falls_back() -> None:
    assert classify_building_height({"height": "12", "building:levels": "9"}) == (
        12.0,
        BuildingHeightQuality.EXPLICIT,
    )
    assert classify_building_height({"height": "unknown", "building:levels": "4"}) == (
        12.0,
        BuildingHeightQuality.INFERRED_LEVELS,
    )
    assert classify_building_height({"building:levels": "0"}) == (
        None,
        BuildingHeightQuality.UNKNOWN,
    )


def test_solar_position_distinguishes_summer_daytime_and_nighttime() -> None:
    zone = ZoneInfo("America/Chicago")
    noon = solar_position(datetime(2026, 6, 21, 13, tzinfo=zone), 29.42, -98.49)
    night = solar_position(datetime(2026, 6, 21, 1, tzinfo=zone), 29.42, -98.49)

    assert noon.elevation_degrees > 70
    assert night.elevation_degrees < 0
    assert 0 <= noon.azimuth_degrees < 360


def test_nighttime_has_zero_modeled_building_shade() -> None:
    route = LineString([(-98.49, 29.42), (-98.489, 29.42)])
    building = BuildingFootprint(
        "way/1",
        Polygon(
            [
                (-98.4896, 29.4199),
                (-98.4895, 29.4199),
                (-98.4895, 29.4201),
                (-98.4896, 29.4201),
            ]
        ),
        12.0,
        BuildingHeightQuality.EXPLICIT,
    )

    assert route_shade_percent(route, (building,), SolarPosition(180.0, 0.0)) == 0.0


def test_shadow_union_returns_a_bounded_finite_percentage() -> None:
    route = LineString([(-98.49, 29.42), (-98.489, 29.42)])
    building = BuildingFootprint(
        "way/1",
        Polygon(
            [
                (-98.4896, 29.42002),
                (-98.4895, 29.42002),
                (-98.4895, 29.42012),
                (-98.4896, 29.42012),
            ]
        ),
        20.0,
        BuildingHeightQuality.EXPLICIT,
    )

    shade = route_shade_percent(route, (building,), SolarPosition(0.0, 45.0))

    assert math.isfinite(shade)
    assert 0 < shade <= 100
