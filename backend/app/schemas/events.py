import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.metrics import EVENT_NAMES

MAX_PROPERTIES_BYTES = 4096
MAX_CLOCK_SKEW = timedelta(minutes=5)
MIN_EVENT_TIME = datetime(2000, 1, 1, tzinfo=UTC)
_ID = {"min_length": 1, "max_length": 128, "pattern": r"^[A-Za-z0-9_.:-]+$"}


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(**_ID)
    customer_id: str = Field(**_ID)
    event_name: str
    event_timestamp: datetime
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("event_name")
    @classmethod
    def _known_event(cls, v: str) -> str:
        if v not in EVENT_NAMES:
            raise ValueError(f"unknown event_name; allowed: {', '.join(EVENT_NAMES)}")
        return v

    @field_validator("event_timestamp")
    @classmethod
    def _aware_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("event_timestamp must include a timezone")
        v = v.astimezone(UTC)
        # A single bad clock would move "data through" and empty every default view.
        if v > datetime.now(UTC) + MAX_CLOCK_SKEW:
            raise ValueError(f"event_timestamp is in the future (allowed skew {MAX_CLOCK_SKEW})")
        if v < MIN_EVENT_TIME:
            raise ValueError(f"event_timestamp is before {MIN_EVENT_TIME:%Y-%m-%d}")
        return v

    @field_validator("properties")
    @classmethod
    def _small(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v)) > MAX_PROPERTIES_BYTES:
            raise ValueError(f"properties exceeds {MAX_PROPERTIES_BYTES} bytes")
        return v


class Rejection(BaseModel):
    index: int
    reason: str  # never contains property values or other payload data


class IngestResult(BaseModel):
    received: int
    inserted: int
    duplicates: int  # event_id already stored (or repeated in the batch); nothing written
    conflicts: int  # duplicates whose content differs from the stored event (first write wins)
    rejected: list[Rejection]
