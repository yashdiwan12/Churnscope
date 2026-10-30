from labels import cohorts_label, cutoff_label, freshness_label, window_label


def test_window_label_shows_inclusive_end():
    window = {"start": "2026-10-01T00:00:00Z", "end": "2026-10-31T00:00:00Z"}
    assert window_label(window) == "Window: 1 Oct to 30 Oct 2026 (30 days)"


def test_window_label_31_days_across_months():
    window = {"start": "2026-10-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"}
    assert window_label(window) == "Window: 1 Oct to 31 Oct 2026 (31 days)"


def test_window_label_across_years_and_single_day():
    window = {"start": "2025-12-31T00:00:00Z", "end": "2026-01-02T00:00:00Z"}
    assert window_label(window) == "Window: 31 Dec 2025 to 1 Jan 2026 (2 days)"
    one = {"start": "2026-10-30T00:00:00Z", "end": "2026-10-31T00:00:00Z"}
    assert window_label(one) == "Window: 30 Oct to 30 Oct 2026 (1 day)"


def test_freshness_label():
    assert freshness_label(None) == "No data yet"
    assert freshness_label("2026-10-30T12:30:00Z") == "Data through 30 Oct 2026"


def test_cohorts_label():
    assert cohorts_label("2026-10-30T00:00:00Z") == "Cohorts as of 30 Oct 2026"
    assert cohorts_label(None) == "No data yet"


def test_cutoff_label():
    assert (
        cutoff_label("2026-10-30T00:00:00Z", 28)
        == "Scored at cutoff 30 Oct 2026 using the 28 days before it"
    )
    assert cutoff_label(None, 28) == "No data yet"
