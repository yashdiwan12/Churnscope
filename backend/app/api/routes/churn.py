from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.ml.artifact import ModelBundle
from app.schemas.churn import PredictRequest, PredictResponse
from app.services import prediction

# Phase 5 attaches the verified-token dependency here (`dependencies=[Depends(...)]`).
router = APIRouter(prefix="/churn", tags=["churn"])

SessionDep = Annotated[Session, Depends(get_session)]


def get_bundle(request: Request) -> ModelBundle:
    """The model loaded (and integrity-checked) at startup; 503 if it could not be loaded."""
    bundle = getattr(request.app.state, "model_bundle", None)
    if bundle is None:
        raise HTTPException(503, "Churn model is unavailable")
    return bundle


@router.post("/predict", response_model=PredictResponse)
def predict(
    body: PredictRequest, session: SessionDep, bundle: Annotated[ModelBundle, Depends(get_bundle)]
) -> PredictResponse:
    return prediction.predict(session, bundle, body.customer_ids)
