"""Retention: share of each signup-week cohort still active in later weeks."""

import streamlit as st

import data
from api_client import ApiClient, ApiError, NotAllowed, NotSignedIn, ServiceUnavailable
from charts import retention_heatmap, retention_matrix
from labels import cohorts_label, freshness_label
from states import render_empty, render_error


def render(api: ApiClient) -> None:
    st.header("Retention")
    periods = st.sidebar.slider("Weeks after signup", 1, 26, 8)
    try:
        with st.spinner("Loading retention..."):
            result = data.retention(api, periods)
    except (ApiError, NotAllowed, NotSignedIn, ServiceUnavailable) as exc:
        render_error(exc, retry_key="retention_retry")
        return

    st.caption(cohorts_label(result["as_of"]))
    st.caption(freshness_label(result["as_of"]))
    matrix = retention_matrix(result["cells"])
    figure = retention_heatmap(matrix)
    if figure is None:
        render_empty("No cohorts to show yet")
        return

    if not matrix["complete"].all():
        st.warning(
            "Some cells are incomplete: their cohort has not had the full period to return yet, "
            "so they are shown in grey and not coloured by their rate."
        )
    st.plotly_chart(figure, width="stretch")
    with st.expander("Cell details"):
        for row in matrix.itertuples():
            st.caption(f"Cohort {row.cohort}, week {row.period}: {row.label}")
