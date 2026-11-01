import httpx
import pytest

from api_client import ApiClient, ApiError, NotAllowed, NotSignedIn, ServiceUnavailable


def client_for(handler) -> ApiClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return ApiClient("http://api", get_token=lambda: "TOK", http=http)


def test_sends_bearer_token_and_returns_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer TOK"
        assert request.url.params["limit"] == "5"
        return httpx.Response(200, json={"ok": True})

    assert client_for(handler).get("/me/reports", limit=5) == {"ok": True}


def test_delete_204_returns_none():
    assert client_for(lambda r: httpx.Response(204)).delete("/me/reports/1") is None


@pytest.mark.parametrize(
    "status,error",
    [(401, NotSignedIn), (403, NotAllowed), (503, ServiceUnavailable), (500, ServiceUnavailable)],
)
def test_status_mapping(status, error):
    with pytest.raises(error):
        client_for(lambda r: httpx.Response(status, json={"detail": "x"})).get("/me")


def test_timeout_and_network_errors_are_service_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ServiceUnavailable):
        client_for(handler).get("/me")


def test_error_text_never_contains_the_token():
    with pytest.raises(NotSignedIn) as exc:
        client_for(lambda r: httpx.Response(401)).get("/me")
    assert "TOK" not in str(exc.value)


def _timeout_seen(call) -> dict:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.extensions["timeout"])
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={})

    call(client_for(handler))
    return seen


def test_per_call_timeout_is_used_and_not_sent_as_query():
    seen = _timeout_seen(lambda c: c.get("/x", timeout=30, limit=5))
    assert seen["read"] == 30
    assert seen["query"] == {"limit": "5"}


def test_default_timeout_is_unchanged():
    assert _timeout_seen(lambda c: c.get("/x"))["read"] == 10


def test_post_and_delete_accept_timeout():
    assert _timeout_seen(lambda c: c.post("/x", json={}, timeout=30))["read"] == 30
    assert _timeout_seen(lambda c: c.delete("/x", timeout=30))["read"] == 30


@pytest.mark.parametrize(
    "body,code",
    [
        ({"detail": {"code": "empty_file", "message": "secret"}}, "empty_file"),
        ({"detail": "plain text"}, None),
        ({"detail": {"code": 5}}, None),
        ({"detail": [{"loc": ["x"]}]}, None),
        (None, None),
    ],
)
def test_api_error_exposes_only_the_code(body, code):
    response = httpx.Response(422, json=body) if body is not None else httpx.Response(422)
    with pytest.raises(ApiError) as caught:
        client_for(lambda r: response).get("/x")
    assert caught.value.status_code == 422
    assert caught.value.code == code
    assert "secret" not in str(caught.value)
