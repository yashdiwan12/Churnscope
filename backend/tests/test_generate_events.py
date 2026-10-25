import importlib.util
from pathlib import Path

import pandas as pd

from app.services import metrics

_spec = importlib.util.spec_from_file_location(
    "generate_events", Path(__file__).parents[1] / "scripts" / "generate_events.py"
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def test_generator_is_deterministic_and_valid():
    _, e1 = gen.generate(50, 7, "2026-01-01", 90)
    _, e2 = gen.generate(50, 7, "2026-01-01", 90)
    pd.testing.assert_frame_equal(e1.drop(columns="properties"), e2.drop(columns="properties"))
    assert e1["event_id"].is_unique
    assert set(e1["event_name"]) <= set(metrics.EVENT_NAMES)
    assert (e1["event_timestamp"] < pd.Timestamp("2026-04-01", tz="UTC")).all()
    metrics.validate_events(e1)


def test_funnel_events_happen_in_order():
    """The key action follows onboarding, and sharing follows creating (review finding)."""
    _, ev = gen.generate(400, 3, "2026-01-01", 120)
    first = ev.groupby(["customer_id", "event_name"])["event_timestamp"].min().unstack()
    both = first.dropna(subset=["onboarding_complete", "report_created"])
    assert len(both) > 50
    assert (both["report_created"] > both["onboarding_complete"]).all()
    shared = first.dropna(subset=["report_shared"])
    assert len(shared) > 10
    assert (shared["report_shared"] > shared["report_created"]).all()
    assert first.loc[first["onboarding_complete"].isna(), "report_created"].isna().all()
