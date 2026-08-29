"""Provider-neutral orchestration for district hotel heat ranking."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, cast

from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry

from app.domain.analysis import SpatialMetadata, TileGeometry
from app.domain.contracts import ExecutionMode
from app.domain.provenance import AcquisitionRecord
from app.domain.hotel_heat_score import (
    COMPONENTS,
    ComponentEvidence,
    HotelHeatAssignment,
    NeighbourhoodHeatScore,
    NeighbourhoodHeatScorer,
)
from app.domain.hotels import (
    BoundingBox,
    DiscoveryState,
    HotelCandidate,
    HotelDiscoveryResult,
    OsmIdentity,
)
from app.integrations.fortyguard.errors import ProviderError
from app.domain.ledger import BudgetExceededError
from app.services.sidecars import load_acquisition_record


HotelDiscoveryCallable = Callable[[], HotelDiscoveryResult]
ComponentLoaderCallable = Callable[[str], ComponentEvidence | None]


class HotelHeatAnalysisState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ComponentAnalysisMetadata:
    component: str
    available: bool
    unit: str
    threshold_celsius: float | None
    provenance: str | None
    coverage: float | None
    confidence: str | None
    caveats: tuple[str, ...]
    provenance_details: Mapping[str, object] | None = None
    missing_reason: str | None = None


@dataclass(frozen=True)
class HotelHeatAnalysisOutcome:
    state: HotelHeatAnalysisState
    district_name: str
    execution_mode: ExecutionMode
    discovered_count: int
    usable_count: int
    evidence: Mapping[str, ComponentEvidence]
    assignments: tuple[HotelHeatAssignment, ...]
    components: Mapping[str, ComponentAnalysisMetadata]
    score: NeighbourhoodHeatScore | None
    reason: str | None = None


class HotelHeatAnalysisService:
    """Load district evidence once, assign it locally, and retain rerankable inputs."""

    def __init__(
        self,
        hotel_discovery: HotelDiscoveryCallable,
        component_loader: ComponentLoaderCallable,
        *,
        aoi: BaseGeometry,
        scorer: NeighbourhoodHeatScorer | None = None,
        supported_modes: frozenset[ExecutionMode] | None = None,
        district_name: str | None = None,
    ) -> None:
        self._hotel_discovery = hotel_discovery
        self._component_loader = component_loader
        self._aoi = aoi
        self._scorer = scorer or NeighbourhoodHeatScorer()
        self._supported_modes = supported_modes or frozenset(ExecutionMode)
        self._district_name = district_name

    def discover(self) -> HotelDiscoveryResult:
        """Expose the discovery seam for composition and deterministic replay."""
        return self._hotel_discovery()

    def load_component(self, component: str) -> ComponentEvidence | None:
        """Load one component through the configured execution boundary."""
        return self._component_loader(component)

    def analyze(
        self,
        district_name: str,
        execution_mode: ExecutionMode,
        *,
        weights: Mapping[str, float] | None = None,
    ) -> HotelHeatAnalysisOutcome:
        if not district_name.strip():
            raise ValueError("district_name must be a non-empty string")
        if execution_mode not in self._supported_modes:
            return self._unavailable(district_name, execution_mode, "execution_mode_unavailable")
        if self._district_name is not None and district_name != self._district_name:
            return self._unavailable(district_name, execution_mode, "district_not_available")
        discovery = self._hotel_discovery()
        if discovery.state is DiscoveryState.UNAVAILABLE:
            return HotelHeatAnalysisOutcome(
                HotelHeatAnalysisState.UNAVAILABLE,
                district_name,
                execution_mode,
                discovery.discovered_count,
                discovery.usable_count,
                MappingProxyType({}),
                (),
                MappingProxyType({}),
                None,
                discovery.reason or "hotel_discovery_unavailable",
            )

        evidence, components = self._load_components(district_name, execution_mode)
        if len(evidence) != len(COMPONENTS):
            return HotelHeatAnalysisOutcome(
                HotelHeatAnalysisState.UNAVAILABLE,
                district_name,
                execution_mode,
                discovery.discovered_count,
                discovery.usable_count,
                MappingProxyType(evidence),
                (),
                MappingProxyType(components),
                None,
                "missing_component_evidence",
            )

        assignments = self._scorer.assign(discovery.candidates, evidence, aoi=self._aoi)
        score = self._scorer.score(assignments, weights=weights)
        state = (
            HotelHeatAnalysisState.AVAILABLE
            if score.ranked_output
            else HotelHeatAnalysisState.UNAVAILABLE
        )
        return HotelHeatAnalysisOutcome(
            state,
            district_name,
            execution_mode,
            discovery.discovered_count,
            discovery.usable_count,
            MappingProxyType(evidence),
            assignments,
            MappingProxyType(components),
            score,
            None if score.ranked_output else "insufficient_complete_hotels",
        )

    @staticmethod
    def _unavailable(
        district_name: str, execution_mode: ExecutionMode, reason: str
    ) -> HotelHeatAnalysisOutcome:
        return HotelHeatAnalysisOutcome(
            HotelHeatAnalysisState.UNAVAILABLE,
            district_name,
            execution_mode,
            0,
            0,
            MappingProxyType({}),
            (),
            MappingProxyType({}),
            None,
            reason,
        )

    def rerank(
        self,
        outcome: HotelHeatAnalysisOutcome,
        *,
        weights: Mapping[str, float] | None = None,
    ) -> HotelHeatAnalysisOutcome:
        """Recompute relative ranking solely from retained local assignments."""
        if not outcome.assignments:
            raise ValueError("hotel heat analysis has no assignments to rerank")
        score = self._scorer.score(outcome.assignments, weights=weights)
        state = (
            HotelHeatAnalysisState.AVAILABLE
            if score.ranked_output
            else HotelHeatAnalysisState.UNAVAILABLE
        )
        return HotelHeatAnalysisOutcome(
            state,
            outcome.district_name,
            outcome.execution_mode,
            outcome.discovered_count,
            outcome.usable_count,
            outcome.evidence,
            outcome.assignments,
            outcome.components,
            score,
            None if score.ranked_output else "insufficient_complete_hotels",
        )

    def _load_components(
        self, district_name: str, execution_mode: ExecutionMode
    ) -> tuple[dict[str, ComponentEvidence], dict[str, ComponentAnalysisMetadata]]:
        evidence: dict[str, ComponentEvidence] = {}
        missing: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(COMPONENTS)) as executor:
            futures = {
                executor.submit(self._component_loader, component): component
                for component in COMPONENTS
            }
            for future in as_completed(futures):
                component = futures[future]
                try:
                    item = future.result()
                except (ProviderError, OSError, TimeoutError, ValueError):
                    missing[component] = "component_load_failed"
                    continue
                except BudgetExceededError:
                    raise
                if item is None:
                    missing[component] = "component_not_available"
                elif item.component != component:
                    missing[component] = "component_mismatch"
                else:
                    evidence[component] = item

        components = {
            component: self._component_metadata(
                component, evidence.get(component), missing.get(component)
            )
            for component in COMPONENTS
        }
        return evidence, components

    @staticmethod
    def _component_metadata(
        component: str, evidence: ComponentEvidence | None, missing_reason: str | None
    ) -> ComponentAnalysisMetadata:
        unit = "C" if component in {"night", "day"} else "hours"
        if evidence is None:
            return ComponentAnalysisMetadata(
                component=component,
                available=False,
                unit=unit,
                threshold_celsius=35.0 if component in {"hot_hours", "persistence"} else None,
                provenance=None,
                coverage=None,
                confidence=None,
                caveats=(),
                missing_reason=missing_reason,
            )
        return ComponentAnalysisMetadata(
            component=component,
            available=True,
            unit=evidence.unit,
            threshold_celsius=evidence.threshold_celsius,
            provenance=evidence.provenance,
            coverage=evidence.coverage,
            confidence=_confidence(evidence.coverage),
            caveats=evidence.caveats,
            provenance_details=evidence.provenance_details,
        )


def _confidence(coverage: float | None) -> str | None:
    if coverage is None:
        return None
    if coverage >= 0.95:
        return "high"
    if coverage >= 0.7:
        return "limited"
    return "insufficient"


def build_fixture_hotel_heat_analysis_service(
    fixture_path: Path, *, district_aoi: BoundingBox
) -> HotelHeatAnalysisService:
    """Load and validate the canonical offline district analysis fixture."""
    payload = _object(json.loads(fixture_path.read_text(encoding="utf-8")), "fixture")
    if payload.get("schema_version") != "hotel-heat-analysis-v1":
        raise ValueError("unsupported hotel heat fixture schema_version")

    district = _string(payload, "district_name")
    fixture_aoi = _bbox(_object(payload.get("aoi"), "aoi"), "aoi")
    if fixture_aoi != district_aoi:
        raise ValueError("hotel heat fixture AOI does not match configured district AOI")
    aoi_geometry = box(district_aoi.west, district_aoi.south, district_aoi.east, district_aoi.north)

    discovery_payload = _object(payload.get("hotel_discovery"), "hotel_discovery")
    candidates = tuple(
        _hotel(_object(item, "hotel_discovery.hotels[]"), aoi_geometry)
        for item in _array(discovery_payload, "hotels")
    )
    if len({hotel.primary_identity for hotel in candidates}) != len(candidates):
        raise ValueError("hotel heat fixture contains duplicate primary OSM identities")
    discovered_count = _integer(discovery_payload, "discovered_count")
    if discovered_count < len(candidates) or len(candidates) < 5:
        raise ValueError("hotel heat fixture requires at least five usable discovered hotels")
    acquisition = load_acquisition_record(fixture_path)
    if acquisition is None:
        raise ValueError("hotel heat fixture requires an acquisition sidecar")
    if acquisition.schema_version != "hotel-heat-analysis-v1":
        raise ValueError("hotel heat fixture sidecar schema does not match payload")
    expected_request = {
        "district_name": district,
        "aoi": district_aoi.to_payload(),
        "components": list(COMPONENTS),
        "threshold_celsius": 35,
        "tile_resolution_m": 80,
    }
    if acquisition.request_configuration != expected_request:
        raise ValueError("hotel heat fixture sidecar request does not match payload")
    if acquisition.source == "synthesized" and acquisition.retrieved_at is not None:
        raise ValueError("synthesized hotel heat fixtures cannot have retrieval times")
    retrieved_at = acquisition.retrieved_at
    if acquisition.data_date is None:
        raise ValueError("hotel heat fixture sidecar requires a data date")
    source_timestamp = _timestamp(discovery_payload, "source_timestamp")
    discovery = HotelDiscoveryResult(
        DiscoveryState.AVAILABLE,
        candidates,
        discovered_count,
        len(candidates),
        source_timestamp,
        retrieved_at,
        "fixture",
        False,
    )

    component_payloads = _object(payload.get("components"), "components")
    if set(component_payloads) != set(COMPONENTS):
        raise ValueError("hotel heat fixture must contain exactly four shared components")
    evidence = {
        component: _component(
            component,
            _object(component_payloads[component], f"components.{component}"),
            aoi_geometry,
            acquisition,
        )
        for component in COMPONENTS
    }
    return HotelHeatAnalysisService(
        lambda: discovery,
        evidence.get,
        aoi=aoi_geometry,
        supported_modes=frozenset({ExecutionMode.FIXTURE}),
        district_name=district,
    )


def _component(
    component: str,
    payload: dict[str, object],
    aoi: BaseGeometry,
    acquisition: AcquisitionRecord,
) -> ComponentEvidence:
    unit = _string(payload, "unit")
    threshold_value = payload.get("threshold_celsius")
    threshold = None if threshold_value is None else _number(threshold_value, "threshold_celsius")
    provenance = _string(payload, "provenance")
    resolution = _number(payload.get("tile_resolution_m"), "tile_resolution_m")
    if resolution != 80.0:
        raise ValueError(f"{component} fixture evidence must use 80 m resolution")
    if component in {"hot_hours", "persistence"} and threshold != 35.0:
        raise ValueError(f"{component} fixture evidence must use a 35 C threshold")
    coverage = _number(payload.get("coverage"), "coverage")
    caveats = tuple(
        _nonempty_string(item, f"components.{component}.caveats[]")
        for item in _array(payload, "caveats")
    )
    tiles = _grid_tiles(component, unit, threshold, provenance, payload, aoi)
    if not tiles or len({tile.identity for tile in tiles}) != len(tiles):
        raise ValueError(f"{component} must contain uniquely identified tiles")
    return ComponentEvidence(
        component,
        tiles,
        unit,
        threshold,
        provenance,
        resolution,
        coverage=coverage,
        caveats=caveats,
        provenance_details={
            "source": "fixture",
            "retrieved_at": acquisition.retrieved_at.isoformat()
            if acquisition.retrieved_at is not None
            else None,
            "data_date": acquisition.data_date,
            "stale": False,
            "forecast": False,
            "activity_id": acquisition.activity_id,
            "transformations": [
                {"name": item.name, "version": item.version} for item in acquisition.transformations
            ],
        },
    )


def _grid_tiles(
    component: str,
    unit: str,
    threshold: float | None,
    provenance: str,
    component_payload: dict[str, object],
    aoi: BaseGeometry,
) -> tuple[TileGeometry, ...]:
    rows = _integer(component_payload, "grid_rows")
    if rows < 1:
        raise ValueError(f"{component} grid_rows must be positive")
    tiles: list[TileGeometry] = []
    for column_index, value in enumerate(_array(component_payload, "tiles"), start=1):
        payload = _object(value, f"components.{component}.tiles[]")
        bounds = payload.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise ValueError(f"{component} grid column bounds must contain west,south,east,north")
        west, south, east, north = (
            _number(item, f"components.{component}.tiles[].bounds") for item in bounds
        )
        if west >= east or south >= north:
            raise ValueError(f"{component} grid column bounds are invalid")
        column_geometry = box(west, south, east, north)
        if not aoi.covers(column_geometry):
            raise ValueError(f"{component} grid columns must be inside the configured district AOI")
        valid_time = _string(payload, "valid_time")
        try:
            datetime.fromisoformat(valid_time.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(
                f"{component} tile valid_time must be an ISO 8601 date or timestamp"
            ) from None
        metadata = SpatialMetadata(
            metric=component,
            unit=unit,
            source=provenance,
            valid_time=valid_time,
            forecast=_boolean(payload, "forecast"),
            threshold_celsius=threshold,
            direction="above" if threshold is not None else None,
        )
        cell_height = (north - south) / rows
        tiles.extend(
            TileGeometry(
                f"{component}-r{row_index + 1:02d}-c{column_index:02d}",
                box(
                    west,
                    south + row_index * cell_height,
                    east,
                    south + (row_index + 1) * cell_height,
                ),
                _number(payload.get("value"), "tile.value"),
                metadata,
            )
            for row_index in range(rows)
        )
    return tuple(tiles)


def _hotel(payload: dict[str, object], aoi: BaseGeometry) -> HotelCandidate:
    primary = _identity(_object(payload.get("primary_identity"), "primary_identity"))
    identities = tuple(
        _identity(_object(item, "source_identities[]"))
        for item in _array(payload, "source_identities")
    )
    if primary not in identities or len(set(identities)) != len(identities):
        raise ValueError("hotel source identities must be unique and include the primary identity")
    latitude = _number(payload.get("latitude"), "hotel.latitude")
    longitude = _number(payload.get("longitude"), "hotel.longitude")
    if not aoi.covers(Point(longitude, latitude)):
        raise ValueError("hotel coordinates must be inside the configured district AOI")
    address_payload = _object(payload.get("address", {}), "hotel.address")
    address = tuple(
        (key, _nonempty_string(value, f"hotel.address.{key}"))
        for key, value in sorted(address_payload.items())
    )
    return HotelCandidate(
        primary,
        identities,
        _string(payload, "name"),
        latitude,
        longitude,
        address,
        _optional_string(payload.get("website"), "hotel.website"),
        _optional_string(payload.get("operator"), "hotel.operator"),
    )


def _identity(payload: dict[str, object]) -> OsmIdentity:
    return OsmIdentity(_string(payload, "object_type"), _integer(payload, "object_id"))


def _bbox(payload: dict[str, object], field: str) -> BoundingBox:
    return BoundingBox(
        _number(payload.get("south"), f"{field}.south"),
        _number(payload.get("west"), f"{field}.west"),
        _number(payload.get("north"), f"{field}.north"),
        _number(payload.get("east"), f"{field}.east"),
    )


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _array(payload: dict[str, object], field: str) -> list[object]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return cast(list[object], value)


def _string(payload: dict[str, object], field: str) -> str:
    return _nonempty_string(payload.get(field), field)


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _nonempty_string(value, field)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _integer(payload: dict[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _boolean(payload: dict[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _timestamp(payload: dict[str, object], field: str) -> datetime:
    value = _string(payload, field)
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be an ISO 8601 timestamp") from None
    if timestamp.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return timestamp
