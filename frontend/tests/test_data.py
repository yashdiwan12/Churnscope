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
        data.overview(api, None, None)
    assert data.overview(api, None, None) == {"ok": 1}
    assert len(api.calls) == 2  # the failure was not cached

    assert data.overview(api, None, None) == {"ok": 1}
    assert len(api.calls) == 2  # the success was


def test_data_sends_analytics_timeout_and_omits_none_params():
    api = FakeApi({}, {}, {}, {}, {})
    data.overview(api, None, None)
    data.funnel(api, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z", 14)
    data.retention(api, 8)
    data.engagement(api, None, "2026-10-31T00:00:00Z")
    data.at_risk(api, 50, 0)
    t = ANALYTICS_TIMEOUT
    assert api.calls == [
        ("/analytics/overview", t, {}),
        (
            "/analytics/funnel",
            t,
            {"start": "2026-10-01T00:00:00Z", "end": "2026-10-31T00:00:00Z", "window_days": 14},
        ),
        ("/analytics/retention", t, {"periods": 8}),
        ("/analytics/engagement", t, {"end": "2026-10-31T00:00:00Z"}),
        ("/churn/at-risk", t, {"limit": 50, "offset": 0}),
    ]


def test_different_params_are_cached_separately():
    api = FakeApi({"a": 1}, {"b": 2})
    assert data.overview(api, None, None) == {"a": 1}
    assert data.overview(api, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z") == {"b": 2}
    assert len(api.calls) == 2
