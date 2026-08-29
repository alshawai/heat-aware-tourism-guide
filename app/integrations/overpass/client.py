"""Bounded Overpass client for hotel queries."""

from __future__ import annotations

from time import sleep as default_sleep
from typing import Callable, Protocol

from app.domain.hotels import BoundingBox
from app.integrations.overpass.errors import OverpassRateLimited


class OverpassTransport(Protocol):
    def execute(self, query: str) -> dict[str, object]: ...


class OverpassClient:
    def __init__(
        self,
        transport: OverpassTransport,
        *,
        max_attempts: int = 2,
        retry_delay_seconds: float = 30,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("Overpass max attempts must be positive")
        if retry_delay_seconds < 0:
            raise ValueError("Overpass retry delay must be non-negative")
        self._transport = transport
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep

    def query(self, aoi: BoundingBox) -> dict[str, object]:
        query = build_hotel_query(aoi)
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._transport.execute(query)
            except OverpassRateLimited:
                if attempt == self._max_attempts:
                    raise
                self._sleep(self._retry_delay_seconds)
        raise AssertionError("unreachable")


def build_hotel_query(aoi: BoundingBox) -> str:
    bounds = ",".join(format(value, ".12g") for value in (aoi.south, aoi.west, aoi.north, aoi.east))
    return f'[out:json][timeout:60];\nnwr["tourism"="hotel"]({bounds});\nout center;'
