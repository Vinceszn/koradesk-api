"""Sprint 4 order drafts, immutable snapshots and stock reservations."""
from __future__ import annotations

import json
import re
import secrets
import time
from datetime import datetime, time as day_time, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app import commerce_models as m
from app.db import get_session

router = APIRouter()
RESERVATION_SECONDS = 30 * 60
PAGE_SIZE = 25
ORDER_STATES = ("draft", "placed", "completed", "cancelled", "expired")
PAYMENT_STATES = ("unpaid", "partially_paid", "paid", "partially_refunded", "refunded")
FULFILMENT_STATES = ("unfulfilled", "partially_fulfilled", "fulfilled", "cancelled")


def _positive(value, label="Quantity"):
    if not re.fullmatch(r"[1-9]\d{0,6}", str(value or "")) or int(value) > 1_000_000:
        raise HTTPException(400, f"{label} must be a whole number between 1 and 1,000,000.")
    return int(value)


def _optional(value, maximum):
    result = str(value or "").strip()
    if len(result) > maximum:
        raise HTTPException(400, f"Keep this value under {maximum} characters.")
    return result


def _reference(db, merchant_id):
    for _ in range(8):
        value = "KD-" + secrets.token_hex(4).upper()
        if not db.scalar(select(m.CommerceOrder.id).where(m.CommerceOrder.merchant_id == merchant_id, m.CommerceOrder.reference == value)):
            return value
    raise HTTPException(503, "Could not create an order reference. Try again.")


def _event(db, order, actor_id, kind, details="", at=None):
    db.add(m.OrderEvent(merchant_id=order.merchant_id, order_id=order.id, actor_id=actor_id,
                        event_type=kind, details=details[:300], at=at or int(time.time())))


def _order(db, merchant_id, order_id, lock=False):
    query = select(m.CommerceOrder).where(m.CommerceOrder.id == order_id, m.CommerceOrder.merchant_id == merchant_id)
    if lock:
        query = query.with_for_update()
    result = db.scalar(query)
    if not result:
        raise HTTPException(404, "Order not found.")
    return result


def _request(db, order, data, kind, fingerprint):
    key = str(data.get("key", ""))
    if not re.fullmatch(r"[a-f0-9]{48}", key):
        raise HTTPException(400, "Reload the order before trying again.")
    request_key = kind + ":" + key
    existing = db.scalar(select(m.OrderRequest).where(
        m.OrderRequest.merchant_id == order.merchant_id, m.OrderRequest.request_key == request_key))
    if existing:
        if existing.order_id != order.id or existing.kind != kind or existing.request_hash != fingerprint:
            raise HTTPException(409, "This submission was already used for a different order change.")
        return existing
    db.add(m.OrderRequest(merchant_id=order.merchant_id, order_id=order.id, request_key=request_key,
                          kind=kind, request_hash=fingerprint, created_at=int(time.time())))
    return None


def _draft_lines(db, merchant_id, data):
    variant_values = list(data.getlist("variant_id"))
    quantity_values = list(data.getlist("quantity"))
    if len(variant_values) != len(quantity_values) or len(variant_values) > 20:
        raise HTTPException(400, "An order can contain up to 20 different items.")
    requested = []
    seen = set()
    for variant_value, quantity_value in zip(variant_values, quantity_values):
        if not str(variant_value).strip() and not str(quantity_value).strip():
            continue
        if not str(variant_value).isdigit():
            raise HTTPException(400, "Choose a product for every order line.")
        variant_id = int(variant_value)
        if variant_id in seen:
            raise HTTPException(400, "Add each variant once, then change its quantity.")
        seen.add(variant_id)
        requested.append((variant_id, _positive(quantity_value)))
    if not requested:
        raise HTTPException(400, "Add at least one item to this order.")
    records = {variant.id: (product, variant, balance) for product, variant, balance in db.execute(
        select(m.Product, m.Variant, m.Balance)
        .join(m.Variant, m.Variant.product_id == m.Product.id)
        .join(m.Balance, m.Balance.variant_id == m.Variant.id)
        .where(m.Product.merchant_id == merchant_id, m.Variant.id.in_([row[0] for row in requested]),
               m.Variant.archived.is_(False), m.Balance.counted.is_(True)))}
    if len(records) != len(requested):
        raise HTTPException(409, "One of these products is archived, uncounted or unavailable. Refresh the order.")
    lines, total = [], 0
    for variant_id, quantity in requested:
        product, variant, _ = records[variant_id]
        line_total = variant.price_kobo * quantity
        total += line_total
        lines.append(dict(variant_id=variant.id, product_name=product.name, variant_label=variant.label,
                          sku=variant.sku, quantity=quantity, unit_price_kobo=variant.price_kobo,
                          line_total_kobo=line_total))
    if total > 2_000_000_000:
        raise HTTPException(400, "Order total cannot exceed ₦20,000,000.")
    return lines, total


