"""Churn-risk inference. Uses the same feature code as training (app.services.features)."""

import threading

import pandas as pd
from sqlalchemy.orm import Session

from app.db import repositories
from app.db.datasets import DEMO_DATASET_ID
from app.ml.artifact import ModelBundle
from app.schemas.churn import (
    AtRiskOut,
    AtRiskRow,
    AtRiskSort,
    CustomerPrediction,
    Evaluation,
    HistogramBin,
    PredictResponse,
)
from app.services import features

CAVEAT = (
    "Risk scores are estimates from a model trained on synthetic data. They are relative scores "
    "(the model is trained with class balancing), not calibrated probabilities, and not guarantees."
)
_NOT_ELIGIBLE = (
    f"No qualifying activity in the {features.WINDOW_DAYS} days before the cutoff (or no signup on "
    "record), so there is nothing to predict: the customer is already inactive."
)


def default_cutoff(session: Session) -> pd.Timestamp | None:
    """The last midnight (UTC) at or before the latest event.

    Training cutoffs always have complete data before them. Using the start of the *next* day
    would count the unobserved rest of the latest day as inactivity and inflate
    ``days_since_last_activity``, so the partial latest day is left out instead.
    """
    through = repositories.data_through(session, DEMO_DATASET_ID)
    return None if through is None else through.floor("D")


def _score_frame(bundle: ModelBundle, events: pd.DataFrame, cutoff: pd.Timestamp) -> pd.Series:
    """Raw model scores at ``cutoff``, indexed by customer primary key; empty if none eligible.

    The one place features are built and the model is called, shared by ``predict`` and
    ``score_all`` so single-customer and ranked-list scores cannot drift apart.
    """
    x = features.build_features(events, [cutoff])
    if x.empty:
        return pd.Series(dtype=float)
    x = x[bundle.metadata["feature_columns"]]  # exact training column order
    proba = bundle.pipeline.predict_proba(x)[:, 1]
    return pd.Series(proba, index=x.index.get_level_values("customer_id"))


def predict(
    session: Session,
    bundle: ModelBundle,
    customer_ids: list[str],
    cutoff: pd.Timestamp | None = None,
) -> PredictResponse:
    cutoff = cutoff if cutoff is not None else default_cutoff(session)
    unique_ids = list(dict.fromkeys(customer_ids))  # drop repeats, keep request order
    known = repositories.resolve_customers(session, DEMO_DATASET_ID, unique_ids)

    scores: dict[int, float] = {}
    if known and cutoff is not None:  # cutoff is None only when no events exist at all
        events = repositories.load_events(
            session, DEMO_DATASET_ID, until=cutoff, customer_ids=list(known.values())
        )
        scores = _score_frame(bundle, events, cutoff).to_dict()

    results = []
    for ext in unique_ids:
        pk = known.get(ext)
        if pk is None:
            results.append(
                CustomerPrediction(
                    customer_id=ext, status="unknown_customer", reason="customer not found"
                )
            )
        elif pk in scores:
            # Classify from the same rounded value we return, so the two fields always agree.
            score = round(float(scores[pk]), 4)
            results.append(
                CustomerPrediction(
                    customer_id=ext,
                    status="scored",
                    risk_score=score,
                    predicted_class="at_risk" if score >= bundle.threshold else "not_at_risk",
                )
            )
        else:
            reason = _NOT_ELIGIBLE if cutoff is not None else "no events have been recorded yet"
            results.append(
                CustomerPrediction(customer_id=ext, status="not_eligible", reason=reason)
            )

    return PredictResponse(
        model_version=bundle.version,
        cutoff=cutoff,
        window_days=features.WINDOW_DAYS,
        horizon_days=features.HORIZON_DAYS,
        decision_threshold=bundle.threshold,
        predictions=results,
        caveat=CAVEAT,
    )


# ----------------------------------------------------------------------------- ranked list
_BINS = 10
# One entry: (model_version, cutoff, latest event id) -> scored frame. The key uses the highest
# event id, not the latest timestamp: a late event with an old timestamp leaves max(timestamp)
# unchanged but always raises max(id), so the list can never go stale.
_cache_lock = threading.Lock()
_cache: tuple[tuple, pd.DataFrame] | None = None


