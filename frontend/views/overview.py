"""Overview: KPI cards, the daily-active-users line and the events that count as activity."""

import streamlit as st

import data
from api_client import ApiClient, ApiError, NotAllowed, NotSignedIn, ServiceUnavailable
from charts import dau_line
from filters import date_range_sidebar
from labels import freshness_label, window_label
from states import render_empty, render_error


def render(api: ApiClient) -> None:
    st.header("Overview")
    selection = date_range_sidebar()
    if selection.error is not None:
        st.sidebar.error(selection.error)
        return
    try:
        with st.spinner("Loading the overview..."):
            result = data.overview(api, selection.start, selection.end)
    except (ApiError, NotAllowed, NotSignedIn, ServiceUnavailable) as exc:
        render_error(exc, retry_key="overview_retry")
        return

    st.caption(window_label(result["window"]))
    st.caption(freshness_label(result["window"]["data_through"]))
    if result["active_users"] == 0:
        render_empty("No events in this window")
        return

    active = result["active_users"]
    cards = st.columns(4)
    cards[0].metric("Active users", f"{active:,}")
    cards[1].metric("New users", f"{result['new_users']:,}")
    cards[2].metric("Returning users", f"{result['returning_users']:,}")
    cards[3].metric("Qualifying events", f"{result['qualifying_events']:,}")
    rate = result["returning_user_rate"]
    if rate is not None:
        cards[2].caption(f"{rate * 100:.1f}% of active users (n={active:,})")

    figure = dau_line(result["daily_active_users"])
    if figure is not None:
        st.plotly_chart(figure, width="stretch")
    names = ", ".join(result["qualifying_event_names"])
    with st.expander("What counts as activity"):
        st.caption(f"Activity means any of these events: {names}")
