from datetime import datetime
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.authorization import current_user
from app.db.datasets import DEMO_DATASET_ID
from app.db.session import get_session
from app.schemas.analytics import EngagementOut, FunnelOut, OverviewOut, RetentionOut
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]

Start = Annotated[datetime | None, Query(description="Inclusive, tz-aware. Default: end - 30 days")]
End = Annotated[
    datetime | None, Query(description="Exclusive, tz-aware. Default: day after latest data")
]


def _utc(name: str, value: datetime | None) -> pd.Timestamp | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(422, f"{name} must include a timezone (e.g. 2026-01-01T00:00:00Z)")
    return pd.Timestamp(value).tz_convert("UTC")


@router.get("/overview", response_model=OverviewOut)
def overview(session: SessionDep, start: Start = None, end: End = None) -> OverviewOut:
    try:
        return analytics.overview(session, DEMO_DATASET_ID, _utc("start", start), _utc("end", end))
    except analytics.InvalidRange as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/funnel", response_model=FunnelOut)
def funnel(
    session: SessionDep,
    start: Start = None,
    end: End = None,
    window_days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> FunnelOut:
    try:
        return analytics.funnel_report(
            session, DEMO_DATASET_ID, _utc("start", start), _utc("end", end), window_days
        )
    except analytics.InvalidRange as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/retention", response_model=RetentionOut)
def retention(session: SessionDep, periods: Annotated[int, Query(ge=1, le=26)] = 8) -> RetentionOut:
    return analytics.retention_report(session, DEMO_DATASET_ID, periods)


@router.get("/engagement", response_model=EngagementOut)
def engagement(session: SessionDep, start: Start = None, end: End = None) -> EngagementOut:
    try:
        return analytics.engagement_report(
            session, DEMO_DATASET_ID, _utc("start", start), _utc("end", end)
        )
    except analytics.InvalidRange as exc:
        raise HTTPException(422, str(exc)) from exc
