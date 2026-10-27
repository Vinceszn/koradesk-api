"""Personal account management, independently scoped from merchant settings."""
import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import struct
import time
import warnings
from datetime import datetime
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from jinja2 import pass_context
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import commerce_models as m, commerce_mail
from app.db import get_session

router = APIRouter()
DEFAULTS = dict(theme="dark", sidebar="expanded", density="comfortable", timezone="Africa/Lagos",
                date_format="dmy", clock="24", language="en", landing="overview", default_business=0,
                reduced_motion=False, chart_patterns=False, product_updates=False,
                cards=["value", "units", "variants", "team"])
CHOICES = dict(theme=("dark", "light", "system"), sidebar=("expanded", "collapsed"),
               density=("comfortable", "compact"), date_format=("dmy", "mdy", "iso"),
               clock=("12", "24"), language=("en", "fr"), landing=("overview", "orders", "products", "inventory"))


def profile(db, user):
    item = db.get(m.AccountProfile, user.id)
    if item is None:
        item = m.AccountProfile(user_id=user.id)
        db.add(item)
        db.flush()
    return item


def preferences(item):
    result = dict(DEFAULTS)
    if item and item.preferences:
        result.update(json.loads(item.preferences))
    return result


def device_name(request):
    agent = request.headers.get("user-agent", "")
    browser = next((label for marker, label in [("Edg/", "Edge"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")] if marker in agent), "Browser")
    system = next((label for marker, label in [("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"), ("Macintosh", "macOS"), ("Linux", "Linux")] if marker in agent), "Unknown device")
    return f"{browser} on {system}"


def event(db, user, request, action):
    db.add(m.SecurityEvent(user_id=user.id, action=action, device=device_name(request), at=int(time.time())))


def rate_limit(db, request, user_id, purpose="sensitive", maximum=10):
    now = int(time.time())
    key = c.digest(f"account:{purpose}:{user_id}")
    if db.scalar(select(func.count()).select_from(m.LoginAttempt).where(m.LoginAttempt.key == key, m.LoginAttempt.at > now - 900)) >= maximum:
        raise HTTPException(429, "Too many attempts. Wait 15 minutes and try again.")
    db.add(m.LoginAttempt(key=key, at=now))
    db.commit()


def cipher():
    key = os.getenv("COMMERCE_ACCOUNT_KEY", "")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "Two-factor setup is unavailable. The service needs its account encryption key configured.")


def otp(secret, step, digits=6):
    raw = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = raw[-1] & 15
    value = (struct.unpack(">I", raw[offset:offset + 4])[0] & 0x7fffffff) % (10 ** digits)
    return str(value).zfill(digits)


def factor(db, item, code):
    """Atomically consume a TOTP time step or one hashed recovery code."""
    code = str(code).strip().replace(" ", "")
    if not item.totp_secret:
        return
    try:
        secret = cipher().decrypt(item.totp_secret.encode()).decode()
    except InvalidToken:
        raise HTTPException(503, "Two-factor verification is temporarily unavailable.")
    now = int(time.time()) // 30
    if len(code) == 6 and code.isdigit():
        for step in (now - 1, now, now + 1):
            if hmac.compare_digest(otp(secret, step), code):
                consumed = db.execute(update(m.AccountProfile).where(m.AccountProfile.user_id == item.user_id, m.AccountProfile.totp_last_step < step).values(totp_last_step=step))
                if consumed.rowcount == 1:
                    return
                break
    else:
        consumed = db.execute(update(m.RecoveryCode).where(m.RecoveryCode.user_id == item.user_id, m.RecoveryCode.code_hash == c.digest(code.lower()), m.RecoveryCode.used.is_(False)).values(used=True))
        if consumed.rowcount == 1:
            return
    raise HTTPException(400, "Enter an unused authenticator code or recovery code. Wait for the next code if you just used one.")


def reauthenticate(db, request, user, data):
    rate_limit(db, request, user.id)
    user = db.scalar(select(m.User).where(m.User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not c.verify_password(str(data.get("current_password", "")), user.password_hash):
        raise HTTPException(400, "Your current password was not recognised.")
    factor(db, profile(db, user), data.get("code", ""))


def landing(db, user):
    prefs = preferences(db.get(m.AccountProfile, user.id))
    member = db.scalar(select(m.Membership).where(m.Membership.user_id == user.id, m.Membership.merchant_id == prefs["default_business"]))
    if member:
        return f"/app/{member.merchant_id}" + ("" if prefs["landing"] == "overview" else "/" + prefs["landing"])
    return None


def page(request, db, tab="profile", error=None, status=200, **extra):
    user, login = c.identity(request, db)
    item = profile(db, user)
    memberships = db.execute(select(m.Merchant, m.Membership).join(m.Membership).where(m.Membership.user_id == user.id).order_by(m.Merchant.name)).all()
    pending = db.execute(select(m.Invitation, m.Merchant, m.User.name).join(m.Merchant, m.Merchant.id == m.Invitation.merchant_id).join(m.User, m.User.id == m.Invitation.invited_by).where(m.Invitation.email == user.email, m.Invitation.accepted.is_(False), m.Invitation.expires > int(time.time()))).all()
    candidates = {business.id: db.execute(select(m.Membership, m.User).join(m.User, m.User.id == m.Membership.user_id).where(m.Membership.merchant_id == business.id, m.Membership.user_id != user.id, m.User.closed.is_(False))).all() for business, member in memberships if member.role == "owner"}
    notification_settings = {row.merchant_id: row.low_stock for row in db.scalars(select(m.BusinessNotification).where(m.BusinessNotification.user_id == user.id))}
    prefs = preferences(item)
    card_order = prefs["cards"] + [key for key in DEFAULTS["cards"] if key not in prefs["cards"]]
    ctx = dict(user=user, csrf=login.csrf, account_profile=item, prefs=prefs, card_order=card_order, account_tab=tab,
               businesses=memberships, pending=pending, candidates=candidates, notification_settings=notification_settings,
               sessions=db.scalars(select(m.LoginSession).where(m.LoginSession.user_id == user.id, m.LoginSession.expires > int(time.time())).order_by(m.LoginSession.last_seen.desc())).all(),
               current_session=login.token_hash,
               events=db.scalars(select(m.SecurityEvent).where(m.SecurityEvent.user_id == user.id).order_by(m.SecurityEvent.id.desc()).limit(30)).all(),
               recovery_remaining=db.scalar(select(func.count()).select_from(m.RecoveryCode).where(m.RecoveryCode.user_id == user.id, m.RecoveryCode.used.is_(False))),
               pending_email=db.scalar(select(m.EmailChange).where(m.EmailChange.user_id == user.id, m.EmailChange.used.is_(False), m.EmailChange.expires > int(time.time()))),
               error=error, preview_mail=c.settings.env == "dev" and os.getenv("COMMERCE_MAIL_MODE") == "file", **extra)
    return c.templates.TemplateResponse(request, "account_workspace.html", ctx, status_code=status)


@router.get("/account")
def account(request: Request, db: Session = Depends(get_session)):
    tab = request.query_params.get("tab", "profile")
    return page(request, db, tab if tab in ("profile", "security", "businesses", "preferences") else "profile")


def saved(tab, message):
    return c.redirect("/account?" + urlencode(dict(tab=tab, notice=message)))


@router.post("/account/profile")
async def save_profile(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    item = profile(db, user)
    user.name = c.clean(data.get("name", ""), "Full name")
    from app.commerce_sprint1 import optional
    item.display_name = optional(data.get("display_name"), "Display name", 80)
    item.phone = optional(data.get("phone"), "Phone number", 40)
    event(db, user, request, "Profile updated")
    db.commit()
    return saved("profile", "Your profile has been saved.")


@router.get("/account/avatar")
def avatar(request: Request, db: Session = Depends(get_session)):
    user, _ = c.identity(request, db)
    item = db.get(m.AccountProfile, user.id)
    if not item or not item.avatar:
        raise HTTPException(404, "No profile photo.")
    return Response(item.avatar, media_type="image/jpeg")


@router.post("/account/avatar")
async def save_avatar(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    item = profile(db, user)
    if data.get("remove") == "yes":
        item.avatar = None
    else:
        upload = data.get("photo")
        if not hasattr(upload, "read"):
            raise HTTPException(400, "Choose a JPEG, PNG, or WebP photo under 1 MB.")
        raw = await upload.read(1_000_001)
        if len(raw) > 1_000_000:
            raise HTTPException(400, "Choose a photo under 1 MB.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in ("JPEG", "PNG", "WEBP") or image.width * image.height > 16_000_000:
                        raise ValueError()
                    image = ImageOps.fit(ImageOps.exif_transpose(image).convert("RGB"), (256, 256))
                    output = io.BytesIO()
                    image.save(output, format="JPEG", quality=88)
                    item.avatar = output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(400, "Use a valid JPEG, PNG, or WebP photo up to 16 megapixels.")
    db.commit()
    return saved("profile", "Profile photo updated.")


@router.post("/account/preferences")
async def save_preferences(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    item = profile(db, user)
    if data.get("restore") == "yes":
        item.preferences = "{}"
    else:
        prefs = preferences(item)
        for key, options in CHOICES.items():
            value = str(data.get(key, ""))
            if value not in options:
                raise HTTPException(400, "Choose one of the available preference options.")
            prefs[key] = value
        zone = str(data.get("timezone", ""))
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(400, "Choose a valid IANA time zone, such as Africa/Lagos.")
        prefs["timezone"] = zone
        for key in ("reduced_motion", "chart_patterns", "product_updates"):
            prefs[key] = data.get(key) == "yes"
        raw = str(data.get("default_business", "0"))
        if not raw.isdigit():
            raise HTTPException(400, "Choose an available business.")
        business_id = int(raw)
        if business_id and not db.scalar(select(m.Membership).where(m.Membership.user_id == user.id, m.Membership.merchant_id == business_id)):
            raise HTTPException(403, "Choose a business you belong to.")
        prefs["default_business"] = business_id
        cards = data.getlist("cards")
        if not cards or len(cards) != len(set(cards)) or any(card not in DEFAULTS["cards"] for card in cards):
            raise HTTPException(400, "Keep at least one overview card and use each card once.")
        ranks = {card: str(data.get("order_" + card, "")) for card in cards}
        if any(rank not in ("1", "2", "3", "4") for rank in ranks.values()) or len(set(ranks.values())) != len(cards):
            raise HTTPException(400, "Give each visible overview card a different position.")
        prefs["cards"] = sorted(cards, key=lambda card: int(ranks[card]))
        item.preferences = json.dumps(prefs)
    db.commit()
    return saved("preferences", "Your preferences have been saved.")


@router.post("/account/sidebar")
async def save_sidebar(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    item = profile(db, user)
    prefs = preferences(item)
    if data.get("sidebar") not in CHOICES["sidebar"]:
        raise HTTPException(400, "Choose a sidebar state.")
    prefs["sidebar"] = data["sidebar"]
    item.preferences = json.dumps(prefs)
    db.commit()
    return Response(status_code=204)


@router.post("/account/notifications/{merchant_id}")
async def notifications(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = c.workspace(request, db, merchant_id)
    data = await c.form_data(request, login.csrf)
    item = db.scalar(select(m.BusinessNotification).where(m.BusinessNotification.user_id == user.id, m.BusinessNotification.merchant_id == merchant_id))
    if item is None:
        item = m.BusinessNotification(user_id=user.id, merchant_id=merchant_id)
        db.add(item)
    item.low_stock = data.get("low_stock") == "yes"
    db.commit()
    return saved("preferences", "Notification preference saved.")


@router.post("/account/events/read")
async def read_events(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    await c.form_data(request, login.csrf)
    db.execute(update(m.SecurityEvent).where(m.SecurityEvent.user_id == user.id).values(read=True))
    db.commit()
    return saved("security", "Security notices marked as read.")


@router.post("/account/sessions/revoke")
async def revoke_sessions(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    target = str(data.get("session", ""))
    query = delete(m.LoginSession).where(m.LoginSession.user_id == user.id)
    if target == "others":
        query = query.where(m.LoginSession.token_hash != login.token_hash)
    else:
        query = query.where(m.LoginSession.token_hash == target)
    db.execute(query)
    event(db, user, request, "Sessions signed out")
    db.commit()
    return c.redirect("/login") if target == login.token_hash else saved("security", "Selected sessions have been signed out.")


@router.post("/account/email")
async def change_email(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    email = c.email_value(data.get("email", ""))
    if email == user.email or db.scalar(select(m.User.id).where(m.User.email == email)):
        raise HTTPException(409, "Choose a different available email address.")
    from app.commerce_sprint1 import throttle
    throttle(request, db, user.email)
    try:
        commerce_mail.configuration()
    except RuntimeError:
        raise HTTPException(503, "Account email is unavailable. Please try again later.")
    db.execute(update(m.EmailChange).where(m.EmailChange.user_id == user.id).values(used=True))
    raw = secrets.token_urlsafe(32)
    change = m.EmailChange(token_hash=c.digest(raw), user_id=user.id, email=email, previous_email=user.email, expires=int(time.time()) + 1800)
    db.add(change)
    db.commit()
    try:
        await run_in_threadpool(commerce_mail.send_account_mail, email, "email", raw)
        await run_in_threadpool(commerce_mail.send_security_notice, user.email, "An email address change was requested for your Kora account. Your existing address remains active until the new address is verified. If this was not you, change your password and sign out other sessions.")
    except Exception:
        change.used = True
        db.commit()
        raise HTTPException(503, "Email change could not be delivered. Your address has not changed. Please try again later.")
    event(db, user, request, "Email change requested")
    db.commit()
    return saved("profile", "Verification sent to your new address. Your current address remains active until you confirm it.")


@router.post("/account/email/cancel")
async def cancel_email(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    await c.form_data(request, login.csrf)
    db.execute(update(m.EmailChange).where(m.EmailChange.user_id == user.id).values(used=True))
    db.commit()
    return saved("profile", "Pending email change cancelled.")


@router.get("/account/email-confirm/{raw}")
def email_confirmation(request: Request, raw: str, db: Session = Depends(get_session)):
    change = db.get(m.EmailChange, c.digest(raw))
    if not change or change.used or change.expires <= int(time.time()):
        raise HTTPException(400, "This email change link has expired or has already been used.")
    from app.commerce_sprint1 import account_page
    return account_page(request, "email-confirm", target_email=change.email)


@router.post("/account/email-confirm/{raw}")
async def confirm_email(request: Request, raw: str, db: Session = Depends(get_session)):
    data = await c.form_data(request, request.cookies.get("kora_form", ""))
    change = db.get(m.EmailChange, c.digest(raw))
    if not change or change.used or change.expires <= int(time.time()):
        raise HTTPException(400, "This email change link has expired or has already been used.")
    user = db.scalar(select(m.User).where(m.User.id == change.user_id).with_for_update())
    if user.closed or user.email != change.previous_email:
        raise HTTPException(409, "This request is no longer valid.")
    reauthenticate(db, request, user, data)
    consumed = db.execute(update(m.EmailChange).where(m.EmailChange.token_hash == change.token_hash, m.EmailChange.used.is_(False), m.EmailChange.expires > int(time.time())).values(used=True))
    if consumed.rowcount != 1:
        raise HTTPException(409, "This request was already completed.")
    if db.scalar(select(m.User.id).where(m.User.email == change.email)):
        raise HTTPException(409, "This email address is no longer available. Request another change.")
    # Delivery to the previous address must succeed before applying the change.
    try:
        await run_in_threadpool(commerce_mail.send_security_notice, user.email, "Your Kora account email address is being changed after verification. Existing sessions will be signed out. If this was not you, contact support using your established support channel.")
    except Exception:
        raise HTTPException(503, "Security notification could not be delivered. Your address has not changed. Try again later.")
    db.execute(update(m.Invitation).where(m.Invitation.email == user.email, m.Invitation.accepted.is_(False)).values(expires=0))
    user.email, user.email_verified = change.email, True
    db.execute(update(m.EmailChange).where(m.EmailChange.user_id == user.id).values(used=True))
    db.execute(update(m.AccountToken).where(m.AccountToken.user_id == user.id).values(used=True))
    db.execute(delete(m.LoginSession).where(m.LoginSession.user_id == user.id))
    event(db, user, request, "Email address changed")
    db.commit()
    from app.commerce_sprint1 import account_page
    response = account_page(request, "email-done")
    response.delete_cookie("kora_session")
    return response


@router.post("/account/two-factor/setup")
async def setup_factor(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    item = profile(db, user)
    if item.totp_secret:
        raise HTTPException(409, "Two-factor authentication is already enabled.")
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    item.totp_pending = cipher().encrypt(secret.encode()).decode()
    item.totp_pending_expires = int(time.time()) + 600
    db.commit()
    return page(request, db, "security", setup_secret=secret,
                setup_uri="otpauth://totp/" + quote("Kora Desk:" + user.email, safe="") + "?" + urlencode(dict(secret=secret, issuer="Kora Desk", algorithm="SHA1", digits=6, period=30)))


@router.get("/account/two-factor/qr")
def factor_qr(request: Request, db: Session = Depends(get_session)):
    user, _ = c.identity(request, db)
    item = profile(db, user)
    if not item.totp_pending or item.totp_pending_expires <= int(time.time()) or item.totp_secret:
        raise HTTPException(404, "Start two-factor setup again.")
    secret = cipher().decrypt(item.totp_pending.encode()).decode()
    import qrcode
    import qrcode.image.svg
    uri = "otpauth://totp/" + quote("Kora Desk:" + user.email, safe="") + "?" + urlencode(dict(secret=secret, issuer="Kora Desk", algorithm="SHA1", digits=6, period=30))
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    output = io.BytesIO()
    image.save(output)
    return Response(output.getvalue(), media_type="image/svg+xml")


def new_recovery_codes(db, user):
    db.execute(delete(m.RecoveryCode).where(m.RecoveryCode.user_id == user.id))
    codes = [secrets.token_hex(5) + "-" + secrets.token_hex(5) for _ in range(8)]
    for code in codes:
        db.add(m.RecoveryCode(user_id=user.id, code_hash=c.digest(code)))
    return codes


@router.post("/account/two-factor/enable")
async def enable_factor(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    item = profile(db, user)
    if item.totp_secret or not item.totp_pending or item.totp_pending_expires <= int(time.time()):
        raise HTTPException(400, "Setup expired. Start two-factor setup again.")
    secret = cipher().decrypt(item.totp_pending.encode()).decode()
    now = int(time.time()) // 30
    step = next((step for step in (now - 1, now, now + 1) if hmac.compare_digest(otp(secret, step), str(data.get("code", "")).strip())), None)
    if step is None:
        raise HTTPException(400, "The authenticator code was not recognised. Start setup again if it has expired.")
    item.totp_secret, item.totp_pending = item.totp_pending, ""
    item.totp_pending_expires, item.totp_last_step = 0, step
    codes = new_recovery_codes(db, user)
    db.execute(delete(m.LoginSession).where(m.LoginSession.user_id == user.id, m.LoginSession.token_hash != login.token_hash))
    db.execute(update(m.AccountToken).where(m.AccountToken.user_id == user.id).values(used=True))
    event(db, user, request, "Two-factor authentication enabled")
    db.commit()
    return page(request, db, "security", recovery_codes=codes)


@router.post("/account/two-factor/recovery")
async def regenerate_codes(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    if not profile(db, user).totp_secret:
        raise HTTPException(400, "Enable two-factor authentication first.")
    codes = new_recovery_codes(db, user)
    event(db, user, request, "Recovery codes replaced")
    db.commit()
    return page(request, db, "security", recovery_codes=codes)


@router.post("/account/two-factor/disable")
async def disable_factor(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    item = profile(db, user)
    item.totp_secret, item.totp_pending, item.totp_last_step = "", "", -1
    db.execute(delete(m.RecoveryCode).where(m.RecoveryCode.user_id == user.id))
    event(db, user, request, "Two-factor authentication disabled")
    db.commit()
    return saved("security", "Two-factor authentication disabled.")


@router.post("/account/businesses/{merchant_id}/leave")
async def leave_business(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    user, login, member, _ = c.workspace(request, db, merchant_id)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    db.scalar(select(m.Merchant).where(m.Merchant.id == merchant_id).with_for_update())
    db.refresh(member)
    if member.role == "owner":
        raise HTTPException(409, "Transfer ownership before leaving this business.")
    db.delete(member)
    db.execute(delete(m.BusinessNotification).where(m.BusinessNotification.user_id == user.id, m.BusinessNotification.merchant_id == merchant_id))
    event(db, user, request, "Business access removed")
    db.commit()
    return saved("businesses", "You have left the business. Its records are preserved.")


@router.post("/account/businesses/{merchant_id}/transfer")
async def transfer_business(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    user, login, member, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    db.scalar(select(m.Merchant).where(m.Merchant.id == merchant_id).with_for_update())
    db.refresh(member)
    if member.role != "owner":
        raise HTTPException(409, "Ownership has already changed.")
    recipient = str(data.get("recipient", ""))
    target = db.scalar(select(m.Membership).where(m.Membership.merchant_id == merchant_id, m.Membership.user_id == int(recipient))) if recipient.isdigit() else None
    target_user = db.get(m.User, target.user_id) if target else None
    if target_user:
        target_user = db.scalar(select(m.User).where(m.User.id == target_user.id).with_for_update().execution_options(populate_existing=True))
    if not target or target.user_id == user.id or target_user.closed or not target_user.email_verified:
        raise HTTPException(400, "Choose an active teammate with a verified email address.")
    if data.get("confirmation") != "TRANSFER":
        raise HTTPException(400, "Type TRANSFER to confirm the ownership change.")
    member.role, target.role = "staff", "owner"
    event(db, user, request, "Business ownership transferred")
    event(db, target_user, request, "Business ownership received")
    db.commit()
    return saved("businesses", "Ownership transferred. Your access is now read only.")


@router.post("/account/invitations/{invitation_id}/{action}")
async def account_invitation(request: Request, invitation_id: int, action: str, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    await c.form_data(request, login.csrf)
    invitation = db.scalar(select(m.Invitation).where(m.Invitation.id == invitation_id).with_for_update())
    if not invitation or invitation.email != user.email or invitation.accepted or invitation.expires <= int(time.time()):
        raise HTTPException(404, "Invitation unavailable.")
    if action == "accept":
        if not user.email_verified:
            raise HTTPException(403, "Verify your email before accepting invitations from your account page.")
        member = db.scalar(select(m.Membership).where(m.Membership.user_id == user.id, m.Membership.merchant_id == invitation.merchant_id))
        if not member:
            db.add(m.Membership(user_id=user.id, merchant_id=invitation.merchant_id, role="staff"))
        invitation.accepted = True
    elif action == "decline":
        invitation.expires = 0
    else:
        raise HTTPException(404, "Action unavailable.")
    event(db, user, request, "Business invitation " + ("accepted" if action == "accept" else "declined"))
    db.commit()
    return saved("businesses", "Invitation " + ("accepted." if action == "accept" else "declined."))


@router.post("/account/export")
async def export_account(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    item = profile(db, user)
    result = dict(exported_at=int(time.time()), profile=dict(id=user.id, name=user.name, email=user.email,
        email_verified=user.email_verified, created_at=user.created_at or None, display_name=item.display_name,
        phone=item.phone, photo_base64=base64.b64encode(item.avatar).decode() if item.avatar else None), preferences=preferences(item))
    result["business_access"] = [dict(business_id=business.id, business_name=business.name, role=member.role) for business, member in db.execute(select(m.Merchant, m.Membership).join(m.Membership).where(m.Membership.user_id == user.id))]
    result["notifications"] = [dict(business_id=row.merchant_id, low_stock=row.low_stock) for row in db.scalars(select(m.BusinessNotification).where(m.BusinessNotification.user_id == user.id))]
    result["security_activity"] = [dict(action=row.action, at=row.at, device=row.device) for row in db.scalars(select(m.SecurityEvent).where(m.SecurityEvent.user_id == user.id).order_by(m.SecurityEvent.id))]
    result["invitations"] = [dict(business_id=row.merchant_id, expires=row.expires, accepted=row.accepted) for row in db.scalars(select(m.Invitation).where(m.Invitation.email == user.email))]
    event(db, user, request, "Personal data exported")
    db.commit()
    return Response(json.dumps(result, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="kora-personal-data.json"'})


@router.post("/account/close")
async def close_account(request: Request, db: Session = Depends(get_session)):
    user, login = c.identity(request, db)
    data = await c.form_data(request, login.csrf)
    reauthenticate(db, request, user, data)
    if db.scalar(select(m.Membership.id).where(m.Membership.user_id == user.id, m.Membership.role == "owner")):
        raise HTTPException(409, "Transfer ownership of every business before closing your account.")
    if data.get("confirmation") != "CLOSE MY ACCOUNT":
        raise HTTPException(400, "Type CLOSE MY ACCOUNT to confirm.")
    db.execute(delete(m.Invitation).where(m.Invitation.email == user.email))
    for model in (m.LoginSession, m.AccountToken, m.EmailChange, m.RecoveryCode, m.BusinessNotification, m.Membership, m.SecurityEvent, m.AccountProfile):
        db.execute(delete(model).where(model.user_id == user.id))
    # Retain an anonymous actor ID so immutable stock records keep their FK.
    user.name, user.email = "Closed account", f"closed-{user.id}-{secrets.token_hex(8)}@account.invalid"
    user.password_hash, user.email_verified, user.closed = c.hash_password(secrets.token_urlsafe(48)), False, True
    user.created_at = 0
    db.commit()
    response = c.redirect("/login?notice=Account+closed.+Business+records+have+been+preserved.")
    response.delete_cookie("kora_session")
    return response


def personal_context(request):
    user = getattr(request.state, "account_user", None)
    db = getattr(request.state, "account_db", None)
    item = db.get(m.AccountProfile, user.id) if user and db else None
    ctx = dict(prefs=preferences(item), display_name=(item.display_name if item else "") or (user.name if user else ""), has_avatar=bool(item and item.avatar))
    parts = request.url.path.split("/")
    if user and len(parts) > 2 and parts[1] == "app" and parts[2].isdigit():
        notification = db.scalar(select(m.BusinessNotification).where(m.BusinessNotification.user_id == user.id, m.BusinessNotification.merchant_id == int(parts[2])))
        ctx["show_low_stock"] = notification.low_stock if notification else True
    return ctx


@pass_context
def account_date(context, value):
    prefs = context.get("prefs", DEFAULTS)
    try:
        zone = ZoneInfo(prefs["timezone"])
    except (ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo("UTC")
    pattern = {"dmy": "%d/%m/%Y", "mdy": "%m/%d/%Y", "iso": "%Y-%m-%d"}.get(prefs["date_format"], "%d/%m/%Y")
    pattern += " · %I:%M %p" if prefs["clock"] == "12" else " · %H:%M"
    return datetime.fromtimestamp(value, zone).strftime(pattern) + " " + prefs["timezone"]


# Import the shared application after declaring routes so either module can be
# imported first (including direct test imports) without a partial router.
from app import commerce as c
c.templates.context_processors.append(personal_context)
c.templates.env.filters["date"] = account_date
