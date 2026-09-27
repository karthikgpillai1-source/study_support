"""Database engine, session factory and fast-init helper for local development."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.models import Base


def _build_engine() -> Engine:
    url = settings.database_url
    kwargs: dict[str, object] = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # check_same_thread=False lets FastAPI's threadpool share one connection
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    return create_engine(url, **kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # pragma: no cover
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist.

    Alembic owns schema migrations; this keeps ``uvicorn app.main:app`` working
    from a clean checkout without a migration step.
    """
    Base.metadata.create_all(bind=engine)
