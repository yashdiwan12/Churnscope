from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cors_origins_empty_when_unset(monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings(_env_file=None).cors_origin_list == []


def test_cors_origins_only_from_setting(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", " https://a.example , ,https://b.example")
    assert Settings(_env_file=None).cors_origin_list == ["https://a.example", "https://b.example"]
