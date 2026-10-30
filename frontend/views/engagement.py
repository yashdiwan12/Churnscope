"""Engagement: how often active users come back and which features they use."""

import streamlit as st

import data
from api_client import ApiClient, ApiError, NotAllowed, NotSignedIn, ServiceUnavailable
from charts import adoption_bars
from filters import date_range_sidebar
from labels import freshness_label, window_label
from states import render_empty, render_error


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def render(api: ApiClient) -> None:
    st.header("Engagement")
    selection = date_range_sidebar()
    if selection.error is not None:
        st.sidebar.error(selection.error)
        return
    try:
        with st.spinner("Loading engagement..."):
            result = data.engagement(api, selection.start, selection.end)
    except (ApiError, NotAllowed, NotSignedIn, ServiceUnavailable) as exc:
        render_error(exc, retry_key="engagement_retry")
        return

    st.caption(window_label(result["window"]))
    st.caption(freshness_label(result["window"]["data_through"]))
    active = result["active_users"]
    if active == 0:
        render_empty("No events in this window")
        return

    n = f"(n={active:,})"
    st.caption(f"Active users: {active:,}")
    st.caption(f"Active days per user (mean): {_number(result['active_days_per_user_mean'])} {n}")
    st.caption(
        f"Active days per user (median): {_number(result['active_days_per_user_median'])} {n}"
    )
    st.caption(f"Events per active user: {_number(result['events_per_active_user'])} {n}")
    st.caption(
        f"Median hours between activities: {_number(result['median_hours_between_activities'])} {n}"
    )

    figure = adoption_bars(result["feature_adoption"])
    if figure is not None:
        st.plotly_chart(figure, width="stretch")
    st.caption(
        "Feature adoption is the share of active users who used each feature, "
        f"not a share of events {n}."
    )
