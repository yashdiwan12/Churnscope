import uuid

from sqlalchemy import event

from app.core.authorization import current_profile
from app.core.security import AuthUser


def test_current_profile_inserts_once(engine, session):
    user = AuthUser(id=uuid.uuid4(), email="a@b.com", amr_methods=("oauth",), provider="google")
    inserts: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("INSERT INTO user_profiles"):
            inserts.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        first = current_profile(user, session)
        created_at = first.created_at
        assert len(inserts) == 1
        second = current_profile(user, session)
        assert len(inserts) == 1
        assert second.created_at == created_at
    finally:
        event.remove(engine, "before_cursor_execute", count)
