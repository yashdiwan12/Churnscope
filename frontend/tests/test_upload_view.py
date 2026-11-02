"""The Upload data page. The file widget is faked (AppTest cannot drive file_uploader)."""

import json
import tomllib
from pathlib import Path

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from labels import escape_markdown
from tests.fake_api import (
    DATASETS_DEMO_ONLY,
    DATASETS_WITH_UPLOAD,
    DEMO_ROW,
    UPLOAD_ROW,
    install,
    run,
    texts,
)
from views import upload

NOTICE = (
    "Your file is kept until you delete it or your access is removed. "
    "Do not upload personal data you are not allowed to share."
)
CENSOR = (
    "Most customers' first event falls in the first week of your file. They probably joined "
    "earlier, so signup dates, new users and the first retention cohort will be approximate."
)
ACK = "I understand signup dates are approximate"
DERIVE = "Treat each customer's first event as signup"
REPLACE = "Replace my existing upload"
DELETE_CONFIRM = "Yes, delete my data"
SERVER_TEXT = "SERVER-SECRET-TEXT"
UPLOAD_BANNER = "Your uploaded data: events.csv, private to you."
CSV = b"customer_id,event_name,event_timestamp,event_id\nc1,login,2026-10-01T00:00:00Z,e1\n"
FILE = ("events.csv", CSV, "text/csv")

CHECK_OK = {
    "total_rows": 100,
    "valid_rows": 98,
    "customers": 20,
    "first_event": "2026-10-01T00:00:00Z",
    "last_event": "2026-10-30T00:00:00Z",
    "event_names": [{"name": "Sign Up", "count": 20}, {"name": "login", "count": 78}],
    "suggested_mapping": {"Sign Up": "signup", "login": "login"},
    "skipped_count": 2,
    "skipped": [{"row": 5, "code": "bad_timestamp"}, {"row": 9, "code": "missing_customer_id"}],
    "zoneless_timestamps": False,
    "first_week_share": 0.2,
    "censor_warning": False,
    "our_event_names": ["signup", "login", "first_report", "export"],
    "qualifying_events": ["login", "report_viewed"],
    "funnel_steps": ["signup", "first_report", "export"],
}
CENSORED = CHECK_OK | {"censor_warning": True, "first_week_share": 0.9}
NO_SIGNUP = {"Sign Up": None, "login": "login"}
IMPORT_OK = {
    "dataset": dict(UPLOAD_ROW),
    "imported_events": 90,
    "derived_signups": 0,
    "ignored_rows": 3,
    "duplicate_rows": 2,
    "invalid_rows": 3,
    "skipped": [{"row": 5, "code": "bad_timestamp"}],
}


def page_script(file_name, file_bytes):
    import streamlit as st

    import dataset
    from api_client import ApiClient
    from tests.fake_api import ME_OK
    from views import upload

    upload.current_upload = lambda: None if file_name is None else (file_name, file_bytes)
    api = ApiClient("http://api.test", lambda: "AT")
    ctx = dataset.select(api, ME_OK)
    st.info(dataset.banner_text(ctx))
    upload.render(api, ctx)