def clear_at_risk_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def score_all(session: Session, bundle: ModelBundle, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Score every eligible customer at ``cutoff``.

    Columns ``customer_id`` (external id) and ``risk_score`` (rounded to 4 places), sorted by
    score descending then id ascending. Empty when nobody is eligible.
    """
    empty = pd.DataFrame(
        {"customer_id": pd.Series(dtype=str), "risk_score": pd.Series(dtype=float)}
    )
    raw = _score_frame(
        bundle, repositories.load_events(session, DEMO_DATASET_ID, until=cutoff), cutoff
    )
    if raw.empty:
        return empty
    pks = [int(p) for p in raw.index]
    names = repositories.customer_external_ids(session, DEMO_DATASET_ID, pks)
    frame = pd.DataFrame(
        {"customer_id": [names[p] for p in pks], "risk_score": [round(float(v), 4) for v in raw]}
    )
    return frame.sort_values(["risk_score", "customer_id"], ascending=[False, True]).reset_index(
        drop=True
    )


def _scored(session: Session, bundle: ModelBundle, cutoff: pd.Timestamp) -> pd.DataFrame:
    global _cache
    key = (bundle.version, cutoff, repositories.latest_event_id(session, DEMO_DATASET_ID))
    with _cache_lock:
        if _cache is not None and _cache[0] == key:
            return _cache[1]
        frame = score_all(session, bundle, cutoff)
        _cache = (key, frame)
        return frame


def _evaluation(bundle: ModelBundle) -> Evaluation:
    metrics = bundle.metadata.get("test_metrics") or {}
    data = bundle.metadata.get("data") or {}
    return Evaluation(
        roc_auc=metrics.get("roc_auc"),
        f1=metrics.get("f1"),
        precision=metrics.get("precision"),
        recall=metrics.get("recall"),
        threshold=metrics.get("threshold"),
        test_churn_rate=metrics.get("test_churn_rate"),
        n=metrics.get("n"),
        synthetic=data.get("synthetic"),
    )


def _sorted_positions(scored: pd.DataFrame, sort: AtRiskSort) -> list[int]:
    """Row positions of the rank-ordered ``scored`` frame (position + 1 == rank) in ``sort`` order."""
    n = len(scored)
    if sort == "risk_desc":
        return list(range(n))
    if sort == "customer_asc":
        ids = scored["customer_id"].tolist()
        return sorted(range(n), key=ids.__getitem__)
    # risk_asc: score ascending, ties by customer id ascending (rank order breaks ties descending).
    ids, risk = scored["customer_id"], scored["risk_score"]
    return sorted(range(n), key=lambda i: (risk.iloc[i], ids.iloc[i]))


def at_risk(
    session: Session,
    bundle: ModelBundle,
    limit: int,
    offset: int,
    sort: AtRiskSort = "risk_desc",
) -> AtRiskOut:
    cutoff = default_cutoff(session)
    scored = _scored(session, bundle, cutoff) if cutoff is not None else None
    scores = [] if scored is None else scored["risk_score"].tolist()

    # Integer arithmetic on the rounded scores: float bin edges would misplace 0.3, 0.7, etc.
    counts = [0] * _BINS
    for s in scores:
        counts[min(round(s * 10000) // 1000, _BINS - 1)] += 1
    histogram = [
        HistogramBin(bin_start=i / _BINS, bin_end=(i + 1) / _BINS, count=c)
        for i, c in enumerate(counts)
    ]

    rows = []
    if scored is not None:
        # ``scored`` is in rank order, so a row's rank is its position + 1 whatever the sort.
        positions = _sorted_positions(scored, sort)[offset : offset + limit]
        rows = [
            AtRiskRow(
                rank=pos + 1,
                customer_id=scored["customer_id"].iloc[pos],
                risk_score=scored["risk_score"].iloc[pos],
                predicted_class=(
                    "at_risk"
                    if scored["risk_score"].iloc[pos] >= bundle.threshold
                    else "not_at_risk"
                ),
            )
            for pos in positions
        ]

    return AtRiskOut(
        model_version=bundle.version,
        cutoff=cutoff,
        data_through=repositories.data_through(session, DEMO_DATASET_ID),
        window_days=features.WINDOW_DAYS,
        horizon_days=features.HORIZON_DAYS,
        decision_threshold=bundle.threshold,
        eligible_customers=len(scores),
        at_risk_count=sum(1 for s in scores if s >= bundle.threshold),
        score_histogram=histogram,
        sort=sort,
        rows=rows,
        evaluation=_evaluation(bundle),
        caveat=CAVEAT,
    )
