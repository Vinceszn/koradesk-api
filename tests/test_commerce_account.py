import io
import json
import re
import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, func

from app import commerce_account as a, commerce_mail, commerce_models as m
from app.commerce import app, digest
from tests.test_commerce import env, client, product

PASSWORD = "correct-password-123"


def post(c, path, **data):
    return c.post(path, data=dict(csrf="csrf1", **data), follow_redirects=False)


def pref_data(**overrides):
    result = dict(a.DEFAULTS, csrf="csrf1", order_value="1", order_units="2", order_variants="3", order_team="4")
    result.update(overrides)
    for key in ("reduced_motion", "chart_patterns", "product_updates"):
        result[key] = "yes" if result[key] else "no"
    return result


def enable(c, env, monkeypatch):
    monkeypatch.setenv("COMMERCE_ACCOUNT_KEY", Fernet.generate_key().decode())
    setup = post(c, "/account/two-factor/setup", current_password=PASSWORD)
    assert setup.status_code == 200
    assert c.get("/account/two-factor/qr").headers["content-type"].startswith("image/svg+xml")
    with env() as db:
        item = db.get(m.AccountProfile, 1)
        secret = a.cipher().decrypt(item.totp_pending.encode()).decode()
    code = a.otp(secret, int(time.time()) // 30)
    response = post(c, "/account/two-factor/enable", current_password=PASSWORD, code=code)
    assert response.status_code == 200
    codes = re.findall(r"<code>([0-9a-f-]+)</code>", response.text)
    assert len(codes) == 8
    return secret, codes


def test_account_profile_photo_and_validation(env):
    c = client()
    assert all(c.get("/account?tab=" + tab).status_code == 200 for tab in ("profile", "security", "businesses", "preferences"))
    assert post(c, "/account/profile", name="Ada Okafor", display_name="Ada", phone="+2348012345678").status_code == 303
    assert "Ada Okafor" in c.get("/account").text
    assert post(c, "/account/profile", name="", display_name="x").status_code == 400
    image = Image.new("RGB", (50, 90), "red")
    source = io.BytesIO()
    image.save(source, "PNG")
    assert c.post("/account/avatar", data={"csrf": "csrf1"}, files={"photo": ("photo.png", source.getvalue(), "image/png")}, follow_redirects=False).status_code == 303
    assert c.get("/account/avatar").headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(c.get("/account/avatar").content)) as result:
        assert result.size == (256, 256)
    assert c.post("/account/avatar", data={"csrf": "csrf1"}, files={"photo": ("bad.svg", b"<svg></svg>", "image/svg+xml")}).status_code == 400
    assert c.post("/account/avatar", data={"csrf": "csrf1"}, files={"photo": ("huge.jpg", b"x" * 1_000_001, "image/jpeg")}).status_code == 400
    assert client(2).get("/account/avatar").status_code == 404
    assert post(c, "/account/avatar", remove="yes").status_code == 303
    assert c.get("/account/avatar").status_code == 404


def test_preferences_persist_validate_and_respect_membership(env):
    c = client()
    data = pref_data(theme="light", density="compact", sidebar="collapsed", timezone="America/New_York", date_format="iso", clock="12", landing="inventory", default_business=1, cards=["units", "value"], order_units="1", order_value="2", reduced_motion=True, chart_patterns=True)
    assert c.post("/account/preferences", data=data, follow_redirects=False).status_code == 303
    page = client().get("/app/1")
    assert 'data-theme="light"' in page.text and 'data-density="compact"' in page.text
    assert 'data-cards="units,value"' in page.text and 'data-motion="reduced"' in page.text
    assert client().get("/", follow_redirects=False).headers["location"] == "/app/1/inventory"
    assert c.post("/account/preferences", data=pref_data(default_business=2)).status_code == 403
    assert c.post("/account/preferences", data=pref_data(timezone="Not/AZone")).status_code == 400
    assert c.post("/account/preferences", data=pref_data(theme="injected")).status_code == 400
    assert c.post("/account/preferences", data=pref_data(cards=[])).status_code == 400
    assert c.post("/account/preferences", data=pref_data(order_units="1")).status_code == 400
    assert post(c, "/account/sidebar", sidebar="expanded").status_code == 204
    with env() as db:
        assert a.preferences(db.get(m.AccountProfile, 1))["sidebar"] == "expanded"
    assert post(c, "/account/preferences", restore="yes").status_code == 303
    assert 'data-theme="dark"' in c.get("/account").text


