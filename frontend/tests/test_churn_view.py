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
    from tests.fake_api import context_for
    from views import churn

    st.info("Demo data: synthetic events from a seeded generator, not real customers.")
    churn.render(ApiClient("http://api.test", lambda: "AT"), context_for())


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


def expander(at, label):
    found = [e for e in at.expander if e.label == label]
    assert len(found) == 1, [e.label for e in at.expander]
    return found[0]


def inside(box):
    """Visible text of one container (an expander)."""
    return "\n".join(str(el.value) for kind in ("caption", "markdown") for el in box.get(kind))


def calls(requested):
    return [q for p, q in zip(requested, requested.queries) if p == "/churn/at-risk"]


def test_baseline_note():
    assert BASELINE_NOTE_FOR_VERSION == "churn-lr-e330fa34d3"
    note = baseline_note("churn-lr-e330fa34d3")
    assert "does not clearly beat" in note
    assert "inactive for 7 or more days" in note
    assert baseline_note("churn-lr-other") == NAIVE


def test_churn_renders_time_basis_counts_and_caveat(monkeypatch):
    at, _ = churn_app(monkeypatch)
    shown = texts(run(at))
    assert BANNER in shown
    assert "Scored at cutoff 30 Oct 2026 using the 28 days before it" in shown
    assert "Data through 30 Oct 2026" in shown
    assert "Scores estimate which customers are likely to go quiet over the next 30 days." in shown
    assert "Eligible customers scored: 120" in shown
    assert "Eligible customers scored: 120 (n=120)" not in shown
    assert "At risk (score at or above the threshold): 18 (n=120)" in shown
    assert AT_RISK_OK["caveat"] in shown
    assert len(at.get("plotly_chart")) == 1


def test_churn_model_details_are_in_the_collapsed_about_expander(monkeypatch):
    at, _ = churn_app(monkeypatch)
    run(at)
    box = expander(at, "About this model")
    assert box.proto.expanded is False
    details = inside(box)
    assert "churn-lr-e330fa34d3" in details
    assert "ROC-AUC: 0.879" in details
    assert "F1: 0.746" in details
    assert "Precision: 0.700" in details
    assert "Recall: 0.800" in details
    assert "Test churn rate: 35.0%" in details
    assert "Test set size n: 400" in details
    assert "Test data synthetic: yes" in details
    assert "does not clearly beat" in details
    outside = "\n".join(
        str(el.value) for kind in ("caption", "markdown") for el in at.main.get(kind)
    )
    main_only = outside.replace(details, "")
    for text in ("ROC-AUC", "Test churn rate", "does not clearly beat", "churn-lr-e330fa34d3"):
        assert text not in main_only


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
    run(at)
    details = inside(expander(at, "About this model"))
    assert "ROC-AUC: n/a" in details
    assert "Test churn rate: n/a" in details
    assert "Test set size n: n/a" in details
    assert "Test data synthetic: n/a" in details
    assert "none" not in details.lower()


def test_churn_table_columns_and_rows(monkeypatch):
    at, requested = churn_app(monkeypatch)
    run(at)
    frame = at.dataframe[0].value
    assert list(frame.columns) == ["rank", "customer", "risk score (relative)", "predicted class"]
    assert frame["customer"].tolist() == ["cust-001", "cust-002", "cust-003"]
    assert frame["rank"].tolist() == [1, 2, 3]
    assert frame["predicted class"].tolist() == ["At risk", "At risk", "Not at risk"]
    assert frame["risk score (relative)"].tolist() == [0.93, 0.88, 0.41]
    assert calls(requested)[-1] == {
        "dataset_id": 1,
        "limit": 50,
        "offset": 0,
        "sort": "risk_desc",
    }


def test_churn_table_rank_is_integer_and_score_is_float(monkeypatch):
    at, _ = churn_app(monkeypatch)
    run(at)
    frame = at.dataframe[0].value
    assert frame["rank"].dtype.kind == "i"
    assert frame["risk score (relative)"].dtype.kind == "f"


def test_churn_table_caption_explains_the_sort_scope(monkeypatch):
    at, _ = churn_app(monkeypatch)
    shown = texts(run(at))
    assert (
        "The sort above applies to the whole list. "
        "Clicking a column header only reorders the rows on this page."
    ) in shown


