"""Pure local assignment and relative scoring for neighbourhood hotel heat."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping, Sequence

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from app.domain.analysis import TileGeometry, join_point_to_tiles
from app.domain.hotels import HotelCandidate, OsmIdentity


COMPONENTS = ("night", "hot_hours", "persistence", "day")
DEFAULT_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {"night": 0.35, "hot_hours": 0.25, "persistence": 0.20, "day": 0.20}
)
DEFAULT_WEIGHT_LABEL = "product defaults"
WEIGHT_SUM_TOLERANCE = 0.001
NEAREST_FALLBACK_MAX_M = 100.0


def _finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


@dataclass(frozen=True)
class ComponentEvidence:
    """One district analysis whose tiles can be reused for every hotel."""

    component: str
    tiles: tuple[TileGeometry, ...]
    unit: str
    threshold_celsius: float | None
    provenance: str
    tile_resolution_m: float

    def __post_init__(self) -> None:
        if self.component not in COMPONENTS:
            raise ValueError(f"component must be one of {COMPONENTS}")
        expected_unit = "C" if self.component in {"night", "day"} else "hours"
        if self.unit != expected_unit:
            raise ValueError(f"{self.component} evidence must use {expected_unit}")
        if self.component in {"hot_hours", "persistence"}:
            if not _finite_number(self.threshold_celsius):
                raise ValueError(f"{self.component} evidence requires a finite threshold")
        elif self.threshold_celsius is not None:
            raise ValueError(f"{self.component} evidence must not define a threshold")
        if not self.provenance.strip():
            raise ValueError("component evidence provenance is required")
        if not _finite_number(self.tile_resolution_m) or self.tile_resolution_m <= 0:
            raise ValueError("tile resolution must be finite and positive")


@dataclass(frozen=True)
class ComponentAssignment:
    """Local evidence assigned to one hotel for one component."""

    component: str
    value: float | None
    unit: str
    threshold_celsius: float | None
    provenance: str
    tile_id: str | None
    tile_resolution_m: float
    quality: str
    distance_m: float | None


@dataclass(frozen=True)
class HotelHeatAssignment:
    identity: OsmIdentity
    name: str
    components: Mapping[str, ComponentAssignment]

    @property
    def complete(self) -> bool:
        return set(self.components) == set(COMPONENTS) and all(
            assignment.value is not None and _finite_number(assignment.value)
            for assignment in self.components.values()
        )


@dataclass(frozen=True)
class ScoredComponent:
    assignment: ComponentAssignment
    percentile: float | None

    def __getattr__(self, name: str) -> object:
        return getattr(self.assignment, name)


@dataclass(frozen=True)
class ScoredHotel:
    identity: OsmIdentity
    name: str
    components: Mapping[str, ScoredComponent]
    complete: bool
    relative_aggregate: float | None
    rank: int | None


@dataclass(frozen=True)
class NeighbourhoodHeatScore:
    hotels: tuple[ScoredHotel, ...]
    weights: Mapping[str, float]
    weight_label: str
    complete_candidate_count: int
    ranked_output: bool


class NeighbourhoodHeatScorer:
    """Assign shared district tiles and rank hotels using candidate-relative evidence."""

    def assign(
        self,
        hotels: Sequence[HotelCandidate],
        evidence: Mapping[str, ComponentEvidence],
        *,
        aoi: BaseGeometry,
    ) -> tuple[HotelHeatAssignment, ...]:
        if set(evidence) != set(COMPONENTS) or any(
            name != item.component for name, item in evidence.items()
        ):
            raise ValueError(f"evidence components must be exactly {set(COMPONENTS)}")

        assignments: list[HotelHeatAssignment] = []
        for hotel in hotels:
            point = Point(hotel.longitude, hotel.latitude)
            components: dict[str, ComponentAssignment] = {}
            for component in COMPONENTS:
                item = evidence[component]
                match = join_point_to_tiles(
                    point,
                    item.tiles,
                    aoi=aoi,
                    nearest_max_distance_m=NEAREST_FALLBACK_MAX_M,
                )
                components[component] = ComponentAssignment(
                    component=component,
                    value=match.value,
                    unit=item.unit,
                    threshold_celsius=item.threshold_celsius,
                    provenance=item.provenance,
                    tile_id=match.tile_id,
                    tile_resolution_m=item.tile_resolution_m,
                    quality=match.quality,
                    distance_m=match.distance_m,
                )
            assignments.append(
                HotelHeatAssignment(
                    hotel.primary_identity, hotel.name, MappingProxyType(components)
                )
            )
        return tuple(assignments)

    def score(
        self,
        assignments: Sequence[HotelHeatAssignment],
        *,
        weights: Mapping[str, float] | None = None,
    ) -> NeighbourhoodHeatScore:
        selected_weights, weight_label = self._weights(weights)
        identities = [assignment.identity for assignment in assignments]
        if len(set(identities)) != len(identities):
            raise ValueError("hotel identities must be unique")
        complete = [assignment for assignment in assignments if assignment.complete]
        percentiles: dict[str, dict[OsmIdentity, float]] = {name: {} for name in COMPONENTS}

        for component in COMPONENTS:
            component_values: set[float] = set()
            for assignment in complete:
                value = assignment.components[component].value
                assert value is not None
                component_values.add(value)
            values = sorted(component_values)
            for assignment in complete:
                value = assignment.components[component].value
                assert value is not None
                percentiles[component][assignment.identity] = (
                    100.0 * (1.0 - values.index(value) / (len(values) - 1))
                    if len(values) > 1
                    else 100.0
                )

        aggregates = {
            assignment.identity: round(
                sum(
                    (1.0 - percentiles[component][assignment.identity] / 100.0)
                    * selected_weights[component]
                    for component in COMPONENTS
                ),
                6,
            )
            for assignment in complete
        }
        ranked_output = len(complete) >= 5
        ranks: dict[OsmIdentity, int] = {}
        if ranked_output:
            ordered_complete = sorted(
                complete, key=lambda item: (aggregates[item.identity], item.identity)
            )
            for position, assignment in enumerate(ordered_complete, start=1):
                score = aggregates[assignment.identity]
                ranks[assignment.identity] = next(
                    index
                    for index, candidate in enumerate(ordered_complete, start=1)
                    if aggregates[candidate.identity] == score
                )
            ordered = ordered_complete + [item for item in assignments if not item.complete]
        else:
            ordered = list(assignments)

        hotels = tuple(
            ScoredHotel(
                identity=assignment.identity,
                name=assignment.name,
                components=MappingProxyType(
                    {
                        component: ScoredComponent(
                            assignment.components[component],
                            percentiles[component].get(assignment.identity),
                        )
                        for component in COMPONENTS
                    }
                ),
                complete=assignment.complete,
                relative_aggregate=aggregates.get(assignment.identity),
                rank=ranks.get(assignment.identity),
            )
            for assignment in ordered
        )
        return NeighbourhoodHeatScore(
            hotels=hotels,
            weights=MappingProxyType(selected_weights),
            weight_label=weight_label,
            complete_candidate_count=len(complete),
            ranked_output=ranked_output,
        )

    @staticmethod
    def _weights(weights: Mapping[str, float] | None) -> tuple[dict[str, float], str]:
        selected = dict(DEFAULT_WEIGHTS if weights is None else weights)
        if set(selected) != set(COMPONENTS) or any(
            not _finite_number(value) or value < 0 for value in selected.values()
        ):
            raise ValueError("weights must be complete, finite, and nonnegative")
        if abs(sum(selected.values()) - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ValueError("weights must sum to 1")
        return selected, DEFAULT_WEIGHT_LABEL if weights is None else "custom"
