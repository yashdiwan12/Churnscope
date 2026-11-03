"""The palette: OS-following light and dark themes in config.toml, and chart colours from theme.py."""

import tomllib
from pathlib import Path

import theme
from charts import (
    adoption_bars,
    dau_line,
    funnel_bar,
    retention_heatmap,
    retention_matrix,
    risk_histogram,
)

CONFIG = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"


def _theme_config():
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))["theme"]


def test_light_and_dark_themes_are_both_set_and_no_base_forces_one():
    config = _theme_config()
    assert "base" not in config  # the viewer's OS picks light or dark
    assert config["light"]["backgroundColor"] == theme.LIGHT["background"]
    assert config["dark"]["backgroundColor"] == theme.DARK["background"]
    for mode, tokens in (("light", theme.LIGHT), ("dark", theme.DARK)):
        section = config[mode]
        assert section["primaryColor"] == tokens["primary"]
        assert section["secondaryBackgroundColor"] == tokens["surface"]
        assert section["textColor"] == tokens["text"]
        assert section["borderColor"] == tokens["border"]


def test_chart_colours_are_shared_by_both_modes():
    # Plotly figures cannot see the OS mode, so every series colour must work on both surfaces.
    assert theme.SERIES == "#3987e5"
    assert theme.AT_RISK == "#e34948"
    assert len(theme.SEQUENTIAL) == 7
    assert theme.SEQUENTIAL[0] == "#cde2fb" and theme.SEQUENTIAL[-1] == "#0d366b"


def _bins(counts):
    return [
        {"bin_start": i / 10, "bin_end": (i + 1) / 10, "count": c} for i, c in enumerate(counts)
    ]


def test_single_series_charts_use_the_series_blue():
    line = dau_line([{"date": "2026-10-29", "active_users": 5}])
    assert line.data[0].line.color == theme.SERIES
    assert line.data[0].line.width == 2
    assert line.data[0].marker.size == 8
    funnel = funnel_bar([{"step": "signup", "users": 4, "conversion_from_start": 1.0}])
    adoption = adoption_bars({"export": 0.5})
    for figure in (funnel, adoption):
        assert figure.data[0].marker.color == theme.SERIES
        assert figure.layout.barcornerradius == 4


def test_charts_have_transparent_backgrounds():
    figure = dau_line([{"date": "2026-10-29", "active_users": 5}])
    assert figure.layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert figure.layout.plot_bgcolor == "rgba(0,0,0,0)"


def test_risk_histogram_colours_only_bins_at_or_above_the_threshold_red():
    fig = risk_histogram(_bins([30, 25, 20, 15, 12, 8, 5, 3, 1, 1]), 0.5)
    colours = list(fig.data[0].marker.color)
    assert colours == [theme.SERIES] * 5 + [theme.AT_RISK] * 5
    # identity is never colour alone: a legend names both groups
    names = {trace.name for trace in fig.data if trace.showlegend is not False}
    assert {"At risk", "Not at risk"} <= names


def test_days_histogram_marks_the_at_risk_weeks():
    bins = [
        {"bin_start": i * 7, "bin_end": (i + 1) * 7, "count": c} for i, c in enumerate([5, 3, 2, 1])
    ]
    fig = risk_histogram(bins, 7.0, unit="days_inactive")
    assert list(fig.data[0].marker.color) == [theme.SERIES] + [theme.AT_RISK] * 3


def test_retention_heatmap_uses_the_blue_ramp_and_neutral_incomplete_cells():
    cell = {
        "cohort": "2026-10-05",
        "period": 0,
        "cohort_size": 30,
        "eligible": 30,
        "retained": 15,
        "retention": 0.5,
        "complete": True,
    }
    partial = {**cell, "period": 1, "complete": False}
    coloured, grey = retention_heatmap(retention_matrix([cell, partial])).data
    assert [stop[1] for stop in coloured.colorscale] == list(theme.SEQUENTIAL)
    assert {stop[1] for stop in grey.colorscale} == {theme.INCOMPLETE}
