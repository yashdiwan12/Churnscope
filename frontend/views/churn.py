"""Churn Risk: relative risk scores for current customers and how the model was evaluated."""

import streamlit as st

import data
from api_client import ApiClient, ApiError, NotAllowed, NotSignedIn, ServiceUnavailable
from charts import risk_histogram
from labels import cutoff_label, freshness_label, percent
from states import render_empty, render_error

PAGE_SIZE = 50
BASELINE_NOTE_FOR_VERSION = "churn-lr-e330fa34d3"  # the version docs/model_card.md was written for
_BEATS_NOTE = (
    "On the test set this model does not clearly beat a one-line rule, customers "
    "inactive for 7 or more days (F1 0.746 vs 0.742, ROC-AUC 0.879 vs 0.881)."
)
_OTHER_NOTE = "Compare with the naive baselines in the model card."


def baseline_note(model_version: str) -> str:
    return _BEATS_NOTE if model_version == BASELINE_NOTE_FOR_VERSION else _OTHER_NOTE


def _score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _evaluation(evaluation: dict) -> None:
    st.subheader("Model evaluation (test set)")
    size = evaluation["n"]
    synthetic = evaluation["synthetic"]
    kind = "n/a" if synthetic is None else ("yes" if synthetic else "no")
    st.caption(f"ROC-AUC: {_score(evaluation['roc_auc'])}")
    st.caption(f"F1: {_score(evaluation['f1'])}")
    st.caption(f"Precision: {_score(evaluation['precision'])}")
    st.caption(f"Recall: {_score(evaluation['recall'])}")
    st.caption(f"Test churn rate: {percent(evaluation['test_churn_rate'])}")
    st.caption(f"Test set size n: {'n/a' if size is None else f'{size:,}'}")
    st.caption(f"Test data synthetic: {kind}")


def render(api: ApiClient) -> None:
    st.header("Churn Risk")
    page = int(st.number_input("Page", min_value=1, value=1, step=1, key="churn_page"))
    offset = (page - 1) * PAGE_SIZE
    try:
        with st.spinner("Loading churn risk..."):
            result = data.at_risk(api, PAGE_SIZE, offset)
    except (ApiError, NotAllowed, NotSignedIn, ServiceUnavailable) as exc:
        render_error(exc, retry_key="churn_retry")
        return

    if result["cutoff"] is None or result["eligible_customers"] == 0:
        render_empty("No customers to score yet")
        return

    st.caption(cutoff_label(result["cutoff"], result["window_days"]))
    st.caption(freshness_label(result["data_through"]))
    eligible = result["eligible_customers"]
    st.caption(f"Model version: {result['model_version']}")
    st.caption(f"Prediction horizon: {result['horizon_days']} days")
    st.caption(f"Eligible customers scored: {eligible:,} (n={eligible:,})")
    st.caption(
        f"At risk (score at or above the threshold): {result['at_risk_count']:,} (n={eligible:,})"
    )
    st.caption(
        "Each customer has a risk score (relative): higher means more at risk, not a likelihood."
    )
    st.caption(result["caveat"])
    st.caption(baseline_note(result["model_version"]))

    figure = risk_histogram(result["score_histogram"], result["decision_threshold"])
    if figure is not None:
        st.plotly_chart(figure, width="stretch")

    rows = result["rows"]
    if rows:
        st.dataframe(
            {
                "rank": [row["rank"] for row in rows],
                "customer": [row["customer_id"] for row in rows],
                "risk score (relative)": [row["risk_score"] for row in rows],
                "predicted class": [row["predicted_class"] for row in rows],
            },
            hide_index=True,
            width="stretch",
        )
    else:
        render_empty("No customers on this page")
    _evaluation(result["evaluation"])
