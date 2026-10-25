"""ML behaviour: split hygiene, preprocessing fit, metrics, reproducibility, artifact safety."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.ml import artifact, evaluate, train
from app.services import features

_spec = importlib.util.spec_from_file_location(
    "generate_events", Path(__file__).parents[1] / "scripts" / "generate_events.py"
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    _, ev = gen.generate(400, seed=11, start="2026-01-01", days=150)
    return ev[["customer_id", "event_name", "event_timestamp", "properties"]]


@pytest.fixture(scope="module")
def result(events):
    return train.train(events, seed=42, n_test=3)


def test_train_cutoffs_close_before_test_starts(events):
    ds = train.build_dataset(events, n_test=3)
    horizon = pd.Timedelta(days=features.HORIZON_DAYS)
    assert max(ds.train_cutoffs) + horizon <= min(ds.test_cutoffs)
    assert set(ds.x_train.index.get_level_values("cutoff")) == set(ds.train_cutoffs)
    assert set(ds.x_test.index.get_level_values("cutoff")) == set(ds.test_cutoffs)
    assert max(ds.test_cutoffs) + horizon <= events["event_timestamp"].max()  # labels observed


def test_preprocessing_is_fitted_on_training_rows_only(events):
    ds = train.build_dataset(events, n_test=3)
    pipe = train.make_logistic(seed=1).fit(ds.x_train, ds.y_train)
    scaler = pipe.named_steps["scale"]
    np.testing.assert_allclose(scaler.mean_, ds.x_train.mean().to_numpy())
    both = pd.concat([ds.x_train, ds.x_test])
    assert not np.allclose(scaler.mean_, both.mean().to_numpy())  # test rows did not leak in


def test_model_uses_exactly_the_feature_schema(result):
    assert result.metadata["feature_columns"] == features.FEATURE_COLUMNS
    assert (
        list(result.report["shipped_model_standardised_coefficients"]) == features.FEATURE_COLUMNS
    )


def test_training_is_reproducible(events, result):
    again = train.train(events, seed=42, n_test=3)
    assert again.metadata["model_version"] == result.metadata["model_version"]
    assert again.metadata["test_metrics"] == result.metadata["test_metrics"]
    assert (
        again.report["shipped_model_standardised_coefficients"]
        == result.report["shipped_model_standardised_coefficients"]
    )
    assert again.metadata["data"]["sha256"] == result.metadata["data"]["sha256"]


def test_data_fingerprint_ignores_row_order(events):
    shuffled = events.sample(frac=1, random_state=0)
    assert train.data_fingerprint(shuffled) == train.data_fingerprint(events)


def test_model_beats_the_majority_baseline(result):
    t = result.report["models"]["logistic_regression"]["test"]
    majority = result.report["baselines"]["majority_class"]
    assert t["roc_auc"] > 0.65 and majority["roc_auc"] == 0.5
    assert t["f1"] > majority["f1"] == 0.0
    assert "inactive_rule" in result.report["baselines"]  # the stronger comparison is recorded


def test_metrics_hand_checked():
    # y = 1 1 0 0, scores .9 .4 .6 .1, threshold .5 -> predictions 1 0 1 0
    m = evaluate.classification_metrics([1, 1, 0, 0], [0.9, 0.4, 0.6, 0.1])
    assert m["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert (m["precision"], m["recall"], m["f1"], m["accuracy"]) == (0.5, 0.5, 0.5, 0.5)
    assert m["roc_auc"] == pytest.approx(0.75)  # 3 of 4 positive/negative pairs ranked correctly


def test_metrics_with_a_single_class_do_not_crash():
    m = evaluate.classification_metrics([0, 0, 0], [0.1, 0.2, 0.3])
    assert m["roc_auc"] is None and m["recall"] == 0.0


def test_error_profile_groups_cover_every_row():
    x = pd.DataFrame({"days_since_last_activity": [1.0, 2.0, 20.0, 30.0]})
    p = evaluate.error_profile(x, [0, 1, 0, 1], [0.1, 0.2, 0.9, 0.8])
    assert {k: v["n"] for k, v in p.items()} == {
        "true_negative": 1,
        "false_negative": 1,
        "false_positive": 1,
        "true_positive": 1,
    }


# ---------------------------------------------------------------- artifact safety
@pytest.fixture
def saved(result, tmp_path):
    meta = artifact.save(result.pipeline, result.metadata, tmp_path)
    return tmp_path, meta


def test_artifact_round_trip_preserves_predictions(result, saved, events):
    directory, meta = saved
    bundle = artifact.load(directory)
    x = train.build_dataset(events, n_test=3).x_test
    np.testing.assert_allclose(
        bundle.pipeline.predict_proba(x), result.pipeline.predict_proba(x), rtol=1e-12
    )
    assert bundle.version == meta["model_version"] and bundle.threshold == 0.5


def test_missing_artifact_is_unavailable(tmp_path):
    with pytest.raises(artifact.ModelUnavailable, match="not found"):
        artifact.load(tmp_path)


def test_tampered_artifact_is_rejected_before_unpickling(saved):
    directory, _ = saved
    with (directory / artifact.MODEL_FILE).open("ab") as fh:
        fh.write(b"tampered")
    with pytest.raises(artifact.ModelUnavailable, match="integrity"):
        artifact.load(directory)


@pytest.mark.parametrize(
    "key,value,message",
    [
        ("feature_columns", ["only_one"], "feature schema"),
        ("horizon_days", 99, "windows"),
        ("sklearn_version", "0.0.1", "scikit-learn"),
    ],
)
def test_incompatible_metadata_is_rejected(saved, key, value, message):
    directory, meta = saved
    (directory / artifact.META_FILE).write_text(json.dumps({**meta, key: value}))
    with pytest.raises(artifact.ModelUnavailable, match=message):
        artifact.load(directory)


# ---------------------------------------------------------------- review fixes
def test_pinned_hash_mismatch_is_rejected_before_unpickling(saved):
    directory, _ = saved
    with pytest.raises(artifact.ModelUnavailable, match="pinned"):
        artifact.load(directory, expected_sha256="0" * 64)


def test_pinned_hash_match_loads(saved):
    directory, meta = saved
    assert artifact.load(directory, expected_sha256=meta["artifact_sha256"].upper()).version


def _rewrite(directory, model_bytes: bytes, meta: dict) -> None:
    import hashlib

    (directory / artifact.MODEL_FILE).write_bytes(model_bytes)
    meta = {**meta, "artifact_sha256": hashlib.sha256(model_bytes).hexdigest()}
    (directory / artifact.META_FILE).write_text(json.dumps(meta))


def test_corrupt_pickle_with_matching_hash_is_unavailable_not_a_crash(saved):
    directory, meta = saved
    _rewrite(directory, b"definitely not a pickle", meta)
    with pytest.raises(artifact.ModelUnavailable, match="unpickled"):
        artifact.load(directory)


def test_artifact_without_predict_proba_is_rejected(saved):
    import io

    import joblib

    directory, meta = saved
    buf = io.BytesIO()
    joblib.dump({"not": "a model"}, buf)
    _rewrite(directory, buf.getvalue(), meta)
    with pytest.raises(artifact.ModelUnavailable, match="predict_proba"):
        artifact.load(directory)


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda m: [m], "not a JSON object"),
        (lambda m: {k: v for k, v in m.items() if k != "model_version"}, "model_version"),
        (lambda m: {**m, "decision_threshold": "0.5"}, "decision_threshold"),
        (lambda m: {**m, "decision_threshold": 1.5}, "decision_threshold"),
        (lambda m: {**m, "sklearn_version": 1}, "scikit-learn"),
        (lambda m: {**m, "numpy_version": "0.1"}, "numpy"),
        (
            lambda m: {**m, "label": {**m["label"], "qualifying_events": ["session_start"]}},
            "qualifying",
        ),
        (lambda m: {**m, "label": "nope"}, "qualifying"),
    ],
)
def test_malformed_metadata_is_unavailable_not_a_crash(saved, mutate, message):
    directory, meta = saved
    (directory / artifact.META_FILE).write_text(json.dumps(mutate(meta)))
    with pytest.raises(artifact.ModelUnavailable, match=message):
        artifact.load(directory)


def test_model_version_changes_with_hyperparameters(events, result, monkeypatch):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    def other(seed):
        clf = LogisticRegression(C=0.1, class_weight="balanced", max_iter=1000, random_state=seed)
        return Pipeline([("scale", StandardScaler()), ("clf", clf)])

    monkeypatch.setattr(train, "make_logistic", other)
    assert (
        train.train(events, seed=42, n_test=3).metadata["model_version"]
        != result.metadata["model_version"]
    )


def test_fingerprint_covers_event_properties(events):
    changed = events.copy()
    i = changed.index[changed["event_name"] == "feature_used"][0]
    changed.at[i, "properties"] = {"feature": "something_else"}
    assert train.data_fingerprint(changed)["sha256"] != train.data_fingerprint(events)["sha256"]
