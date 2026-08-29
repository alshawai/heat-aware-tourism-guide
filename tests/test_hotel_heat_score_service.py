from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from shapely.geometry import Polygon

from app.domain.analysis import SpatialMetadata, TileGeometry
from app.domain.contracts import ExecutionMode
from app.domain.hotel_heat_score import COMPONENTS, ComponentEvidence
from app.domain.hotels import (
    DiscoveryState,
    HotelCandidate,
    HotelDiscoveryResult,
    OsmIdentity,
)
from app.services.hotel_heat_score import HotelHeatAnalysisService, HotelHeatAnalysisState
from app.services.hotel_heat_score import build_fixture_hotel_heat_analysis_service
from app.settings import OverpassSettings


AOI = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])


def _discovery() -> HotelDiscoveryResult:
    candidates = tuple(
        HotelCandidate(
            OsmIdentity("node", index + 1),
            (OsmIdentity("node", index + 1),),
            f"Hotel {index + 1}",
            0.005,
            index * 0.001 + 0.0005,
        )
        for index in range(5)
    )
    now = datetime(2026, 8, 29, tzinfo=timezone.utc)
    return HotelDiscoveryResult(
        DiscoveryState.AVAILABLE, candidates, 6, 5, now, now, "fixture", False
    )


def _evidence(component: str) -> ComponentEvidence:
    unit = "C" if component in {"night", "day"} else "hours"
    threshold = None if unit == "C" else 35.0
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
            float(index + 1),
            SpatialMetadata(metric=component, unit=unit, source="fixture"),
        )
        for index in range(5)
    )
    return ComponentEvidence(
        component,
        tiles,
        unit,
        threshold,
        "district-fixture",
        80.0,
        coverage=0.95,
        caveats=("candidate-relative",),
    )


def test_service_loads_each_component_once_and_reranks_without_more_loads() -> None:
    calls: list[str] = []
    lock = Lock()

    def load(component: str) -> ComponentEvidence:
        with lock:
            calls.append(component)
        return _evidence(component)

    service = HotelHeatAnalysisService(_discovery, load, aoi=AOI)
    initial = service.analyze("Downtown", ExecutionMode.FIXTURE)

    assert initial.state is HotelHeatAnalysisState.AVAILABLE
    assert sorted(calls) == sorted(COMPONENTS)
    assert len(calls) == 4
    assert initial.discovered_count == 6
    assert initial.usable_count == 5
    assert initial.components["night"].coverage == 0.95
    assert initial.components["night"].caveats == ("candidate-relative",)

    reranked = service.rerank(
        initial,
        weights={"night": 1.0, "hot_hours": 0.0, "persistence": 0.0, "day": 0.0},
    )

    assert len(calls) == 4
    assert reranked.assignments is initial.assignments
    assert reranked.score is not None and reranked.score.weight_label == "custom"


def test_service_reports_missing_component_without_assigning_or_scoring() -> None:
    def load(component: str) -> ComponentEvidence | None:
        return None if component == "persistence" else _evidence(component)

    outcome = HotelHeatAnalysisService(_discovery, load, aoi=AOI).analyze(
        "Downtown", ExecutionMode.FIXTURE
    )

    assert outcome.state is HotelHeatAnalysisState.UNAVAILABLE
    assert outcome.reason == "missing_component_evidence"
    assert outcome.assignments == ()
    assert outcome.score is None
    assert outcome.components["persistence"].missing_reason == "component_not_available"
    assert outcome.components["persistence"].available is False
    assert outcome.components["persistence"].threshold_celsius == 35.0


def test_canonical_fixture_preserves_exactly_four_shared_component_analyses() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "hotel-heat-analysis.json"
    service = build_fixture_hotel_heat_analysis_service(
        fixture, district_aoi=OverpassSettings().district_aoi
    )

    outcome = service.analyze("Downtown San Antonio", ExecutionMode.FIXTURE)

    assert outcome.state is HotelHeatAnalysisState.AVAILABLE
    assert set(outcome.evidence) == set(COMPONENTS)
    assert len(outcome.evidence) == 4
    assert all(evidence.tile_resolution_m == 80.0 for evidence in outcome.evidence.values())
    assert all(evidence.tiles for evidence in outcome.evidence.values())
    assert all(
        tile.metadata.metric == component
        and tile.metadata.unit == evidence.unit
        and tile.metadata.source == evidence.provenance
        for component, evidence in outcome.evidence.items()
        for tile in evidence.tiles
    )
