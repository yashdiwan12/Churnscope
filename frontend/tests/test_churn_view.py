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


# ----------------------------------------------------------------------------- uploads
UPLOAD_CAVEAT = (
    "Churn here means no activity for 14 days, not cancellation. Results are measured on your "
    "file's own history, which shows the method worked recently, not that it will keep working."
)
DERIVED = (
    "Account age is unreliable: signup dates are derived from each customer's "
    "first event in your file."
)
BACKTEST = {
    "train_rows": 1200,
    "train_churners": 300,
    "test_rows": 400,
    "test_churners": 90,
    "train_cutoffs": ["2026-08-01T00:00:00+00:00"],
    "test_cutoffs": ["2026-09-01T00:00:00+00:00", "2026-09-08T00:00:00+00:00"],
    "model": {"pr_auc": 0.71, "roc_auc": 0.83, "precision": 0.6, "recall": 0.7},
    "rule": {"pr_auc": 0.55, "roc_auc": 0.7, "precision": 0.5, "recall": 0.9},
}
SYNTHETIC_TEXTS = (
    "About this model",
    "Model evaluation (test set)",
    "Test data synthetic",
    "Test churn rate",
    "F1:",
    "does not clearly beat",
    "Compare with the naive baselines in the model card.",
    "churn-lr-e330fa34d3",
    "synthetic",
)


def _days_row(rank, customer_id, days, predicted_class):
    return {
        "rank": rank,
        "customer_id": customer_id,
        "risk_score": None,
        "days_inactive": days,
        "predicted_class": predicted_class,
    }


def upload_body(method="logistic", **changes):
    body = copy.deepcopy(AT_RISK_OK)
    body.update(
        dataset_id=7,
        method=method,
        reason=None,
        model_version=method,
        backtest=copy.deepcopy(BACKTEST),
        evaluation=None,
        caveat="SERVER CAVEAT TEXT",
        horizon_days=14,
    )
    if method != "logistic":
        body.update(
            histogram_unit="days_inactive",
            decision_threshold=7.0,
            score_histogram=[
                {"bin_start": i * 7, "bin_end": (i + 1) * 7, "count": c}
                for i, c in enumerate([60, 30, 20, 10])
            ],
            rows=[
                _days_row(1, "cust-009", 25.5, "at_risk"),
                _days_row(2, "cust-004", 8.25, "at_risk"),
                _days_row(3, "cust-001", 0.5, "not_at_risk"),
            ],
        )
    if method == "rule_unchecked":
        body.update(backtest=None, reason="not_enough_history_for_test")
    body.update(changes)
    return body


def upload_row(method="logistic", churn=True, signup_rule="event"):
    from tests.fake_api import dataset_row

    row = dataset_row(7, "upload", "events.csv", signup_rule=signup_rule, churn=churn)
    row["scoring_method"] = method
    return row


def upload_script(row):
    import streamlit as st

    from api_client import ApiClient
    from tests.fake_api import context_for
    from views import churn

    st.info("Your uploaded data: events.csv, private to you.")
    churn.render(ApiClient("http://api.test", lambda: "AT"), context_for(row))


def upload_app(monkeypatch, row, routes):
    for key, value in CONFIGURED.items():
        monkeypatch.setenv(key, value)
    requested = install(monkeypatch, routes)
    at = AppTest.from_function(upload_script, args=(row,), default_timeout=30)
    at.session_state["tokens"] = Tokens("AT", "RT", time.time() + 3600)
    return at, requested


def all_text(at) -> str:
    shown = texts(at)
    frames = [str(list(df.value.columns)) for df in at.dataframe]
    return "\n".join([shown, *frames, *[e.label for e in at.expander]])


def test_upload_churn_shows_backtest_counts(monkeypatch):
    row = upload_row("logistic", signup_rule="derived_from_first_event")
    at, requested = upload_app(monkeypatch, row, {"/churn/at-risk": (200, upload_body())})
    shown = texts(run(at))
    assert calls(requested)[-1]["dataset_id"] == 7
    assert "Method used: a model trained on your file" in shown
    assert (
        "Measured on your history: 400 test rows, 90 churners, PR-AUC model 0.710 vs rule 0.550"
        in shown
    )
    assert "Training: 1,200 rows, 300 churners" in shown
    assert "ROC-AUC: model 0.830, rule 0.700" in shown
    assert UPLOAD_CAVEAT in shown
    assert DERIVED in shown
    assert list(at.dataframe[0].value.columns) == [
        "rank",
        "customer",
        "risk score (relative)",
        "predicted class",
    ]


def test_upload_churn_never_shows_synthetic_metrics(monkeypatch):
    for method in ("logistic", "inactive_rule", "rule_unchecked"):
        # Even a payload that wrongly carries the demo's evaluation block is not shown.
        body = upload_body(method, evaluation=AT_RISK_OK["evaluation"])
        at, _ = upload_app(monkeypatch, upload_row(method), {"/churn/at-risk": (200, body)})
        shown = all_text(run(at))
        for text in SYNTHETIC_TEXTS:
            assert text not in shown, (method, text)
        assert "SERVER CAVEAT TEXT" not in shown
        assert AT_RISK_OK["caveat"] not in shown
        assert UPLOAD_CAVEAT in shown


