"""The cached data layer: successes are cached, failures are not, None params are not sent."""

import pytest

import data
from api_client import ANALYTICS_TIMEOUT, ServiceUnavailable


class FakeApi:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, float | None, dict]] = []

    def get(self, path, *, timeout=None, **params):
        self.calls.append((path, timeout, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_data_caches_successes_only():
    api = FakeApi(ServiceUnavailable("down"), {"ok": 1})
    with pytest.raises(ServiceUnavailable):
        data.overview(api, 1, "u1", None, None)
    assert data.overview(api, 1, "u1", None, None) == {"ok": 1}
    assert len(api.calls) == 2  # the failure was not cached

    assert data.overview(api, 1, "u1", None, None) == {"ok": 1}
    assert len(api.calls) == 2  # the success was


def test_data_sends_analytics_timeout_and_omits_none_params():
    api = FakeApi({}, {}, {}, {}, {})
    data.overview(api, 1, "u1", None, None)
    data.funnel(api, 1, "u1", "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z", 14)
    data.retention(api, 1, "u1", 8)
    data.engagement(api, 1, "u1", None, "2026-10-31T00:00:00Z")
    data.at_risk(api, 1, "u1", 50, 0)
    t = ANALYTICS_TIMEOUT
    assert api.calls == [
        ("/analytics/overview", t, {"dataset_id": 1}),
        (
            "/analytics/funnel",
            t,
            {
                "dataset_id": 1,
                "start": "2026-10-01T00:00:00Z",
                "end": "2026-10-31T00:00:00Z",
                "window_days": 14,
            },
        ),
        ("/analytics/retention", t, {"dataset_id": 1, "periods": 8}),
        ("/analytics/engagement", t, {"dataset_id": 1, "end": "2026-10-31T00:00:00Z"}),
        ("/churn/at-risk", t, {"dataset_id": 1, "limit": 50, "offset": 0, "sort": "risk_desc"}),
    ]


def test_at_risk_sort_is_part_of_the_cache_key():
    api = FakeApi({"a": 1}, {"b": 2})
    assert data.at_risk(api, 1, "u1", 50, 0, "risk_desc") == {"a": 1}
    assert data.at_risk(api, 1, "u1", 50, 0, "risk_asc") == {"b": 2}
    assert api.calls[-1][2]["sort"] == "risk_asc"


def test_different_params_are_cached_separately():
    api = FakeApi({"a": 1}, {"b": 2})
    assert data.overview(api, 1, "u1", None, None) == {"a": 1}
    assert data.overview(api, 1, "u1", "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z") == {"b": 2}
    assert len(api.calls) == 2


def test_cache_key_includes_dataset_and_user():
    api = FakeApi({"a": 1}, {"b": 2}, {"c": 3})
    assert data.overview(api, 1, "u1", None, None) == {"a": 1}
    assert data.overview(api, 7, "u1", None, None) == {"b": 2}  # only dataset_id differs
    assert data.overview(api, 7, "u2", None, None) == {"c": 3}  # only user_id differs
    assert len(api.calls) == 3
    assert [call[2]["dataset_id"] for call in api.calls] == [1, 7, 7]
    assert data.overview(api, 7, "u1", None, None) == {"b": 2}  # same key: a hit
    assert len(api.calls) == 3
