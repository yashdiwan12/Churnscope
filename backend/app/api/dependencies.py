"""Shared route dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.authorization import current_profile
from app.db import datasets
from app.db.models import Dataset, UserProfile
from app.db.session import get_session


def visible_dataset(
    profile: Annotated[UserProfile, Depends(current_profile)],
    session: Annotated[Session, Depends(get_session)],
    dataset_id: Annotated[int, Query(ge=1, le=2**63 - 1)] = datasets.DEMO_DATASET_ID,
) -> Dataset:
    """The requested dataset if the caller may see it; 404 otherwise (never 403)."""
    dataset = datasets.visible(session, profile.id, dataset_id)
    if dataset is None:
        raise HTTPException(404, "Dataset not found")
    return dataset


DatasetDep = Annotated[Dataset, Depends(visible_dataset)]
