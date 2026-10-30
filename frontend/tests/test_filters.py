from datetime import date

import pytest

from filters import MAX_RANGE_DAYS, to_api_range, validate_range


def test_reversed_range_is_rejected():
    assert validate_range(date(2026, 10, 30), date(2026, 10, 1))


def test_equal_dates_are_valid():
    assert validate_range(date(2026, 10, 30), date(2026, 10, 30)) is None


def test_span_limit_is_inclusive():
    start = date(2025, 1, 1)
    ok_end = date.fromordinal(start.toordinal() + MAX_RANGE_DAYS - 1)
    too_long = date.fromordinal(start.toordinal() + MAX_RANGE_DAYS)
    assert validate_range(start, ok_end) is None
    assert validate_range(start, too_long)


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (date(2026, 10, 30), date(2026, 10, 30), ("2026-10-30T00:00:00Z", "2026-10-31T00:00:00Z")),
        (date(2026, 10, 1), date(2026, 10, 31), ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")),
        (date(2026, 12, 31), date(2026, 12, 31), ("2026-12-31T00:00:00Z", "2027-01-01T00:00:00Z")),
    ],
)
def test_to_api_range_end_is_next_midnight(start, end, expected):
    assert to_api_range(start, end) == expected
