"""Run against migrated PostgreSQL tables, including real constraints and locks."""

import time

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app import commerce_models as m
from app.commerce import app, digest
from app.config import settings
from app.db import get_session
from tests.test_commerce_migrations import config

pytestmark = pytest.mark.postgres


@pytest.fixture
def migrated(postgres_url, monkeypatch):
    monkeypatch.setattr(settings, "database_url", postgres_url)
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE shops (id INTEGER PRIMARY KEY, name TEXT)"))
            connection.execute(text("INSERT INTO shops VALUES (1, 'Legacy shop')"))
        command.upgrade(config(), "head")
        yield engine
    finally:
        engine.dispose()


def test_postgres_migration_roundtrip_preserves_legacy_data(migrated):
    command.upgrade(config(), "head")  # Repeat deploy is safe.
    with migrated.connect() as connection:
        assert "commerce_stock_operations" in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT name FROM shops WHERE id=1")) == "Legacy shop"
    command.downgrade(config(), "base")
    with migrated.connect() as connection:
        assert "commerce_users" not in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT name FROM shops WHERE id=1")) == "Legacy shop"
    command.upgrade(config(), "head")


@pytest.fixture
def stock(migrated):
    factory = sessionmaker(bind=migrated, expire_on_commit=False)
    with factory() as db:
        user = m.User(name="Owner", email="owner@example.com", password_hash="unused")
        first = m.Merchant(name="First", category="Retail")
        second = m.Merchant(name="Second", category="Retail")
        db.add_all([user, first, second])
        db.flush()
        location = m.Location(merchant_id=first.id, name="Main")
        product = m.Product(merchant_id=first.id, name="Shirt")
        db.add_all([location, product])
        db.flush()
        variant = m.Variant(
            merchant_id=first.id, product_id=product.id, sku="SHIRT", price_kobo=500
        )
        db.add(variant)
        db.flush()
        balance = m.Balance(
            merchant_id=first.id,
            location_id=location.id,
            variant_id=variant.id,
            on_hand=10,
            reserved=0,
            counted=True,
        )
        db.add_all(
            [
                balance,
                m.Membership(user_id=user.id, merchant_id=first.id, role="owner"),
                m.LoginSession(
                    token_hash=digest("pg-token"),
                    user_id=user.id,
                    csrf="pg-csrf",
                    expires=int(time.time()) + 3600,
                ),
                m.Movement(
                    merchant_id=first.id,
                    location_id=location.id,
                    variant_id=variant.id,
                    actor_id=user.id,
                    quantity=10,
                    reason="Opening",
                    idempotency_key="opening",
                    at=int(time.time()),
                ),
            ]
        )
        db.commit()
    return factory, first.id, second.id, location.id, variant.id, balance.id


def test_postgres_tenant_constraint_and_rollback(stock):
    factory, first, second, location, variant, _ = stock
    with factory() as db:
        db.add(
            m.Balance(
                merchant_id=second,
                location_id=location,
                variant_id=variant,
                on_hand=1,
                reserved=0,
                counted=True,
            )
        )
        with pytest.raises(IntegrityError) as caught:
            db.commit()
        assert caught.value.orig.sqlstate == "23503"
        db.rollback()
        assert db.scalar(select(func.count()).select_from(m.Balance)) == 1
        assert db.scalar(select(m.Balance.merchant_id)) == first


def test_postgres_row_lock_blocks_another_writer(migrated, stock):
    balance_id = stock[-1]
    with migrated.connect() as first, migrated.connect() as second:
        first.execute(select(m.Balance).where(m.Balance.id == balance_id).with_for_update())
        second.execute(text("SET LOCAL lock_timeout = '300ms'"))
        with pytest.raises(OperationalError) as caught:
            second.execute(select(m.Balance).where(m.Balance.id == balance_id).with_for_update())
        assert caught.value.orig.sqlstate == "55P03"
        second.rollback()
        first.rollback()
        assert second.scalar(select(m.Balance.id).with_for_update(nowait=True)) == balance_id


def test_postgres_http_stock_commit_replay_and_stale_recount(stock):
    factory, merchant, other, _, variant, _ = stock

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = session
    try:
        with TestClient(app) as client:
            client.cookies.set("kora_session", "pg-token")
            path = f"/app/{merchant}/inventory/{variant}/change"
            data = dict(
                csrf="pg-csrf", kind="adjust", key="a" * 48, quantity="2", reason="Delivery"
            )
            assert client.post(path, data=data, follow_redirects=False).status_code == 303
            assert client.post(path, data=data, follow_redirects=False).status_code == 303
            assert client.post(path, data={**data, "quantity": "3"}).status_code == 409
            stale = dict(
                csrf="pg-csrf",
                kind="recount",
                key="b" * 48,
                quantity="15",
                version="1",
                reason="Count",
            )
            assert client.post(path, data=stale).status_code == 409
            assert client.get(f"/app/{other}/inventory").status_code == 404
        with factory() as db:
            balance = db.scalar(select(m.Balance))
            assert (balance.on_hand, balance.version) == (12, 2)
            assert db.scalar(select(func.sum(m.Movement.quantity))) == 12
            assert db.scalar(select(func.count()).select_from(m.StockOperation)) == 1
    finally:
        app.dependency_overrides.pop(get_session, None)
