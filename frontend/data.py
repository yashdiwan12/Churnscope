"""One cached fetch per endpoint. The leading underscore keeps the ApiClient out of the cache key.

Only successes are cached: st.cache_data stores nothing when the function raises. The cache is
shared by every user, which is safe only while all allowed users see the same demo data
(assumption A1) and because the gate re-checks `/me` on every rerun before any page renders.
"""

from typing import Any

import streamlit as st

from api_client import ANALYTICS_TIMEOUT, ApiClient

TTL_SECONDS = 300


def _get(api: ApiClient, path: str, **params: Any) -> dict:
    sent = {key: value for key, value in params.items() if value is not None}
    return api.get(path, timeout=ANALYTICS_TIMEOUT, **sent)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def overview(_api: ApiClient, start: str | None, end: str | None) -> dict:
    return _get(_api, "/analytics/overview", start=start, end=end)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def funnel(_api: ApiClient, start: str | None, end: str | None, window_days: int) -> dict:
    return _get(_api, "/analytics/funnel", start=start, end=end, window_days=window_days)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def retention(_api: ApiClient, periods: int) -> dict:
    return _get(_api, "/analytics/retention", periods=periods)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def engagement(_api: ApiClient, start: str | None, end: str | None) -> dict:
    return _get(_api, "/analytics/engagement", start=start, end=end)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def at_risk(_api: ApiClient, limit: int, offset: int) -> dict:
    return _get(_api, "/churn/at-risk", limit=limit, offset=offset)
