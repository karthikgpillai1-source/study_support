"""Authentication routes: register, login, profile, availability."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.schemas import TokenOut, UserCreate, UserLogin, UserOut, UserUpdate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: DbSession) -> TokenOut:
    email = payload.email.lower().strip()
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        daily_minutes=payload.daily_minutes,
        preferred_start_time=payload.preferred_start_time,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token(user)


@router.post("/login", response_model=TokenOut)
def login(payload: UserLogin, db: DbSession) -> TokenOut:
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")
    return _token(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserOut)
def update_me(payload: UserUpdate, user: CurrentUser, db: DbSession) -> User:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


def _token(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, {"email": user.email}),
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )
