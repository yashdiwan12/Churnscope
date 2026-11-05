"""Data & Uploads: check a CSV, match its columns and event names to ours, import it, or delete it.

The file widget is read through `current_upload` alone, so tests can replace it. Every message
for a rejected file is fixed text chosen by the error's code; server text is never shown.
"""

import csv
import io
import json
import zlib
from datetime import datetime

import streamlit as st

from api_client import (
    IMPORT_TIMEOUT,
    ApiClient,
    ApiError,
    NotAllowed,
    NotSignedIn,
    ServiceUnavailable,
)
from dataset import DEMO_ID, Context
from labels import escape_markdown
from states import UNAVAILABLE, render_error

NOTICE = (
    "Your file is kept until you delete it or your access is removed. "
    "Do not upload personal data you are not allowed to share."
)
CENSOR_WARNING = (
    "Most customers' first event falls in the first week of your file. They probably joined "
    "earlier, so signup dates, new users and the first retention cohort will be approximate."
)
ACKNOWLEDGEMENT = "I understand signup dates are approximate"
DERIVE_LABEL = "Treat each customer's first event as signup"
REPLACE_LABEL = "Replace my existing upload"
DELETE_LABEL = "Yes, delete my data"
IGNORE = "Ignore"
TEMPLATE_CSV = (
    "customer_id,event_name,event_timestamp,event_id\n"
    "cust-001,signup,2026-01-05T09:30:00Z,evt-0001\n"
    "cust-001,login,2026-01-06T10:00:00Z,evt-0002\n"
    "cust-002,signup,2026-01-07T14:15:00Z,evt-0003\n"
)

CHOOSE = "Choose a column"
NO_COLUMN = "None"
MAX_HEADERS = 200
# (our column, label, required, header names that usually mean it), compared in lower case with
# spaces and hyphens read as underscores
COLUMN_FIELDS = (
    ("customer_id", "customer_id", True, ("customer", "user_id", "userid", "user", "account_id")),
    ("event_name", "event_name", True, ("event", "event_type", "action", "activity", "name")),
    (
        "event_timestamp",
        "event_timestamp",
        True,
        ("timestamp", "time", "date", "datetime", "created_at", "occurred_at", "event_time", "ts"),
    ),
    ("event_id", "event_id (optional)", False, ("event_uuid", "eventid", "uuid")),
)
COLUMNS_HELP = (
    "Your file's column names differ from ours. Say which of your columns holds each one."
)
COLUMNS_INCOMPLETE = "Choose a column for each required field to check the file."
COLUMNS_REPEATED = "Each column can be used only once."

GENERIC_MESSAGE = "The upload was not accepted. Please check the file and try again."
MESSAGES = {
    "empty_file": "The file is empty.",
    "not_utf8": "The file is not UTF-8 text. Save it as CSV (UTF-8) and try again.",
    "missing_columns": "The file needs the columns customer_id, event_name and event_timestamp.",
    "too_many_rows": "The file has too many rows. Split it and upload a smaller one.",
    "too_many_customers": "The file has too many customers.",
    "too_many_event_names": "The file has too many different event names.",
    "too_many_invalid": (
        "Too many rows in the file could not be read. Compare the file with the template."
    ),
    "no_activity_event": (
        "None of your events count as customer activity. Map at least one event to an "
        "activity event."
    ),
    "bad_mapping": "That event mapping is not valid. Check it and try again.",
    "bad_columns": "That column matching is not valid. Check it and try again.",
    "derive_not_allowed": "First-event signup cannot be used when an event is mapped to signup.",
    "acknowledgement_required": "Tick the box confirming that signup dates are approximate.",
    "bad_form": "The upload request was not understood. Please try again.",
    "missing_file": "No file was received. Choose a file and try again.",
    "file_too_large": "The file is too large to upload.",
    "length_required": "The upload could not be sent. Please try again.",
    "storage_full": "Your upload could not be stored because storage is full.",
}
SKIP_REASONS = {
    "missing_customer_id": "the customer ID is empty",
    "missing_event_name": "the event name is empty",
    "bad_timestamp": "the timestamp could not be read",
    "timestamp_out_of_range": "the timestamp is outside the supported date range",
    "value_too_long": "a value is too long",
    "invalid_character": "a value contains a character that cannot be stored",
}
GENERIC_SKIP = "the row could not be used"
PAGE_ORDER = ["Overview", "Funnel", "Retention", "Engagement", "Churn Risk"]
NO_USABLE_ROWS = "No usable rows in this file. Fix the rows listed below and check the file again."
CHURN_MIN_DAYS = 28
CHURN_NO_SIGNUP = "needs a signup event, or the first-event option"
CHURN_SHORT = "needs at least 28 days of history"
CHURN_NO_EVENTS = "no usable events in this file"
CHURN_OK = "will work; results are checked on your own history from about 9 weeks"


