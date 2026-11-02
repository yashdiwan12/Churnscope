"""The dataset selector: which dataset the signed-in user is looking at, and its page context.

`select` asks `GET /datasets` on every rerun, uncached. That call is the guard that stops a
deleted or foreign dataset id from being read out of the shared result cache: an id the API no
longer lists falls back to the demo (id 1) before any page fetches.
"""

from dataclasses import dataclass

import streamlit as st

from api_client import ApiClient, ApiError, NotAllowed, NotSignedIn, ServiceUnavailable
from labels import escape_markdown
from states import render_error

DEMO_ID = 1
DEMO_BANNER = "Demo data: synthetic events from a seeded generator, not real customers."
FALLBACK_NOTICE = "Your selected dataset is no longer available. Showing demo data."
DERIVED = "derived_from_first_event"


@dataclass(frozen=True)
class Context:
    dataset_id: int
    user_id: str
    kind: str
    name: str
    signup_rule: str
    capabilities: dict
    scoring_method: str | None
    upload_id: int | None = None  # the caller's own upload, whichever dataset is selected
    upload_name: str | None = None

    @property
    def derived_signup(self) -> bool:
        return self.signup_rule == DERIVED


def banner_text(ctx: Context) -> str:
    if ctx.kind == "demo":
        return DEMO_BANNER
    return f"Your uploaded data: {escape_markdown(ctx.name)}, private to you."


def _label(row: dict) -> str:
    return "Demo data" if row["kind"] == "demo" else f"My data: {row['name']}"


def select(api: ApiClient, me: dict) -> Context:
    try:
        rows = api.get("/datasets")
    except (ApiError, NotAllowed, NotSignedIn, ServiceUnavailable) as exc:
        render_error(exc, retry_key="dataset_retry")
        st.stop()
    # A page that created or removed an upload cannot set the selector's key after the selector
    # exists in the same run, so it leaves the id here for the next run to apply first.
    if "next_dataset_id" in st.session_state:
        st.session_state["dataset_id"] = st.session_state.pop("next_dataset_id")
    by_id = {row["id"]: row for row in rows}
    if not by_id:  # the API always lists the demo; treat an empty list as unavailable
        render_error(ServiceUnavailable("no datasets"), retry_key="dataset_retry")
        st.stop()
    if "dataset_id" in st.session_state and st.session_state["dataset_id"] not in by_id:
        st.session_state["dataset_id"] = DEMO_ID if DEMO_ID in by_id else next(iter(by_id))
        st.warning(FALLBACK_NOTICE)
    chosen = st.sidebar.selectbox(
        "Data",
        list(by_id),
        format_func=lambda dataset_id: _label(by_id[dataset_id]),
        key="dataset_id",
    )
    row = by_id[chosen]
    own = next((r for r in by_id.values() if r["kind"] == "upload"), None)
    return Context(
        dataset_id=row["id"],
        user_id=me["id"],
        kind=row["kind"],
        name=row["name"],
        signup_rule=row["signup_rule"],
        capabilities=row["capabilities"],
        scoring_method=row["scoring_method"],
        upload_id=None if own is None else own["id"],
        upload_name=None if own is None else own["name"],
    )