def _customer_snapshot(db, merchant_id, data):
    raw = str(data.get("customer_id", "")).strip()
    if raw:
        if not raw.isdigit():
            raise HTTPException(400, "Choose a valid customer.")
        customer = db.scalar(select(m.Customer).where(m.Customer.id == int(raw), m.Customer.merchant_id == merchant_id,
                                                       m.Customer.archived.is_(False)))
        if not customer:
            raise HTTPException(404, "Active customer not found.")
        return customer.id, customer.name, customer.email, customer.phone
    name = _optional(data.get("customer_name"), 120)
    email = _optional(data.get("customer_email"), 254).lower()
    phone = _optional(data.get("customer_phone"), 40)
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(400, "Enter a valid customer email address.")
    return None, name, email, phone


def _submitted(data):
    variants = list(data.getlist("variant_id"))
    quantities = list(data.getlist("quantity"))
    return dict(customer_id=str(data.get("customer_id", "")), customer_name=str(data.get("customer_name", "")),
                customer_email=str(data.get("customer_email", "")), customer_phone=str(data.get("customer_phone", "")),
                rows=[dict(variant_id=value, quantity=quantities[index] if index < len(quantities) else "")
                      for index, value in enumerate(variants)], key=str(data.get("key", "")), version=str(data.get("version", "")))


def _form_page(request, db, merchant_id, order=None, error=None, status=200, submitted=None):
    ctx = c.context(request, db, merchant_id, "orders")
    if ctx["membership"].role != "owner":
        raise HTTPException(403, "Only the business owner can create or edit orders.")
    ctx.update(mode="order-form", order=order, error=error,
               customers=db.scalars(select(m.Customer).where(m.Customer.merchant_id == merchant_id,
                                      m.Customer.archived.is_(False)).order_by(m.Customer.name)).all(),
               sellable=[row for row in ctx["rows"] if not row[1].archived and row[2].counted])
    if submitted is not None:
        ctx["draft"] = submitted
    elif order:
        items = db.scalars(select(m.OrderItem).where(m.OrderItem.order_id == order.id,
                                                     m.OrderItem.merchant_id == merchant_id).order_by(m.OrderItem.id)).all()
        ctx["draft"] = dict(customer_id=str(order.customer_id or ""), customer_name=order.customer_name,
                            customer_email=order.customer_email, customer_phone=order.customer_phone,
                            rows=[dict(variant_id=str(item.variant_id), quantity=str(item.quantity)) for item in items],
                            key=secrets.token_hex(24), version=str(order.version))
    else:
        ctx["draft"] = dict(customer_id="", customer_name="", customer_email="", customer_phone="",
                            rows=[dict(variant_id="", quantity="1")], key=secrets.token_hex(24), version="")
    return c.templates.TemplateResponse(request, "orders.html", ctx, status_code=status)


def expire_due(db, merchant_id=None, now=None):
    """Release overdue unpaid reservations. Safe to retry and suitable for a scheduled job."""
    now = now or int(time.time())
    query = select(m.CommerceOrder.id).where(m.CommerceOrder.order_status == "placed",
        m.CommerceOrder.payment_status == "unpaid", m.CommerceOrder.reserved_until > 0,
        m.CommerceOrder.reserved_until <= now).order_by(m.CommerceOrder.id).limit(100)
    if merchant_id is not None:
        query = query.where(m.CommerceOrder.merchant_id == merchant_id)
    expired = 0
    for order_id in list(db.scalars(query)):
        order = db.scalar(select(m.CommerceOrder).where(m.CommerceOrder.id == order_id).with_for_update())
        if not order or order.order_status != "placed" or order.payment_status != "unpaid" or order.reserved_until > now:
            continue
        claimed = db.execute(update(m.CommerceOrder).where(m.CommerceOrder.id == order.id,
            m.CommerceOrder.order_status == "placed", m.CommerceOrder.payment_status == "unpaid",
            m.CommerceOrder.reserved_until <= now).values(order_status="expired", updated_at=now,
            version=m.CommerceOrder.version + 1))
        if claimed.rowcount != 1:
            continue
        reservations = db.scalars(select(m.StockReservation).where(m.StockReservation.order_id == order.id,
            m.StockReservation.merchant_id == order.merchant_id, m.StockReservation.state == "active").order_by(m.StockReservation.variant_id)).all()
        for reservation in reservations:
            changed = db.execute(update(m.Balance).where(m.Balance.merchant_id == order.merchant_id,
                m.Balance.location_id == reservation.location_id, m.Balance.variant_id == reservation.variant_id,
                m.Balance.reserved >= reservation.quantity).values(
                    reserved=m.Balance.reserved - reservation.quantity, version=m.Balance.version + 1))
            if changed.rowcount != 1:
                raise HTTPException(409, "An expired order could not release its stock. Ask support to review it.")
            reservation.state, reservation.transitioned_at = "expired", now
        _event(db, order, None, "expired", "Unpaid reservation expired", now)
        db.add(m.OrderRequest(merchant_id=order.merchant_id, order_id=order.id,
            request_key=f"expire:{order.id}:{order.reserved_until}", kind="expire",
            request_hash=c.digest(f"expire:{order.id}:{order.reserved_until}"), created_at=now))
        expired += 1
    if expired:
        db.commit()
    return expired


