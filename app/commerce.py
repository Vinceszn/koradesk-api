"""Merchant application. Isolated entrypoint: no legacy admin or WhatsApp jobs."""
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app import commerce_models as m

ROOT = Path(__file__).parent
app = FastAPI(title="Kora merchant workspace")
app.mount("/assets", StaticFiles(directory=ROOT / "static"), name="assets")
templates = Jinja2Templates(directory=ROOT / "templates" / "commerce")
templates.env.filters["money"] = lambda value: f"₦{value / 100:,.2f}"
templates.env.filters["date"] = lambda value: datetime.fromtimestamp(value, timezone.utc).strftime("%d %b %Y, %H:%M UTC")


class RequestSizeLimit:
    """Bound multipart bodies even when Content-Length is absent."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 2_000_000:
                return await Response("Upload too large. Keep uploaded files under 1 MB.", status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)


app.add_middleware(RequestSizeLimit)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password):
    salt = secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ":" + key.hex()


def verify_password(password, stored):
    salt, expected = stored.split(":")
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(key.hex(), expected)


def clean(value, label, maximum=120):
    value = str(value).strip()
    if not value or len(value) > maximum:
        raise HTTPException(400, f"{label} is required and must be at most {maximum} characters.")
    return value


def email_value(value):
    value = clean(value, "Email", 254).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise HTTPException(400, "Enter a valid email address.")
    return value


def price_value(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 20000000 or amount * 100 != (amount * 100).to_integral_value():
            raise ValueError()
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "Price must be between ₦0 and ₦20,000,000, with at most two decimal places.")


def quantity_value(value):
    if not re.fullmatch(r"\d{1,7}", str(value)):
        raise HTTPException(400, "Opening stock must be a whole number between 0 and 1,000,000.")
    quantity = int(value)
    if quantity > 1000000:
        raise HTTPException(400, "Opening stock cannot exceed 1,000,000 units.")
    return quantity


def identity(request, db):
    token = request.cookies.get("kora_session", "")
    login = db.get(m.LoginSession, digest(token)) if token else None
    if not login or login.expires <= int(time.time()):
        raise HTTPException(401, "Please sign in to continue.")
    user = db.get(m.User, login.user_id)
    if not user or user.closed:
        raise HTTPException(401, "Please sign in to continue.")
    request.state.account_user = user
    request.state.account_db = db
    if login.last_seen < int(time.time()) - 60:
        login.last_seen = int(time.time())
        db.commit()
    return user, login


def workspace(request, db, merchant_id, owner=False):
    user, login = identity(request, db)
    membership = db.scalar(select(m.Membership).where(m.Membership.merchant_id == merchant_id, m.Membership.user_id == user.id))
    if not membership:
        raise HTTPException(404, "Business not found.")
    if owner and membership.role != "owner":
        raise HTTPException(403, "Only the business owner can make this change.")
    return user, login, membership, db.get(m.Merchant, merchant_id)


async def form_data(request, expected):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "This form must be submitted from your Kora workspace.")
    data = await request.form(max_files=1, max_fields=50)
    csrf = str(data.get("csrf", ""))
    if not expected or not hmac.compare_digest(csrf, expected):
        raise HTTPException(403, "Your form has expired. Reload the page and try again.")
    return data


def redirect(url):
    return RedirectResponse(url, status_code=303)


def start_session(db, user, url, request=None):
    token = secrets.token_urlsafe(32)
    from app.commerce_account import device_name, event
    now = int(time.time())
    db.add(m.LoginSession(token_hash=digest(token), user_id=user.id, csrf=secrets.token_hex(32), expires=now + 86400, created_at=now, last_seen=now, device=device_name(request) if request else "Unknown device"))
    if request:
        event(db, user, request, "Signed in")
    db.commit()
    response = redirect(url)
    response.set_cookie("kora_session", token, httponly=True, secure=settings.env != "dev", samesite="lax", max_age=86400)
    return response


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # no-referrer can make a browser's form POST Origin null. Preserve the
    # origin for same-site forms while suppressing cross-site referrers.
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    if exc.status_code == 401:
        return redirect("/login")
    db = getattr(request.state, "account_db", None)
    if request.method == "POST" and request.url.path.startswith("/account/") and db and not request.url.path.startswith(("/account/reset/", "/account/verify/", "/account/email-confirm/")):
        db.rollback()
        from app.commerce_account import page
        path = request.url.path
        tab = "preferences" if any(part in path for part in ("preferences", "notifications", "sidebar")) else "businesses" if any(part in path for part in ("businesses", "invitations")) else "profile" if any(part in path for part in ("profile", "avatar", "email", "verify")) else "security"
        return page(request, db, tab, error=exc.detail, status=exc.status_code)
    return templates.TemplateResponse(request, "error.html", {"message": exc.detail}, status_code=exc.status_code)


@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    return templates.TemplateResponse(request, "error.html", {"message": "That record already exists or was changed in another tab. Return to your workspace and check it before trying again."}, status_code=409)


@app.get("/health")
def health():
    return {"ok": True, "service": "merchant"}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/")
def home(request: Request, db: Session = Depends(get_session)):
    user, login = identity(request, db)
    from app.commerce_account import landing, preferences
    preferred = landing(db, user)
    if preferred:
        return redirect(preferred)
    merchants = db.execute(select(m.Merchant, m.Membership.role).join(m.Membership).where(m.Membership.user_id == user.id)).all()
    if len(merchants) == 1:
        tab = preferences(db.get(m.AccountProfile, user.id))["landing"]
        return redirect(f"/app/{merchants[0][0].id}" + ("" if tab == "overview" else "/" + tab))
    return templates.TemplateResponse(request, "businesses.html", {"user": user, "csrf": login.csrf, "merchants": merchants})


@app.get("/login")
@app.get("/register")
def auth_page(request: Request):
    csrf = secrets.token_hex(32)
    response = templates.TemplateResponse(request, "auth.html", {"register": request.url.path == "/register", "csrf": csrf})
    response.set_cookie("kora_form", csrf, httponly=True, secure=settings.env != "dev", samesite="strict", max_age=1800)
    return response


@app.post("/register")
@app.post("/login")
async def authenticate(request: Request, db: Session = Depends(get_session)):
    data = await form_data(request, request.cookies.get("kora_form", ""))
    email = email_value(data.get("email", ""))
    password = str(data.get("password", ""))
    if len(password) < 12 or len(password) > 128:
        raise HTTPException(400, "Use a password between 12 and 128 characters.")
    now = int(time.time())
    key = digest((request.client.host if request.client else "local") + email)
    if db.scalar(select(func.count()).select_from(m.LoginAttempt).where(m.LoginAttempt.key == key, m.LoginAttempt.at > now - 900)) >= 10:
        raise HTTPException(429, "Too many attempts. Please wait 15 minutes before trying again.")
    db.add(m.LoginAttempt(key=key, at=now))
    db.commit()
    user = db.scalar(select(m.User).where(m.User.email == email))
    if request.url.path == "/register":
        if user:
            raise HTTPException(409, "Unable to create this account. Try signing in with these details.")
        user = m.User(name=clean(data.get("name", ""), "Your name"), email=email, password_hash=hash_password(password))
        db.add(user)
        db.flush()
    elif not user or user.closed or not verify_password(password, user.password_hash):
        raise HTTPException(400, "Email or password was not recognised.")
    else:
        from app.commerce_account import factor, profile
        user = db.scalar(select(m.User).where(m.User.id == user.id).with_for_update().execution_options(populate_existing=True))
        if user.closed or not verify_password(password, user.password_hash):
            raise HTTPException(400, "Email or password was not recognised.")
        factor(db, profile(db, user), data.get("code", ""))
    old_token = request.cookies.get("kora_session", "")
    old_login = db.get(m.LoginSession, digest(old_token)) if old_token else None
    if old_login:
        db.delete(old_login)
    return start_session(db, user, "/", request)


@app.post("/logout")
async def logout(request: Request, db: Session = Depends(get_session)):
    _, login = identity(request, db)
    await form_data(request, login.csrf)
    db.delete(login)
    db.commit()
    response = redirect("/login")
    response.delete_cookie("kora_session")
    return response


@app.get("/business/new")
def new_business(request: Request, db: Session = Depends(get_session)):
    user, login = identity(request, db)
    return templates.TemplateResponse(request, "businesses.html", {"user": user, "csrf": login.csrf, "merchants": []})


@app.post("/business/new")
async def create_business(request: Request, db: Session = Depends(get_session)):
    user, login = identity(request, db)
    data = await form_data(request, login.csrf)
    merchant = m.Merchant(name=clean(data.get("name", ""), "Business name"), category=clean(data.get("category", ""), "Category", 80))
    db.add(merchant)
    db.flush()
    db.add(m.Membership(merchant_id=merchant.id, user_id=user.id, role="owner"))
    db.add(m.Location(merchant_id=merchant.id, name=clean(data.get("location", ""), "Stock location")))
    db.commit()
    return redirect(f"/app/{merchant.id}")


def context(request, db, merchant_id, tab):
    user, login, membership, merchant = workspace(request, db, merchant_id)
    location = db.scalar(select(m.Location).where(m.Location.merchant_id == merchant_id))
    rows = db.execute(select(m.Product, m.Variant, m.Balance).join(m.Variant, m.Variant.product_id == m.Product.id).join(m.Balance, m.Balance.variant_id == m.Variant.id).where(m.Product.merchant_id == merchant_id).order_by(m.Product.name, m.Variant.label)).all()
    counted = sum(1 for _, _, balance in rows if balance.counted)
    members = db.execute(select(m.User, m.Membership).join(m.Membership, m.Membership.user_id == m.User.id).where(m.Membership.merchant_id == merchant_id)).all()
    return dict(user=user, csrf=login.csrf, membership=membership, merchant=merchant, location=location, rows=rows, tab=tab,
                catalogue_count=len(rows), counted=counted, units=sum(b.on_hand for _, _, b in rows), value=sum(v.price_kobo * b.on_hand for _, v, b in rows),
                members=members, ready=bool(rows) and counted == len(rows),
                invitations=db.scalars(select(m.Invitation).where(m.Invitation.merchant_id == merchant_id, m.Invitation.accepted.is_(False), m.Invitation.expires > int(time.time()))).all())


@app.get("/app/{merchant_id}")
@app.get("/app/{merchant_id}/{tab}")
def dashboard(request: Request, merchant_id: int, tab: str = "overview", db: Session = Depends(get_session)):
    if tab == "import":
        workspace(request, db, merchant_id, owner=True)
        return redirect(f"/app/{merchant_id}/products#catalogue-import")
    if tab not in ("overview", "orders", "products", "inventory", "team", "settings", "customers", "suppliers"):
        raise HTTPException(404, "Page not found.")
    if tab == "orders":
        from app.commerce_orders import orders_page
        return orders_page(request, db, merchant_id)
    if tab in ("inventory", "suppliers"):
        if tab == "suppliers":
            workspace(request, db, merchant_id, owner=True)
        from app.commerce_inventory import inventory_page
        return inventory_page(request, db, merchant_id, tab)
    ctx = context(request, db, merchant_id, tab)
    if tab == "team":
        return templates.TemplateResponse(request, "team.html", ctx)
    if tab in ("inventory", "overview"):
        ctx["movements"] = db.execute(select(m.Movement, m.Variant, m.User).join(m.Variant, m.Variant.id == m.Movement.variant_id).join(m.User, m.User.id == m.Movement.actor_id).where(m.Movement.merchant_id == merchant_id).order_by(m.Movement.id.desc()).limit(100)).all()
    if tab in ("settings", "customers"):
        workspace(request, db, merchant_id, owner=True)
        ctx["mode"] = tab
        if tab == "customers":
            query = select(m.Customer).where(m.Customer.merchant_id == merchant_id)
            if request.query_params.get("archived") != "1":
                query = query.where(m.Customer.archived.is_(False))
            search = request.query_params.get("q", "").strip()[:120]
            if search:
                query = query.where(m.Customer.name.contains(search, autoescape=True) | m.Customer.email.contains(search, autoescape=True) | m.Customer.phone.contains(search, autoescape=True))
            ctx["customers"] = db.scalars(query.order_by(m.Customer.name)).all()
        return templates.TemplateResponse(request, "manage.html", ctx)
    if tab == "products" and request.query_params.get("archived") != "1":
        ctx["rows"] = [row for row in ctx["rows"] if not row[1].archived]
    return templates.TemplateResponse(request, "workspace.html", ctx)


def add_variant(db, merchant_id, data):
    name = clean(data.get("name", ""), "Product name", 160)
    sku = clean(data.get("sku", ""), "SKU", 64).upper()
    label = clean(data.get("variant", "Standard") or "Standard", "Variant")
    price = price_value(data.get("price", ""))
    product = db.scalar(select(m.Product).where(m.Product.merchant_id == merchant_id, m.Product.name == name))
    if not product:
        product = m.Product(merchant_id=merchant_id, name=name)
        db.add(product)
        db.flush()
    variant = m.Variant(merchant_id=merchant_id, product_id=product.id, sku=sku, label=label, price_kobo=price)
    db.add(variant)
    db.flush()
    location = db.scalar(select(m.Location).where(m.Location.merchant_id == merchant_id))
    db.add(m.Balance(merchant_id=merchant_id, location_id=location.id, variant_id=variant.id, counted=False))
    db.flush()
    return variant


@app.post("/app/{merchant_id}/products")
async def create_product(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    _, login, _, _ = workspace(request, db, merchant_id, owner=True)
    data = await form_data(request, login.csrf)
    add_variant(db, merchant_id, data)
    db.commit()
    return redirect(f"/app/{merchant_id}/products?notice=Product+added.+Record+its+opening+stock+next.")


@app.get("/sample.csv")
def sample():
    return Response("name,variant,sku,price\nEveryday T-shirt,Olive / M,TEE-OLV-M,8500.00\nEveryday T-shirt,Olive / L,TEE-OLV-L,8500.00\n", media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="kora-products.csv"'})


@app.post("/app/{merchant_id}/import")
async def import_products(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    _, login, _, _ = workspace(request, db, merchant_id, owner=True)
    data = await form_data(request, login.csrf)
    upload = data.get("file")
    if not hasattr(upload, "read"):
        raise HTTPException(400, "Choose a CSV file.")
    raw = await upload.read(1000001)
    if len(raw) > 1000000:
        raise HTTPException(400, "CSV must be smaller than 1 MB.")
    try:
        from app.commerce_csv import catalogue_rows
        rows = catalogue_rows(raw)
        added, skipped, seen = 0, 0, set()
        for index, row in rows:
            try:
                sku = clean(row["sku"], "SKU", 64).upper()
                name = clean(row["name"], "Product name", 160)
                label = clean(row["variant"] or "Standard", "Variant")
                price = price_value(row["price"])
                if sku in seen:
                    raise HTTPException(400, f"SKU {sku} appears more than once in this file.")
                seen.add(sku)
                existing = db.scalar(select(m.Variant).where(m.Variant.merchant_id == merchant_id, m.Variant.sku == sku))
                if existing:
                    product = db.get(m.Product, existing.product_id)
                    if (product.name, existing.label, existing.price_kobo, existing.archived) != (name, label, price, row["archived"]):
                        raise HTTPException(400, f"SKU {sku} already exists with different details. Edit that variant in Products or use a new SKU.")
                    skipped += 1
                    continue
                variant = add_variant(db, merchant_id, row)
                variant.archived = row["archived"]
                added += 1
            except HTTPException as exc:
                raise HTTPException(400, f"CSV row {index}: {exc.detail} Nothing was imported.")
        db.commit()
    except (HTTPException, IntegrityError) as exc:
        db.rollback()
        ctx = context(request, db, merchant_id, "products")
        ctx["rows"] = [row for row in ctx["rows"] if not row[1].archived]
        ctx["import_error"] = exc.detail if isinstance(exc, HTTPException) else "A product changed while importing. Nothing was imported. Reload your catalogue and try again."
        return templates.TemplateResponse(request, "workspace.html", ctx, status_code=400)
    return redirect(f"/app/{merchant_id}/products?notice=Imported+{added}+variants.+Skipped+{skipped}+unchanged+variants.+Stock+quantities+were+not+changed.")


@app.post("/app/{merchant_id}/stock/{variant_id}")
async def opening_stock(request: Request, merchant_id: int, variant_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = workspace(request, db, merchant_id, owner=True)
    data = await form_data(request, login.csrf)
    quantity = quantity_value(data.get("quantity", ""))
    balance = db.scalar(select(m.Balance).where(m.Balance.merchant_id == merchant_id, m.Balance.variant_id == variant_id))
    if not balance:
        raise HTTPException(404, "Variant not found.")
    # Conditional update serialises concurrent counts in PostgreSQL. Ledger write
    # shares this transaction; retries cannot overwrite an established count.
    result = db.execute(update(m.Balance).where(m.Balance.id == balance.id, m.Balance.counted.is_(False)).values(on_hand=quantity, counted=True, version=m.Balance.version + 1))
    if result.rowcount != 1:
        raise HTTPException(409, "Opening stock is already recorded. It cannot be overwritten.")
    db.add(m.Movement(merchant_id=merchant_id, location_id=balance.location_id, variant_id=variant_id, actor_id=user.id,
                      quantity=quantity, reason="Opening physical count", idempotency_key=f"opening:{balance.location_id}:{variant_id}", at=int(time.time())))
    db.commit()
    return redirect(f"/app/{merchant_id}/inventory?notice=Opening+stock+recorded.")


@app.post("/app/{merchant_id}/invite")
async def invite(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = workspace(request, db, merchant_id, owner=True)
    data = await form_data(request, login.csrf)
    email = email_value(data.get("email", ""))
    existing = db.scalar(select(m.User).join(m.Membership).where(m.Membership.merchant_id == merchant_id, m.User.email == email))
    if existing:
        raise HTTPException(409, "This person is already a member of your business.")
    token = secrets.token_urlsafe(32)
    db.execute(update(m.Invitation).where(m.Invitation.merchant_id == merchant_id, m.Invitation.email == email,
        m.Invitation.accepted.is_(False)).values(expires=0))
    db.add(m.Invitation(merchant_id=merchant_id, email=email, token_hash=digest(token), invited_by=user.id, expires=int(time.time()) + 7 * 86400))
    db.commit()
    ctx = context(request, db, merchant_id, "team")
    ctx["invite_link"] = str(request.base_url).rstrip("/") + "/invite/" + token
    ctx["invite_email"] = email
    return templates.TemplateResponse(request, "team.html", ctx)


@app.get("/invite/{token}")
def invitation_page(request: Request, token: str, db: Session = Depends(get_session)):
    invitation = db.scalar(select(m.Invitation).where(m.Invitation.token_hash == digest(token), m.Invitation.accepted.is_(False), m.Invitation.expires > int(time.time())))
    if not invitation:
        raise HTTPException(404, "This invitation has expired or has already been used.")
    try:
        user, login = identity(request, db)
    except HTTPException:
        user, login = None, None
    return templates.TemplateResponse(request, "invitation.html", {"invitation": invitation, "business": db.get(m.Merchant, invitation.merchant_id), "user": user, "csrf": login.csrf if login else ""})


@app.post("/invite/{token}")
async def accept_invitation(request: Request, token: str, db: Session = Depends(get_session)):
    user, login = identity(request, db)
    await form_data(request, login.csrf)
    invitation = db.scalar(select(m.Invitation).where(m.Invitation.token_hash == digest(token)).with_for_update())
    if not invitation or invitation.accepted or invitation.expires <= int(time.time()):
        raise HTTPException(404, "This invitation has expired or has already been used.")
    if user.email != invitation.email:
        raise HTTPException(403, "Sign in using the email address this invitation was sent to.")
    existing = db.scalar(select(m.Membership).where(m.Membership.user_id == user.id, m.Membership.merchant_id == invitation.merchant_id))
    if not existing:
        db.add(m.Membership(user_id=user.id, merchant_id=invitation.merchant_id, role="staff"))
    invitation.accepted = True
    db.commit()
    return redirect(f"/app/{invitation.merchant_id}?notice=You+have+joined+the+team.")


@app.post("/app/{merchant_id}/members/{member_id}/remove")
async def remove_member(request: Request, merchant_id: int, member_id: int, db: Session = Depends(get_session)):
    _, login, _, _ = workspace(request, db, merchant_id, owner=True)
    await form_data(request, login.csrf)
    member = db.scalar(select(m.Membership).where(m.Membership.id == member_id, m.Membership.merchant_id == merchant_id, m.Membership.role == "staff"))
    if not member:
        raise HTTPException(404, "Staff member not found.")
    db.delete(member)
    db.commit()
    return redirect(f"/app/{merchant_id}/team")


@app.post("/app/{merchant_id}/invites/{invite_id}/revoke")
async def revoke_invite(request: Request, merchant_id: int, invite_id: int, db: Session = Depends(get_session)):
    _, login, _, _ = workspace(request, db, merchant_id, owner=True)
    await form_data(request, login.csrf)
    invitation = db.scalar(select(m.Invitation).where(m.Invitation.id == invite_id, m.Invitation.merchant_id == merchant_id))
    if not invitation:
        raise HTTPException(404, "Invitation not found.")
    invitation.expires = 0
    db.commit()
    return redirect(f"/app/{merchant_id}/team")

# Account routes precede the older generic account-link routes.
from app.commerce_account import router as account_router
app.include_router(account_router)
# Register maintenance routes after the shared authorization helpers are defined.
from app.commerce_sprint1 import router as maintenance_router
app.include_router(maintenance_router)
from app.commerce_inventory import router as inventory_router
app.include_router(inventory_router)
from app.commerce_orders import router as orders_router
app.include_router(orders_router)
