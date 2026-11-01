"""Shared empty and error states with fixed copy. Server text is never shown to the user."""

import streamlit as st

from api_client import ApiError, NotAllowed, NotSignedIn, ServiceUnavailable

INVALID_SETTINGS = "Those settings are not valid. Change the filters and try again."
NOT_ALLOWED = "This account is not allowed to use Churnscope."
UNAVAILABLE = "The service is unavailable. Please try again shortly."
DATASET_GONE = "That dataset is no longer available. Choose a dataset in the sidebar."
STALE_NOTE = "Results may be up to 5 minutes old."


def render_error(exc: Exception, retry_key: str) -> None:
    if isinstance(exc, NotSignedIn):
        # The session ended after the gate's check: drop it and let the gate show sign-in.
        st.session_state.pop("tokens", None)
        st.rerun()
    if isinstance(exc, NotAllowed):
        st.error(NOT_ALLOWED)
    elif isinstance(exc, ServiceUnavailable):
        st.error(UNAVAILABLE)
        st.button("Retry", key=retry_key)  # a click reruns; failures are never cached
        st.caption(STALE_NOTE)
    elif isinstance(exc, ApiError):
        st.error(DATASET_GONE if exc.status_code == 404 else INVALID_SETTINGS)
    else:
        raise exc


def render_empty(message: str) -> None:
    st.info(message)
