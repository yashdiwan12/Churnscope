"""Who may call what. Identity is only ever the verified token; failures fail closed.

`current_user`: valid token + allow-list (no DB write). `current_profile`: the same, plus the
`user_profiles` row that `saved_reports.user_id` points at.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import (
    AuthUnavailable,
    AuthUser,
    InvalidToken,
    TokenVerifier,
    get_verifier,
)
from app.db.models import UserProfile
from app.db.session import get_session

NOT_AUTHENTICATED = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def is_allowed(user: AuthUser, settings: Settings) -> bool:
    """Allow-list by exact lower-cased email, or exact domain. An empty list allows nobody."""
    if not user.email:
        return False
    email = user.email.strip().lower()
    if email in settings.allowed_email_list:
        return True
    return "@" in email and email.rsplit("@", 1)[1] in settings.allowed_domain_list


def signed_in_with_google(user: AuthUser) -> bool:
    """The account must have come through Google, not another way of claiming the address."""
    return "oauth" in user.amr_methods and user.provider in (None, "google")


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise NOT_AUTHENTICATED
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise NOT_AUTHENTICATED
    return parts[1]


def current_user(
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthUser:
    token = _bearer_token(authorization)
    try:
        user = verifier.verify(token)
    except InvalidToken:
        raise NOT_AUTHENTICATED from None
    except AuthUnavailable:
        raise HTTPException(503, "Authentication unavailable") from None
    if not (is_allowed(user, get_settings()) and signed_in_with_google(user)):
        raise HTTPException(403, "Not allowed")
    return user


def current_profile(
    user: Annotated[AuthUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
) -> UserProfile:
    session.execute(pg_insert(UserProfile).values(id=user.id).on_conflict_do_nothing())
    session.commit()
    profile = session.get(UserProfile, user.id)
    assert profile is not None
    return profile
