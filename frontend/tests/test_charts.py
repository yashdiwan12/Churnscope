import plotly.graph_objects as go

from charts import (
    LOW_N_MIN_ELIGIBLE,
    adoption_bars,
    dau_line,
    funnel_bar,
    retention_heatmap,
    retention_matrix,
    risk_histogram,
)


def test_dau_line_none_for_empty_and_figure_for_data():
    assert dau_line([]) is None
    rows = [
        {"date": "2026-10-29", "active_users": 50},
        {"date": "2026-10-30", "active_users": 60},
    ]
    fig = dau_line(rows)
    assert isinstance(fig, go.Figure)
    assert list(fig.data[0].x) == ["2026-10-29", "2026-10-30"]
    assert list(fig.data[0].y) == [50, 60]


def test_low_n_threshold_is_twenty():
    assert LOW_N_MIN_ELIGIBLE == 20


def test_funnel_bar_none_for_no_steps_and_for_zero_first_step():
    assert funnel_bar([]) is None
    zero = [
        {"step": "a", "users": 0, "conversion_from_previous": None, "conversion_from_start": None}
    ]
    assert funnel_bar(zero) is None


def test_funnel_bar_one_bar_per_step_with_na_for_missing_conversion():
    steps = [
        {"step": "a", "users": 200, "conversion_from_previous": None, "conversion_from_start": 1.0},
        {"step": "b", "users": 50, "conversion_from_previous": 0.25, "conversion_from_start": 0.25},
        {"step": "c", "users": 0, "conversion_from_previous": None, "conversion_from_start": None},
    ]
    fig = funnel_bar(steps)
    assert isinstance(fig, go.Figure)
    assert list(fig.data[0].x) == [200, 50, 0]
    assert list(fig.data[0].y) == ["a", "b", "c"]
    assert not any("nan" in str(t).lower() or "none" in str(t).lower() for t in fig.data[0].text)


def _cell(eligible, complete=True, retention=0.5):
    return {
        "cohort": "2026-10-05",
        "period": 1,
        "cohort_size": 40,
        "eligible": eligible,
        "retained": 1,
        "retention": retention,
        "complete": complete,
    }


def test_retention_matrix_flags_low_n_below_twenty_and_keeps_complete():
    matrix = retention_matrix([_cell(19, complete=False), _cell(20)])
    assert list(matrix["low_n"]) == [True, False]
    assert list(matrix["complete"]) == [False, True]


def test_retention_matrix_labels():
    matrix = retention_matrix([_cell(19, complete=False), _cell(20), _cell(0, retention=None)])
    assert matrix["label"][0] == "50.0% n=19, incomplete, low n"
    assert matrix["label"][1] == "50.0% n=20"
    assert matrix["label"][2] == "not enough data n=0, low n"


def test_retention_heatmap_none_for_empty_and_greys_incomplete_cells():
    assert retention_heatmap(retention_matrix([])) is None
    done = {**_cell(20, retention=0.5), "period": 1}
    partial = {**_cell(20, complete=False, retention=0.9), "period": 2}
    figure = retention_heatmap(retention_matrix([done, partial]))
    assert isinstance(figure, go.Figure)
    coloured, grey = figure.data
    assert list(coloured.z[0]) == [0.5, None]
    assert list(grey.z[0]) == [None, 0]


def test_retention_heatmap_hover_shows_label_not_raw_z():
    figure = retention_heatmap(retention_matrix([_cell(20), _cell(20, complete=False)]))
    for trace in figure.data:
        assert "%{text}" in trace.hovertemplate
        assert "%{z}" not in trace.hovertemplate


def test_adoption_bars_none_for_empty():
    assert adoption_bars({}) is None


def test_adoption_bars_sorted_descending_with_one_decimal_percent_text():
    fig = adoption_bars({"export": 0.05, "login": 0.9, "report_viewed": 0.425})
    bar = fig.data[0]
    assert list(bar.y) == ["login", "report_viewed", "export"]
    assert list(bar.x) == [0.9, 0.425, 0.05]
    assert list(bar.text) == ["90.0%", "42.5%", "5.0%"]
    assert "active users" in fig.layout.xaxis.title.text


def _bins(counts):
    return [
        {"bin_start": i / 10, "bin_end": (i + 1) / 10, "count": c} for i, c in enumerate(counts)
    ]


def test_risk_histogram_none_when_all_counts_zero():
    assert risk_histogram(_bins([0] * 10), 0.5) is None
    assert risk_histogram([], 0.5) is None


def test_risk_histogram_has_ten_bins_threshold_line_and_labels():
    fig = risk_histogram(_bins([30, 25, 20, 15, 12, 8, 5, 3, 1, 1]), 0.5)
    assert isinstance(fig, go.Figure)
    assert list(fig.data[0].y) == [30, 25, 20, 15, 12, 8, 5, 3, 1, 1]
    assert len(fig.data[0].x) == 10
    lines = [s for s in fig.layout.shapes if s.type == "line"]
    assert len(lines) == 1
    assert lines[0].x0 == lines[0].x1 == 0.5
    assert fig.layout.xaxis.title.text == "risk score (relative)"
    assert fig.layout.yaxis.title.text == "customers"
    assert "probability" not in fig.to_json().lower()