def message_for(code: str | None) -> str:
    return MESSAGES.get(code, GENERIC_MESSAGE)


def current_upload() -> tuple[str, bytes] | None:
    """The file chosen in the widget as (name, bytes), or None."""
    chosen = st.file_uploader("CSV file", type=["csv"])
    return None if chosen is None else (chosen.name, chosen.getvalue())


def header_names(data: bytes) -> list[str]:
    """The file's header cells, trimmed, without blanks or repeats. Never raises: a file we
    cannot read here is left for the server to refuse with its own message."""
    first = data[:20_000].split(b"\n", 1)[0]
    try:
        row = next(csv.reader(io.StringIO(first.decode("utf-8-sig", errors="replace"))), [])
    except csv.Error:
        return []
    names: list[str] = []
    for cell in row:
        cell = cell.strip()
        if cell and cell not in names:
            names.append(cell)
    return names[:MAX_HEADERS]


def _simple(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _default_header(target: str, guesses: tuple[str, ...], headers: list[str]) -> str | None:
    for wanted in (target, *guesses):
        for header in headers:
            if _simple(header) == wanted:
                return header
    return None


def _columns_form(data: bytes) -> tuple[dict[str, str] | None, bool]:
    """Let the user say which of their columns is ours. Returns (columns to send, ready).

    Nothing is shown, and None returned, when the file already has the three required names."""
    headers = header_names(data)
    present = {h.strip().lower() for h in headers}
    if not headers or all(target in present for target, *_ in COLUMN_FIELDS[:3]):
        return None, True
    st.subheader("Match your columns")
    st.caption(COLUMNS_HELP)
    stamp = zlib.crc32("|".join(headers).encode())  # new file or headers, fresh widgets
    columns: dict[str, str] = {}
    for target, label, required, guesses in COLUMN_FIELDS:
        options = [CHOOSE if required else NO_COLUMN, *headers]
        default = (
            _default_header(target, guesses, headers) if required or target in present else None
        )
        choice = st.selectbox(
            f"Column for {label}",
            options,
            index=options.index(default) if default in options else 0,
            key=f"upload_col_{stamp}_{target}",
        )
        if choice not in (CHOOSE, NO_COLUMN):
            columns[target] = choice
    if len(set(columns.values())) != len(columns):
        st.warning(COLUMNS_REPEATED)
        return None, False
    if not all(target in columns for target, *_ in COLUMN_FIELDS[:3]):
        st.caption(COLUMNS_INCOMPLETE)
        return None, False
    return columns, True


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _parse_ts(value) -> datetime:
    return datetime.fromisoformat(str(value))


def _history_days(check: dict) -> float | None:
    """Days between the first and last valid event, or None when the file has no valid event."""
    if not check["valid_rows"] or not check["first_event"] or not check["last_event"]:
        return None
    delta = _parse_ts(check["last_event"]) - _parse_ts(check["first_event"])
    return delta.total_seconds() / 86400


def _churn(mapped: set, check: dict) -> str:
    """Churn needs a signup (as Retention does) and at least 28 days of history."""
    if "signup" not in mapped:
        return CHURN_NO_SIGNUP
    days = _history_days(check)
    if days is None:
        return CHURN_NO_EVENTS
    if days < CHURN_MIN_DAYS:
        return CHURN_SHORT
    return CHURN_OK


def preview(mapping: dict, derive_signup: bool, check: dict) -> dict:
    """Page title -> None when it will work, else why not. Uses the check's own lists."""
    mapped = {target for target in mapping.values() if target}
    if derive_signup:
        mapped.add("signup")
    has_activity = bool(mapped & set(check["qualifying_events"]))
    missing = [step for step in check["funnel_steps"] if step not in mapped]
    no_activity = None if has_activity else "needs at least one activity event"
    return {
        "Overview": no_activity,
        "Funnel": None
        if not missing
        else f"needs the {_join(missing)} step{'s' if len(missing) > 1 else ''}",
        "Retention": None
        if "signup" in mapped
        else "needs a signup event, or the first-event option",
        "Engagement": no_activity,
        "Churn Risk": _churn(mapped, check),
    }


def _skip_line(skip: dict) -> str:
    return f"row {skip['row']}: {SKIP_REASONS.get(skip['code'], GENERIC_SKIP)}"


def _reset_check() -> None:
    for key in ("upload_check", "upload_pending", "upload_failed"):
        st.session_state.pop(key, None)


def _finish(next_id: int) -> None:
    """After an import or delete: drop cached results and point the selector at `next_id`."""
    st.cache_data.clear()
    st.session_state["next_dataset_id"] = next_id  # applied by dataset.select on the next run
    _reset_check()
    st.rerun()


def _show_summary(summary: dict) -> None:
    st.success(f"{summary['imported_events']} events imported.")
    if summary["derived_signups"]:
        st.caption(f"{summary['derived_signups']} signup events derived from first events.")
    st.caption(f"{summary['ignored_rows']} rows ignored (events you did not map).")
    st.caption(f"{summary['duplicate_rows']} duplicate rows skipped.")
    st.caption(f"{summary['invalid_rows']} invalid rows skipped.")
    for skip in summary["skipped"]:
        st.caption(_skip_line(skip))


def _check(api: ApiClient, name: str, data: bytes, columns: dict[str, str] | None) -> None:
    form = {"columns": json.dumps(columns)} if columns else {}
    try:
        result = api.post_file("/datasets/check", file=(name, data, "text/csv"), data=form)
    except ApiError as exc:
        st.error(message_for(exc.code))
        return
    except (NotAllowed, NotSignedIn, ServiceUnavailable) as exc:
        render_error(exc, retry_key="upload_check_retry")
        return
    st.session_state.pop("upload_summary", None)
    previous = st.session_state.get("upload_check", {}).get("n", 0)
    st.session_state["upload_check"] = {
        "name": name,
        "data": data,
        "columns": columns,
        "result": result,
        "n": previous + 1,
    }


def _import(api: ApiClient) -> None:
    pending = st.session_state["upload_pending"]
    try:
        out = api.post_file(
            "/datasets",
            file=(pending["name"], pending["data"], "text/csv"),
            data=pending["form"],
            timeout=IMPORT_TIMEOUT,
        )
    except ServiceUnavailable:
        st.session_state["upload_failed"] = True  # the bytes stay in session_state for Retry
        return
    except ApiError as exc:
        st.session_state["upload_failed"] = False
        st.error(message_for(exc.code))
        return
    except (NotAllowed, NotSignedIn) as exc:
        render_error(exc, retry_key="upload_import_retry")
        return
    st.session_state["upload_summary"] = out
    _finish(out["dataset"]["id"])


def _mapping_form(check: dict, n: int) -> dict:
    st.subheader("Match your events to ours")
    mapping: dict[str, str | None] = {}
    suggested = check["suggested_mapping"]
    options = [IGNORE, *check["our_event_names"]]
    for entry in check["event_names"]:
        name = entry["name"]
        default = suggested.get(name)
        choice = st.selectbox(
            f"Map {escape_markdown(name)}",
            options,
            index=options.index(default) if default in options else 0,
            key=f"upload_map_{n}_{name}",
            help=f"{entry['count']} events",
        )
        mapping[name] = None if choice == IGNORE else choice
    return mapping


def _checked_section(api: ApiClient, ctx: Context, state: dict) -> None:
    check = state["result"]
    st.subheader("Check result")
    if not check["valid_rows"]:
        st.write(f"0 of {check['total_rows']} rows are valid.")
        st.caption(NO_USABLE_ROWS)
        for skip in check["skipped"]:
            st.caption(_skip_line(skip))
        st.button("Import", disabled=True)
        return
    st.write(
        f"{check['valid_rows']} of {check['total_rows']} rows are valid, from "
        f"{check['customers']} customers, between {str(check['first_event'])[:10]} and "
        f"{str(check['last_event'])[:10]}."
    )
    if check["zoneless_timestamps"]:
        st.caption("Some timestamps have no timezone. They are read as UTC.")
    if check["skipped_count"]:
        st.caption(f"{check['skipped_count']} rows will be skipped.")
        for skip in check["skipped"]:
            st.caption(_skip_line(skip))

    mapping = _mapping_form(check, state["n"])
    signup_mapped = "signup" in mapping.values()
    wants_derive = st.checkbox(
        DERIVE_LABEL,
        key=f"upload_derive_{state['n']}",
        disabled=signup_mapped,
        help="Use this when your file has no signup event.",
    )
    derive = wants_derive and not signup_mapped
    acknowledged = False
    if derive and check["censor_warning"]:
        st.warning(CENSOR_WARNING)
        acknowledged = st.checkbox(ACKNOWLEDGEMENT, key=f"upload_ack_{state['n']}")

    st.subheader("What will work")
    for page_title, reason in preview(mapping, derive, check).items():
        st.markdown(f"- {page_title}: {'will work' if reason is None else reason}")

    replacing = ctx.upload_id is not None
    confirmed = True
    if replacing:
        st.caption(
            f"Importing replaces your current upload, {escape_markdown(ctx.upload_name or '')}."
        )
        confirmed = st.checkbox(REPLACE_LABEL, key=f"upload_replace_{state['n']}")
    has_activity = bool(
        {target for target in mapping.values() if target} & set(check["qualifying_events"])
    )
    ready = (
        has_activity and confirmed and (acknowledged or not (derive and check["censor_warning"]))
    )

    def pending() -> dict:  # built from the current bytes, mapping and ticks on every click
        form = {
            "mapping": json.dumps(mapping),
            "derive_signup": "true" if derive else "false",
            "acknowledge_approximate_signup": "true" if acknowledged else "false",
        }
        if state.get("columns"):
            form["columns"] = json.dumps(state["columns"])
        return {"name": state["name"], "data": state["data"], "form": form}

    if st.button("Import", disabled=not ready):
        st.session_state["upload_pending"] = pending()
        st.session_state["upload_failed"] = False
        _import(api)
    if st.session_state.get("upload_failed"):
        st.error(UNAVAILABLE)
        if st.button("Retry import", disabled=not ready):
            st.session_state["upload_pending"] = pending()
            _import(api)


def _delete_section(api: ApiClient, ctx: Context) -> None:
    st.subheader("Delete my data")
    st.caption("This removes your uploaded file's events for good.")
    confirmed = st.checkbox(DELETE_LABEL, key="upload_delete_confirm")
    if st.button("Delete my data", disabled=not confirmed):
        try:
            api.delete(f"/datasets/{ctx.upload_id}")
        except (ApiError, NotAllowed, NotSignedIn, ServiceUnavailable) as exc:
            render_error(exc, retry_key="upload_delete_retry")
            return
        st.session_state.pop("upload_summary", None)
        st.session_state["upload_notice"] = "Your data was deleted."
        _finish(DEMO_ID)


def render(api: ApiClient, ctx: Context) -> None:
    st.header("Data & Uploads")
    st.info(NOTICE)
    if notice := st.session_state.pop("upload_notice", None):
        st.success(notice)
    if summary := st.session_state.get("upload_summary"):
        _show_summary(summary)

    st.download_button(
        "Download template", TEMPLATE_CSV, file_name="churnscope_template.csv", mime="text/csv"
    )
    chosen = current_upload()
    state = st.session_state.get("upload_check")
    if chosen is not None:
        st.markdown(f"File: {escape_markdown(chosen[0])}")
    columns, columns_ready = (None, True) if chosen is None else _columns_form(chosen[1])
    if state and (
        chosen is None
        or chosen != (state["name"], state["data"])
        or columns != state.get("columns")
    ):
        _reset_check()  # a different file or column choice, or none: the old result is stale
        state = None
    if st.button("Check file", disabled=chosen is None or not columns_ready):
        _check(api, *chosen, columns)
        state = st.session_state.get("upload_check")
    if state:
        _checked_section(api, ctx, state)
    if ctx.upload_id is not None:
        _delete_section(api, ctx)
