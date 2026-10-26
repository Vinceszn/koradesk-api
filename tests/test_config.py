"""Configuration errors must be caught before accepting requests."""

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def settings(**values):
    return Settings(_env_file=None, **values)


def test_development_defaults_and_sqlite_preview():
    assert settings().env == "dev"
    assert settings(database_url="sqlite:///work/preview.db").database_url.startswith("sqlite:")


@pytest.mark.parametrize(
    "field,value",
    [
        ("env", "prd"),
        ("daily_summary_hour", -1),
        ("daily_summary_hour", 24),
        ("retention_months", 0),
        ("smtp_port", 0),
        ("smtp_port", 65536),
        ("meta_cost_per_msg_ngn", -1),
        ("ai_cost_per_conversation_ngn", float("nan")),
        ("meta_cost_per_msg_ngn", float("inf")),
        ("database_url", "not-a-url"),
        ("database_url", "mysql://host/db"),
        ("database_url", "postgresql+psycopg://host"),
        ("database_url", "postgresql+psycopg://host:99999/db"),
        ("database_url", "sqlite://remote/db"),
    ],
)
def test_invalid_values(field, value):
    with pytest.raises(ValidationError):
        settings(**{field: value})


@pytest.mark.parametrize("env", ["prod", "production"])
def test_production_requires_database_and_real_secrets(env):
    with pytest.raises(ValidationError, match="app_secret"):
        settings(env=env)
    secrets = dict(app_secret="a" * 40, verify_token="b" * 40)
    assert settings(env=env, **secrets).env == env
    with pytest.raises(ValidationError, match="PostgreSQL"):
        settings(env=env, database_url="sqlite:///preview.db", **secrets)
    with pytest.raises(ValidationError, match="verify_token"):
        settings(env=env, app_secret="a" * 40)
    with pytest.raises(ValidationError, match="app_secret"):
        settings(env=env, app_secret="changeme" * 10, verify_token="b" * 40)


def test_environment_values_are_loaded_and_validated(monkeypatch):
    monkeypatch.setenv("DAILY_SUMMARY_HOUR", "7")
    assert settings().daily_summary_hour == 7
    monkeypatch.setenv("DAILY_SUMMARY_HOUR", "24")
    with pytest.raises(ValidationError):
        settings()


@pytest.mark.parametrize("credentials", [{"smtp_user": "user"}, {"smtp_pass": "secret"}])
def test_smtp_credentials_must_be_paired(credentials):
    with pytest.raises(ValidationError, match="together"):
        settings(**credentials)


def test_dotenv_loading(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("DAILY_SUMMARY_HOUR=6\nUNKNOWN_SETTING=ignored\n", encoding="utf-8")
    assert Settings(_env_file=dotenv).daily_summary_hour == 6
