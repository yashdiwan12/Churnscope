"""Funnel: users and conversion at each step, within a conversion window."""

import streamlit as st

import data
from api_client import ApiClient, ApiError, NotAllowed, NotSignedIn, ServiceUnavailable
from charts import funnel_bar
from dataset import Context
from filters import date_range_sidebar
from labels import freshness_label, percent, window_label
from states import render_empty, render_error


def render(api: ApiClient, ctx: Context) -> None:
    st.header("Funnel")
    if not ctx.capabilities["funnel"]:
        missing = ", ".join(ctx.capabilities["funnel_missing"])
        render_empty(f"The funnel needs these steps: {missing}.")
        return
    selection = date_range_sidebar()
    window_days = st.sidebar.slider("Conversion window (days)", 1, 90, 14)
    if selection.error is not None:
        st.sidebar.error(selection.error)
        return
    try:
        with st.spinner("Loading the funnel..."):
            result = data.funnel(
                api, ctx.dataset_id, ctx.user_id, selection.start, selection.end, window_days
            )
    except (ApiError, NotAllowed, NotSignedIn, ServiceUnavailable) as exc:
        render_error(exc, retry_key="funnel_retry")
        return

    st.caption(window_label(result["window"]))
    st.caption(freshness_label(result["window"]["data_through"]))
    steps = result["steps"]
    if not steps or steps[0]["users"] == 0:
        render_empty("No eligible users in this window")
        return

    eligible = result["eligible_users"]
    st.caption(f"Eligible users: {eligible:,}")
    figure = funnel_bar(steps)
    if figure is not None:
        st.container(border=True).plotly_chart(figure, width="stretch")
    previous_users = None
    for row in steps:
        line = f"{row['step']}: {row['users']:,} users"
        if previous_users is not None:
            line += f", {percent(row['conversion_from_previous'])} from previous"
            line += f" (n={previous_users:,})"
        line += f", {percent(row['conversion_from_start'])} from start (n={steps[0]['users']:,})"
        st.caption(line)
        previous_users = row["users"]
    st.caption(result["note"])
