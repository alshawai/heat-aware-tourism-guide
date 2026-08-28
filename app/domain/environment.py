"""Temporal data-prep domain: traveler time window and anchor selection (issue #44).

This module is provider-free. It owns the product rule — one day, whole
hours, at most twelve of them — and the conservative chaining policy that
turns a heatmap response into the environmental-parameters temperature
anchor. Provider adapters translate a validated window into their own
request payloads; they never redefine the rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol

MAX_WINDOW_HOURS = 12


@dataclass(frozen=True)
class TimeWindow:
    """A half-open window of whole hours within one calendar day.

    ``start_hour`` is inclusive, ``end_hour`` exclusive: the traveler visits
    from 08:00 up to (but not including) 20:00. Because the provider range
    filter takes a single ``start_date``, a window cannot cross midnight.
    """

    start_hour: int
    end_hour: int

    def __post_init__(self) -> None:
        for name, value in (("start_hour", self.start_hour), ("end_hour", self.end_hour)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23:
                raise ValueError(f"{name} must be a whole hour between 0 and 23")
        if self.start_hour >= self.end_hour:
            raise ValueError("start_hour must be before end_hour within one day")
        if self.end_hour - self.start_hour > MAX_WINDOW_HOURS:
            raise ValueError(f"time window spans at most {MAX_WINDOW_HOURS} hours")

    @property
    def hours(self) -> range:
        return range(self.start_hour, self.end_hour)

    def contains_hour(self, hour: int) -> bool:
        return hour in self.hours

    def start_time(self) -> str:
        return f"{self.start_hour:02d}:00"

    def end_time(self) -> str:
        return f"{self.end_hour:02d}:00"


class CelsiusReading(Protocol):
    """The minimal structural interface the anchor policy consumes.

    ``Tile`` satisfies it structurally: any reading shape with a valid time
    and an optional °C value can be chained into the anchor policy. Both
    members are read-only properties so frozen dataclasses conform.
    """

    @property
    def valid_time(self) -> datetime: ...

    @property
    def value_celsius(self) -> float | None: ...


def select_anchor_celsius(readings: Iterable[CelsiusReading], window: TimeWindow) -> float:
    """Return the maximum °C among readings whose hour falls inside ``window``.

    Conservative by design: the environmental series is anchored to the
    worst in-window heat so #14's analysis never under-reports exposure.
    Raises when no in-window reading carries a value — the anchor is never
    invented.
    """
    in_window = [
        reading.value_celsius
        for reading in readings
        if window.contains_hour(reading.valid_time.hour) and reading.value_celsius is not None
    ]
    if not in_window:
        raise ValueError(
            "no in-window temperature reading is available to anchor the environmental series"
        )
    return max(in_window)
