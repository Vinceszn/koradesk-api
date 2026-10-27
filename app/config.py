"""Settings loaded from environment (.env in dev). Fail fast on missing secrets."""

from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    env: Literal["dev", "prod", "production"] = "dev"
    database_url: str = "postgresql+psycopg://kora:kora@localhost:5432/koradesk"

    whatsapp_token: str = "changeme"
    whatsapp_phone_number_id: str = "changeme"
    app_secret: str = "changeme"
    verify_token: str = "changeme"
    graph_version: str = "v21.0"

    daily_summary_hour: int = Field(default=18, ge=0, le=23)
    retention_months: int = Field(default=18, ge=1)

    # --- Ops mail (stuck approvals, margin alerts, new leads) ---
    # Comma-separated. One address for now; add more any time, no code change.
    admin_emails: str = "hello@koradesk.com"
    smtp_host: str = ""  # empty = log to console (dev), no send
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "Kora Desk Ops <ops@koradesk.com>"
    smtp_tls: bool = True

    # Pricing-model inputs (per pricing-model.md — change only with a re-run)
    meta_cost_per_msg_ngn: float = Field(default=10.0, ge=0, allow_inf_nan=False)
    ai_cost_per_conversation_ngn: float = Field(default=8.0, ge=0, allow_inf_nan=False)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        try:
            url = make_url(value)
            if url.drivername == "postgresql+psycopg":
                if not url.host or not url.database:
                    raise ValueError
                if url.port is not None and not 1 <= url.port <= 65535:
                    raise ValueError
            elif url.drivername == "sqlite":
                if url.host or not url.database:
                    raise ValueError
            else:
                raise ValueError
        except (ArgumentError, ValueError):
            raise ValueError(
                "Use a PostgreSQL psycopg URL or a local SQLite database URL"
            ) from None
        return value

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.env in {"prod", "production"}:
            if make_url(self.database_url).drivername != "postgresql+psycopg":
                raise ValueError("Production requires PostgreSQL with psycopg")
            for name in ("app_secret", "verify_token"):
                value = getattr(self, name).strip()
                if len(value) < 32 or value.lower().startswith("changeme"):
                    raise ValueError(
                        f"Production {name} must be a non-placeholder secret of at least 32 characters"
                    )
        if bool(self.smtp_user) != bool(self.smtp_pass):
            raise ValueError("SMTP_USER and SMTP_PASS must be configured together")
        return self


settings = Settings()
