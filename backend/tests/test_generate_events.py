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
