"""Save/load the versioned churn model artifact.

The artifact is a joblib (pickle) file, and unpickling can execute code. What the checks below
do and do not guarantee:

* The model file is read **once**; its SHA-256 is computed over exactly the bytes that are then
  unpickled, so the file cannot be swapped between check and load.
* The hash recorded in ``churn_model.json`` sits next to the model, so it detects corruption and
  accidental mismatches, **not** a deliberate attacker who can write to that directory. To guard
  against that, pin the expected hash from a trusted source (``CHURN_MODEL_SHA256``), which is
  checked before anything is unpickled.
* Feature schema, windows and library versions must match the serving code.

Any failure raises ``ModelUnavailable`` so the API can degrade to a 503 on prediction only.
"""

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn

from app.services import features

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL_FILE = "churn_model.joblib"
META_FILE = "churn_model.json"


class ModelUnavailable(RuntimeError):
    """The artifact is missing, corrupt, untrusted, or incompatible with this code."""


@dataclass(frozen=True)
class ModelBundle:
    pipeline: Any
    metadata: dict

    @property
    def version(self) -> str:
        return self.metadata["model_version"]

    @property
    def threshold(self) -> float:
        return float(self.metadata["decision_threshold"])


def _minor(version: object) -> str:
    return ".".join(str(version).split(".")[:2])


def _major(version: object) -> str:
    return str(version).split(".")[0]


def save(pipeline: Any, metadata: dict, directory: Path = ARTIFACT_DIR) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    joblib.dump(pipeline, buffer)
    data = buffer.getvalue()
    (directory / MODEL_FILE).write_bytes(data)
    metadata = {**metadata, "artifact_sha256": hashlib.sha256(data).hexdigest()}
    (directory / META_FILE).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return metadata


def _validate_metadata(metadata: object) -> dict:
    if not isinstance(metadata, dict):
        raise ModelUnavailable("model metadata is not a JSON object")
    if not isinstance(metadata.get("model_version"), str) or not metadata["model_version"]:
        raise ModelUnavailable("model metadata has no model_version")
    threshold = metadata.get("decision_threshold")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, int | float)
        or not 0 < threshold < 1
    ):
        raise ModelUnavailable("model metadata has no valid decision_threshold")
    if metadata.get("feature_columns") != features.FEATURE_COLUMNS:
        raise ModelUnavailable("model feature schema does not match the serving code")
    if (metadata.get("window_days"), metadata.get("horizon_days")) != (
        features.WINDOW_DAYS,
        features.HORIZON_DAYS,
    ):
        raise ModelUnavailable("model windows do not match the serving code")
    if _minor(metadata.get("sklearn_version", "")) != _minor(sklearn.__version__):
        raise ModelUnavailable("model was trained with a different scikit-learn version; retrain")
    if _major(metadata.get("numpy_version", "")) != _major(np.__version__):
        raise ModelUnavailable("model was trained with a different numpy major version; retrain")
    return metadata


def load(directory: Path = ARTIFACT_DIR, expected_sha256: str | None = None) -> ModelBundle:
    """Load and verify the artifact. ``expected_sha256`` comes from a trusted source (env)."""
    model_path, meta_path = directory / MODEL_FILE, directory / META_FILE
    try:
        data = model_path.read_bytes()
        raw_meta = meta_path.read_text()
    except FileNotFoundError as exc:
        raise ModelUnavailable("model artifact not found") from exc
    except OSError as exc:
        raise ModelUnavailable("model artifact could not be read") from exc

    try:
        metadata = json.loads(raw_meta)
    except json.JSONDecodeError as exc:
        raise ModelUnavailable("model metadata is not valid JSON") from exc
    metadata = _validate_metadata(metadata)

    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 and digest != expected_sha256.strip().lower():
        raise ModelUnavailable("model artifact does not match the pinned CHURN_MODEL_SHA256")
    if metadata.get("artifact_sha256") != digest:
        raise ModelUnavailable("model artifact failed its integrity check")

    try:
        pipeline = joblib.load(io.BytesIO(data))  # the same bytes that were hashed
    except Exception as exc:  # corrupt or ABI-incompatible pickle: never crash the API
        raise ModelUnavailable(
            f"model artifact could not be unpickled ({type(exc).__name__})"
        ) from exc
    if not callable(getattr(pipeline, "predict_proba", None)):
        raise ModelUnavailable("model artifact is not a classifier with predict_proba")
    return ModelBundle(pipeline=pipeline, metadata=metadata)
