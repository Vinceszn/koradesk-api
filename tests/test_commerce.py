"""Exercise HTTP authorization and transactions, not just rendered controls."""

import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import commerce_models as m
from app.commerce import app, digest, hash_password
from app.db import Base, get_session


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = session
    with factory() as db:
        for i in (1, 2, 3):
            db.add(
                m.User(
                    id=i,
                    name=f"User {i}",
                    email=f"user{i}@example.com",
                    password_hash=hash_password("correct-password-123"),
                )
            )
        db.flush()
        for i in (1, 2):
            db.add(m.Merchant(id=i, name=f"Business {i}", category="Retail"))
        db.flush()
        for i in (1, 2):
            db.add(m.Location(id=i, merchant_id=i, name="Main shop"))
            db.add(m.Membership(merchant_id=i, user_id=i, role="owner"))
        db.add(m.Membership(merchant_id=1, user_id=3, role="staff"))
        for i in (1, 2, 3):
            db.add(
                m.LoginSession(
                    token_hash=digest(f"token{i}"),
                    user_id=i,
                    csrf=f"csrf{i}",
                    expires=int(time.time()) + 3600,
                )
            )
        db.commit()
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def client(user=1):
    result = TestClient(app)
    result.cookies.set("kora_session", f"token{user}")
    return result


def product(c, **kw):
    data = dict(
        csrf="csrf1", name="Everyday shirt", sku="SHIRT-M", variant="Olive / M", price="8500.25"
    )
    data.update(kw)
    return c.post("/app/1/products", data=data, follow_redirects=False)


def test_unauthenticated_and_tenant_boundaries(env):
    assert TestClient(app).get("/app/1", follow_redirects=False).status_code == 303
    c = client(2)
    for page in ("", "/products", "/inventory", "/team"):
        assert c.get("/app/1" + page).status_code == 404
    assert c.post("/app/1/products", data={"csrf": "csrf2"}).status_code == 404
    assert c.post("/app/1/stock/1", data={"csrf": "csrf2", "quantity": "10"}).status_code == 404


def test_staff_can_read_but_cannot_mutate(env):
    c = client(3)
    assert c.get("/app/1/products").status_code == 200
    for path in ("products", "import", "stock/1", "invite", "members/1/remove", "invites/1/revoke"):
        assert c.post("/app/1/" + path, data={"csrf": "csrf3"}).status_code == 403


def test_csrf_and_origin_enforced(env):
    c = client()
    assert c.get("/login").headers["referrer-policy"] == "same-origin"
    assert product(c, csrf="wrong").status_code == 403
    assert (
        c.post(
            "/app/1/products",
            data={"csrf": "csrf1"},
            headers={"origin": "https://untrusted.example"},
        ).status_code
        == 403
    )


def test_product_opening_count_and_retry(env):
    c = client()
    assert product(c).status_code == 303
    with env() as db:
        variant = db.scalar(select(m.Variant))
        assert variant.price_kobo == 850025
        variant_id = variant.id
    path = f"/app/1/stock/{variant_id}"
    assert (
        c.post(path, data={"csrf": "csrf1", "quantity": "12"}, follow_redirects=False).status_code
        == 303
    )
    assert c.post(path, data={"csrf": "csrf1", "quantity": "99"}).status_code == 409
    with env() as db:
        balance = db.scalar(select(m.Balance))
        assert balance.on_hand == 12 and balance.reserved == 0
        movement = db.scalar(select(m.Movement))
        assert movement.quantity == 12 and movement.actor_id == 1
        assert db.scalar(select(func.count()).select_from(m.Movement)) == 1
    assert "Recorded" in c.get("/app/1/inventory").text


def test_variant_id_cannot_cross_tenants(env):
    c = client()
    product(c)
    # Owner of business 2 must not mutate a business 1 variant through their URL.
    assert (
        client(2).post("/app/2/stock/1", data={"csrf": "csrf2", "quantity": "10"}).status_code
        == 404
    )


