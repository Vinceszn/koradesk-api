"""Settings loaded from environment (.env in dev). Fail fast on missing secrets."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://kora:kora@localhost:5432/koradesk"

    whatsapp_token: str = "changeme"
    whatsapp_phone_number_id: str = "changeme"
    app_secret: str = "changeme"
    verify_token: str = "changeme"
    graph_version: str = "v21.0"

    daily_summary_hour: int = 18
    retention_months: int = 18

    # Pricing-model inputs (per pricing-model.md — change only with a re-run)
    meta_cost_per_msg_ngn: float = 10.0
    ai_cost_per_conversation_ngn: float = 8.0


settings = Settings()
