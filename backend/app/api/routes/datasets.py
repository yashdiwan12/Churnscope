import logging
from pathlib import PureWindowsPath
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.authorization import current_profile
from app.db import datasets as datasets_db
from app.db.models import Dataset, UserProfile
from app.db.session import get_session
from app.schemas.datasets import (
    Capabilities,
    CheckOut,
    DatasetOut,
    EventNameCount,
    ImportOut,
    SkipReason,
)
from app.services import prediction, uploads
from app.services.metrics import EVENT_NAMES, FUNNEL_STEPS, QUALIFYING_EVENTS

logger = logging.getLogger("churnscope.datasets")
router = APIRouter(prefix="/datasets", tags=["datasets"])

Profile = Annotated[UserProfile, Depends(current_profile)]
SessionDep = Annotated[Session, Depends(get_session)]
DatasetId = Annotated[int, Path(ge=1, le=2**63 - 1)]

MAX_NAME_CHARS = 100
DEFAULT_FILENAME = "upload.csv"


def rejection(err: uploads.UploadRejected) -> HTTPException:
    return HTTPException(err.status, err.detail())


def clean_filename(filename: str | None) -> str:
    """The last path part (Windows or POSIX separators), at most 100 chars."""
    name = PureWindowsPath(filename or "").name.strip()[:MAX_NAME_CHARS]
    return name or DEFAULT_FILENAME


def dataset_out(dataset: Dataset) -> DatasetOut:
    scoring = dataset.scoring or {}
    return DatasetOut(
        id=dataset.id,
        kind=dataset.kind,
        name=dataset.name,
        source_filename=dataset.source_filename,
        signup_rule=dataset.signup_rule,
        customer_count=dataset.customer_count,
        event_count=dataset.event_count,
        data_through=dataset.data_through,
        created_at=dataset.created_at,
        capabilities=Capabilities(**uploads.capabilities(dataset)),
        scoring_method=scoring.get("method"),
    )


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


@router.get("", response_model=list[DatasetOut])
def list_datasets(profile: Profile, session: SessionDep) -> list[DatasetOut]:
    """The demo dataset first, then the caller's upload (if any)."""
    return [dataset_out(d) for d in datasets_db.list_visible(session, profile.id)]


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


def _parse_and_prepare(form: uploads.UploadForm) -> uploads.Prepared:
    mapping, derive, acknowledged = uploads.import_options(form.fields)
    parsed = uploads.parse_csv(form.data, pd.Timestamp.now(tz="UTC"))
    return uploads.prepare(parsed, mapping, derive, acknowledged)


@router.post("", response_model=ImportOut, status_code=201)
async def import_upload(request: Request, profile: Profile, session: SessionDep) -> ImportOut:
    """Import a CSV as the caller's upload, replacing the previous one in one transaction.

    Multipart fields: `file`, `mapping` (JSON object), `derive_signup` and
    `acknowledge_approximate_signup` ("true" or "false", default false).
    """
    try:
        form = await uploads.read_form(request)  # size checks run before the body is parsed
        prepared = await run_in_threadpool(_parse_and_prepare, form)
    except uploads.UploadRejected as err:
        raise rejection(err) from None
    try:
        dataset = await run_in_threadpool(
            datasets_db.replace_upload,
            session,
            profile.id,
            clean_filename(form.filename),
            prepared,
        )
    except datasets_db.StorageFull:
        raise HTTPException(
            409,
            {"code": "storage_full", "message": "Upload storage is full. Try again later."},
        ) from None
    except (OperationalError, InterfaceError):
        raise  # the app's 503 handler, which logs only the exception type
    except SQLAlchemyError as exc:
        # The exception text carries the SQL parameters, i.e. values from the file: log the
        # type only and drop the chain so no traceback with them reaches the server log.
        logger.error("import failed: %s", type(exc).__name__)
        raise HTTPException(500, "Import failed") from None
    return ImportOut(
        dataset=dataset_out(dataset),
        imported_events=len(prepared.events),
        derived_signups=prepared.derived_signups,
        ignored_rows=prepared.ignored_rows,
        duplicate_rows=prepared.duplicate_rows,
        invalid_rows=prepared.invalid_rows,
        skipped=[SkipReason(row=r, code=c) for r, c in prepared.skipped[: uploads.MAX_REASONS]],
    )


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: DatasetId, profile: Profile, session: SessionDep) -> Response:
    """Delete the caller's upload. The demo, a missing id or someone else's dataset is 404."""
    if not datasets_db.delete_upload(session, profile.id, dataset_id):
        raise HTTPException(404, "Dataset not found")
    prediction.evict_dataset(dataset_id)
    return Response(status_code=204)
