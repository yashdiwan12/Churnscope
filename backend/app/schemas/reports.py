import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

MAX_FILTERS_BYTES = 4096


class ReportCreate(BaseModel):
    """No `user_id` field: the owner is the verified token, and unknown fields are a 422."""

    model_config = ConfigDict(extra="forbid")

    report_type: Literal["overview", "funnel", "retention", "engagement", "churn"]
    filters: dict[str, Any] = {}

    @field_validator("filters")
    @classmethod
    def _small_enough(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value)) > MAX_FILTERS_BYTES:
            raise ValueError(f"filters must be at most {MAX_FILTERS_BYTES} bytes of JSON")
        return value


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_type: str
    filters: dict[str, Any] | None
    created_at: datetime


class MeOut(BaseModel):
    id: uuid.UUID
    email: str | None
    created_at: datetime
