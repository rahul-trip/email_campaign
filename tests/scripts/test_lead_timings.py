"""The timing report's arithmetic, and the two read-only queries it stands on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts.lead_timings import percentile, stage_times

T0 = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_the_time_before_each_status_and_to_the_first_draft() -> None:
    changes = [
        ("a", "researched", at(0)),
        ("a", "qualified", at(30)),
        ("a", "copy_ready", at(100)),
        ("b", "researched", at(10)),
        ("b", "qualified", at(70)),
    ]
    in_status, first_draft = stage_times(changes)
    assert in_status["qualified"] == [30.0, 60.0]
    assert in_status["copy_ready"] == [70.0]
    assert first_draft == [100.0]  # only lead a reached a draft


def test_a_percentile_of_nothing_is_zero() -> None:
    assert percentile([], 0.95) == 0.0
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10
