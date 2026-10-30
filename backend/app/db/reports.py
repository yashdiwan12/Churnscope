"""The only place that queries `saved_reports`. Every function takes the owner's `user_id`, so a
route cannot forget the ownership filter."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import SavedReport, UserProfile

MAX_REPORTS = 100


class ReportLimitReached(Exception):
    pass


def list_reports(
    session: Session, user_id: uuid.UUID, limit: int, offset: int
) -> list[SavedReport]:
    stmt = (
        select(SavedReport)
        .where(SavedReport.user_id == user_id)
        .order_by(SavedReport.created_at.desc(), SavedReport.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt))


def create_report(
    session: Session, user_id: uuid.UUID, report_type: str, filters: dict
) -> SavedReport:
    # Lock the owner's profile row so two concurrent creates cannot both pass the count check.
    session.execute(select(UserProfile.id).where(UserProfile.id == user_id).with_for_update())
    count = session.scalar(
        select(func.count()).select_from(SavedReport).where(SavedReport.user_id == user_id)
    )
    if (count or 0) >= MAX_REPORTS:
        session.rollback()
        raise ReportLimitReached
    report = SavedReport(user_id=user_id, report_type=report_type, filters=filters)
    session.add(report)
    session.commit()
    return report


def delete_report(session: Session, user_id: uuid.UUID, report_id: int) -> bool:
    """True if a report owned by `user_id` was deleted; False if missing or someone else's."""
    result = session.execute(
        delete(SavedReport).where(SavedReport.id == report_id, SavedReport.user_id == user_id)
    )
    session.commit()
    return result.rowcount > 0
