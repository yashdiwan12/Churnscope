"""Retention: share of each signup-week cohort still active in later weeks."""

import streamlit as st

import data
from api_client import ApiClient, ApiError, NotAllowed, NotSignedIn, ServiceUnavailable
from charts import retention_heatmap, retention_matrix, retention_table
from dataset import Context
from labels import cohorts_label, freshness_label
from states import render_empty, render_error

NEEDS_SIGNUP = (
    "Retention needs a signup event. "
    'Map one of your events to signup, or re-upload with "first event counts as signup".'
)
DERIVED_NOTE = (
    "Signup dates are derived from each customer's first event in your file, "
    "so the first cohort includes customers who joined before the file starts."
)


def render(api: ApiClient, ctx: Context) -> None:
    st.header("Retention")
    if not ctx.capabilities["retention"]:
        render_empty(NEEDS_SIGNUP)
        return
    periods = st.sidebar.slider("Weeks after signup", 1, 26, 8)
    try:
        with st.spinner("Loading retention..."):
            result = data.retention(api, ctx.dataset_id, ctx.user_id, periods)
    except (ApiError, NotAllowed, NotSignedIn, ServiceUnavailable) as exc:
        render_error(exc, retry_key="retention_retry")
        return

    st.caption(cohorts_label(result["as_of"]))
    st.caption(freshness_label(result["as_of"]))
    if ctx.derived_signup:
        st.caption(DERIVED_NOTE)
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
        st.dataframe(
            retention_table(matrix),
            column_config={"Retention": st.column_config.NumberColumn(format="%.1f%%")},
            hide_index=True,
            width="stretch",
        )
