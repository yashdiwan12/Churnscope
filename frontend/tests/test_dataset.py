"""The dataset selector, banner, fallback, capability gating and derived-signup notes."""

import pytest
from streamlit.testing.v1 import AppTest

from dataset import banner_text
from tests.fake_api import (
    AT_RISK_OK,
    BANNER,
    DATASETS_DEMO_ONLY,
    DATASETS_WITH_UPLOAD,
    ENGAGEMENT_OK,
    FUNNEL_OK,
    ME_OK,
    OVERVIEW_OK,
    RETENTION_OK,
    UPLOAD_ROW,
    context_for,
    dataset_row,
    install,
    run,
    signed_in_app,
    texts,
)

FALLBACK = "Your selected dataset is no longer available. Showing demo data."
UPLOAD_BANNER = "Your uploaded data: events.csv, private to you."
GONE = "That dataset is no longer available. Choose a dataset in the sidebar."
OVERVIEW_NOTE = (
    "Signup dates are derived from each customer's first event in your file, "
    "so New users includes customers who joined before the file starts."
)
RETENTION_NOTE = (
    "Signup dates are derived from each customer's first event in your file, "
    "so the first cohort includes customers who joined before the file starts."
)
CHURN_NOTE = (
    "Account age is unreliable: signup dates are derived from each customer's "
    "first event in your file."
)
NO_RETENTION = (
    'Retention needs a signup event. Map one of your events to signup, or re-upload with "first '
    'event counts as signup".'
)


def app(monkeypatch, datasets=DATASETS_WITH_UPLOAD, **extra):
    routes = {"/me": (200, ME_OK), "/datasets": datasets, "/analytics/overview": (200, OVERVIEW_OK)}
    routes = routes | extra
    at, requested = signed_in_app(monkeypatch, routes)
    at.routes = routes  # tests may change an answer between runs
    return at, requested


def overview_queries(requested):
    return [q for p, q in zip(requested, requested.queries) if p == "/analytics/overview"]


def test_selector_lists_demo_and_upload(monkeypatch):
    at, _ = app(monkeypatch)
    run(at)
    box = at.sidebar.selectbox(key="dataset_id")
    assert box.label == "Data"
    assert list(box.options) == ["Demo data", "My data: events.csv"]
    assert box.value == 1
    assert BANNER in texts(at)


def test_selecting_the_upload_changes_banner_and_request(monkeypatch):
    at, requested = app(monkeypatch)
    run(at)
    at.sidebar.selectbox(key="dataset_id").select(7)
    run(at)
    shown = texts(at)
    assert UPLOAD_BANNER in shown
    assert BANNER not in shown
    assert overview_queries(requested)[-1]["dataset_id"] == 7


def test_banner_follows_dataset():
    assert banner_text(context_for()) == BANNER
    assert banner_text(context_for(UPLOAD_ROW)) == UPLOAD_BANNER


def test_unknown_selected_id_falls_back_with_notice(monkeypatch):
    at, requested = app(monkeypatch, datasets=DATASETS_DEMO_ONLY)
    at.session_state["dataset_id"] = 7
    shown = texts(run(at))
    assert FALLBACK in shown
    assert BANNER in shown
    assert at.session_state["dataset_id"] == 1
    assert overview_queries(requested)[-1]["dataset_id"] == 1


def test_no_notice_when_selection_is_listed(monkeypatch):
    at, _ = app(monkeypatch)
    at.session_state["dataset_id"] = 7
    assert FALLBACK not in texts(run(at))


def test_deleted_dataset_never_served_from_cache(monkeypatch):
    at, requested = app(monkeypatch)
    at.session_state["dataset_id"] = 7
    run(at)
    assert overview_queries(requested)[-1]["dataset_id"] == 7  # id 7 is now cached
    at.routes["/datasets"] = DATASETS_DEMO_ONLY
    run(at)
    queries = overview_queries(requested)
    assert len(queries) == 2
    assert queries[-1]["dataset_id"] == 1
    shown = texts(at)
    assert FALLBACK in shown
    assert "Active users" in shown


