"""OSM building-height and deterministic shadow geometry behavior."""

from datetime import datetime, timedelta, timezone
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


@pytest.mark.parametrize(  # type: ignore[misc]
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


@pytest.mark.parametrize("raw", [None, "", "0", "-2", "10;12", "10-12", "ten"])  # type: ignore[misc]
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


_SAN_ANTONIO = (29.4245914, -98.4864288)
_CHICAGO = ZoneInfo("America/Chicago")
_AXIAL_TILT_DEGREES = 23.44


def test_solar_noon_elevation_matches_solstice_reference_geometry() -> None:
    """Solar-noon elevation is 90 - |latitude - declination| at each solstice."""
    latitude = _SAN_ANTONIO[0]
    summer = solar_position(datetime(2026, 6, 21, 13, 35, tzinfo=_CHICAGO), *_SAN_ANTONIO)
    winter = solar_position(datetime(2026, 12, 21, 12, 30, tzinfo=_CHICAGO), *_SAN_ANTONIO)

    assert summer.elevation_degrees == pytest.approx(90 - (latitude - _AXIAL_TILT_DEGREES), abs=0.2)
    assert winter.elevation_degrees == pytest.approx(90 - (latitude + _AXIAL_TILT_DEGREES), abs=0.2)


def test_solar_azimuth_moves_from_east_to_west_across_the_day() -> None:
    morning = solar_position(datetime(2026, 6, 21, 8, tzinfo=_CHICAGO), *_SAN_ANTONIO)
    evening = solar_position(datetime(2026, 6, 21, 19, tzinfo=_CHICAGO), *_SAN_ANTONIO)

    assert 45 < morning.azimuth_degrees < 135
    assert 225 < evening.azimuth_degrees < 315
    assert morning.elevation_degrees > 0
    assert evening.elevation_degrees > 0


def test_solar_position_depends_on_the_instant_not_the_wall_clock() -> None:
    """One instant expressed in two zones resolves to a single solar position."""
    local = datetime(2026, 6, 21, 13, tzinfo=_CHICAGO)

    assert solar_position(local, *_SAN_ANTONIO) == solar_position(
        local.astimezone(timezone.utc), *_SAN_ANTONIO
    )


def test_solar_position_honors_daylight_saving_offsets() -> None:
    """The same local hour resolves through CDT in summer and CST in winter."""
    daylight = datetime(2026, 6, 21, 13, tzinfo=_CHICAGO)
    standard = datetime(2026, 12, 21, 13, tzinfo=_CHICAGO)

    assert daylight.utcoffset() == timedelta(hours=-5)
    assert standard.utcoffset() == timedelta(hours=-6)
    assert solar_position(daylight, *_SAN_ANTONIO).elevation_degrees > 80
    assert solar_position(standard, *_SAN_ANTONIO).elevation_degrees < 40


def test_solar_position_requires_a_timezone_aware_instant() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        solar_position(datetime(2026, 6, 21, 13), *_SAN_ANTONIO)


@pytest.mark.parametrize(("latitude", "longitude"), [(91.0, 0.0), (0.0, 181.0)])  # type: ignore[misc]
def test_solar_position_rejects_out_of_range_coordinates(latitude: float, longitude: float) -> None:
    with pytest.raises(ValueError, match="out of range"):
        solar_position(datetime(2026, 6, 21, 13, tzinfo=_CHICAGO), latitude, longitude)


def test_sun_below_the_horizon_yields_no_modeled_building_shade() -> None:
    night = solar_position(datetime(2026, 6, 21, 3, tzinfo=_CHICAGO), *_SAN_ANTONIO)
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

    assert night.elevation_degrees < 0
    assert route_shade_percent(route, (building,), night) == 0.0


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
