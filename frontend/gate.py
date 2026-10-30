"""The sign-in gate: Google sign-in, token refresh, sign-out, and `GET /me` on every rerun.

`require_session` returns only when `/me` answered 200. Otherwise it shows sign-in (no tokens,
or a 401) or a fixed error with a sign-out button (403, 503) and stops the script, so no page
renders; this is what keeps the shared result cache from outliving a user's access.
"""

import html
import os
import time
from dataclasses import dataclass

import httpx
import streamlit as st

from api_client import ApiClient, ApiError, NotAllowed, NotSignedIn, ServiceUnavailable
from auth import (
    AuthError,
    VerifierStore,
    authorize_url,
    challenge_for,
    exchange_code,
    needs_refresh,
    new_verifier,
    refresh,
    sign_out,
)
from states import NOT_ALLOWED, UNAVAILABLE

FLOW_REUSE_SECONDS = 300  # well inside the verifier TTL of 10 minutes
SIGN_IN_STYLE = (
    "display:inline-block;padding:0.5rem 1rem;border-radius:0.5rem;background:#2563eb;"
    "color:#fff;text-decoration:none;font-weight:600"
)


@dataclass(frozen=True)
class Config:
    api_base_url: str
    supabase_url: str
    supabase_anon_key: str
    app_base_url: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_base_url=os.getenv("API_BASE_URL", "http://localhost:8000"),
            supabase_url=os.getenv("SUPABASE_URL", ""),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
            app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8501"),
        )


@st.cache_resource
def verifier_store() -> VerifierStore:
    # Process-wide: the redirect back from Google arrives in a brand-new Streamlit session.
    return VerifierStore()


@st.cache_resource
def http_client() -> httpx.Client:
    return httpx.Client()


def clear_session() -> None:
    st.session_state.pop("tokens", None)


def finish_sign_in(config: Config, code: str, flow: str) -> None:
    verifier = verifier_store().pop(flow)
    st.query_params.clear()  # the code is single-use; never leave it in the URL
    if verifier is None:
        st.warning("That sign-in link expired. Please sign in again.")
        return
    try:
        st.session_state["tokens"] = exchange_code(
            http_client(),
            supabase_url=config.supabase_url,
            anon_key=config.supabase_anon_key,
            code=code,
            verifier=verifier,
        )
    except AuthError:
        st.error("Sign-in failed. Please try again.")


def sign_in_page(config: Config) -> None:
    st.write("Sign in to view analytics and churn risk.")
    # One pending sign-in per browser session (not one per rerun), so reruns cannot flood the store.
    pending = st.session_state.get("pending_flow")
    if pending is None or time.monotonic() - pending[2] > FLOW_REUSE_SECONDS:
        pending = (new_verifier()[:24], new_verifier(), time.monotonic())
        st.session_state["pending_flow"] = pending
        verifier_store().put(pending[0], pending[1])
    flow, verifier, _ = pending
    url = authorize_url(
        supabase_url=config.supabase_url,
        redirect_to=f"{config.app_base_url}?flow={flow}",
        challenge=challenge_for(verifier),
    )
    # An anchor, not st.link_button: that always opens a new tab, but the OAuth redirect must
    # come back to the tab that started the flow.
    st.markdown(
        f'<a href="{html.escape(url, quote=True)}" target="_self" rel="noopener" '
        f'style="{SIGN_IN_STYLE}">Sign in with Google</a>',
        unsafe_allow_html=True,
    )


def sign_out_button(config: Config) -> None:
    if st.button("Sign out", key="sign_out"):
        sign_out(
            http_client(),
            supabase_url=config.supabase_url,
            anon_key=config.supabase_anon_key,
            access_token=st.session_state["tokens"].access_token,
        )
        clear_session()
        st.rerun()


def _fresh_tokens(config: Config) -> None:
    tokens = st.session_state["tokens"]
    if not needs_refresh(tokens, time.time()):
        return
    try:
        st.session_state["tokens"] = refresh(
            http_client(),
            supabase_url=config.supabase_url,
            anon_key=config.supabase_anon_key,
            refresh_token=tokens.refresh_token,
        )
    except AuthError:
        clear_session()
        st.rerun()


def _blocked(config: Config, message: str) -> None:
    st.error(message)
    sign_out_button(config)
    st.stop()


def require_session() -> tuple[ApiClient, dict]:
    """The API client and the `/me` payload; never returns unless `/me` answered 200."""
    config = Config.from_env()
    if not (config.supabase_url and config.supabase_anon_key):
        st.error("Sign-in is not configured (SUPABASE_URL and SUPABASE_ANON_KEY are required).")
        st.stop()

    params = st.query_params
    if "error" in params:
        st.query_params.clear()
        st.error("Sign-in was cancelled or failed. Please try again.")
    elif "code" in params and "flow" in params and "tokens" not in st.session_state:
        finish_sign_in(config, params["code"], params["flow"])

    if "tokens" not in st.session_state:
        sign_in_page(config)
        st.stop()

    _fresh_tokens(config)
    api = ApiClient(
        config.api_base_url, lambda: st.session_state["tokens"].access_token, http_client()
    )
    try:
        me = api.get("/me")  # on every rerun: a cache hit below must not outlive lost access
    except NotSignedIn:
        clear_session()
        st.rerun()
    except NotAllowed:
        _blocked(config, NOT_ALLOWED)
    except (ServiceUnavailable, ApiError):  # any other 4xx (wrong base URL, proxy) reads the same
        _blocked(config, UNAVAILABLE)
    return api, me


def signed_in_sidebar(me: dict) -> None:
    config = Config.from_env()
    with st.sidebar:
        st.caption(f"Signed in as {me['email']}")
        sign_out_button(config)