def page(monkeypatch, routes, datasets=DATASETS_DEMO_ONLY, file=("events.csv", CSV)):
    monkeypatch.setenv("SUPABASE_URL", "https://p.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    routes = {"/datasets": datasets} | routes
    requested = install(monkeypatch, routes)
    at = AppTest.from_function(page_script, args=file or (None, None), default_timeout=30)
    at.routes = routes
    return at, requested


def button(at, label):
    return next(b for b in at.button if b.label == label)


def click(at, label):
    button(at, label).click()
    return run(at)


def tick(at, label, value=True):
    next(c for c in at.checkbox if c.label == label).set_value(value)
    return run(at)


def checked(monkeypatch, check=CHECK_OK, datasets=DATASETS_DEMO_ONLY, extra=None, dataset_id=1):
    routes = {"POST /datasets/check": (200, check)} | (extra or {})
    at, requested = page(monkeypatch, routes, datasets)
    at.session_state["dataset_id"] = dataset_id
    run(at)
    click(at, "Check file")
    return at, requested


def after(requested, method, listing, before=DATASETS_DEMO_ONLY):
    """The dataset listing: `before` until a request with `method` succeeded, then `listing`."""
    done = any(
        m == method and p.startswith("/datasets") and p != "/datasets/check"
        for m, p, _ in requested.calls
    )
    return listing if done else before


def posts(requested, path="/datasets"):
    return [kwargs for method, p, kwargs in requested.calls if method == "POST" and p == path]


def test_notice_and_template_shown(monkeypatch):
    at, requested = page(monkeypatch, {}, file=None)
    shown = texts(run(at))
    assert NOTICE in shown
    lines = upload.TEMPLATE_CSV.strip().splitlines()
    assert lines[0] == "customer_id,event_name,event_timestamp,event_id"
    assert len(lines) == 4
    assert [d.label for d in at.get("download_button")] == ["Download template"]
    assert button(at, "Check file").disabled  # nothing chosen yet
    assert requested == ["/datasets"]


def test_check_then_mapping_defaults_from_suggestion(monkeypatch):
    at, requested = checked(monkeypatch)
    assert posts(requested, "/datasets/check")[0]["files"]["file"] == FILE
    boxes = {sb.label: sb for sb in at.selectbox if sb.label.startswith("Map ")}
    assert boxes["Map Sign Up"].value == "signup"
    assert boxes["Map login"].value == "login"
    assert list(boxes["Map login"].options) == ["Ignore", *CHECK_OK["our_event_names"]]
    shown = texts(at)
    assert "98 of 100 rows are valid" in shown
    assert "row 5: the timestamp could not be read" in shown
    assert "row 9: the customer ID is empty" in shown


def test_unsuggested_name_defaults_to_ignore(monkeypatch):
    at, _ = checked(monkeypatch, CHECK_OK | {"suggested_mapping": NO_SIGNUP})
    assert next(s for s in at.selectbox if s.label == "Map Sign Up").value == "Ignore"


def test_new_file_discards_old_check(monkeypatch):
    at, _ = checked(monkeypatch)
    assert any(s.label == "Map login" for s in at.selectbox)
    other = AppTest.from_function(page_script, args=("other.csv", b"x"), default_timeout=30)
    other.session_state["upload_check"] = at.session_state["upload_check"]
    run(other)
    assert not any(s.label == "Map login" for s in other.selectbox)
    assert "upload_check" not in other.session_state


def test_import_button_disabled_until_acknowledged(monkeypatch):
    at, _ = checked(monkeypatch, CENSORED | {"suggested_mapping": NO_SIGNUP})
    assert CENSOR not in texts(at)  # nothing is approximate until signup is derived
    assert not button(at, "Import").disabled
    tick(at, DERIVE)
    assert CENSOR in texts(at)
    assert button(at, "Import").disabled
    tick(at, ACK)
    assert not button(at, "Import").disabled
    tick(at, ACK, False)
    assert button(at, "Import").disabled
    # Mapping a signup event turns derive off, so no acknowledgement is needed.
    next(s for s in at.selectbox if s.label == "Map Sign Up").select("signup")
    run(at)
    assert not button(at, "Import").disabled
    assert CENSOR not in texts(at)


def test_no_censor_warning_when_not_flagged(monkeypatch):
    at, _ = checked(monkeypatch)
    assert CENSOR not in texts(at)
    assert not any(c.label == ACK for c in at.checkbox)
    assert not button(at, "Import").disabled


def test_import_disabled_without_qualifying_event_mapped(monkeypatch):
    at, _ = checked(monkeypatch, CHECK_OK | {"suggested_mapping": {"Sign Up": "signup"}})
    assert button(at, "Import").disabled


def test_replace_confirmation_required_when_upload_exists(monkeypatch):
    at, _ = checked(monkeypatch, datasets=DATASETS_WITH_UPLOAD, dataset_id=7)
    assert button(at, "Import").disabled
    tick(at, REPLACE)
    assert not button(at, "Import").disabled


def test_derive_disabled_when_signup_mapped(monkeypatch):
    at, _ = checked(monkeypatch)
    assert next(c for c in at.checkbox if c.label == DERIVE).disabled
    next(s for s in at.selectbox if s.label == "Map Sign Up").select("Ignore")
    run(at)
    assert not next(c for c in at.checkbox if c.label == DERIVE).disabled


def test_preview_names_unavailable_pages():
    mapping = {"Sign Up": "signup", "login": "login", "x": "first_report"}
    result = upload.preview(mapping, False, CHECK_OK)
    assert result["Overview"] is None
    assert result["Engagement"] is None
    assert result["Retention"] is None
    assert result["Funnel"] == "needs the export step"
    assert result["Churn Risk"] == upload.CHURN_OK

    result = upload.preview({"login": "login"}, False, CHECK_OK)
    assert result["Retention"] == "needs a signup event, or the first-event option"
    assert result["Funnel"] == "needs the signup, first_report and export steps"
    assert upload.preview({"login": "login"}, True, CHECK_OK)["Retention"] is None
    assert result["Churn Risk"] == "needs a signup event, or the first-event option"
    assert upload.preview({"login": "login"}, True, CHECK_OK)["Churn Risk"] == upload.CHURN_OK

    result = upload.preview({"Sign Up": "signup"}, False, CHECK_OK)
    assert result["Overview"] == "needs at least one activity event"
    assert result["Engagement"] == "needs at least one activity event"


def test_preview_is_driven_by_the_check_lists():
    check = CHECK_OK | {"qualifying_events": ["zzz"], "funnel_steps": ["a", "b"]}
    result = upload.preview({"t": "zzz", "u": "a"}, False, check)
    assert result["Overview"] is None
    assert result["Funnel"] == "needs the b step"


def test_preview_shown_on_page(monkeypatch):
    shown = texts(checked(monkeypatch)[0])
    assert "Funnel: needs the first_report and export steps" in shown
    assert (
        "Churn Risk: will work; results are checked on your own history from about 9 weeks" in shown
    )
    assert "not available for uploaded data yet" not in shown


def test_preview_churn_needs_28_days_of_history():
    short = CHECK_OK | {"first_event": "2026-10-01T00:00:00Z", "last_event": "2026-10-20T00:00:00Z"}
    mapping = {"Sign Up": "signup", "login": "login"}
    assert upload.preview(mapping, False, short)["Churn Risk"] == (
        "needs at least 28 days of history"
    )
    edge = CHECK_OK | {"last_event": "2026-10-29T00:00:00Z"}
    assert upload.preview(mapping, False, edge)["Churn Risk"] == upload.CHURN_OK


def test_invalid_character_skip_has_fixed_copy():
    line = upload._skip_line({"row": 3, "code": "invalid_character"})
    assert line == "row 3: a value contains a character that cannot be stored"


def test_retry_rebuilds_the_form_from_the_current_mapping(monkeypatch):
    at, requested = checked(monkeypatch, extra={"POST /datasets": (200, httpx.ReadTimeout("t"))})
    click(at, "Import")
    next(s for s in at.selectbox if s.label == "Map Sign Up").select("Ignore")
    run(at)
    at.routes["POST /datasets"] = (201, IMPORT_OK)
    click(at, "Retry import")
    first, second = posts(requested)
    assert json.loads(first["data"]["mapping"])["Sign Up"] == "signup"
    assert json.loads(second["data"]["mapping"])["Sign Up"] is None


def test_retry_is_disabled_when_replace_confirmation_is_removed(monkeypatch):
    at, _ = checked(
        monkeypatch,
        datasets=DATASETS_WITH_UPLOAD,
        dataset_id=7,
        extra={"POST /datasets": (200, httpx.ReadTimeout("t"))},
    )
    tick(at, REPLACE)
    click(at, "Import")
    assert not button(at, "Retry import").disabled
    tick(at, REPLACE, False)
    assert button(at, "Retry import").disabled


def test_import_success_switches_dataset_and_clears_cache(monkeypatch):
    runs = {"n": 0}

    @st.cache_data
    def cached():
        runs["n"] += 1
        return runs["n"]

    cached()
    at, requested = checked(monkeypatch, extra={"POST /datasets": (201, IMPORT_OK)})
    at.routes["/datasets"] = lambda: after(requested, "POST", DATASETS_WITH_UPLOAD)
    click(at, "Import")
    [sent] = posts(requested)
    assert sent["files"]["file"] == FILE
    assert json.loads(sent["data"]["mapping"]) == {"Sign Up": "signup", "login": "login"}
    assert sent["data"]["derive_signup"] == "false"
    assert sent["data"]["acknowledge_approximate_signup"] == "false"
    assert at.session_state["dataset_id"] == 7
    assert "upload_check" not in at.session_state
    assert cached() == 2  # the import cleared the cache
    shown = texts(at)
    for part in ["90 events imported", "3 rows ignored", "2 duplicate rows", "3 invalid rows"]:
        assert part in shown
    assert "row 5: the timestamp could not be read" in shown
    assert UPLOAD_BANNER in shown


def test_derived_signups_in_summary_and_flags_sent(monkeypatch):
    at, requested = checked(
        monkeypatch,
        CENSORED | {"suggested_mapping": NO_SIGNUP},
        extra={"POST /datasets": (201, IMPORT_OK | {"derived_signups": 20})},
    )
    tick(at, DERIVE)
    tick(at, ACK)
    at.routes["/datasets"] = lambda: after(requested, "POST", DATASETS_WITH_UPLOAD)
    click(at, "Import")
    [sent] = posts(requested)
    assert sent["data"]["derive_signup"] == "true"
    assert sent["data"]["acknowledge_approximate_signup"] == "true"
    assert json.loads(sent["data"]["mapping"]) == NO_SIGNUP
    assert "20 signup events derived" in texts(at)


CODES = [
    "empty_file",
    "not_utf8",
    "missing_columns",
    "too_many_rows",
    "too_many_customers",
    "too_many_event_names",
    "too_many_invalid",
    "no_activity_event",
    "bad_mapping",
    "derive_not_allowed",
    "acknowledgement_required",
    "bad_form",
    "missing_file",
    "file_too_large",
    "length_required",
    "storage_full",
]
STATUS = {"file_too_large": 413, "length_required": 411, "storage_full": 409}


def error_body(code):
    return {"detail": {"code": code, "message": SERVER_TEXT}}


@pytest.mark.parametrize("code", [*CODES, "brand_new_code"])
def test_rejection_code_shows_fixed_message_on_check(monkeypatch, code):
    status = STATUS.get(code, 422)
    at, _ = page(monkeypatch, {"POST /datasets/check": (status, error_body(code))})
    run(at)
    click(at, "Check file")
    shown = texts(at)
    assert SERVER_TEXT not in shown
    assert upload.message_for(code) in shown
    assert "upload_check" not in at.session_state


def test_each_code_has_its_own_message_and_unknown_is_generic():
    messages = [upload.message_for(code) for code in CODES]
    assert len(set(messages)) == len(CODES)
    assert upload.message_for("brand_new_code") not in messages
    assert upload.message_for(None) == upload.message_for("brand_new_code")


@pytest.mark.parametrize("code", ["bad_mapping", "storage_full", "too_many_rows", "zzz"])
def test_rejection_code_shows_fixed_message_on_import(monkeypatch, code):
    status = 409 if code == "storage_full" else 422
    at, _ = checked(monkeypatch, extra={"POST /datasets": (status, error_body(code))})
    click(at, "Import")
    shown = texts(at)
    assert SERVER_TEXT not in shown
    assert upload.message_for(code) in shown
    assert at.session_state["dataset_id"] == 1


def test_import_timeout_offers_retry_with_same_bytes(monkeypatch):
    at, requested = checked(monkeypatch, extra={"POST /datasets": (200, httpx.ReadTimeout("t"))})
    click(at, "Import")
    assert "The service is unavailable. Please try again shortly." in texts(at)
    at.routes["POST /datasets"] = (201, IMPORT_OK)
    # The listing shows the upload only once the second (successful) POST has been made.
    at.routes["/datasets"] = lambda: (
        DATASETS_WITH_UPLOAD if len(posts(requested)) >= 2 else DATASETS_DEMO_ONLY
    )
    click(at, "Retry import")
    first, second = posts(requested)
    assert first["files"]["file"] == second["files"]["file"] == FILE
    assert first["data"] == second["data"]
    assert at.session_state["dataset_id"] == 7
    assert "90 events imported" in texts(at)


def test_delete_requires_confirmation_and_falls_back_to_demo(monkeypatch):
    runs = {"n": 0}

    @st.cache_data
    def cached():
        runs["n"] += 1
        return runs["n"]

    cached()
    at, requested = page(
        monkeypatch, {"DELETE /datasets/7": (204, None)}, DATASETS_WITH_UPLOAD, file=None
    )
    at.routes["/datasets"] = lambda: after(
        requested, "DELETE", DATASETS_DEMO_ONLY, DATASETS_WITH_UPLOAD
    )
    at.session_state["dataset_id"] = 7
    run(at)
    assert button(at, "Delete my data").disabled
    tick(at, DELETE_CONFIRM)
    assert not button(at, "Delete my data").disabled
    click(at, "Delete my data")
    assert ("DELETE", "/datasets/7") in [(m, p) for m, p, _ in requested.calls]
    assert at.session_state["dataset_id"] == 1
    assert cached() == 2
    shown = texts(at)
    assert "Your data was deleted." in shown
    assert not any(b.label == "Delete my data" for b in at.button)


def test_replace_confirmation_required_with_demo_selected(monkeypatch):
    at, _ = checked(monkeypatch, datasets=DATASETS_WITH_UPLOAD, dataset_id=1)
    assert "replaces your current upload, events.csv" in texts(at)
    assert button(at, "Import").disabled
    tick(at, REPLACE)
    assert not button(at, "Import").disabled


def test_delete_from_demo_uses_the_upload_id(monkeypatch):
    at, requested = page(
        monkeypatch, {"DELETE /datasets/7": (204, None)}, DATASETS_WITH_UPLOAD, file=None
    )
    at.routes["/datasets"] = lambda: after(
        requested, "DELETE", DATASETS_DEMO_ONLY, DATASETS_WITH_UPLOAD
    )
    run(at)
    assert at.session_state["dataset_id"] == 1
    assert button(at, "Delete my data").disabled
    tick(at, DELETE_CONFIRM)
    click(at, "Delete my data")
    assert ("DELETE", "/datasets/7") in [(m, p) for m, p, _ in requested.calls]
    assert at.session_state["dataset_id"] == 1
    assert "Your data was deleted." in texts(at)


def test_delete_not_offered_on_demo(monkeypatch):
    at, _ = page(monkeypatch, {}, file=None)
    run(at)
    assert not any(b.label == "Delete my data" for b in at.button)


def test_delete_error_shows_fixed_message(monkeypatch):
    routes = {"DELETE /datasets/7": (404, error_body("x"))}
    at, _ = page(monkeypatch, routes, DATASETS_WITH_UPLOAD, file=None)
    at.session_state["dataset_id"] = 7
    run(at)
    tick(at, DELETE_CONFIRM)
    click(at, "Delete my data")
    shown = texts(at)
    assert SERVER_TEXT not in shown
    assert "That dataset is no longer available" in shown


def test_filename_markdown_is_escaped_in_banner_and_page(monkeypatch):
    name = "my_*_[x](http://e.com)_:red[y].csv"
    row = {**UPLOAD_ROW, "name": name, "source_filename": name}
    at, _ = page(monkeypatch, {}, (200, [DEMO_ROW, row]), file=(name, CSV))
    at.session_state["dataset_id"] = 7
    shown = texts(run(at))
    assert f"Your uploaded data: {escape_markdown(name)}, private to you." in shown
    assert name not in shown.replace(escape_markdown(name), "")


def test_max_upload_size_config():
    path = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"
    assert tomllib.loads(path.read_text(encoding="utf-8"))["server"]["maxUploadSize"] == 5


def test_upload_page_is_registered():
    source = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    assert '(upload, "Upload data", "upload")' in source


NO_ROWS = CHECK_OK | {
    "valid_rows": 0,
    "customers": 0,
    "first_event": None,
    "last_event": None,
    "event_names": [],
    "suggested_mapping": {},
    "skipped_count": 2,
}
NO_ROWS_MESSAGE = "No usable rows in this file. Fix the rows listed below and check the file again."


def test_preview_without_dates_reports_no_usable_events():
    result = upload.preview({}, True, NO_ROWS)
    assert result["Churn Risk"] == upload.CHURN_NO_EVENTS
    assert upload._history_days(NO_ROWS) is None


@pytest.mark.parametrize("derive", [False, True])
def test_file_with_no_usable_rows_renders_message_and_disabled_import(monkeypatch, derive):
    at, _ = checked(monkeypatch, NO_ROWS)
    assert not at.exception
    if derive:  # the option is not offered, so it cannot be ticked
        assert not [c for c in at.checkbox if c.label == DERIVE]
    shown = texts(at)
    assert NO_ROWS_MESSAGE in shown
    assert "row 5: the timestamp could not be read" in shown
    assert "row 9: the customer ID is empty" in shown
    assert not any(s.label.startswith("Map ") for s in at.selectbox)
    assert button(at, "Import").disabled
