from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.core.authorization import ingest_key
from app.db.datasets import DEMO_DATASET_ID
from app.db.session import get_session
from app.schemas.events import IngestResult
from app.services.ingestion import MAX_BATCH, ingest_events

MAX_BODY_BYTES = 5 * 1024 * 1024

router = APIRouter(tags=["events"], dependencies=[Depends(ingest_key)])


class EventsBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[dict[str, Any]]


@router.post("/events", response_model=IngestResult)
async def post_events(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> IngestResult:
    # Read by hand so the size limit is enforced before any JSON is parsed.
    try:
        length = int(request.headers["content-length"])
        if length < 0:
            raise ValueError
    except (KeyError, ValueError):
        raise HTTPException(411, "Content-Length required") from None
    if length > MAX_BODY_BYTES:
        raise HTTPException(413, "Request body too large")
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "Request body too large")
    try:
        batch = EventsBatch.model_validate_json(raw)
    except ValidationError as err:  # field paths and messages only, never the input values
        detail = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in err.errors()]
        raise HTTPException(422, detail) from None
    if len(batch.events) > MAX_BATCH:
        raise HTTPException(422, f"batch exceeds {MAX_BATCH} events")
    return await run_in_threadpool(ingest_events, session, batch.events, DEMO_DATASET_ID)
