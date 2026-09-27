"""Authentication + user schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import KnowledgeLevel


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    daily_minutes: int = Field(default=120, ge=15, le=240)
    preferred_start_time: str = Field(default="18:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    daily_minutes: int | None = Field(default=None, ge=15, le=240)
    preferred_start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    daily_minutes: int
    preferred_start_time: str
    timezone: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class AvailabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    daily_minutes: int
    preferred_start_time: str
    timezone: str
    default_knowledge_level: KnowledgeLevel = KnowledgeLevel.BEGINNER
