"""One cached fetch per endpoint. The leading underscore keeps the ApiClient out of the cache key.

Only successes are cached: st.cache_data stores nothing when the function raises. The cache is
shared by every user, so every key carries `dataset_id` and `user_id` (the arguments after
`_api`): an upload's results are never served to another user. `dataset.select` re-checks the
visible datasets on every rerun, and the gate re-checks `/me`, before any page renders. After an
import or delete the acting session calls `st.cache_data.clear()`.
"""

from typing import Any

import streamlit as st

from api_client import ANALYTICS_TIMEOUT, ApiClient

TTL_SECONDS = 300


def _get(api: ApiClient, path: str, dataset_id: int, **params: Any) -> dict:
    sent = {"dataset_id": dataset_id} | {
        key: value for key, value in params.items() if value is not None
    }
    return api.get(path, timeout=ANALYTICS_TIMEOUT, **sent)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def overview(
    _api: ApiClient, dataset_id: int, user_id: str, start: str | None, end: str | None
) -> dict:
    return _get(_api, "/analytics/overview", dataset_id, start=start, end=end)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def funnel(
    _api: ApiClient,
    dataset_id: int,
    user_id: str,
    start: str | None,
    end: str | None,
    window_days: int,
) -> dict:
    return _get(
        _api, "/analytics/funnel", dataset_id, start=start, end=end, window_days=window_days
    )


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def retention(_api: ApiClient, dataset_id: int, user_id: str, periods: int) -> dict:
    return _get(_api, "/analytics/retention", dataset_id, periods=periods)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def engagement(
    _api: ApiClient, dataset_id: int, user_id: str, start: str | None, end: str | None
) -> dict:
    return _get(_api, "/analytics/engagement", dataset_id, start=start, end=end)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def at_risk(
    _api: ApiClient, dataset_id: int, user_id: str, limit: int, offset: int, sort: str = "risk_desc"
) -> dict:
    return _get(_api, "/churn/at-risk", dataset_id, limit=limit, offset=offset, sort=sort)
