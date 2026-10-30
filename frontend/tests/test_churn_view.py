"""The Churn Risk page with a fake API: time basis, honesty labels, table, paging, states."""

import copy
import time

from streamlit.testing.v1 import AppTest

from auth import Tokens
from tests.fake_api import AT_RISK_OK, BANNER, CONFIGURED, install, run, texts
from views.churn import BASELINE_NOTE_FOR_VERSION, baseline_note

NAIVE = "Compare with the naive baselines in the model card."


def churn_script():
    import streamlit as st

    from api_client import ApiClient
    from views import churn

    st.info("Demo data: synthetic events from a seeded generator, not real customers.")
    churn.render(ApiClient("http://api.test", lambda: "AT"))


def churn_app(monkeypatch, status=200, body=AT_RISK_OK):
    for key, value in CONFIGURED.items():
        monkeypatch.setenv(key, value)
    requested = install(monkeypatch, {"/churn/at-risk": (status, body)})
    at = AppTest.from_function(churn_script, default_timeout=30)
    at.session_state["tokens"] = Tokens("AT", "RT", time.time() + 3600)
    return at, requested


def with_changes(**changes):
    body = copy.deepcopy(AT_RISK_OK)
    body.update(changes)
    return body


def calls(requested):
    return [q for p, q in zip(requested, requested.queries) if p == "/churn/at-risk"]


def test_baseline_note():
    assert BASELINE_NOTE_FOR_VERSION == "churn-lr-e330fa34d3"
    note = baseline_note("churn-lr-e330fa34d3")
    assert "does not clearly beat" in note
    assert "inactive for 7 or more days" in note
    assert baseline_note("churn-lr-other") == NAIVE


def test_churn_renders_time_basis_counts_caveat_and_evaluation(monkeypatch):
    at, _ = churn_app(monkeypatch)
    shown = texts(run(at))
    assert BANNER in shown
    assert "Scored at cutoff 30 Oct 2026 using the 28 days before it" in shown
    assert "Data through 30 Oct 2026" in shown
    assert "churn-lr-e330fa34d3" in shown
    assert "30 days" in shown
    assert "120" in shown
    assert "18" in shown
    assert "n=120" in shown
    assert AT_RISK_OK["caveat"] in shown
    assert "ROC-AUC: 0.879" in shown
    assert "F1: 0.746" in shown
    assert "Precision: 0.700" in shown
    assert "Recall: 0.800" in shown
    assert "Test churn rate: 35.0%" in shown
    assert "Test set size n: 400" in shown
    assert "Test data synthetic: yes" in shown
    assert "does not clearly beat" in shown
    assert len(at.get("plotly_chart")) == 1


def test_churn_labels_never_say_probability(monkeypatch):
    body = with_changes(caveat="Relative scores only.")
    at, _ = churn_app(monkeypatch, body=body)
    shown = texts(run(at))
    assert "risk score (relative)" in shown
    assert "probability" not in shown.lower()
    assert "probability" not in str(at.dataframe[0].value.columns).lower()


def test_churn_evaluation_none_fields_show_na(monkeypatch):
    evaluation = dict.fromkeys(AT_RISK_OK["evaluation"])
    at, _ = churn_app(monkeypatch, body=with_changes(evaluation=evaluation))
    shown = texts(run(at))
    assert "ROC-AUC: n/a" in shown
    assert "Test churn rate: n/a" in shown
    assert "Test set size n: n/a" in shown
    assert "Test data synthetic: n/a" in shown
    assert "none" not in shown.lower()


def test_churn_table_columns_and_rows(monkeypatch):
    at, requested = churn_app(monkeypatch)
    run(at)
    frame = at.dataframe[0].value
    assert list(frame.columns) == ["rank", "customer", "risk score (relative)", "predicted class"]
    assert frame["customer"].tolist() == ["cust-001", "cust-002", "cust-003"]
    assert frame["rank"].tolist() == [1, 2, 3]
    assert calls(requested)[-1] == {"limit": 50, "offset": 0}


def test_churn_page_two_requests_offset_50(monkeypatch):
    at, requested = churn_app(monkeypatch)
    run(at)
    at.number_input[0].set_value(2)
    run(at)
    assert calls(requested)[-1] == {"limit": 50, "offset": 50}


def test_churn_page_beyond_end_does_not_crash(monkeypatch):
    at, _ = churn_app(monkeypatch, body=with_changes(rows=[]))
    shown = texts(run(at))
    assert "No customers on this page" in shown


def test_churn_empty_when_no_eligible_customers(monkeypatch):
    body = with_changes(eligible_customers=0, at_risk_count=0, rows=[])
    at, _ = churn_app(monkeypatch, body=body)
    shown = texts(run(at))
    assert "No customers to score yet" in shown
    assert len(at.get("plotly_chart")) == 0
    assert len(at.dataframe) == 0


def test_churn_empty_when_cutoff_is_none(monkeypatch):
    body = with_changes(cutoff=None, data_through=None, eligible_customers=0, rows=[])
    at, _ = churn_app(monkeypatch, body=body)
    shown = texts(run(at))
    assert "No customers to score yet" in shown
    assert len(at.get("plotly_chart")) == 0
    assert len(at.dataframe) == 0


def test_churn_503_shows_retry_without_server_text(monkeypatch):
    at, _ = churn_app(monkeypatch, status=503, body={"detail": "model not loaded"})
    shown = texts(run(at))
    assert "The service is unavailable. Please try again shortly." in shown
    assert "model not loaded" not in shown
    assert "Retry" in [b.label for b in at.get("button")]
    assert len(at.dataframe) == 0
