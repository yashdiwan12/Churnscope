from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.authorization import current_user
from app.db.session import get_session
from app.ml.artifact import ModelBundle
from app.schemas.churn import AtRiskOut, PredictRequest, PredictResponse
from app.services import prediction

router = APIRouter(prefix="/churn", tags=["churn"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]


def get_bundle(request: Request) -> ModelBundle:
    """The model loaded (and integrity-checked) at startup; 503 if it could not be loaded."""
    bundle = getattr(request.app.state, "model_bundle", None)
    if bundle is None:
        raise HTTPException(503, "Churn model is unavailable")
    return bundle


@router.post("/predict", response_model=PredictResponse)
def predict(
    # The model check is declared first so a missing model is a 503 even if the DB is broken.
    bundle: Annotated[ModelBundle, Depends(get_bundle)],
    body: PredictRequest,
    session: SessionDep,
) -> PredictResponse:
    return prediction.predict(session, bundle, body.customer_ids)


@router.get("/at-risk", response_model=AtRiskOut)
def at_risk(
    # The model check is declared first so a missing model is a 503 even if the DB is broken.
    bundle: Annotated[ModelBundle, Depends(get_bundle)],
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> AtRiskOut:
    return prediction.at_risk(session, bundle, limit, offset)
