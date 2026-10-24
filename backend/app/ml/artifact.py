"""Save/load the versioned churn model artifact with an integrity check.

The artifact is a joblib (pickle) file. Pickles can execute code when loaded, so we only ever load
our own: ``load`` refuses a file whose SHA-256 does not match the one recorded in the metadata
JSON, and refuses an artifact whose feature schema or library version does not match this code.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import sklearn

from app.services import features

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL_FILE = "churn_model.joblib"
META_FILE = "churn_model.json"


class ModelUnavailable(RuntimeError):
    """The artifact is missing, tampered with, or incompatible with this code."""


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minor(version: str) -> str:
    return ".".join(version.split(".")[:2])


def save(pipeline: Any, metadata: dict, directory: Path = ARTIFACT_DIR) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / MODEL_FILE
    joblib.dump(pipeline, model_path)
    metadata = {**metadata, "artifact_sha256": _sha256(model_path)}
    (directory / META_FILE).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return metadata


def load(directory: Path = ARTIFACT_DIR) -> ModelBundle:
    model_path, meta_path = directory / MODEL_FILE, directory / META_FILE
    if not model_path.exists() or not meta_path.exists():
        raise ModelUnavailable("model artifact not found")
    try:
        metadata = json.loads(meta_path.read_text())
    except json.JSONDecodeError as exc:
        raise ModelUnavailable("model metadata is not valid JSON") from exc

    if metadata.get("artifact_sha256") != _sha256(model_path):
        raise ModelUnavailable("model artifact failed its integrity check")
    if metadata.get("feature_columns") != features.FEATURE_COLUMNS:
        raise ModelUnavailable("model feature schema does not match the serving code")
    if (metadata.get("window_days"), metadata.get("horizon_days")) != (
        features.WINDOW_DAYS,
        features.HORIZON_DAYS,
    ):
        raise ModelUnavailable("model windows do not match the serving code")
    if _minor(metadata.get("sklearn_version", "")) != _minor(sklearn.__version__):
        raise ModelUnavailable("model was trained with a different scikit-learn version; retrain")

    return ModelBundle(pipeline=joblib.load(model_path), metadata=metadata)
