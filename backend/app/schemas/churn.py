from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_CUSTOMERS_PER_REQUEST = 100
UPLOAD_CAVEAT = (
    "Churn here means no activity for 14 days, not cancellation. Results are measured on your "
    "file's own history, which shows the method worked recently, not that it will keep working."
)
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


AtRiskSort = Literal["risk_desc", "risk_asc", "customer_asc"]


AtRiskMethod = Literal["shipped_model", "logistic", "inactive_rule", "rule_unchecked"]
HistogramUnit = Literal["risk_score", "days_inactive"]


class AtRiskRow(BaseModel):
    rank: int  # 1-based, distinct even for tied scores
    customer_id: str
    risk_score: float | None  # model methods only; None when ranked by the rule
    days_inactive: float | None = None  # rule methods only: days since last activity
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
    dataset_id: int
    method: AtRiskMethod  # shipped_model for the demo; an upload's scoring method otherwise
    reason: str | None = None  # an upload's scoring reason code (why it is unchecked), if any
    model_version: str
    cutoff: datetime | None  # None if no events exist
    data_through: datetime | None  # latest event timestamp (freshness label)
    window_days: int
    horizon_days: int
    decision_threshold: float  # a score for model methods; days inactive for rule methods
    eligible_customers: int
    at_risk_count: int
    # risk_score: 10 equal bins over [0, 1], the last one inclusive.
    # days_inactive: 4 bins of 7 days over [0, 28).
    score_histogram: list[HistogramBin]
    histogram_unit: HistogramUnit
    sort: AtRiskSort  # the applied row order; rank is always the global rank by risk
    rows: list[AtRiskRow]
    evaluation: Evaluation | None  # the shipped model's synthetic test metrics; None for uploads
    backtest: dict | None  # an upload's backtest on its own history; None for the demo
    caveat: str
