"""Pure chart builders: API payload in, Plotly figure out (None when there is nothing to draw)."""

import plotly.graph_objects as go

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


def _percent(fraction: float | None) -> str:
    return "n/a" if fraction is None else f"{fraction * 100:.1f}%"


def funnel_bar(steps: list[dict]) -> go.Figure | None:
    if not steps or steps[0]["users"] == 0:
        return None
    labels = [
        f"{row['users']:,} ({_percent(row['conversion_from_start'])} of start)" for row in steps
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
