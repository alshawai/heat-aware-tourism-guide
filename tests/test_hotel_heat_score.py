import math

import pytest
from shapely.geometry import Polygon

from app.domain.analysis import SpatialMetadata, TileGeometry
from app.domain.hotel_heat_score import (
    COMPONENTS,
    DEFAULT_WEIGHT_LABEL,
    DEFAULT_WEIGHTS,
    ComponentEvidence,
    NeighbourhoodHeatScorer,
)
from app.domain.hotels import HotelCandidate, OsmIdentity


AOI = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])


def hotel(identity: int, longitude: float, latitude: float = 0.005) -> HotelCandidate:
    osm_identity = OsmIdentity("node", identity)
    return HotelCandidate(osm_identity, (osm_identity,), f"Hotel {identity}", latitude, longitude)


def evidence(component: str, values: list[float]) -> ComponentEvidence:
    unit = "C" if component in {"night", "day"} else "hours"
    threshold = 35.0 if component in {"hot_hours", "persistence"} else None
    tiles = tuple(
        TileGeometry(
            f"{component}-{index}",
            Polygon(
                [
                    (index * 0.001, 0),
                    ((index + 1) * 0.001, 0),
                    ((index + 1) * 0.001, 0.01),
                    (index * 0.001, 0.01),
                ]
            ),
            value,
            SpatialMetadata(metric=component, unit=unit, source="fixture"),
        )
        for index, value in enumerate(values)
    )
    return ComponentEvidence(
        component=component,
        tiles=tiles,
        unit=unit,
        threshold_celsius=threshold,
        provenance="district-fixture",
        tile_resolution_m=80.0,
    )


def complete_evidence(values: list[float]) -> dict[str, ComponentEvidence]:
    return {component: evidence(component, values) for component in COMPONENTS}


def test_assignment_uses_spatial_join_and_preserves_evidence_metadata() -> None:
    scorer = NeighbourhoodHeatScorer()
    assignments = scorer.assign(
        [hotel(1, 0.0005), hotel(2, 0.00505)],
        complete_evidence([10, 20, 30, 40, 50]),
        aoi=AOI,
    )

    first = assignments[0].components["night"]
    assert first.value == 10
    assert first.tile_id == "night-0"
    assert first.tile_resolution_m == 80.0
    assert first.quality == "containing_tile"
    assert first.unit == "C"
    assert first.threshold_celsius is None
    assert first.provenance == "district-fixture"

    fallback = assignments[1].components["hot_hours"]
    assert fallback.value == 50
    assert fallback.tile_id == "hot_hours-4"
    assert fallback.quality == "nearest_fallback"
    assert fallback.distance_m is not None and fallback.distance_m < 100
    assert fallback.threshold_celsius == 35.0


def test_score_uses_dense_component_percentiles_and_competition_ranking() -> None:
    scorer = NeighbourhoodHeatScorer()
    assignments = scorer.assign(
        [
            hotel(index + 1, longitude)
            for index, longitude in enumerate([0.0004, 0.0014, 0.0024, 0.0034, 0.0044])
        ],
        complete_evidence([10, 10, 20, 30, 40]),
        aoi=AOI,
    )

    result = scorer.score(assignments)

    assert result.weights == DEFAULT_WEIGHTS
    assert result.weight_label == DEFAULT_WEIGHT_LABEL == "product defaults"
    assert result.complete_candidate_count == 5
    assert result.ranked_output is True
    assert [item.rank for item in result.hotels] == [1, 1, 3, 4, 5]
    assert [item.relative_aggregate for item in result.hotels] == [
        0.0,
        0.0,
        0.333333,
        0.666667,
        1.0,
    ]
    assert result.hotels[0].components["night"].percentile == 100.0
    assert result.hotels[1].components["night"].percentile == 100.0
    assert result.hotels[2].components["night"].percentile == pytest.approx(200 / 3)


def test_hotels_in_the_same_tile_keep_the_same_assignment_and_tie() -> None:
    scorer = NeighbourhoodHeatScorer()
    assignments = scorer.assign(
        [hotel(1, 0.0004), hotel(2, 0.0006)]
        + [hotel(index, index * 0.001 + 0.0005) for index in range(3, 6)],
        complete_evidence([10, 20, 30, 40, 50]),
        aoi=AOI,
    )

    result = scorer.score(assignments)

    assert assignments[0].components["night"].tile_id == "night-0"
    assert assignments[1].components["night"].tile_id == "night-0"
    assert result.hotels[0].rank == result.hotels[1].rank == 1


def test_incomplete_hotels_remain_visible_and_fewer_than_five_complete_are_unranked() -> None:
    scorer = NeighbourhoodHeatScorer()
    all_evidence = complete_evidence([10, 20, 30, 40])
    assignments = scorer.assign(
        [
            hotel(index + 1, longitude)
            for index, longitude in enumerate([0.0005, 0.0015, 0.0025, 0.0035, 0.009])
        ],
        all_evidence,
        aoi=AOI,
    )

    result = scorer.score(assignments)

    assert result.complete_candidate_count == 4
    assert result.ranked_output is False
    assert len(result.hotels) == 5
    assert all(item.rank is None for item in result.hotels)
    assert result.hotels[-1].complete is False
    assert result.hotels[-1].relative_aggregate is None
    assert result.hotels[-1].components["day"].quality == "no_match"


def test_custom_weights_recompute_locally_and_are_labelled_custom() -> None:
    scorer = NeighbourhoodHeatScorer()
    assignments = scorer.assign(
        [hotel(index + 1, index * 0.001 + 0.0005) for index in range(5)],
        {
            "night": evidence("night", [10, 20, 30, 40, 50]),
            "hot_hours": evidence("hot_hours", [5, 4, 3, 2, 1]),
            "persistence": evidence("persistence", [1, 1, 1, 1, 1]),
            "day": evidence("day", [1, 1, 1, 1, 1]),
        },
        aoi=AOI,
    )

    custom = scorer.score(
        assignments,
        weights={"night": 0.0, "hot_hours": 1.0, "persistence": 0.0, "day": 0.0},
    )

    assert custom.weight_label == "custom"
    assert [item.identity.object_id for item in custom.hotels] == [5, 4, 3, 2, 1]
    assert [item.rank for item in custom.hotels] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize(  # type: ignore[misc]
    "weights",
    [
        {"night": 0.5, "hot_hours": 0.25, "persistence": 0.25},
        {"night": -0.1, "hot_hours": 0.4, "persistence": 0.4, "day": 0.3},
        {"night": math.nan, "hot_hours": 0.25, "persistence": 0.25, "day": 0.5},
        {"night": 0.5, "hot_hours": 0.25, "persistence": 0.25, "day": 0.002},
    ],
)
def test_custom_weights_must_be_complete_finite_nonnegative_and_sum_within_tolerance(
    weights: dict[str, float],
) -> None:
    with pytest.raises(ValueError, match="weights"):
        NeighbourhoodHeatScorer().score((), weights=weights)


def test_evidence_requires_exact_components() -> None:
    with pytest.raises(ValueError, match="components"):
        NeighbourhoodHeatScorer().assign([], {"night": evidence("night", [10])}, aoi=AOI)
