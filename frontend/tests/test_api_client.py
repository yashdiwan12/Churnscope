import httpx
import pytest

from api_client import ApiClient, NotAllowed, NotSignedIn, ServiceUnavailable


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
