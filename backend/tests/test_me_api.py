"""/me and /me/reports: identity from the token only; one user can never touch another's reports."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import TokenVerifier, get_verifier
from app.db.session import get_session
from app.main import create_app
from tests.auth_helpers import ISSUER, StaticJWKS, make_ec_key, mint

KEY = make_ec_key()
A_SUB = "11111111-1111-1111-1111-111111111111"
B_SUB = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "alice@example.com,bob@example.com")
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "")
    get_settings.cache_clear()
    app = create_app()
    jwks = StaticJWKS({"k1": KEY})
    app.dependency_overrides[get_verifier] = lambda: TokenVerifier(issuer=ISSUER, jwks_client=jwks)
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app, raise_server_exceptions=False)
    get_settings.cache_clear()


def hdr(sub=A_SUB, email="alice@example.com", **kw):
    return {"Authorization": f"Bearer {mint(KEY, 'ES256', sub=sub, email=email, **kw)}"}


A = hdr()
B = hdr(B_SUB, "bob@example.com")
BODY = {"report_type": "funnel", "filters": {"window_days": 14}}


def test_me_returns_token_identity_and_creates_the_profile_once(client):
    first = client.get("/me", headers=A).json()
    second = client.get("/me", headers=A).json()
    assert first["id"] == A_SUB and first["email"] == "alice@example.com"
    assert first["created_at"] == second["created_at"]


def test_create_list_delete_own_report(client):
    r = client.post("/me/reports", json=BODY, headers=A)
    assert r.status_code == 201
    created = r.json()
    assert created["report_type"] == "funnel" and created["filters"] == {"window_days": 14}
    assert [x["id"] for x in client.get("/me/reports", headers=A).json()] == [created["id"]]
    assert client.delete(f"/me/reports/{created['id']}", headers=A).status_code == 204
    assert client.delete(f"/me/reports/{created['id']}", headers=A).status_code == 404


def test_users_cannot_list_or_delete_each_others_reports_in_either_direction(client):
    a_id = client.post("/me/reports", json=BODY, headers=A).json()["id"]
    b_id = client.post("/me/reports", json=BODY, headers=B).json()["id"]
    assert [x["id"] for x in client.get("/me/reports", headers=B).json()] == [b_id]
    assert [x["id"] for x in client.get("/me/reports", headers=A).json()] == [a_id]
    assert client.delete(f"/me/reports/{a_id}", headers=B).status_code == 404  # never 403
    assert client.delete(f"/me/reports/{b_id}", headers=A).status_code == 404
    assert [x["id"] for x in client.get("/me/reports", headers=A).json()] == [a_id]


def test_nonexistent_and_foreign_ids_look_identical(client):
    a_id = client.post("/me/reports", json=BODY, headers=A).json()["id"]
    foreign = client.delete(f"/me/reports/{a_id}", headers=B)
    missing = client.delete("/me/reports/999999", headers=B)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "user_id": B_SUB},
        {"report_type": "nope", "filters": {}},
        {"report_type": "funnel", "filters": {"k": "x" * 4100}},
        {"report_type": "funnel", "filters": [1]},
        {"filters": {}},
    ],
    ids=["user_id-in-body", "bad-type", "filters-too-big", "filters-not-object", "no-type"],
)
def test_bad_report_bodies_are_422(client, body):
    assert client.post("/me/reports", json=body, headers=A).status_code == 422
    assert client.get("/me/reports", headers=A).json() == []


def test_101st_report_is_409(client):
    for _i in range(100):
        assert client.post("/me/reports", json=BODY, headers=A).status_code == 201
    assert client.post("/me/reports", json=BODY, headers=A).status_code == 409
    assert client.post("/me/reports", json=BODY, headers=B).status_code == 201


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=-1",
        "offset=-1",
        "limit=x",
        "offset=9223372036854775808",
        "offset=" + "9" * 30,
    ],
)
def test_list_bounds_are_422(client, query):
    assert client.get(f"/me/reports?{query}", headers=A).status_code == 422


@pytest.mark.parametrize("report_id", ["abc", "0", "-1", "9" * 30, "9223372036854775808"])
def test_invalid_report_ids_are_422(client, report_id):
    assert client.delete(f"/me/reports/{report_id}", headers=A).status_code == 422


@pytest.mark.parametrize(
    "method,path", [("get", "/me"), ("get", "/me/reports"), ("delete", "/me/reports/1")]
)
def test_unauthenticated_is_401_and_not_allow_listed_is_403(client, method, path):
    assert client.request(method, path).status_code == 401
    stranger = hdr(email="eve@evil.io")
    assert client.request(method, path, headers=stranger).status_code == 403
