"""Pure tourism ranking and route-decision contracts."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class HotelCandidate:
    identity: str
    components: Mapping[str, float]


@dataclass(frozen=True)
class RankedHotel:
    identity: str
    components: Mapping[str, float]
    score: float
    percentile: float
    tie_group: int


class HotelRanker:
    default_weights = {"night": 0.35, "hot_hours": 0.25, "persistence": 0.20, "day": 0.20}

    def rank(
        self, candidates: Sequence[HotelCandidate], weights: Mapping[str, float] | None = None
    ) -> tuple[RankedHotel, ...]:
        selected_weights = dict(weights or self.default_weights)
        if abs(sum(selected_weights.values()) - 1) > 0.001:
            raise ValueError("hotel weights must sum to one")
        required = set(self.default_weights)
        if set(selected_weights) != required or any(
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(weight)
            or weight < 0
            for weight in selected_weights.values()
        ):
            raise ValueError("hotel weights must be finite, non-negative, and complete")
        if any(
            set(candidate.components) != required
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in candidate.components.values()
            )
            for candidate in candidates
        ):
            raise ValueError("hotel components must be finite and complete")
        scores = [
            sum(candidate.components[name] * weight for name, weight in selected_weights.items())
            for candidate in candidates
        ]
        ordered = sorted(zip(candidates, scores), key=lambda item: (item[1], item[0].identity))
        distinct = sorted(set(scores))
        result: list[RankedHotel] = []
        for position, (candidate, score) in enumerate(ordered):
            tie_group = distinct.index(score)
            percentile = 100 * (1 - (distinct.index(score) / max(1, len(distinct) - 1)))
            result.append(
                RankedHotel(candidate.identity, candidate.components, score, percentile, tie_group)
            )
        return tuple(result)


@dataclass(frozen=True)
class RouteCandidate:
    identity: str
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class RouteComparison:
    recommended_id: str | None
    reason: str
    corridor_heat_value: float
    shade_was_computed: bool


class RouteComparator:
    def __init__(self, representative_threshold_m: float = 1500) -> None:
        self.representative_threshold_m = representative_threshold_m

    def compare(
        self,
        route_loader: Callable[[], Sequence[RouteCandidate]],
        *,
        heat_value: float | None = None,
        heat_values: Sequence[float] | None = None,
        heat_threshold: float,
        shade: Callable[[RouteCandidate], float],
        building_coverage: float = 1.0,
    ) -> RouteComparison:
        routes = tuple(route_loader())
        if not routes:
            raise ValueError("at least one route is required")
        shortest = min(routes, key=lambda route: route.distance_m)
        if shortest.distance_m > self.representative_threshold_m:
            corridor_heat = max(heat_values) if heat_values else None
        else:
            corridor_heat = heat_value
        if corridor_heat is None:
            raise ValueError("heat value is required")
        if corridor_heat <= heat_threshold:
            return RouteComparison(shortest.identity, "heat below threshold", corridor_heat, False)
        shade_values = {route.identity: shade(route) for route in routes}
        if building_coverage < 0.7:
            return RouteComparison(
                None, "insufficient shade coverage; traveler comparison required", corridor_heat, True
            )
        best = max(routes, key=lambda route: (shade_values[route.identity], -route.distance_m))
        return RouteComparison(
            best.identity, "highest modeled shade among returned routes", corridor_heat, True
        )