def orders_page(request: Request, db: Session, merchant_id: int):
    ctx = c.context(request, db, merchant_id, "orders")
    expire_due(db, merchant_id)
    from app.commerce_account import preferences
    try:
        user_zone = ZoneInfo(preferences(db.get(m.AccountProfile, ctx["user"].id))["timezone"])
    except (ValueError, ZoneInfoNotFoundError):
        user_zone = timezone.utc
    query = select(m.CommerceOrder).where(m.CommerceOrder.merchant_id == merchant_id)
    search = request.query_params.get("q", "").strip()[:120]
    order_state = request.query_params.get("order_status", "")
    payment_state = request.query_params.get("payment_status", "")
    fulfilment_state = request.query_params.get("fulfilment_status", "")
    if search:
        query = query.where(or_(m.CommerceOrder.reference.contains(search, autoescape=True),
            m.CommerceOrder.customer_name.contains(search, autoescape=True),
            m.CommerceOrder.customer_email.contains(search, autoescape=True),
            m.CommerceOrder.customer_phone.contains(search, autoescape=True)))
    if order_state:
        if order_state not in ORDER_STATES:
            raise HTTPException(400, "Choose a valid order status.")
        query = query.where(m.CommerceOrder.order_status == order_state)
    if payment_state:
        if payment_state not in PAYMENT_STATES:
            raise HTTPException(400, "Choose a valid payment status.")
        query = query.where(m.CommerceOrder.payment_status == payment_state)
    if fulfilment_state:
        if fulfilment_state not in FULFILMENT_STATES:
            raise HTTPException(400, "Choose a valid fulfilment status.")
        query = query.where(m.CommerceOrder.fulfilment_status == fulfilment_state)
    for parameter, comparator in (("from", "from"), ("to", "to")):
        value = request.query_params.get(parameter, "")
        if value:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(400, "Use a valid order date.")
            moment = datetime.combine(parsed, day_time.min if comparator == "from" else day_time.max, user_zone)
            query = query.where(m.CommerceOrder.created_at >= int(moment.timestamp()) if comparator == "from" else
                                m.CommerceOrder.created_at <= int(moment.timestamp()))
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    kept_query = [(key, value) for key, value in request.query_params.multi_items() if key != "page"]
    pagination_query = urlencode(kept_query) + ("&" if kept_query else "")
    ctx.update(mode="orders", orders=db.scalars(query.order_by(m.CommerceOrder.created_at.desc(),
        m.CommerceOrder.id.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all(),
        order_page=page, order_total=total, page_size=PAGE_SIZE, search=search,
        order_state=order_state, payment_state=payment_state, fulfilment_state=fulfilment_state,
        pagination_query=pagination_query)
    return c.templates.TemplateResponse(request, "orders.html", ctx)


@router.get("/app/{merchant_id}/orders/new")
def new_order(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    return _form_page(request, db, merchant_id)


@router.get("/app/{merchant_id}/orders/{order_id}/edit")
def edit_order(request: Request, merchant_id: int, order_id: int, db: Session = Depends(get_session)):
    c.workspace(request, db, merchant_id, owner=True)
    order = _order(db, merchant_id, order_id)
    if order.order_status != "draft":
        raise HTTPException(409, "Only draft orders can be edited.")
    return _form_page(request, db, merchant_id, order)


@router.post("/app/{merchant_id}/orders/draft")
@router.post("/app/{merchant_id}/orders/{order_id}/draft")
async def save_draft(request: Request, merchant_id: int, order_id: int = 0, db: Session = Depends(get_session)):
    user, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    try:
        submitted = _submitted(data)
        fingerprint = c.digest(json.dumps({k: submitted[k] for k in ("customer_id", "customer_name", "customer_email", "customer_phone", "rows")}, sort_keys=True))
        if not order_id:
            key = str(data.get("key", ""))
            if not re.fullmatch(r"[a-f0-9]{48}", key):
                raise HTTPException(400, "Reload the order before trying again.")
            existing = db.scalar(select(m.OrderRequest).where(m.OrderRequest.merchant_id == merchant_id,
                m.OrderRequest.request_key == "draft:" + key))
            if existing:
                if existing.request_hash != fingerprint:
                    raise HTTPException(409, "This submission was already used for a different order change.")
                return c.redirect(f"/app/{merchant_id}/orders/{existing.order_id}?notice=Draft+was+already+saved.")
        customer_id, customer_name, customer_email, customer_phone = _customer_snapshot(db, merchant_id, data)
        lines, total = _draft_lines(db, merchant_id, data)
        now = int(time.time())
        if order_id:
            order = _order(db, merchant_id, order_id, lock=True)
            if order.order_status != "draft":
                raise HTTPException(409, "Only draft orders can be edited.")
            if str(order.version) != str(data.get("version", "")):
                raise HTTPException(409, "This draft changed in another tab. Reload it before saving.")
            db.execute(delete(m.OrderItem).where(m.OrderItem.order_id == order.id, m.OrderItem.merchant_id == merchant_id))
            order.version += 1
            event_type, message = "draft_updated", "Draft order updated"
        else:
            location = db.scalar(select(m.Location).where(m.Location.merchant_id == merchant_id))
            order = m.CommerceOrder(merchant_id=merchant_id, location_id=location.id, reference=_reference(db, merchant_id),
                created_by=user.id, created_at=now, updated_at=now)
            db.add(order)
            db.flush()
            replay = _request(db, order, data, "draft", fingerprint)
            if replay:
                db.rollback()
                return c.redirect(f"/app/{merchant_id}/orders/{replay.order_id}?notice=Draft+was+already+saved.")
            event_type, message = "draft_created", "Draft order created"
        order.customer_id, order.customer_name = customer_id, customer_name
        order.customer_email, order.customer_phone = customer_email, customer_phone
        order.subtotal_kobo = order.total_kobo = total
        order.updated_at = now
        for line in lines:
            db.add(m.OrderItem(merchant_id=merchant_id, order_id=order.id, **line))
        _event(db, order, user.id, event_type, message, now)
        db.commit()
        return c.redirect(f"/app/{merchant_id}/orders/{order.id}?notice=Draft+saved.")
    except HTTPException as exc:
        db.rollback()
        order = _order(db, merchant_id, order_id) if order_id else None
        return _form_page(request, db, merchant_id, order, exc.detail, exc.status_code, _submitted(data))


@router.get("/app/{merchant_id}/orders/{order_id}")
def order_detail(request: Request, merchant_id: int, order_id: int, db: Session = Depends(get_session)):
    ctx = c.context(request, db, merchant_id, "orders")
    expire_due(db, merchant_id)
    order = _order(db, merchant_id, order_id)
    items = db.scalars(select(m.OrderItem).where(m.OrderItem.order_id == order.id,
        m.OrderItem.merchant_id == merchant_id).order_by(m.OrderItem.id)).all()
    reservations = {row.order_item_id: row for row in db.scalars(select(m.StockReservation).where(
        m.StockReservation.order_id == order.id, m.StockReservation.merchant_id == merchant_id))}
    events = db.execute(select(m.OrderEvent, m.User).outerjoin(m.User, m.User.id == m.OrderEvent.actor_id).where(
        m.OrderEvent.order_id == order.id, m.OrderEvent.merchant_id == merchant_id).order_by(m.OrderEvent.id.desc())).all()
    ctx.update(mode="order-detail", order=order, items=items, reservations=reservations, order_events=events,
               place_key=secrets.token_hex(24), cancel_key=secrets.token_hex(24))
    return c.templates.TemplateResponse(request, "orders.html", ctx)


@router.post("/app/{merchant_id}/orders/{order_id}/place")
async def place_order(request: Request, merchant_id: int, order_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    order = _order(db, merchant_id, order_id, lock=True)
    fingerprint = c.digest(f"place:{order.id}:{data.get('version', '')}")
    if _request(db, order, data, "place", fingerprint):
        return c.redirect(f"/app/{merchant_id}/orders/{order.id}?notice=Order+was+already+placed.")
    if order.order_status != "draft" or str(order.version) != str(data.get("version", "")):
        raise HTTPException(409, "This order is no longer the draft you reviewed. Reload it before placing.")
    items = db.scalars(select(m.OrderItem).where(m.OrderItem.order_id == order.id,
        m.OrderItem.merchant_id == merchant_id).order_by(m.OrderItem.variant_id)).all()
    if not items:
        raise HTTPException(409, "Add an item before placing this order.")
    variants = {row.id: row for row in db.scalars(select(m.Variant).where(m.Variant.merchant_id == merchant_id,
        m.Variant.id.in_([item.variant_id for item in items])).with_for_update())}
    now = int(time.time())
    for item in items:
        variant = variants.get(item.variant_id)
        if not variant or variant.archived:
            raise HTTPException(409, f"{item.product_name} · {item.variant_label} is no longer available.")
        if variant.price_kobo != item.unit_price_kobo:
            raise HTTPException(409, f"The price of {item.product_name} · {item.variant_label} changed. Edit and save the draft to review the new total before placing it.")
        balance = db.scalar(select(m.Balance).where(m.Balance.merchant_id == merchant_id,
            m.Balance.location_id == order.location_id, m.Balance.variant_id == item.variant_id).with_for_update())
        if not balance or not balance.counted or balance.on_hand - balance.reserved < item.quantity:
            available = max(0, balance.on_hand - balance.reserved) if balance and balance.counted else 0
            raise HTTPException(409, f"Only {available} units of {item.product_name} · {item.variant_label} are available. Nothing was reserved.")
        changed = db.execute(update(m.Balance).where(m.Balance.id == balance.id, m.Balance.version == balance.version,
            m.Balance.on_hand - m.Balance.reserved >= item.quantity).values(
                reserved=m.Balance.reserved + item.quantity, version=balance.version + 1))
        if changed.rowcount != 1:
            raise HTTPException(409, "Stock changed while placing this order. Nothing was reserved; reload and try again.")
        db.add(m.StockReservation(merchant_id=merchant_id, order_id=order.id, order_item_id=item.id,
            location_id=order.location_id, variant_id=item.variant_id, quantity=item.quantity,
            state="active", created_at=now, transitioned_at=0))
    order.order_status, order.placed_at = "placed", now
    order.reserved_until, order.updated_at, order.version = now + RESERVATION_SECONDS, now, order.version + 1
    noun = "line" if len(items) == 1 else "lines"
    _event(db, order, user.id, "placed", f"Stock reserved for {len(items)} item {noun}", now)
    db.commit()
    return c.redirect(f"/app/{merchant_id}/orders/{order.id}?notice=Order+placed+and+stock+reserved+for+30+minutes.")


@router.post("/app/{merchant_id}/orders/{order_id}/cancel")
async def cancel_order(request: Request, merchant_id: int, order_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    order = _order(db, merchant_id, order_id, lock=True)
    fingerprint = c.digest(f"cancel:{order.id}:{data.get('version', '')}")
    if _request(db, order, data, "cancel", fingerprint):
        return c.redirect(f"/app/{merchant_id}/orders/{order.id}?notice=Order+was+already+cancelled.")
    if str(order.version) != str(data.get("version", "")):
        raise HTTPException(409, "This order changed in another tab. Reload it before cancelling.")
    if order.order_status != "placed" or order.fulfilment_status != "unfulfilled":
        raise HTTPException(409, "Only a placed, unfulfilled order can be cancelled.")
    reservations = db.scalars(select(m.StockReservation).where(m.StockReservation.order_id == order.id,
        m.StockReservation.merchant_id == merchant_id, m.StockReservation.state == "active").order_by(
        m.StockReservation.variant_id).with_for_update()).all()
    now = int(time.time())
    for reservation in reservations:
        changed = db.execute(update(m.Balance).where(m.Balance.merchant_id == merchant_id,
            m.Balance.location_id == reservation.location_id, m.Balance.variant_id == reservation.variant_id,
            m.Balance.reserved >= reservation.quantity).values(
                reserved=m.Balance.reserved - reservation.quantity, version=m.Balance.version + 1))
        if changed.rowcount != 1:
            raise HTTPException(409, "Reserved stock changed unexpectedly. Nothing was cancelled; ask support to review this order.")
        reservation.state, reservation.transitioned_at = "released", now
    order.order_status, order.fulfilment_status = "cancelled", "cancelled"
    order.cancelled_at, order.updated_at, order.version = now, now, order.version + 1
    _event(db, order, user.id, "cancelled", "Active stock reservations released", now)
    db.commit()
    return c.redirect(f"/app/{merchant_id}/orders/{order.id}?notice=Order+cancelled+and+stock+released.")


from app import commerce as c