@pytest.mark.parametrize("price", ["-1", "0.001", "NaN", "Infinity", "20000001"])
def test_prices_are_server_validated(env, price):
    assert product(client(), price=price).status_code == 400


def test_csv_rollback_on_duplicate_or_invalid_row(env):
    c = client()
    for csv in (
        "name,variant,sku,price\nShirt,M,SKU1,100\nShirt,L,SKU1,200\n",
        "name,variant,sku,price\nShirt,M,SKU1,100\nShirt,L,SKU2,-5\n",
    ):
        response = c.post(
            "/app/1/import",
            data={"csrf": "csrf1"},
            files={"file": ("products.csv", csv, "text/csv")},
        )
        assert response.status_code in (400, 409)
        with env() as db:
            assert db.scalar(select(func.count()).select_from(m.Variant)) == 0
            assert db.scalar(select(func.count()).select_from(m.Product)) == 0


def test_csv_success_and_empty_state(env):
    c = client()
    assert "Your next chapter" in c.get("/app/1/products").text
    response = c.post(
        "/app/1/import",
        data={"csrf": "csrf1"},
        files={
            "file": (
                "products.csv",
                "name,variant,sku,price\nShirt,M,SKU1,100\nShirt,L,SKU2,200\n",
                "text/csv",
            )
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Product)) == 1
        assert db.scalar(select(func.count()).select_from(m.Variant)) == 2


def test_invite_bound_to_email_and_one_use(env):
    owner = client()
    response = owner.post("/app/1/invite", data={"csrf": "csrf1", "email": "user2@example.com"})
    token = re.search(r"/invite/([A-Za-z0-9_-]+)", response.text).group(1)
    assert owner.post(f"/invite/{token}", data={"csrf": "csrf1"}).status_code == 403
    staff = client(2)
    assert (
        staff.post(f"/invite/{token}", data={"csrf": "csrf2"}, follow_redirects=False).status_code
        == 303
    )
    assert staff.post(f"/invite/{token}", data={"csrf": "csrf2"}).status_code == 404
    assert staff.get("/app/1").status_code == 200
    assert staff.post("/app/1/products", data={"csrf": "csrf2"}).status_code == 403


def test_revocation_removes_access(env):
    with env() as db:
        member_id = db.scalar(select(m.Membership.id).where(m.Membership.user_id == 3))
    assert (
        client()
        .post(f"/app/1/members/{member_id}/remove", data={"csrf": "csrf1"}, follow_redirects=False)
        .status_code
        == 303
    )
    assert client(3).get("/app/1").status_code == 404


def test_signup_business_and_logout(env):
    c = TestClient(app)
    c.get("/register")
    response = c.post(
        "/register",
        data={
            "csrf": c.cookies.get("kora_form"),
            "name": "New owner",
            "email": "new@example.com",
            "password": "a-long-new-password",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = c.get("/")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = c.post(
        "/business/new",
        data={"csrf": csrf, "name": "New shop", "category": "Retail", "location": "Ikeja"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "New shop" in c.get(response.headers["location"]).text
    assert c.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert c.get("/", follow_redirects=False).headers["location"] == "/login"


def test_database_rejects_cross_merchant_relationship(env):
    from sqlalchemy.exc import IntegrityError

    product(client())
    with env() as db:
        db.add(m.Balance(merchant_id=2, location_id=2, variant_id=1, on_hand=50, reserved=0))
        with pytest.raises(IntegrityError):
            db.commit()


def test_oversized_request_is_rejected(env):
    assert client().post("/app/1/import", content=b"x" * 2_000_001).status_code == 413


def test_wrong_password_and_expired_session(env):
    c = TestClient(app)
    c.get("/login")
    assert (
        c.post(
            "/login",
            data={
                "csrf": c.cookies.get("kora_form"),
                "email": "user1@example.com",
                "password": "wrong-password-123",
            },
        ).status_code
        == 400
    )
    with env() as db:
        login = db.get(m.LoginSession, digest("token1"))
        login.expires = 0
        db.commit()
    assert client().get("/app/1", follow_redirects=False).status_code == 303