def test_notifications_are_personal_and_tenant_scoped(env):
    c = client()
    product(c)
    c.post("/app/1/stock/1", data={"csrf": "csrf1", "quantity": "0"})
    assert "Review low stock" in c.get("/app/1").text
    assert post(c, "/account/notifications/1").status_code == 303
    assert "Review low stock" not in c.get("/app/1").text
    assert "Review low stock" in client(3).get("/app/1").text
    assert post(c, "/account/notifications/2", low_stock="yes").status_code == 404


def test_sessions_revoke_only_self_and_log_activity(env):
    c = client()
    with env() as db:
        db.add(m.LoginSession(token_hash=digest("extra"), user_id=1, csrf="extra-csrf", expires=int(time.time()) + 3600))
        db.commit()
    assert post(c, "/account/sessions/revoke", session="others", current_password="wrong").status_code == 400
    assert post(c, "/account/sessions/revoke", session=digest("token2"), current_password=PASSWORD).status_code == 303
    assert client(2).get("/account").status_code == 200
    assert post(c, "/account/sessions/revoke", session="others", current_password=PASSWORD).status_code == 303
    other = TestClient(app)
    other.cookies.set("kora_session", "extra")
    assert other.get("/account", follow_redirects=False).headers["location"] == "/login"
    assert "Sessions signed out" in c.get("/account?tab=security").text
    assert post(c, "/account/events/read").status_code == 303
    with env() as db:
        assert all(row.read for row in db.scalars(select(m.SecurityEvent).where(m.SecurityEvent.user_id == 1)))


def test_email_change_verification_revocation_and_replay(env, monkeypatch):
    sent, notices = [], []
    monkeypatch.setattr(commerce_mail, "configuration", lambda: ("file", "http://127.0.0.1"))
    monkeypatch.setattr(commerce_mail, "send_account_mail", lambda email, purpose, raw: sent.append((email, purpose, raw)))
    monkeypatch.setattr(commerce_mail, "send_security_notice", lambda email, text: notices.append(email))
    c = client()
    assert post(c, "/account/email", email="new@example.com", current_password=PASSWORD).status_code == 303
    raw = sent[0][2]
    with env() as db:
        assert db.get(m.User, 1).email == "user1@example.com"
    guest = TestClient(app)
    response = guest.get("/account/email-confirm/" + raw)
    assert response.status_code == 200
    data = dict(csrf=guest.cookies.get("kora_form"), current_password=PASSWORD)
    assert guest.post("/account/email-confirm/" + raw, data=data).status_code == 200
    assert guest.get("/account/email-confirm/" + raw).status_code == 400
    assert c.get("/account", follow_redirects=False).headers["location"] == "/login"
    assert notices == ["user1@example.com", "user1@example.com"]
    with env() as db:
        assert db.get(m.User, 1).email == "new@example.com" and db.get(m.User, 1).email_verified


def test_email_change_failure_cancel_and_uniqueness(env, monkeypatch):
    c = client()
    assert post(c, "/account/email", email="user2@example.com", current_password=PASSWORD).status_code == 409
    monkeypatch.setattr(commerce_mail, "configuration", lambda: ("file", "http://127.0.0.1"))
    def fail(*args):
        raise RuntimeError("delivery failed")
    monkeypatch.setattr(commerce_mail, "send_account_mail", fail)
    assert post(c, "/account/email", email="new@example.com", current_password=PASSWORD).status_code == 503
    with env() as db:
        assert db.get(m.User, 1).email == "user1@example.com"
        assert all(row.used for row in db.scalars(select(m.EmailChange)))
    monkeypatch.setattr(commerce_mail, "send_account_mail", lambda *args: None)
    monkeypatch.setattr(commerce_mail, "send_security_notice", lambda *args: None)
    assert post(c, "/account/email", email="new@example.com", current_password=PASSWORD).status_code == 303
    assert post(c, "/account/email/cancel").status_code == 303
    with env() as db:
        assert all(row.used for row in db.scalars(select(m.EmailChange)))


