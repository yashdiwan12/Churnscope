from datetime import date, datetime

from pydantic import BaseModel


class Window(BaseModel):
    start: datetime  # inclusive, UTC
    end: datetime  # exclusive, UTC
    data_through: datetime | None  # latest event in the database (data freshness)


class DailyActive(BaseModel):
    date: date
    active_users: int


class OverviewOut(BaseModel):
    window: Window
    active_users: int
    new_users: int
    returning_users: int
    returning_user_rate: float | None  # returning / active; None when no active users
    qualifying_events: int
    daily_active_users: list[DailyActive]
    qualifying_event_names: list[str]


class FunnelStepOut(BaseModel):
    step: str
    users: int
    conversion_from_previous: float | None
    conversion_from_start: float | None


class FunnelOut(BaseModel):
    window: Window
    window_days: int
    eligible_users: int
    steps: list[FunnelStepOut]
    note: str


class RetentionCell(BaseModel):
    cohort: date  # Monday of the signup week (UTC)
    period: int  # elapsed 7-day period since signup
    cohort_size: int
    eligible: int  # members whose period has fully elapsed
    retained: int
    retention: float | None  # None when no member is eligible yet
    complete: bool  # every cohort member is eligible


class RetentionOut(BaseModel):
    as_of: datetime | None
    period_days: int
    periods: int
    cells: list[RetentionCell]


class EngagementOut(BaseModel):
    window: Window
    active_users: int
    active_days_per_user_mean: float | None
    active_days_per_user_median: float | None
    events_per_active_user: float | None
    median_hours_between_activities: float | None
    feature_adoption: dict[str, float]  # share of active users, not of events
