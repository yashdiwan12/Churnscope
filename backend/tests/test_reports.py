"""db/reports.py: every function is scoped to a user id; ownership is not the route's job."""

import uuid

import pytest
from sqlalchemy import select

from app.db import reports
from app.db.models import SavedReport, UserProfile


@pytest.fixture
def users(session):
    ids = [uuid.uuid4(), uuid.uuid4()]
    session.add_all([UserProfile(id=i) for i in ids])
    session.commit()
    return ids


def test_create_then_list_newest_first(session, users):
    a, _ = users
    first = reports.create_report(session, a, "overview", {"x": 1})
    second = reports.create_report(session, a, "funnel", {})
    listed = reports.list_reports(session, a, limit=50, offset=0)
    assert [r.id for r in listed] == [second.id, first.id]
    assert listed[1].filters == {"x": 1}


def test_list_pagination(session, users):
    a, _ = users
    for _i in range(3):
        reports.create_report(session, a, "overview", {})
    assert len(reports.list_reports(session, a, limit=2, offset=0)) == 2
    assert len(reports.list_reports(session, a, limit=2, offset=2)) == 1


def test_users_only_see_their_own_reports(session, users):
    a, b = users
    reports.create_report(session, a, "overview", {})
    assert reports.list_reports(session, b, limit=50, offset=0) == []


def test_deleting_someone_elses_report_is_a_noop_that_reports_false(session, users):
    a, b = users
    mine = reports.create_report(session, a, "overview", {})
    assert reports.delete_report(session, b, mine.id) is False
    assert session.scalar(select(SavedReport.id).where(SavedReport.id == mine.id)) == mine.id
    assert reports.delete_report(session, a, mine.id) is True
    assert reports.delete_report(session, a, mine.id) is False


def test_limit_is_per_user(session, users):
    a, b = users
    for _i in range(reports.MAX_REPORTS):
        reports.create_report(session, a, "overview", {})
    with pytest.raises(reports.ReportLimitReached):
        reports.create_report(session, a, "overview", {})
    assert reports.create_report(session, b, "overview", {}).id  # b is unaffected
