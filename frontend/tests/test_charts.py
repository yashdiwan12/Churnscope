import plotly.graph_objects as go

from charts import LOW_N_MIN_ELIGIBLE, dau_line, funnel_bar


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
