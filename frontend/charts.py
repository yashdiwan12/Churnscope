"""Pure chart builders: API payload in, Plotly figure out (None when there is nothing to draw)."""

import pandas as pd
import plotly.graph_objects as go

from labels import percent

LOW_N_MIN_ELIGIBLE = 20  # a retention cell with fewer eligible users is labelled "low n"


def dau_line(daily_active_users: list[dict]) -> go.Figure | None:
    if not daily_active_users:
        return None
    fig = go.Figure(
        go.Scatter(
            x=[row["date"] for row in daily_active_users],
            y=[row["active_users"] for row in daily_active_users],
            mode="lines+markers",
            name="Daily active users",
        )
    )
    fig.update_layout(
        title="Daily active users",
        xaxis_title="Date (UTC)",
        yaxis_title="Active users",
        yaxis_rangemode="tozero",
        margin={"t": 40, "b": 40},
    )
    return fig


def funnel_bar(steps: list[dict]) -> go.Figure | None:
    if not steps or steps[0]["users"] == 0:
        return None
    labels = [
        f"{row['users']:,} ({percent(row['conversion_from_start'])} of start)" for row in steps
    ]
    fig = go.Figure(
        go.Bar(
            x=[row["users"] for row in steps],
            y=[row["step"] for row in steps],
            orientation="h",
            text=labels,
            textposition="auto",
            name="Users",
        )
    )
    fig.update_layout(
        title="Users reaching each step",
        xaxis_title="Users",
        yaxis={"autorange": "reversed"},
        margin={"t": 40, "b": 40},
    )
    return fig


MATRIX_COLUMNS = [
    "cohort",
    "period",
    "cohort_size",
    "eligible",
    "retained",
    "retention",
    "complete",
    "low_n",
    "label",
]


def _cell_label(cell: dict) -> str:
    rate = "not enough data" if cell["retention"] is None else percent(cell["retention"])
    text = f"{rate} n={cell['eligible']}"
    if not cell["complete"]:
        text += ", incomplete"
    if cell["eligible"] < LOW_N_MIN_ELIGIBLE:
        text += ", low n"
    return text


def retention_matrix(cells: list[dict]) -> pd.DataFrame:
    """One row per cohort/period cell, with `low_n` (fewer than 20 eligible) and a text label."""
    rows = [
        {**cell, "low_n": cell["eligible"] < LOW_N_MIN_ELIGIBLE, "label": _cell_label(cell)}
        for cell in cells
    ]
    return pd.DataFrame(rows, columns=MATRIX_COLUMNS)


def retention_heatmap(matrix: pd.DataFrame) -> go.Figure | None:
    """Cohort-by-period heatmap; incomplete cells are grey rather than coloured by their rate."""
    if matrix.empty:
        return None
    cohorts = sorted(matrix["cohort"].astype(str).unique())
    periods = sorted(matrix["period"].unique())
    rates: list[list[float | None]] = [[None] * len(periods) for _ in cohorts]
    incomplete: list[list[float | None]] = [[None] * len(periods) for _ in cohorts]
    text = [[""] * len(periods) for _ in cohorts]
    for row in matrix.itertuples():
        y = cohorts.index(str(row.cohort))
        x = periods.index(row.period)
        text[y][x] = row.label
        if not row.complete:
            incomplete[y][x] = 0
        elif not pd.isna(row.retention):
            rates[y][x] = float(row.retention)
    common = {
        "x": [f"Week {p}" for p in periods],
        "y": cohorts,
        "text": text,
        "hovertemplate": "%{y}, %{x}<br>%{text}<extra></extra>",
    }
    fig = go.Figure(
        [
            go.Heatmap(
                z=rates,
                zmin=0,
                zmax=1,
                colorscale="Blues",
                colorbar={"title": "Retention", "tickformat": ".0%"},
                texttemplate="%{text}",
                hoverongaps=False,
                **common,
            ),
            go.Heatmap(
                z=incomplete,
                colorscale=[[0, "#bdbdbd"], [1, "#bdbdbd"]],
                showscale=False,
                texttemplate="%{text}",
                hoverongaps=False,
                **common,
            ),
        ]
    )
    fig.update_layout(
        title="Retention by signup week",
        xaxis_title="Weeks since signup",
        yaxis_title="Signup week (Monday)",
        yaxis={"autorange": "reversed", "type": "category"},
        margin={"t": 40, "b": 40},
    )
    return fig
