from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.authorization import current_profile, current_user
from app.core.security import AuthUser
from app.db import reports
from app.db.models import UserProfile
from app.db.session import get_session
from app.schemas.reports import MeOut, ReportCreate, ReportOut

router = APIRouter(prefix="/me", tags=["me"])

SessionDep = Annotated[Session, Depends(get_session)]
Profile = Annotated[UserProfile, Depends(current_profile)]


@router.get("", response_model=MeOut)
def me(user: Annotated[AuthUser, Depends(current_user)], profile: Profile) -> MeOut:
    return MeOut(id=profile.id, email=user.email, created_at=profile.created_at)


@router.get("/reports", response_model=list[ReportOut])
def list_my_reports(
    profile: Profile,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return reports.list_reports(session, profile.id, limit, offset)


@router.post("/reports", response_model=ReportOut, status_code=201)
def create_my_report(body: ReportCreate, profile: Profile, session: SessionDep):
    try:
        return reports.create_report(session, profile.id, body.report_type, body.filters)
    except reports.ReportLimitReached:
        raise HTTPException(409, "Report limit reached") from None


@router.delete("/reports/{report_id}", status_code=204)
def delete_my_report(report_id: int, profile: Profile, session: SessionDep) -> Response:
    if not reports.delete_report(session, profile.id, report_id):
        raise HTTPException(404, "Report not found")  # same for missing and someone else's
    return Response(status_code=204)
