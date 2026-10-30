"""Streamlit chrome and error-detail settings: the config file and the footer style."""

import tomllib
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.fake_api import APP, run

CONFIG = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"


def test_streamlit_config_hides_toolbar_details_and_telemetry():
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["client"]["toolbarMode"] == "minimal"
    assert config["client"]["showErrorDetails"] == "none"
    assert config["browser"]["gatherUsageStats"] is False


def test_footer_is_hidden_by_a_style_block(monkeypatch):
    for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(key, raising=False)
    at = run(AppTest.from_file(APP, default_timeout=30))
    styles = [md.value for md in at.markdown if "<style>" in md.value]
    assert any("footer {visibility: hidden;}" in style for style in styles)
    assert not any("header" in style or "sidebar" in style.lower() for style in styles)
