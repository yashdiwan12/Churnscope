from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_CUSTOMERS_PER_REQUEST = 100
CustomerId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_ids: list[CustomerId] = Field(
        min_length=1,
        max_length=MAX_CUSTOMERS_PER_REQUEST,
        description="Repeated ids are answered once, in first-seen order.",
    )


class CustomerPrediction(BaseModel):
    customer_id: str
    status: Literal["scored", "not_eligible", "unknown_customer"]
    risk_score: float | None = None  # relative churn-risk score in [0, 1]; None unless scored
    predicted_class: Literal["at_risk", "not_at_risk"] | None = None
    reason: str | None = None  # why a customer was not scored


class PredictResponse(BaseModel):
    model_version: str
    cutoff: datetime | None  # predictions use only events before this; None if no events exist
    window_days: int
    horizon_days: int
    decision_threshold: float
    predictions: list[CustomerPrediction]
    caveat: str


class HistogramBin(BaseModel):
    bin_start: float
    bin_end: float
    count: int


class AtRiskRow(BaseModel):
    rank: int  # 1-based, distinct even for tied scores
    customer_id: str
    risk_score: float
    predicted_class: Literal["at_risk", "not_at_risk"]


class Evaluation(BaseModel):
    """The model's own held-out test metrics, as recorded in the artifact metadata."""

    roc_auc: float | None = None
    f1: float | None = None
    precision: float | None = None
    recall: float | None = None
    threshold: float | None = None
    test_churn_rate: float | None = None
    n: int | None = None
    synthetic: bool | None = None


class AtRiskOut(BaseModel):
    model_version: str
    cutoff: datetime | None  # None if no events exist
    data_through: datetime | None  # latest event timestamp (freshness label)
    window_days: int
    horizon_days: int
    decision_threshold: float
    eligible_customers: int
    at_risk_count: int
    score_histogram: list[HistogramBin]  # 10 equal bins over [0, 1], the last one inclusive
    rows: list[AtRiskRow]
    evaluation: Evaluation
    caveat: str