def test_datasets_call_is_made_on_every_rerun(monkeypatch):
    at, requested = app(monkeypatch)
    run(at)
    run(at)
    assert requested.count("/datasets") == 2


def test_datasets_failure_shows_fixed_error_and_no_page(monkeypatch):
    at, requested = app(monkeypatch, datasets=(503, {"detail": "db password"}))
    shown = texts(run(at))
    assert "The service is unavailable. Please try again shortly." in shown
    assert "db password" not in shown
    assert "Active users" not in shown
    assert "/analytics/overview" not in requested


def test_selection_survives_one_failed_dataset_list(monkeypatch):
    at, _ = app(monkeypatch)
    run(at)
    at.sidebar.selectbox(key="dataset_id").select(7)
    run(at)
    at.routes["/datasets"] = (503, {"detail": "down"})
    shown = texts(run(at))
    assert "The service is unavailable. Please try again shortly." in shown
    # Streamlit drops a widget's state when a run ends without rendering it; AppTest keeps it.
    del at.session_state["dataset_id"]
    at.routes["/datasets"] = DATASETS_WITH_UPLOAD
    shown = texts(run(at))
    assert at.sidebar.selectbox(key="dataset_id").value == 7
    assert FALLBACK not in shown
    assert UPLOAD_BANNER in shown


def view_script(view_name, row):
    import importlib

    import streamlit as st

    from api_client import ApiClient
    from tests.fake_api import context_for

    st.info("x")
    importlib.import_module(f"views.{view_name}").render(
        ApiClient("http://api.test", lambda: "AT"), context_for(row)
    )


def view_app(monkeypatch, view_name, row, routes):
    monkeypatch.setenv("SUPABASE_URL", "https://p.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    requested = install(monkeypatch, routes)
    at = AppTest.from_function(view_script, args=(view_name, row), default_timeout=30)
    return at, requested


def test_missing_capability_makes_no_request(monkeypatch):
    row = dataset_row(
        7, "upload", "events.csv", retention=False, funnel=False, funnel_missing=["export", "pay"]
    )
    at, requested = view_app(monkeypatch, "retention", row, {})
    shown = texts(run(at))
    assert NO_RETENTION in shown
    assert requested == []

    at, requested = view_app(monkeypatch, "funnel", row, {})
    shown = texts(run(at))
    assert "The funnel needs these steps: export, pay." in shown
    assert requested == []


def test_upload_without_scoring_offers_retry_and_makes_no_request(monkeypatch):
    at, requested = view_app(monkeypatch, "churn", UPLOAD_ROW, {})
    shown = texts(run(at))
    assert "Churn scoring failed for your file." in shown
    assert requested == []


def derived(**capabilities):
    return dataset_row(
        7, "upload", "events.csv", signup_rule="derived_from_first_event", **capabilities
    )


@pytest.mark.parametrize(
    "view_name,path,body,note",
    [
        ("overview", "/analytics/overview", OVERVIEW_OK, OVERVIEW_NOTE),
        ("retention", "/analytics/retention", RETENTION_OK, RETENTION_NOTE),
        ("churn", "/churn/at-risk", AT_RISK_OK, CHURN_NOTE),
    ],
)
def test_derived_notes_shown(monkeypatch, view_name, path, body, note):
    at, _ = view_app(monkeypatch, view_name, derived(), {path: (200, body)})
    assert note in texts(run(at))
    # An event-based signup never shows it.
    at, _ = view_app(monkeypatch, view_name, dataset_row(), {path: (200, body)})
    assert note not in texts(run(at))


def test_funnel_and_engagement_pass_dataset_id(monkeypatch):
    for name, path, body in [
        ("funnel", "/analytics/funnel", FUNNEL_OK),
        ("engagement", "/analytics/engagement", ENGAGEMENT_OK),
    ]:
        at, requested = view_app(monkeypatch, name, UPLOAD_ROW, {path: (200, body)})
        run(at)
        assert requested.queries[-1]["dataset_id"] == 7


def test_404_message():
    def error_script():
        from api_client import ApiError
        from states import render_error

        render_error(ApiError(404), retry_key="r")

    at = AppTest.from_function(error_script)
    at.run()
    assert [e.value for e in at.error] == [GONE]