def test_churn_unknown_predicted_class_is_shown_as_is(monkeypatch):
    rows = [{**AT_RISK_OK["rows"][0], "predicted_class": "mystery"}]
    at, _ = churn_app(monkeypatch, body=with_changes(rows=rows))
    run(at)
    assert at.dataframe[0].value["predicted class"].tolist() == ["mystery"]


def test_churn_page_input_shown_after_a_successful_fetch(monkeypatch):
    at, _ = churn_app(monkeypatch)
    run(at)
    assert len(at.number_input) == 1
    assert at.number_input[0].key == "churn_page"


def test_churn_page_two_requests_offset_50(monkeypatch):
    at, requested = churn_app(monkeypatch)
    run(at)
    at.number_input[0].set_value(2)
    run(at)
    assert calls(requested)[-1] == {
        "dataset_id": 1,
        "limit": 50,
        "offset": 50,
        "sort": "risk_desc",
    }


SORT_LABELS = ["Highest risk first", "Lowest risk first", "Customer ID (A-Z)"]


def test_churn_sort_selectbox_options_in_order_after_success(monkeypatch):
    at, _ = churn_app(monkeypatch)
    run(at)
    assert len(at.selectbox) == 1
    box = at.selectbox[0]
    assert box.label == "Sort by"
    assert box.key == "churn_sort"
    assert list(box.options) == SORT_LABELS
    assert box.value == "risk_desc"


def test_churn_sort_choice_reaches_the_request(monkeypatch):
    at, requested = churn_app(monkeypatch)
    run(at)
    at.selectbox[0].select("risk_asc")
    run(at)
    assert calls(requested)[-1] == {"dataset_id": 1, "limit": 50, "offset": 0, "sort": "risk_asc"}
    at.selectbox[0].select("customer_asc")
    run(at)
    assert calls(requested)[-1] == {
        "dataset_id": 1,
        "limit": 50,
        "offset": 0,
        "sort": "customer_asc",
    }


def test_churn_changing_sort_on_page_two_resets_to_page_one(monkeypatch):
    at, requested = churn_app(monkeypatch)
    run(at)
    at.number_input[0].set_value(2)
    run(at)
    assert calls(requested)[-1] == {
        "dataset_id": 1,
        "limit": 50,
        "offset": 50,
        "sort": "risk_desc",
    }
    at.selectbox[0].select("risk_asc")
    run(at)
    assert calls(requested)[-1] == {"dataset_id": 1, "limit": 50, "offset": 0, "sort": "risk_asc"}
    assert at.number_input[0].value == 1


def test_churn_paging_keeps_the_chosen_sort(monkeypatch):
    at, requested = churn_app(monkeypatch)
    run(at)
    at.selectbox[0].select("customer_asc")
    run(at)
    at.number_input[0].set_value(2)
    run(at)
    assert calls(requested)[-1] == {
        "dataset_id": 1,
        "limit": 50,
        "offset": 50,
        "sort": "customer_asc",
    }


def test_churn_page_beyond_end_does_not_crash(monkeypatch):
    at, _ = churn_app(monkeypatch, body=with_changes(rows=[]))
    shown = texts(run(at))
    assert "No customers on this page" in shown
    assert len(at.number_input) == 1  # still there, so the user can page back


def test_churn_empty_when_no_eligible_customers(monkeypatch):
    body = with_changes(eligible_customers=0, at_risk_count=0, rows=[])
    at, _ = churn_app(monkeypatch, body=body)
    shown = texts(run(at))
    assert "No customers to score yet" in shown
    assert len(at.get("plotly_chart")) == 0
    assert len(at.dataframe) == 0
    assert len(at.number_input) == 0
    assert len(at.selectbox) == 0


def test_churn_empty_when_cutoff_is_none(monkeypatch):
    body = with_changes(cutoff=None, data_through=None, eligible_customers=0, rows=[])
    at, _ = churn_app(monkeypatch, body=body)
    shown = texts(run(at))
    assert "No customers to score yet" in shown
    assert len(at.get("plotly_chart")) == 0
    assert len(at.dataframe) == 0
    assert len(at.number_input) == 0
    assert len(at.selectbox) == 0


def test_churn_503_shows_retry_without_server_text(monkeypatch):
    at, _ = churn_app(monkeypatch, status=503, body={"detail": "model not loaded"})
    shown = texts(run(at))
    assert "The service is unavailable. Please try again shortly." in shown
    assert "model not loaded" not in shown
    assert "Retry" in [b.label for b in at.get("button")]
    assert len(at.dataframe) == 0
    assert len(at.number_input) == 0
    assert len(at.selectbox) == 0
