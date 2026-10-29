import os
import time

import httpx
import streamlit as st

from api_client import ApiClient, NotAllowed, NotSignedIn, ServiceUnavailable
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

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8501")


@st.cache_resource
def verifier_store() -> VerifierStore:
    # Process-wide: the redirect back from Google arrives in a brand-new Streamlit session.
    return VerifierStore()


@st.cache_resource
def http_client() -> httpx.Client:
    return httpx.Client()


def clear_session() -> None:
    st.session_state.pop("tokens", None)


def finish_sign_in(code: str, flow: str) -> None:
    verifier = verifier_store().pop(flow)
    st.query_params.clear()  # the code is single-use; never leave it in the URL
    if verifier is None:
        st.warning("That sign-in link expired. Please sign in again.")
        return
    try:
        st.session_state["tokens"] = exchange_code(
            http_client(),
            supabase_url=SUPABASE_URL,
            anon_key=SUPABASE_ANON_KEY,
            code=code,
            verifier=verifier,
        )
    except AuthError:
        st.error("Sign-in failed. Please try again.")


def sign_in_page() -> None:
    st.write("Sign in to view analytics and churn risk.")
    flow, verifier = new_verifier()[:24], new_verifier()
    verifier_store().put(flow, verifier)
    url = authorize_url(
        supabase_url=SUPABASE_URL,
        redirect_to=f"{APP_BASE_URL}?flow={flow}",
        challenge=challenge_for(verifier),
    )
    st.link_button("Sign in with Google", url)


def signed_in_page() -> None:
    tokens = st.session_state["tokens"]
    if needs_refresh(tokens, time.time()):
        try:
            tokens = refresh(
                http_client(),
                supabase_url=SUPABASE_URL,
                anon_key=SUPABASE_ANON_KEY,
                refresh_token=tokens.refresh_token,
            )
            st.session_state["tokens"] = tokens
        except AuthError:
            clear_session()
            st.rerun()
    api = ApiClient(API_BASE_URL, lambda: st.session_state["tokens"].access_token, http_client())
    try:
        me = api.get("/me")
    except NotSignedIn:
        clear_session()
        st.rerun()
    except NotAllowed:
        st.error("This account is not allowed to use Churnscope.")
        me = None
    except ServiceUnavailable:
        st.error("The service is unavailable. Please try again shortly.")
        me = None
    if me:
        st.success(f"Signed in as {me['email']}")
    if st.button("Sign out"):
        sign_out(
            http_client(),
            supabase_url=SUPABASE_URL,
            anon_key=SUPABASE_ANON_KEY,
            access_token=tokens.access_token,
        )
        clear_session()
        st.rerun()


st.set_page_config(page_title="Churnscope", layout="wide")
st.title("Churnscope")
st.caption("Product analytics and churn intelligence")

if not (SUPABASE_URL and SUPABASE_ANON_KEY):
    st.error("Sign-in is not configured (SUPABASE_URL and SUPABASE_ANON_KEY are required).")
    st.stop()

params = st.query_params
if "error" in params:
    st.query_params.clear()
    st.error("Sign-in was cancelled or failed. Please try again.")
elif "code" in params and "flow" in params and "tokens" not in st.session_state:
    finish_sign_in(params["code"], params["flow"])

if "tokens" in st.session_state:
    signed_in_page()
else:
    sign_in_page()
