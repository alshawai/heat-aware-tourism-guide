"""Offline tests for the temporal data-prep domain (issue #44).

Covers the traveler time window (one day, whole hours, at most 12 hours) and
the conservative anchor-selection policy that chains the heatmap result into
the environmental-parameters request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from app.domain.environment import TimeWindow, select_anchor_celsius


@dataclass(frozen=True)
class Reading:
    """Structural stand-in for a provider tile: only what the policy consumes."""

    valid_time: datetime
    value_celsius: float | None


def _reading(hour: int, value: float | None) -> Reading:
    return Reading(datetime(2026, 8, 23, hour, 0), value)


class TestTimeWindow:
    def test_accepts_a_valid_window(self) -> None:
        window = TimeWindow(8, 20)
        assert window.hours == range(8, 20)
        assert window.start_time() == "08:00"
        assert window.end_time() == "20:00"

    def test_accepts_exactly_twelve_hours(self) -> None:
        assert TimeWindow(0, 12).hours == range(0, 12)
        assert TimeWindow(11, 23).hours == range(11, 23)

    def test_rejects_a_window_longer_than_twelve_hours(self) -> None:
        with pytest.raises(ValueError, match="at most 12 hours"):
            TimeWindow(0, 13)

    def test_rejects_start_not_before_end(self) -> None:
        with pytest.raises(ValueError, match="before end_hour"):
            TimeWindow(9, 9)
        with pytest.raises(ValueError, match="before end_hour"):
            TimeWindow(10, 9)

    @pytest.mark.parametrize("bound", [-1, 24, 8.0, True, "8"])  # type: ignore[misc]
    def test_rejects_non_whole_hour_bounds(self, bound: object) -> None:
        with pytest.raises(ValueError, match="between 0 and 23"):
            TimeWindow(bound, 20)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="between 0 and 23"):
            TimeWindow(8, bound)  # type: ignore[arg-type]

    def test_window_is_half_open(self) -> None:
        window = TimeWindow(8, 9)
        assert window.contains_hour(8)
        assert not window.contains_hour(9)


class TestSelectAnchorCelsius:
    def test_returns_the_maximum_in_window_reading(self) -> None:
        readings = [_reading(7, 30.0), _reading(9, 35.5), _reading(15, 41.0), _reading(19, 38.2)]
        assert select_anchor_celsius(readings, TimeWindow(8, 20)) == 41.0

    def test_ignores_readings_outside_the_window(self) -> None:
        readings = [_reading(7, 50.0), _reading(20, 45.0), _reading(10, 33.0)]
        assert select_anchor_celsius(readings, TimeWindow(8, 20)) == 33.0

    def test_ignores_readings_without_a_celsius_value(self) -> None:
        # Non-tcm tiles carry value_celsius=None; the policy skips them.
        readings = [_reading(9, None), _reading(12, 36.0)]
        assert select_anchor_celsius(readings, TimeWindow(8, 20)) == 36.0

    def test_tied_maxima_resolve_to_the_same_anchor(self) -> None:
        readings = [_reading(9, 40.0), _reading(15, 40.0)]
        assert select_anchor_celsius(readings, TimeWindow(8, 20)) == 40.0

    def test_raises_when_no_reading_falls_inside_the_window(self) -> None:
        with pytest.raises(ValueError, match="no in-window temperature"):
            select_anchor_celsius([_reading(7, 30.0)], TimeWindow(8, 20))

    def test_raises_when_every_in_window_reading_lacks_a_value(self) -> None:
        with pytest.raises(ValueError, match="no in-window temperature"):
            select_anchor_celsius([_reading(9, None), _reading(10, None)], TimeWindow(8, 20))
