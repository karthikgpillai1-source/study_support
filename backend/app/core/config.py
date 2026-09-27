from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]

#: Ships in .env.example. Never acceptable outside local development.
PLACEHOLDER_SECRET = "change-me-in-production"
#: RFC 7518 s3.2 requires >= 256 bits for HMAC-SHA256.
MIN_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Study Intelligence Platform API"
    app_env: str = "development"
    api_prefix: str = "/api"

    secret_key: str = PLACEHOLDER_SECRET
    access_token_expire_minutes: int = 60 * 24 * 7
    jwt_algorithm: str = "HS256"

    database_url: str = "sqlite:///./study_intelligence.db"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_timeout_seconds: float = 60.0
    local_llm_url: str = ""
    local_llm_model: str = "qwen2.5-0.5b-instruct"

    # Stored as a raw string on purpose. pydantic-settings JSON-decodes any
    # list-typed field *before* field validators run, so a comma-separated value
    # like "http://localhost:5173,http://127.0.0.1:5173" in .env would fail to
    # parse and crash startup. Parsing it ourselves keeps .env human-writable.
    cors_origins: str = "http://localhost:5173,https://study-support-git-main-karpo-10.vercel.app,https://study-support-karthikgpillai1-sources-projects.vercel.app"

    max_upload_mb: int = 25
    storage_dir: Path = BACKEND_DIR / "storage"

    @model_validator(mode="after")
    def _check_secret_key(self) -> Settings:
        """Refuse to sign tokens with a weak or placeholder key.

        A short HMAC key weakens every JWT this service issues, so this is a
        startup error in production and a loud warning in development.
        """
        key = self.secret_key
        length = len(key.encode("utf-8"))

        if self.is_production and key == PLACEHOLDER_SECRET:
            raise ValueError(
                "SECRET_KEY is still the example placeholder. Generate a real one "
                'with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if length < MIN_SECRET_BYTES:
            message = (
                f"SECRET_KEY is {length} bytes; {MIN_SECRET_BYTES}+ are required for "
                f"{self.jwt_algorithm} (RFC 7518 s3.2). Generate a strong key with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
            if self.is_production:
                raise ValueError(message)
            logger.warning(message)
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def cors_origin_list(self) -> list[str]:
        """Comma-separated origins from config, always at least one entry."""
        origins = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        return origins or ["http://localhost:5173", "https://study-support-git-main-karpo-10.vercel.app", "https://study-support-karthikgpillai1-sources-projects.vercel.app"]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key.strip() or self.local_llm_url.strip())

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def generate_secret_key() -> str:
    """A 48-byte URL-safe key, for scripts and setup tooling."""
    return secrets.token_urlsafe(48)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
