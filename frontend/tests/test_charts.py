import plotly.graph_objects as go

from charts import LOW_N_MIN_ELIGIBLE, dau_line


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
