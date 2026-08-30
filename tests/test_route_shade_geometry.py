"""Overpass building geometry normalization: rings, holes, drops, and part partitioning."""

from typing import Any

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from app.domain.route_shade import BuildingHeightQuality
from app.services.route_shade import _normalize_buildings


def _points(*coordinates: tuple[float, float]) -> list[dict[str, float]]:
    return [{"lat": latitude, "lon": longitude} for longitude, latitude in coordinates]


def _square(
    west: float, south: float, size: float, *, closed: bool = True
) -> list[dict[str, float]]:
    corners = [
        (west, south),
        (west + size, south),
        (west + size, south + size),
        (west, south + size),
    ]
    return _points(*(corners + [corners[0]] if closed else corners))


def _way(identity: int, geometry: list[dict[str, float]], **tags: str) -> dict[str, Any]:
    return {"type": "way", "id": identity, "tags": tags, "geometry": geometry}


def _relation(identity: int, members: list[dict[str, Any]], **tags: str) -> dict[str, Any]:
    return {
        "type": "relation",
        "id": identity,
        "tags": {"type": "multipolygon", **tags},
        "members": members,
    }


def _member(geometry: list[dict[str, float]] | None, role: str = "outer") -> dict[str, Any]:
    member: dict[str, Any] = {"type": "way", "ref": 1, "role": role}
    if geometry is not None:
        member["geometry"] = geometry
    return member


def _area(response: dict[str, Any]) -> float:
    buildings, _ = _normalize_buildings(response)
    return float(unary_union([building.geometry for building in buildings]).area)


