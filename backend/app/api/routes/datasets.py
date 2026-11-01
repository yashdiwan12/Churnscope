from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.core.authorization import current_profile
from app.db.models import UserProfile
from app.schemas.datasets import CheckOut, EventNameCount, SkipReason
from app.services import uploads
from app.services.metrics import EVENT_NAMES, FUNNEL_STEPS, QUALIFYING_EVENTS

router = APIRouter(prefix="/datasets", tags=["datasets"])

Profile = Annotated[UserProfile, Depends(current_profile)]


def rejection(err: uploads.UploadRejected) -> HTTPException:
    return HTTPException(err.status, err.detail())


def summarise(parsed: uploads.ParsedFile) -> CheckOut:
    rows = parsed.rows
    counts = rows["source_name"].value_counts().sort_values(ascending=False, kind="stable")
    share = uploads.first_week_share(rows)
    empty = rows.empty
    return CheckOut(
        total_rows=parsed.total_rows,
        valid_rows=len(rows),
        customers=int(rows["customer_id"].nunique()),
        first_event=None if empty else rows["event_timestamp"].min().to_pydatetime(),
        last_event=None if empty else rows["event_timestamp"].max().to_pydatetime(),
        event_names=[EventNameCount(name=str(n), count=int(c)) for n, c in counts.items()],
        suggested_mapping=uploads.suggest_mapping([str(n) for n in counts.index]),
        skipped_count=len(parsed.skipped),
        skipped=[SkipReason(row=r, code=c) for r, c in parsed.skipped[: uploads.MAX_REASONS]],
        zoneless_timestamps=parsed.zoneless,
        first_week_share=share,
        censor_warning=share >= uploads.CENSOR_WARN_SHARE,
        our_event_names=list(EVENT_NAMES),
        qualifying_events=list(QUALIFYING_EVENTS),
        funnel_steps=list(FUNNEL_STEPS),
    )


@router.post("/check", response_model=CheckOut)
async def check_upload(request: Request, profile: Profile) -> CheckOut:
    """Parse and summarise a CSV. Stores nothing."""
    # The body is read by hand (not a declared File parameter) so the size limits are enforced
    # before FastAPI would buffer the upload.
    try:
        _, raw = await uploads.read_upload(request)
        parsed = await run_in_threadpool(uploads.parse_csv, raw, pd.Timestamp.now(tz="UTC"))
    except uploads.UploadRejected as err:
        raise rejection(err) from None
    return summarise(parsed)
