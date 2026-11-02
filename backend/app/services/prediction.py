"""Churn-risk inference. Uses the same feature code as training (app.services.features)."""

import threading
from collections import OrderedDict
from collections.abc import Callable

import pandas as pd
from sqlalchemy.orm import Session

from app.db import repositories
from app.db.datasets import DEMO_DATASET_ID
from app.db.models import Dataset
from app.ml.artifact import ModelBundle
from app.schemas.churn import (
    UPLOAD_CAVEAT,
    AtRiskOut,
    AtRiskRow,
    AtRiskSort,
    CustomerPrediction,
    Evaluation,
    HistogramBin,
    PredictResponse,
)
from app.services import features, upload_scoring

CAVEAT = (
    "Risk scores are estimates from a model trained on synthetic data. They are relative scores "
    "(the model is trained with class balancing), not calibrated probabilities, and not guarantees."
)
_NOT_ELIGIBLE = (
    f"No qualifying activity in the {features.WINDOW_DAYS} days before the cutoff (or no signup on "
    "record), so there is nothing to predict: the customer is already inactive."
)


class ScoringUnavailable(Exception):
    """The dataset cannot be scored: an upload whose scoring is missing, unavailable or failed."""


def default_cutoff(session: Session, dataset_id: int = DEMO_DATASET_ID) -> pd.Timestamp | None:
    """The last midnight (UTC) at or before the latest event.

    Training cutoffs always have complete data before them. Using the start of the *next* day
    would count the unobserved rest of the latest day as inactivity and inflate
    ``days_since_last_activity``, so the partial latest day is left out instead.
    """
    through = repositories.data_through(session, dataset_id)
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
_DAY_BIN = 7  # the rule's histogram: 4 bins of 7 days over [0, 28)
_DAY_BINS = features.WINDOW_DAYS // _DAY_BIN
# Scored frames. Demo key: (dataset id, model_version, cutoff, latest event id); the highest event
# id, not the latest timestamp, so a late event with an old timestamp still invalidates. Upload
# key: (dataset id, scoring fitted_at, cutoff): an upload's rows never change (a replace makes a
# new dataset) and re-scoring changes fitted_at. Bounded to _CACHE_MAX entries, least recently
# used evicted first.
#
# Scoring runs outside the global lock, so one slow run never blocks cache hits for other
# datasets; a per-key lock stops two requests for the same key scoring twice. An eviction while
# a run is in flight bumps _generation, and the stale result is then returned but not cached.
_CACHE_MAX = 4
_cache_lock = threading.Lock()
_cache: OrderedDict[tuple, pd.DataFrame] = OrderedDict()
_key_locks: dict[tuple, threading.Lock] = {}
_generation = 0


def clear_at_risk_cache() -> None:
    global _generation
    with _cache_lock:
        _cache.clear()
        _generation += 1


def evict_dataset(dataset_id: int) -> None:
    """Drop every cached list for one dataset (call when its rows change or it is deleted)."""
    global _generation
    with _cache_lock:
        for key in [k for k in _cache if k[0] == dataset_id]:
            del _cache[key]
        _generation += 1


