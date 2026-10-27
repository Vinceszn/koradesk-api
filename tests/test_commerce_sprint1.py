import csv
import io
import re

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import commerce_mail
from app import commerce_models as m
from app.commerce import app, digest, verify_password
from tests.test_commerce import client, product
from tests.test_commerce import env as env


def csrf(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def test_settings_roles_and_switcher(env):
    c = client()
    assert c.get("/businesses").status_code == 200
    assert client(3).get("/app/1/settings").status_code == 403
    assert client(2).get("/app/1/settings").status_code == 404
    r = c.post(
        "/app/1/settings",
        data=dict(
            csrf="csrf1",
            name="Renamed",
            category="Fashion",
            location="New store",
            contact_email="shop@example.com",
            phone="08012345678",
            address="Lagos",
            receipt_note="Thank you",
        ),
        follow_redirects=False,
    )
    assert r.status_code == 303
    with env() as db:
        assert db.get(m.Merchant, 1).name == "Renamed"
        assert db.get(m.Location, 1).name == "New store"
    assert "New store" in c.get("/app/1").text


def test_variant_edit_archive_export_history_and_stale_write(env):
    c = client()
    product(c)
    c.post("/app/1/stock/1", data={"csrf": "csrf1", "quantity": "8"})
    data = dict(
        csrf="csrf1",
        name="Updated shirt",
        original_name="Everyday shirt",
        version="1",
        sku="UPDATED",
        variant="Blue / L",
        price="1000.25",
    )
    assert c.post("/app/1/variants/1/edit", data=data, follow_redirects=False).status_code == 303
    assert c.post("/app/1/variants/1/edit", data=data).status_code == 409
    assert (
        client(3)
        .post("/app/1/variants/1/archive", data={"csrf": "csrf3", "action": "archive"})
        .status_code
        == 403
    )
    assert (
        client(2).post("/app/2/variants/1/edit", data=dict(data, csrf="csrf2")).status_code == 404
    )
    assert (
        c.post(
            "/app/1/variants/1/archive",
            data={"csrf": "csrf1", "action": "archive"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert "UPDATED" not in c.get("/app/1/products").text
    assert "UPDATED" in c.get("/app/1/products?archived=1").text
    assert "UPDATED" in c.get("/app/1/inventory").text
    rows = list(csv.DictReader(io.StringIO(c.get("/app/1/catalogue/export").text)))
    assert rows[0]["price"] == "1000.25" and rows[0]["archived"] == "true"
    with env() as db:
        assert db.get(m.Balance, 1).on_hand == 8
        assert db.scalar(select(func.count()).select_from(m.Movement)) == 1
    c.post("/app/1/variants/1/archive", data={"csrf": "csrf1", "action": "restore"})
    assert "UPDATED" in c.get("/app/1/products").text


def test_export_formula_escape_and_tenant(env):
    product(client(), name="=HYPERLINK(bad)", sku="+FORMULA")
    response = client().get("/app/1/catalogue/export")
    row = list(csv.DictReader(io.StringIO(response.text)))[0]
    assert row["name"].startswith("'=") and row["sku"].startswith("'+")
    assert client(3).get("/app/1/catalogue/export").status_code == 403
    assert client(2).get("/app/1/catalogue/export").status_code == 404


def test_customer_crud_and_isolation(env):
    c = client()
    data = dict(
        csrf="csrf1",
        name="Ada Customer",
        email="customer@example.com",
        phone="0801",
        notes="Pickup",
    )
    assert c.post("/app/1/customers", data=data, follow_redirects=False).status_code == 303
    assert "Ada Customer" in c.get("/app/1/customers?q=Ada").text
    assert "Ada Customer" not in c.get("/app/1/customers?q=nobody").text
    assert client(3).get("/app/1/customers").status_code == 403
    assert client(2).get("/app/2/customers/1/edit").status_code == 404
    assert c.post("/app/1/customers/1/edit", data=dict(data, archived="yes")).status_code == 200
    assert "Ada Customer" not in c.get("/app/1/customers").text
    assert "Ada Customer" in c.get("/app/1/customers?archived=1").text


def test_password_change_requires_current_and_revokes_sessions(env):
    c = client()
    assert (
        c.post(
            "/account/password",
            data=dict(csrf="csrf1", current_password="wrong", password="new-password-123"),
        ).status_code
        == 400
    )
    response = c.post(
        "/account/password",
        data=dict(
            csrf="csrf1", current_password="correct-password-123", password="new-password-123"
        ),
    )
    assert "Password updated" in response.text
    assert c.get("/app/1", follow_redirects=False).status_code == 303
    with env() as db:
        assert verify_password("new-password-123", db.get(m.User, 1).password_hash)


def test_recovery_generic_response_one_use_expiry_and_verification(env, monkeypatch):
    sent = []
    monkeypatch.setattr(commerce_mail, "configuration", lambda: ("file", "http://127.0.0.1"))
    monkeypatch.setattr(
        commerce_mail,
        "send_account_mail",
        lambda email, purpose, raw: sent.append((email, purpose, raw)),
    )
    guest = TestClient(app)

    def request(email):
        token = csrf(guest.get("/forgot-password"))
        return guest.post("/forgot-password", data={"csrf": token, "email": email})

    known = request("user1@example.com")
    unknown = request("unknown@example.com")
    assert "Check your email" in known.text and "Check your email" in unknown.text
    assert len(sent) == 1
    raw = sent[0][2]
    url = "/account/reset/" + raw
    assert (
        guest.post(url, data={"csrf": "bad", "password": "changed-password-123"}).status_code == 403
    )
    token = csrf(guest.get(url))
    assert (
        "Password updated"
        in guest.post(url, data={"csrf": token, "password": "changed-password-123"}).text
    )
    assert guest.get(url).status_code == 400
    assert client().get("/app/1", follow_redirects=False).status_code == 303
    with env() as db:
        db.add(
            m.AccountToken(
                token_hash=digest("expired"), user_id=2, purpose="reset", expires=0, used=False
            )
        )
        db.commit()
    assert guest.get("/account/reset/expired").status_code == 400
    owner2 = client(2)
    assert owner2.post("/account/verify", data={"csrf": "csrf2"}).status_code == 200
    raw = sent[-1][2]
    url = "/account/verify/" + raw
    token = csrf(guest.get(url))
    with env() as db:
        assert not db.get(m.User, 2).email_verified
    assert guest.post(url, data={"csrf": token}).status_code == 200
    with env() as db:
        assert db.get(m.User, 2).email_verified
    assert guest.get(url).status_code == 400


def test_recovery_throttle(env, monkeypatch):
    monkeypatch.setattr(commerce_mail, "configuration", lambda: ("file", "http://127.0.0.1"))
    c = TestClient(app)
    for i in range(4):
        token = csrf(c.get("/forgot-password"))
        response = c.post("/forgot-password", data={"csrf": token, "email": "nobody@example.com"})
        assert response.status_code == (200 if i < 3 else 429)


def test_mail_file_is_local_only(env, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "env", "dev")
    monkeypatch.setenv("COMMERCE_MAIL_MODE", "file")
    monkeypatch.setenv("COMMERCE_PUBLIC_URL", "http://127.0.0.1:8010")
    monkeypatch.setenv("COMMERCE_MAIL_DIRECTORY", str(tmp_path))
    commerce_mail.send_account_mail("user@example.com", "verify", "opaque-test-token")
    message = next(tmp_path.glob("*.eml")).read_text()
    assert "/account/verify/opaque-test-token" in message
    monkeypatch.setattr(settings, "env", "production")
    import pytest

    with pytest.raises(RuntimeError):
        commerce_mail.configuration()


def test_recovery_delivery_failure_does_not_expose_account(env, monkeypatch):
    monkeypatch.setattr(commerce_mail, "configuration", lambda: ("smtp", "https://shop.example"))

    def fail(*args):
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr(commerce_mail, "send_account_mail", fail)
    c = TestClient(app)
    for email in ["user1@example.com", "missing@example.com"]:
        token = csrf(c.get("/forgot-password"))
        response = c.post("/forgot-password", data={"csrf": token, "email": email})
        assert response.status_code == 200
        assert "Check your email" in response.text
    with env() as db:
        token = db.scalar(select(m.AccountToken))
        assert token.used