def test_rule_view_shows_days_not_probability(monkeypatch):
    body = upload_body("inactive_rule")
    at, _ = upload_app(monkeypatch, upload_row("inactive_rule"), {"/churn/at-risk": (200, body)})
    run(at)
    shown = all_text(at)
    frame = at.dataframe[0].value
    assert list(frame.columns) == ["rank", "customer", "days inactive", "predicted class"]
    assert frame["days inactive"].tolist() == [25.5, 8.25, 0.5]
    assert frame["days inactive"].dtype.kind == "f"
    assert "Method used: days since last activity (the rule)" in shown
    assert "At risk (inactive for 7 or more days): 18 (n=120)" in shown
    assert "the longer they have been quiet, the more likely they stay quiet" in shown
    assert "probability" not in shown.lower()
    assert "risk score" not in shown.lower()
    assert list(at.selectbox[0].options) == [
        "Most days inactive first",
        "Fewest days inactive first",
        "Customer ID (A-Z)",
    ]
    assert len(at.get("plotly_chart")) == 1


def test_rule_unchecked_label(monkeypatch):
    body = upload_body("rule_unchecked")
    at, _ = upload_app(monkeypatch, upload_row("rule_unchecked"), {"/churn/at-risk": (200, body)})
    shown = all_text(run(at))
    assert "Not checked on your data: too little history." in shown
    assert "A check needs about 9 weeks of events." in shown
    assert "PR-AUC" not in shown and "Measured on your history" not in shown
    assert "Customers are ranked by days since their last activity." in shown
    assert "the more likely they stay quiet" not in shown
    assert "days inactive" in shown
    assert UPLOAD_CAVEAT in shown


def test_rule_unchecked_unknown_reason_shows_only_the_label(monkeypatch):
    body = upload_body("rule_unchecked", reason="server says <b>hi</b>")
    at, _ = upload_app(monkeypatch, upload_row("rule_unchecked"), {"/churn/at-risk": (200, body)})
    shown = all_text(run(at))
    assert "Not checked on your data: too little history." in shown
    assert "server says" not in shown


def test_upload_with_short_history_names_the_missing_history(monkeypatch):
    at, requested = upload_app(monkeypatch, upload_row("unavailable", churn=False), {})
    shown = texts(run(at))
    assert "Churn scoring needs at least 28 days of history in your file." in shown
    assert calls(requested) == []


def test_upload_scoring_failed_offers_retry(monkeypatch):
    routes = {"POST /datasets/7/score": (200, upload_row("inactive_rule"))}
    at, requested = upload_app(monkeypatch, upload_row("failed", churn=False), routes)
    shown = texts(run(at))
    assert "Churn scoring failed for your file." in shown
    assert calls(requested) == []
    retry = [b for b in at.get("button") if b.label == "Retry scoring"]
    assert len(retry) == 1
    retry[0].click()
    run(at)
    assert ("POST", "/datasets/7/score") in [(m, p) for m, p, _ in requested.calls]


def test_upload_scoring_retry_failure_shows_fixed_copy(monkeypatch):
    routes = {"POST /datasets/7/score": (503, {"detail": "boom from server"})}
    at, _ = upload_app(monkeypatch, upload_row("failed", churn=False), routes)
    run(at)
    next(b for b in at.get("button") if b.label == "Retry scoring").click()
    shown = texts(run(at))
    assert "The service is unavailable. Please try again shortly." in shown
    assert "boom from server" not in shown


def test_upload_without_scoring_offers_retry(monkeypatch):
    # The import committed but storing the score failed: scoring_method is None, signup exists.
    routes = {"POST /datasets/7/score": (200, upload_row("inactive_rule"))}
    at, requested = upload_app(monkeypatch, upload_row(None, churn=False), routes)
    shown = texts(run(at))
    assert "Churn scoring failed for your file." in shown
    assert calls(requested) == []
    retry = [b for b in at.get("button") if b.label == "Retry scoring"]
    assert len(retry) == 1
    retry[0].click()
    run(at)
    assert ("POST", "/datasets/7/score") in [(m, p) for m, p, _ in requested.calls]


def test_upload_without_signup_names_the_missing_signup(monkeypatch):
    row = upload_row(None, churn=False)
    row["capabilities"] = row["capabilities"] | {"retention": False}
    at, requested = upload_app(monkeypatch, row, {})
    shown = texts(run(at))
    assert (
        "Churn Risk needs a signup event. Map one of your events to signup, or re-upload with "
        '"first event counts as signup".'
    ) in shown
    assert "Retry scoring" not in [b.label for b in at.get("button")]
    assert calls(requested) == []
