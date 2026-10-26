import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def pytest_addoption(parser):
    parser.addoption(
        "--require-postgres", action="store_true", help="Fail without TEST_DATABASE_URL"
    )


def pytest_configure(config):
    if config.getoption("--require-postgres") and not os.getenv("TEST_DATABASE_URL"):
        raise pytest.UsageError("--require-postgres requires TEST_DATABASE_URL")


@pytest.fixture
def postgres_url():
    """Create only a disposable schema; never drop or reset the supplied database."""
    raw = os.getenv("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Set TEST_DATABASE_URL to run live PostgreSQL integration tests")
    url = make_url(raw)
    if url.drivername != "postgresql+psycopg":
        pytest.fail("TEST_DATABASE_URL must use postgresql+psycopg")
    schema = "test_foundation_" + uuid.uuid4().hex
    admin = create_engine(url)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Alembic and application connections must use the same isolated schema.
        isolated = url.update_query_dict({"options": f"-csearch_path={schema}"})
        yield isolated.render_as_string(hide_password=False)
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
