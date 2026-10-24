from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_CUSTOMERS_PER_REQUEST = 100
CustomerId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_ids: list[CustomerId] = Field(min_length=1, max_length=MAX_CUSTOMERS_PER_REQUEST)


class CustomerPrediction(BaseModel):
    customer_id: str
    status: Literal["scored", "not_eligible", "unknown_customer"]
    risk_score: float | None = None  # relative churn-risk score in [0, 1]; None unless scored
    predicted_class: Literal["at_risk", "not_at_risk"] | None = None
    reason: str | None = None  # why a customer was not scored


class PredictResponse(BaseModel):
    model_version: str
    cutoff: datetime  # predictions use only events before this instant
    window_days: int
    horizon_days: int
    decision_threshold: float
    predictions: list[CustomerPrediction]
    caveat: str