def _cached(key: tuple, compute: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        key_lock = _key_locks.setdefault(key, threading.Lock())
    with key_lock:
        with _cache_lock:
            if key in _cache:  # another request scored it while this one waited
                _cache.move_to_end(key)
                return _cache[key]
            generation = _generation
        try:
            frame = compute()
        finally:
            with _cache_lock:
                if _key_locks.get(key) is key_lock:
                    del _key_locks[key]
        with _cache_lock:
            if generation == _generation:
                _cache[key] = frame
                while len(_cache) > _CACHE_MAX:
                    _cache.popitem(last=False)
        return frame


def _ranked(session: Session, dataset_id: int, raw: pd.Series, column: str) -> pd.DataFrame:
    """External ids plus ``column`` rounded to 4 places, value descending then id ascending."""
    if raw.empty:
        return pd.DataFrame({"customer_id": pd.Series(dtype=str), column: pd.Series(dtype=float)})
    pks = [int(p) for p in raw.index]
    names = repositories.customer_external_ids(session, dataset_id, pks)
    frame = pd.DataFrame(
        {"customer_id": [names[p] for p in pks], column: [round(float(v), 4) for v in raw]}
    )
    return frame.sort_values([column, "customer_id"], ascending=[False, True]).reset_index(
        drop=True
    )


def score_all(
    session: Session, bundle: ModelBundle, dataset_id: int, cutoff: pd.Timestamp
) -> pd.DataFrame:
    """Score every eligible customer at ``cutoff``.

    Columns ``customer_id`` (external id) and ``risk_score`` (rounded to 4 places), sorted by
    score descending then id ascending. Empty when nobody is eligible.
    """
    raw = _score_frame(bundle, repositories.load_events(session, dataset_id, until=cutoff), cutoff)
    return _ranked(session, dataset_id, raw, "risk_score")


def score_upload(session: Session, dataset: Dataset, cutoff: pd.Timestamp) -> pd.DataFrame:
    """An upload's eligible customers at ``cutoff``, ranked by its stored scoring method.

    ``logistic``: column ``risk_score`` from the stored JSON model. The rule methods: column
    ``days_inactive`` (days since last activity), most days first.
    """
    scoring = dataset.scoring or {}
    x = features.build_features(
        repositories.load_events(session, dataset.id, until=cutoff), [cutoff]
    )
    ids = x.index.get_level_values("customer_id")
    if scoring.get("method") == "logistic":
        values = upload_scoring.json_proba(scoring["model"], x) if len(x) else []
        return _ranked(session, dataset.id, pd.Series(values, index=ids, dtype=float), "risk_score")
    days = x["days_since_last_activity"].to_numpy(dtype=float)
    return _ranked(session, dataset.id, pd.Series(days, index=ids, dtype=float), "days_inactive")


def _scored(
    session: Session, bundle: ModelBundle, dataset_id: int, cutoff: pd.Timestamp
) -> pd.DataFrame:
    key = (dataset_id, bundle.version, cutoff, repositories.latest_event_id(session, dataset_id))
    return _cached(key, lambda: score_all(session, bundle, dataset_id, cutoff))


def _scored_upload(session: Session, dataset: Dataset, cutoff: pd.Timestamp) -> pd.DataFrame:
    key = (dataset.id, dataset.scoring["fitted_at"], cutoff)
    return _cached(key, lambda: score_upload(session, dataset, cutoff))


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


def _sorted_positions(scored: pd.DataFrame, sort: AtRiskSort, column: str) -> list[int]:
    """Row positions of the rank-ordered ``scored`` frame (position + 1 == rank) in ``sort`` order.

    ``column`` is the ranking value (risk score or days inactive); higher means more at risk.
    """
    n = len(scored)
    if sort == "risk_desc":
        return list(range(n))
    if sort == "customer_asc":
        ids = scored["customer_id"].tolist()
        return sorted(range(n), key=ids.__getitem__)
    # risk_asc: value ascending, ties by customer id ascending (rank order breaks ties descending).
    ids, value = scored["customer_id"], scored[column]
    return sorted(range(n), key=lambda i: (value.iloc[i], ids.iloc[i]))


def _score_histogram(scores: list[float]) -> list[HistogramBin]:
    # Integer arithmetic on the rounded scores: float bin edges would misplace 0.3, 0.7, etc.
    counts = [0] * _BINS
    for s in scores:
        counts[min(round(s * 10000) // 1000, _BINS - 1)] += 1
    return [
        HistogramBin(bin_start=i / _BINS, bin_end=(i + 1) / _BINS, count=c)
        for i, c in enumerate(counts)
    ]


def _days_histogram(days: list[float]) -> list[HistogramBin]:
    counts = [0] * _DAY_BINS
    for d in days:
        counts[min(round(d * 10000) // (_DAY_BIN * 10000), _DAY_BINS - 1)] += 1
    return [
        HistogramBin(bin_start=i * _DAY_BIN, bin_end=(i + 1) * _DAY_BIN, count=c)
        for i, c in enumerate(counts)
    ]


def at_risk(
    session: Session,
    bundle: ModelBundle | None,
    dataset: Dataset,
    limit: int,
    offset: int,
    sort: AtRiskSort = "risk_desc",
) -> AtRiskOut:
    """The ranked list for a dataset: the shipped model for the demo, the upload's own scoring
    method otherwise. ScoringUnavailable when an upload has no usable scoring yet."""
    scoring = dataset.scoring or {}
    if dataset.kind == "demo":
        method, column = "shipped_model", "risk_score"
        threshold = bundle.threshold
    elif scoring.get("method") in upload_scoring.SCOREABLE:
        method = scoring["method"]
        column = "risk_score" if method == "logistic" else "days_inactive"
        threshold = (
            float(scoring["model"]["threshold"])
            if method == "logistic"
            else upload_scoring.RULE_DAYS
        )
    else:
        raise ScoringUnavailable(dataset.id)

    cutoff = default_cutoff(session, dataset.id)
    scored = None
    if cutoff is not None:
        if dataset.kind == "demo":
            scored = _scored(session, bundle, dataset.id, cutoff)
        else:
            scored = _scored_upload(session, dataset, cutoff)
    values = [] if scored is None else scored[column].tolist()
    histogram = _score_histogram(values) if column == "risk_score" else _days_histogram(values)

    rows = []
    if scored is not None:
        # ``scored`` is in rank order, so a row's rank is its position + 1 whatever the sort.
        positions = _sorted_positions(scored, sort, column)[offset : offset + limit]
        for pos in positions:
            value = float(scored[column].iloc[pos])
            rows.append(
                AtRiskRow(
                    rank=pos + 1,
                    customer_id=scored["customer_id"].iloc[pos],
                    risk_score=value if column == "risk_score" else None,
                    days_inactive=value if column == "days_inactive" else None,
                    predicted_class="at_risk" if value >= threshold else "not_at_risk",
                )
            )

    demo = dataset.kind == "demo"
    return AtRiskOut(
        dataset_id=dataset.id,
        method=method,
        reason=None if demo else scoring.get("reason"),
        model_version=bundle.version if demo else method,
        cutoff=cutoff,
        data_through=repositories.data_through(session, dataset.id),
        window_days=features.WINDOW_DAYS,
        horizon_days=features.HORIZON_DAYS,
        decision_threshold=threshold,
        eligible_customers=len(values),
        at_risk_count=sum(1 for v in values if v >= threshold),
        score_histogram=histogram,
        histogram_unit=column,
        sort=sort,
        rows=rows,
        evaluation=_evaluation(bundle) if demo else None,
        backtest=None if demo else scoring.get("backtest"),
        caveat=CAVEAT if demo else UPLOAD_CAVEAT,
    )
