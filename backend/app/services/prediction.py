"""Churn-risk inference. Uses the same feature code as training (app.services.features)."""

import pandas as pd
from sqlalchemy.orm import Session

from app.db import repositories
from app.ml.artifact import ModelBundle
from app.schemas.churn import CustomerPrediction, PredictResponse
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
    through = repositories.data_through(session)
    return None if through is None else through.floor("D")


def predict(
    session: Session,
    bundle: ModelBundle,
    customer_ids: list[str],
    cutoff: pd.Timestamp | None = None,
) -> PredictResponse:
    cutoff = cutoff if cutoff is not None else default_cutoff(session)
    unique_ids = list(dict.fromkeys(customer_ids))  # drop repeats, keep request order
    known = repositories.resolve_customers(session, unique_ids)

    scores: dict[int, float] = {}
    if known and cutoff is not None:  # cutoff is None only when no events exist at all
        events = repositories.load_events(session, until=cutoff, customer_ids=list(known.values()))
        x = features.build_features(events, [cutoff])
        if not x.empty:
            x = x[bundle.metadata["feature_columns"]]  # exact training column order
            proba = bundle.pipeline.predict_proba(x)[:, 1]
            scores = dict(zip(x.index.get_level_values("customer_id"), proba, strict=True))

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
