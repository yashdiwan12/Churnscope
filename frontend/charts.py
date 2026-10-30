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


def adoption_bars(feature_adoption: dict[str, float]) -> go.Figure | None:
    """Share of active users who used each feature, largest first."""
    if not feature_adoption:
        return None
    ranked = sorted(feature_adoption.items(), key=lambda item: item[1], reverse=True)
    fig = go.Figure(
        go.Bar(
            x=[share for _, share in ranked],
            y=[name for name, _ in ranked],
            orientation="h",
            text=[percent(share) for _, share in ranked],
            textposition="auto",
            name="Share of active users",
        )
    )
    fig.update_layout(
        title="Feature adoption",
        xaxis_title="Share of active users",
        xaxis={"tickformat": ".0%", "range": [0, 1]},
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


RETENTION_TABLE_COLUMNS = ["Cohort", "Week", "Retention", "Eligible", "Cohort size", "Status"]


def _status(complete: bool, low_n: bool) -> str:
    text = "Complete" if complete else "Incomplete"
    return f"{text} \u00b7 low n" if low_n else text


def retention_table(matrix: pd.DataFrame) -> pd.DataFrame:
    """The matrix as a plain table: retention in percent (NaN when missing), one status string."""
    return pd.DataFrame(
        {
            "Cohort": matrix["cohort"].astype(str),
            "Week": matrix["period"].astype(int),
            "Retention": pd.to_numeric(matrix["retention"], errors="coerce").astype(float) * 100,
            "Eligible": matrix["eligible"].astype(int),
            "Cohort size": matrix["cohort_size"].astype(int),
            "Status": [_status(c, n) for c, n in zip(matrix["complete"], matrix["low_n"])],
        },
        columns=RETENTION_TABLE_COLUMNS,
    ).reset_index(drop=True)


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


def risk_histogram(bins: list[dict], threshold: float) -> go.Figure | None:
    """Customers per risk-score bin with a vertical line at the decision threshold."""
    if not bins or all(row["count"] == 0 for row in bins):
        return None
    fig = go.Figure(
        go.Bar(
            x=[(row["bin_start"] + row["bin_end"]) / 2 for row in bins],
            y=[row["count"] for row in bins],
            width=[row["bin_end"] - row["bin_start"] for row in bins],
            customdata=[f"{row['bin_start']:.1f} to {row['bin_end']:.1f}" for row in bins],
            hovertemplate="risk score (relative) %{customdata}<br>%{y} customers<extra></extra>",
            name="Customers",
        )
    )
    fig.add_vline(
        x=threshold,
        line_dash="dash",
        annotation_text=f"decision threshold {threshold:.2f}",
    )
    fig.update_layout(
        title="Customers by risk score (relative)",
        xaxis_title="risk score (relative)",
        yaxis_title="customers",
        xaxis={"range": [0, 1]},
        margin={"t": 40, "b": 40},
    )
    return fig
