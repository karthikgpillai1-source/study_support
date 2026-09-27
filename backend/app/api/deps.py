"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(credentials: Credentials, db: DbSession) -> User:
    if credentials is None or not credentials.credentials:
        raise _UNAUTHORIZED
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise _UNAUTHORIZED
    subject = payload.get("sub")
    if not subject:
        raise _UNAUTHORIZED
    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise _UNAUTHORIZED from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