def test_relation_inner_rings_become_courtyard_holes() -> None:
    outer = _square(-98.49, 29.42, 0.004)
    courtyard = _square(-98.489, 29.421, 0.002)
    response = {
        "elements": [
            _relation(
                1,
                [_member(outer, "outer"), _member(courtyard, "inner")],
                building="hotel",
                height="40",
            )
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert dropped == 0
    assert len(buildings) == 1
    geometry = buildings[0].geometry
    expected = (
        Polygon([(point["lon"], point["lat"]) for point in outer]).area
        - Polygon([(point["lon"], point["lat"]) for point in courtyard]).area
    )
    assert geometry.area == pytest.approx(expected, rel=1e-9)
    # The courtyard centre is open sky, not building.
    assert not geometry.contains(Polygon([(point["lon"], point["lat"]) for point in courtyard]))


def test_fragmented_outer_ways_are_stitched_into_one_ring() -> None:
    whole = _square(-98.49, 29.42, 0.004)
    first, second = whole[:3], whole[2:]
    response = {
        "elements": [
            _relation(
                2,
                [_member(first, "outer"), _member(second, "outer")],
                building="yes",
                height="20",
            )
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert dropped == 0
    assert len(buildings) == 1
    assert buildings[0].geometry.geom_type == "Polygon"
    assert buildings[0].geometry.area == pytest.approx(
        Polygon([(point["lon"], point["lat"]) for point in whole]).area, rel=1e-9
    )


def test_fragmented_outer_ways_stitch_regardless_of_member_direction() -> None:
    whole = _square(-98.49, 29.42, 0.004)
    first, second = whole[:3], list(reversed(whole[2:]))
    response = {
        "elements": [
            _relation(
                3,
                [_member(second, "outer"), _member(first, "outer")],
                building="yes",
                height="20",
            )
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert dropped == 0
    assert buildings[0].geometry.area == pytest.approx(
        Polygon([(point["lon"], point["lat"]) for point in whole]).area, rel=1e-9
    )


def test_a_fragmented_outer_ring_with_a_gap_drops_the_whole_relation() -> None:
    whole = _square(-98.49, 29.42, 0.004)
    detached = _points((-98.470, 29.410), (-98.469, 29.411))
    response = {
        "elements": [
            _relation(
                4,
                [_member(whole[:3], "outer"), _member(detached, "outer")],
                building="yes",
                height="20",
            )
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert buildings == ()
    assert dropped == 1


def test_malformed_relation_members_are_counted_while_valid_rings_survive() -> None:
    outer = _square(-98.49, 29.42, 0.004)
    response = {
        "elements": [
            _relation(
                5,
                [
                    _member(outer, "outer"),
                    _member(None, "outer"),
                    _member([{"lat": 91.0, "lon": -98.48}, {"lat": 29.42, "lon": -98.48}], "inner"),
                    "not a member",  # type: ignore[list-item]
                ],
                building="yes",
                height="20",
            )
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert len(buildings) == 1
    assert dropped == 3
    assert buildings[0].geometry.area == pytest.approx(
        Polygon([(point["lon"], point["lat"]) for point in outer]).area, rel=1e-9
    )


def test_a_relation_without_any_usable_outer_ring_counts_as_one_dropped_building() -> None:
    response = {
        "elements": [
            _relation(
                6,
                [_member(None, "outer"), _member(None, "inner")],
                building="yes",
                height="20",
            )
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert buildings == ()
    assert dropped == 1


def test_node_and_sub_relation_members_discard_no_area() -> None:
    outer = _square(-98.49, 29.42, 0.004)
    response = {
        "elements": [
            _relation(
                7,
                [
                    _member(outer, "outer"),
                    {"type": "node", "ref": 9, "role": "label"},
                    {"type": "relation", "ref": 8, "role": "outer"},
                ],
                building="yes",
                height="20",
            )
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert dropped == 0
    assert len(buildings) == 1


def test_inner_ring_covering_the_whole_outer_ring_leaves_no_building() -> None:
    outer = _square(-98.49, 29.42, 0.004)
    response = {
        "elements": [
            _relation(
                8,
                [_member(outer, "outer"), _member(outer, "inner")],
                building="yes",
                height="20",
            )
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert buildings == ()
    assert dropped == 1


def test_disjoint_outer_rings_stay_a_single_multipolygon_building() -> None:
    response = {
        "elements": [
            _relation(
                9,
                [
                    _member(_square(-98.49, 29.42, 0.001), "outer"),
                    _member(_square(-98.48, 29.43, 0.001), "outer"),
                ],
                building="yes",
                height="20",
            )
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert dropped == 0
    assert len(buildings) == 1
    assert buildings[0].geometry.geom_type == "MultiPolygon"


def test_parent_and_part_partitioning_preserves_total_effective_area() -> None:
    parent = _square(-98.49, 29.42, 0.004)
    part = _square(-98.489, 29.421, 0.002)
    response: dict[str, Any] = {
        "elements": [
            _way(101, parent, building="office", height="30"),
            _way(102, part, **{"building:part": "yes", "height": "70"}),
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert dropped == 0
    raw_union = unary_union(
        [
            Polygon([(point["lon"], point["lat"]) for point in parent]),
            Polygon([(point["lon"], point["lat"]) for point in part]),
        ]
    )
    effective = unary_union([building.geometry for building in buildings])
    assert effective.area == pytest.approx(raw_union.area, rel=1e-9)
    # Effective footprints partition the union: no pair overlaps.
    total = sum(building.geometry.area for building in buildings)
    assert total == pytest.approx(effective.area, rel=1e-9)


def test_a_part_keeps_its_own_height_and_never_inherits_the_parent() -> None:
    response: dict[str, Any] = {
        "elements": [
            _way(201, _square(-98.49, 29.42, 0.004), building="office", height="30"),
            _way(
                202,
                _square(-98.489, 29.421, 0.002),
                **{"building:part": "yes", "building:levels": "9"},
            ),
        ]
    }

    buildings, _ = _normalize_buildings(response)

    by_identity = {building.identity: building for building in buildings}
    assert by_identity["way/202"].height_m == pytest.approx(27.0)
    assert by_identity["way/202"].height_quality is BuildingHeightQuality.INFERRED_LEVELS
    assert by_identity["way/201"].height_m == pytest.approx(30.0)
    assert by_identity["way/201"].height_quality is BuildingHeightQuality.EXPLICIT


def test_overlapping_parts_are_never_double_counted() -> None:
    first = _square(-98.49, 29.42, 0.003)
    second = _square(-98.4885, 29.4215, 0.003)
    response: dict[str, Any] = {
        "elements": [
            _way(301, first, **{"building:part": "yes", "height": "40"}),
            _way(302, second, **{"building:part": "yes", "height": "60"}),
        ]
    }

    buildings, _ = _normalize_buildings(response)

    expected = unary_union(
        [
            Polygon([(point["lon"], point["lat"]) for point in first]),
            Polygon([(point["lon"], point["lat"]) for point in second]),
        ]
    )
    assert sum(building.geometry.area for building in buildings) == pytest.approx(
        expected.area, rel=1e-9
    )


def test_a_part_covering_its_parent_entirely_replaces_it() -> None:
    footprint = _square(-98.49, 29.42, 0.003)
    response: dict[str, Any] = {
        "elements": [
            _way(401, footprint, building="office", height="30"),
            _way(402, footprint, **{"building:part": "yes", "height": "80"}),
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert dropped == 0
    assert [building.identity for building in buildings] == ["way/402"]
    assert buildings[0].height_m == pytest.approx(80.0)


def test_an_unclosed_standalone_way_is_dropped() -> None:
    response = {
        "elements": [
            _way(501, _square(-98.49, 29.42, 0.003, closed=False), building="yes", height="20")
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert buildings == ()
    assert dropped == 1


def test_untagged_and_non_building_elements_are_skipped_without_counting_drops() -> None:
    response = {
        "elements": [
            _way(601, _square(-98.49, 29.42, 0.003), highway="footway"),
            {"type": "way", "id": 602, "geometry": _square(-98.48, 29.43, 0.003)},
            {"type": "node", "id": 603, "tags": {"building": "yes"}},
        ]
    }

    buildings, dropped = _normalize_buildings(response)

    assert buildings == ()
    assert dropped == 0


def test_a_courtyard_hole_removes_exactly_its_own_area_from_the_building() -> None:
    outer = _square(-98.49, 29.42, 0.006)
    courtyard = _square(-98.4885, 29.4215, 0.003)
    solid = _area({"elements": [_relation(701, [_member(outer, "outer")], building="yes")]})
    hollow = _area(
        {
            "elements": [
                _relation(
                    702,
                    [_member(outer, "outer"), _member(courtyard, "inner")],
                    building="yes",
                )
            ]
        }
    )

    assert hollow < solid
    assert solid - hollow == pytest.approx(
        Polygon([(point["lon"], point["lat"]) for point in courtyard]).area, rel=1e-9
    )
