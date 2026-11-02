from datetime import datetime

from pydantic import BaseModel


class SkipReason(BaseModel):
    row: int  # 1-based data row; never a value from the file
    code: str


class EventNameCount(BaseModel):
    name: str
    count: int


class CheckOut(BaseModel):
    total_rows: int
    valid_rows: int
    customers: int
    first_event: datetime | None
    last_event: datetime | None
    event_names: list[EventNameCount]
    suggested_mapping: dict[str, str | None]
    skipped_count: int
    skipped: list[SkipReason]
    zoneless_timestamps: bool
    first_week_share: float
    censor_warning: bool
    our_event_names: list[str]
    qualifying_events: list[str]
    funnel_steps: list[str]


class Capabilities(BaseModel):
    overview: bool
    engagement: bool
    retention: bool
    funnel: bool
    churn: bool
    funnel_missing: list[str]


class DatasetOut(BaseModel):
    id: int
    kind: str
    name: str
    source_filename: str | None
    signup_rule: str
    customer_count: int
    event_count: int
    data_through: datetime | None
    created_at: datetime
    capabilities: Capabilities
    scoring_method: str | None


class ImportOut(BaseModel):
    dataset: DatasetOut
    imported_events: int
    derived_signups: int
    ignored_rows: int
    duplicate_rows: int
    invalid_rows: int
    skipped: list[SkipReason]  # the first MAX_REASONS of them