def test_totp_rfc_vector_and_recovery_login(env, monkeypatch):
    import base64
    assert a.otp(base64.b32encode(b"12345678901234567890").decode(), 59 // 30, digits=8) == "94287082"
    c = client()
    secret, codes = enable(c, env, monkeypatch)
    with env() as db:
        item = db.get(m.AccountProfile, 1)
        assert secret not in item.totp_secret and item.totp_pending == ""
        assert db.scalar(select(func.count()).select_from(m.RecoveryCode)) == 8
    guest = TestClient(app)
    guest.get("/login")
    data = dict(csrf=guest.cookies.get("kora_form"), email="user1@example.com", password=PASSWORD)
    assert guest.post("/login", data=data, follow_redirects=False).status_code == 400
    assert guest.post("/login", data=dict(data, code=codes[0]), follow_redirects=False).status_code == 303
    another = TestClient(app)
    another.get("/login")
    data["csrf"] = another.cookies.get("kora_form")
    assert another.post("/login", data=dict(data, code=codes[0]), follow_redirects=False).status_code == 400
    assert post(c, "/account/two-factor/disable", current_password=PASSWORD, code=codes[1]).status_code == 303
    with env() as db:
        assert not db.get(m.AccountProfile, 1).totp_secret
        assert db.scalar(select(func.count()).select_from(m.RecoveryCode)) == 0


def test_two_factor_password_recovery_cannot_bypass_factor(env, monkeypatch):
    c = client()
    _, codes = enable(c, env, monkeypatch)
    with env() as db:
        db.add(m.AccountToken(token_hash=digest("reset-factor"), user_id=1, purpose="reset", expires=int(time.time()) + 900, used=False))
        db.commit()
    guest = TestClient(app)
    guest.get("/account/reset/reset-factor")
    data = dict(csrf=guest.cookies.get("kora_form"), password="new-correct-password-123")
    assert guest.post("/account/reset/reset-factor", data=data).status_code == 400
    with env() as db:
        assert not db.get(m.AccountToken, digest("reset-factor")).used
    assert guest.post("/account/reset/reset-factor", data=dict(data, code=codes[0])).status_code == 200
    with env() as db:
        assert db.get(m.AccountProfile, 1).totp_secret
        assert db.scalar(select(func.count()).select_from(m.LoginSession).where(m.LoginSession.user_id == 1)) == 0


def test_business_transfer_leave_and_closure_preserve_stock(env):
    owner = client()
    product(owner)
    owner.post("/app/1/stock/1", data={"csrf": "csrf1", "quantity": "5"})
    assert post(owner, "/account/close", current_password=PASSWORD, confirmation="CLOSE MY ACCOUNT").status_code == 409
    assert post(owner, "/account/businesses/1/leave", current_password=PASSWORD).status_code == 409
    assert post(owner, "/account/businesses/1/transfer", recipient="2", current_password=PASSWORD, confirmation="TRANSFER").status_code == 400
    with env() as db:
        db.get(m.User, 3).email_verified = True
        db.commit()
    assert post(owner, "/account/businesses/1/transfer", recipient="3", current_password=PASSWORD, confirmation="TRANSFER").status_code == 303
    assert owner.post("/app/1/products", data={"csrf": "csrf1"}).status_code == 403
    assert post(owner, "/account/businesses/1/leave", current_password=PASSWORD).status_code == 303
    assert owner.get("/app/1").status_code == 404
    assert client(3).post("/app/1/invite", data={"csrf":"csrf3", "email":"user1@example.com"}).status_code == 200
    assert post(owner, "/account/close", current_password=PASSWORD, confirmation="CLOSE MY ACCOUNT").status_code == 303
    with env() as db:
        assert db.get(m.User, 1).closed and db.get(m.User, 1).name == "Closed account"
        assert db.scalar(select(m.Movement)).actor_id == 1
        assert db.get(m.Balance, 1).on_hand == 5
        assert db.scalar(select(func.count()).select_from(m.Invitation).where(m.Invitation.email == "user1@example.com")) == 0
    assert client(3).get("/app/1/settings").status_code == 200


def test_invitation_decisions_and_export_exclude_secrets(env):
    owner = client()
    owner.post("/app/1/invite", data={"csrf": "csrf1", "email": "user2@example.com"})
    second = client(2)
    with env() as db:
        invitation_id = db.scalar(select(m.Invitation.id))
        db.get(m.User, 2).email_verified = True
        db.commit()
    assert post(owner, f"/account/invitations/{invitation_id}/accept").status_code == 404
    assert second.post(f"/account/invitations/{invitation_id}/accept", data={"csrf": "csrf2"}, follow_redirects=False).status_code == 303
    assert second.post(f"/account/invitations/{invitation_id}/accept", data={"csrf": "csrf2"}).status_code == 404
    response = post(owner, "/account/export", current_password=PASSWORD)
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    result = response.json()
    assert result["profile"]["email"] == "user1@example.com"
    assert [row["business_id"] for row in result["business_access"]] == [1]
    assert all(secret not in response.text for secret in ("password_hash", "totp_secret", "csrf1", digest("token1"), "user2@example.com"))


def test_account_actions_require_csrf_and_origin(env):
    c = client()
    assert c.post("/account/profile", data={"csrf": "bad", "name": "Changed"}).status_code == 403
    assert c.post("/account/profile", data={"csrf": "csrf1", "name": "Changed"}, headers={"origin": "https://other.example"}).status_code == 403
    with env() as db:
        assert db.get(m.User, 1).name == "User 1"
