import logging
import uuid
from pathlib import PureWindowsPath
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from app.core import authorization
from app.core.authorization import current_profile, current_user
from app.core.security import AuthUser
from app.db import datasets as datasets_db
from app.db import repositories
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
from app.services import prediction, upload_scoring, uploads
from app.services.metrics import EVENT_NAMES, FUNNEL_STEPS, QUALIFYING_EVENTS

logger = logging.getLogger("churnscope.datasets")
router = APIRouter(prefix="/datasets", tags=["datasets"])

Profile = Annotated[UserProfile, Depends(current_profile)]
User = Annotated[AuthUser, Depends(current_user)]
SessionDep = Annotated[Session, Depends(get_session)]
DatasetId = Annotated[int, Path(ge=1, le=2**63 - 1)]

MAX_NAME_CHARS = 100
DEFAULT_FILENAME = "upload.csv"


def rejection(err: uploads.UploadRejected) -> HTTPException:
    return HTTPException(err.status, err.detail())


def clean_filename(filename: str | None) -> str:
    """The last path part (Windows or POSIX separators), at most 100 chars. Empty, "." and ".."
    become the default name."""
    name = PureWindowsPath(filename or "").name.strip()[:MAX_NAME_CHARS]
    return DEFAULT_FILENAME if name in ("", ".", "..") else name


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
async def check_upload(request: Request, user: User) -> CheckOut:
    """Parse and summarise a CSV. Stores nothing, so it needs no session or profile row."""
    # The body is read by hand (not a declared File parameter) so the size limits are enforced
    # before FastAPI would buffer the upload.
    try:
        form = await uploads.read_form(request)
        columns = uploads.column_options(form.fields)
        parsed = await run_in_threadpool(
            uploads.parse_csv, form.data, pd.Timestamp.now(tz="UTC"), columns
        )
    except uploads.UploadRejected as err:
        raise rejection(err) from None
    return summarise(parsed)


def _parse_and_prepare(form: uploads.UploadForm) -> uploads.Prepared:
    mapping, derive, acknowledged = uploads.import_options(form.fields)
    columns = uploads.column_options(form.fields)
    parsed = uploads.parse_csv(form.data, pd.Timestamp.now(tz="UTC"), columns)
    return uploads.prepare(parsed, mapping, derive, acknowledged)


def _transient(exc: Exception) -> bool:
    """A lost or unreachable database: worth a retry, not a stored ``FAILED``."""
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    return isinstance(exc, DBAPIError) and bool(exc.connection_invalidated)


def run_scoring(session: Session, dataset: Dataset) -> bool:
    """Spec 5a for one upload, stored on its row in a transaction of its own.

    A failure while fitting is stored as ``FAILED`` (the page then offers a Retry) and logged by
    exception type only: the message or traceback could carry values from the file. A transient
    database error is re-raised instead and nothing is stored. Storing the result can still raise
    a database error, which the caller handles. False when the row was gone by the time the
    result was stored (deleted or replaced meanwhile).
    """
    try:
        events = repositories.load_events(session, dataset.id)
        scoring = upload_scoring.fit(events, pd.Timestamp.now(tz="UTC"))
    except Exception as exc:
        session.rollback()
        if _transient(exc):
            raise
        logger.error("scoring failed: %s", type(exc).__name__)
        scoring = dict(upload_scoring.FAILED)
    stored = datasets_db.set_scoring(session, dataset.id, scoring)
    prediction.evict_dataset(dataset.id)
    if stored:
        session.refresh(dataset)
    return stored


def _score_after_import(session: Session, dataset: Dataset) -> DatasetOut:
    """The import has committed, so its 201 stands whatever happens here.

    The response is built before scoring, so a failure needs no further SQL: it is the dataset as
    imported, with no scoring method.
    """
    before = dataset_out(dataset)
    try:
        if run_scoring(session, dataset):
            return dataset_out(dataset)
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("storing scoring failed: %s", type(exc).__name__)
    return before


def _store_upload(
    session: Session, user_id: uuid.UUID, filename: str, prepared: uploads.Prepared
) -> Dataset:
    # The profile row is made only now, after the body has been read and checked.
    profile = authorization.ensure_profile(session, user_id)
    return datasets_db.replace_upload(session, profile.id, filename, prepared)


@router.post("", response_model=ImportOut, status_code=201)
async def import_upload(request: Request, user: User, session: SessionDep) -> ImportOut:
    """Import a CSV as the caller's upload, replacing the previous one in one transaction.

    Multipart fields: `file`, `mapping` (JSON object), optional `columns` (JSON object: our column
    to the file's header), `derive_signup` and
    `acknowledge_approximate_signup` ("true" or "false", default false).
    """
    try:
        form = await uploads.read_form(request)  # size checks run before the body is parsed
        prepared = await run_in_threadpool(_parse_and_prepare, form)
    except uploads.UploadRejected as err:
        raise rejection(err) from None
    try:
        dataset = await run_in_threadpool(
            _store_upload,
            session,
            user.id,
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
    out = await run_in_threadpool(_score_after_import, session, dataset)
    return ImportOut(
        dataset=out,
        imported_events=len(prepared.events),
        derived_signups=prepared.derived_signups,
        ignored_rows=prepared.ignored_rows,
        duplicate_rows=prepared.duplicate_rows,
        invalid_rows=prepared.invalid_rows,
        skipped=[SkipReason(row=r, code=c) for r, c in prepared.skipped[: uploads.MAX_REASONS]],
    )


@router.post("/{dataset_id}/score", response_model=DatasetOut)
def score_dataset(dataset_id: DatasetId, profile: Profile, session: SessionDep) -> DatasetOut:
    """(Re)run churn scoring on the caller's upload. The demo, a missing id or someone else's
    dataset is 404."""
    dataset = datasets_db.own_upload(session, profile.id)
    if dataset is None or dataset.id != dataset_id:
        raise HTTPException(404, "Dataset not found")
    try:
        stored = run_scoring(session, dataset)
    except ObjectDeletedError:  # replaced or deleted between storing and re-reading
        stored = False
    except (OperationalError, InterfaceError):
        raise  # the app's 503 handler, which logs only the exception type
    except SQLAlchemyError as exc:
        if _transient(exc):  # e.g. an invalidated connection: same answer as the 503 handler
            logger.error("database unavailable on score: %s", type(exc).__name__)
            raise HTTPException(503, "Database unavailable") from None
        logger.error("storing scoring failed: %s", type(exc).__name__)
        raise HTTPException(500, "Scoring failed") from None
    if not stored:
        raise HTTPException(404, "Dataset not found")
    return dataset_out(dataset)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: DatasetId, profile: Profile, session: SessionDep) -> Response:
    """Delete the caller's upload. The demo, a missing id or someone else's dataset is 404."""
    if not datasets_db.delete_upload(session, profile.id, dataset_id):
        raise HTTPException(404, "Dataset not found")
    prediction.evict_dataset(dataset_id)
    return Response(status_code=204)
