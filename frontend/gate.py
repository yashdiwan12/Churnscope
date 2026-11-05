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
DEFAULT_IDLE_MINUTES = 30
WAKE_RETRY_SECONDS = 3  # between tries while a sleeping host starts up
WAKING = (
    "Waking up the service. A free host sleeps when idle, so the first visit can take a minute."
)
SIGN_IN_STYLE = (
    "display:inline-block;padding:0.5rem 1rem;border-radius:0.5rem;background:#2563eb;"
    "color:#fff;text-decoration:none;font-weight:600"
)


def _pause(seconds: float) -> None:  # a name tests replace
    time.sleep(seconds)


def _now() -> float:  # a name tests replace
    return time.monotonic()


def wake_seconds_from_env() -> float:
    """API_WAKE_SECONDS: how long to keep trying a sleeping API. Unset, malformed or negative is 0
    (fail fast, right for a local API that is simply down); the deployment sets about 45."""
    try:
        seconds = float(os.getenv("API_WAKE_SECONDS", "").strip() or 0)
    except ValueError:
        return 0
    return max(0, seconds)


def idle_minutes_from_env() -> float:
    """IDLE_TIMEOUT_MINUTES; unset, malformed or negative falls back to the default, 0 disables."""
    raw = os.getenv("IDLE_TIMEOUT_MINUTES", "").strip()
    try:
        minutes = float(raw) if raw else DEFAULT_IDLE_MINUTES
    except ValueError:
        return DEFAULT_IDLE_MINUTES
    return minutes if minutes >= 0 else DEFAULT_IDLE_MINUTES


@dataclass(frozen=True)
class Config:
    api_base_url: str
    supabase_url: str
    supabase_anon_key: str
    app_base_url: str
    idle_timeout_seconds: float = DEFAULT_IDLE_MINUTES * 60  # 0 turns the idle sign-out off
    api_wake_seconds: float = 0

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_base_url=os.getenv("API_BASE_URL", "http://localhost:8000"),
            supabase_url=os.getenv("SUPABASE_URL", ""),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
            app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8501"),
            idle_timeout_seconds=idle_minutes_from_env() * 60,
            api_wake_seconds=wake_seconds_from_env(),
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
    st.session_state.pop("last_seen", None)


def _minutes_text(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes} minute" + ("" if minutes == 1 else "s")


def _end_idle_session(config: Config) -> None:
    """Revoke the refresh token on the server (best effort) and drop the local session."""
    sign_out(
        http_client(),
        supabase_url=config.supabase_url,
        anon_key=config.supabase_anon_key,
        access_token=st.session_state["tokens"].access_token,
    )
    clear_session()
    st.session_state["idle_notice"] = _minutes_text(config.idle_timeout_seconds)


def _check_idle(config: Config) -> None:
    """Sign out a session untouched for the idle limit. Only a rerun can notice, so an open but
    untouched tab stays on screen until its next click; that click lands on the sign-in page."""
    now = time.time()
    last_seen = st.session_state.get("last_seen")
    limit = config.idle_timeout_seconds
    if limit and last_seen is not None and now - last_seen > limit:
        _end_idle_session(config)
        return
    st.session_state["last_seen"] = now


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
    idle = st.session_state.pop("idle_notice", None)
    if idle:
        st.info(f"You were signed out after {idle} of inactivity. Please sign in again.")
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
    # come back to the tab that started the flow. _top, not _self: Streamlit Community Cloud shows
    # the app inside an iframe, and Google refuses to render its sign-in page in a frame (403).
    st.markdown(
        f'<a href="{html.escape(url, quote=True)}" target="_top" rel="noopener" '
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


def _get_me(api: ApiClient, config: Config) -> dict:
    """`GET /me`, trying again for `api_wake_seconds` while the API answers unavailable (a free
    host that was asleep). Any other failure, 401 and 403 included, is raised at once."""
    deadline = _now() + config.api_wake_seconds
    notice = None
    try:
        while True:
            try:
                return api.get("/me")
            except ServiceUnavailable:
                if _now() >= deadline:
                    raise
                if notice is None:
                    notice = st.empty()
                    notice.info(WAKING)
                _pause(WAKE_RETRY_SECONDS)
    finally:
        if notice is not None:
            notice.empty()


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

    if "tokens" in st.session_state:
        _check_idle(config)

    if "tokens" not in st.session_state:
        sign_in_page(config)
        st.stop()

    _fresh_tokens(config)
    api = ApiClient(
        config.api_base_url, lambda: st.session_state["tokens"].access_token, http_client()
    )
    try:
        me = _get_me(api, config)  # on every rerun: a cache hit below must not outlive lost access
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
