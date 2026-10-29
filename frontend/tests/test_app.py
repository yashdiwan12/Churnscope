"""Smoke tests of the Streamlit script with the framework's AppTest (no browser, no network)."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run(monkeypatch, **env):
    for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return AppTest.from_file(APP).run()


def test_unconfigured_app_says_so_and_offers_no_sign_in(monkeypatch):
    at = run(monkeypatch)
    assert "not configured" in at.error[0].value
    assert len(at.get("link_button")) == 0


def test_signed_out_user_gets_a_google_link_with_pkce(monkeypatch):
    at = run(monkeypatch, SUPABASE_URL="https://p.supabase.co", SUPABASE_ANON_KEY="anon")
    link = at.get("link_button")[0].proto.url
    assert link.startswith("https://p.supabase.co/auth/v1/authorize?")
    assert "code_challenge=" in link and "flow%3D" in link


def test_reruns_reuse_one_pending_sign_in(monkeypatch):
    at = run(monkeypatch, SUPABASE_URL="https://p.supabase.co", SUPABASE_ANON_KEY="anon")
    first = at.get("link_button")[0].proto.url
    second = at.run().get("link_button")[0].proto.url
    assert first == second
