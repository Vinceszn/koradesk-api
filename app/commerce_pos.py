"""Cash POS and reserved order fulfilment. Every stock change is transactional."""
import json
import re
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app import commerce as c, commerce_models as m
from app.db import get_session
from app.commerce_barcodes import normalize_barcode
from app.commerce_orders import _reference, _event, _customer_snapshot, expire_due

router = APIRouter()

def seller(request, db, merchant_id):
    values = c.workspace(request, db, merchant_id)
    if values[2].role != "owner" and not values[2].can_sell:
        raise HTTPException(403, "Ask the owner to enable cashier access.")
    return values

def page(request, db, merchant_id):
    seller(request, db, merchant_id)
    expire_due(db, merchant_id)
    ctx = c.context(request, db, merchant_id, "pos")
    ctx["key"] = secrets.token_hex(24)
    ctx["codes"] = db.scalars(select(m.VariantBarcode).where(m.VariantBarcode.merchant_id == merchant_id, m.VariantBarcode.archived.is_(False))).all()
    ctx["customers"] = db.scalars(select(m.Customer).where(m.Customer.merchant_id == merchant_id, m.Customer.archived.is_(False))).all()
    return c.templates.TemplateResponse(request, "pos.html", ctx)

@router.post("/app/{merchant_id}/cashier/{member_id}")
async def cashier(request: Request, merchant_id: int, member_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    member = db.scalar(select(m.Membership).where(m.Membership.id == member_id, m.Membership.merchant_id == merchant_id, m.Membership.role == "staff"))
    if not member:
        raise HTTPException(404, "Staff member not found.")
    member.can_sell = data.get("enabled") == "yes"
    from app.commerce_account import event
    event(db, user, request, f"Cashier access {'enabled' if member.can_sell else 'disabled'} for member {member.id}")
    db.commit()
    return c.redirect(f"/app/{merchant_id}/team?notice=Cashier+access+saved.")

@router.post("/app/{merchant_id}/pos/barcodes")
async def barcode(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    code = normalize_barcode(data.get("code"), data.get("symbology", "unknown"))
    variant = db.scalar(select(m.Variant).where(m.Variant.merchant_id == merchant_id, m.Variant.id == c.quantity_value(data.get("variant_id", ""))))
    if not variant or variant.archived:
        raise HTTPException(404, "Active variant not found.")
    existing = db.scalar(select(m.VariantBarcode).where(m.VariantBarcode.merchant_id == merchant_id, m.VariantBarcode.code == code, m.VariantBarcode.archived.is_(False)))
    if existing:
        matched = db.get(m.Variant, existing.variant_id)
        raise HTTPException(409, f"This barcode is already assigned to {matched.sku}.")
    if data.get("primary") == "yes":
        db.execute(update(m.VariantBarcode).where(m.VariantBarcode.merchant_id == merchant_id, m.VariantBarcode.variant_id == variant.id).values(is_primary=False))
    db.add(m.VariantBarcode(merchant_id=merchant_id, variant_id=variant.id, code=code,
        symbology=data.get("symbology", "unknown"), is_primary=data.get("primary") == "yes"))
    from app.commerce_account import event
    event(db, user, request, f"Barcode assigned to variant {variant.id}")
    db.commit()
    return c.redirect(f"/app/{merchant_id}/pos?notice=Barcode+assigned.")

def replay(db, merchant_id, key, kind, fingerprint):
    if not re.fullmatch(r"[a-f0-9]{48}", key):
        raise HTTPException(400, "Reload the page before submitting.")
    record = db.scalar(select(m.OrderRequest).where(m.OrderRequest.merchant_id == merchant_id, m.OrderRequest.request_key == kind + ":" + key))
    if record and record.request_hash != fingerprint:
        raise HTTPException(409, "This submission key was already used with different details.")
    return record

@router.post("/app/{merchant_id}/pos/barcodes/{barcode_id}/archive")
async def archive_barcode(request: Request, merchant_id: int, barcode_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    await c.form_data(request, login.csrf)
    record = db.scalar(select(m.VariantBarcode).where(m.VariantBarcode.id == barcode_id, m.VariantBarcode.merchant_id == merchant_id))
    if not record:
        raise HTTPException(404, "Barcode not found.")
    record.archived = True
    from app.commerce_account import event
    event(db, user, request, f"Barcode {record.id} archived")
    db.commit()
    return c.redirect(f"/app/{merchant_id}/variants/{record.variant_id}/edit")

def cash(db, order, user, tendered):
    amount = c.price_value(tendered)
    if amount < order.total_kobo:
        raise HTTPException(400, "Cash tendered is less than the order total.")
    db.add(m.CashSale(merchant_id=order.merchant_id, order_id=order.id, amount_kobo=order.total_kobo,
        tendered_kobo=amount, actor_id=user.id, at=int(time.time())))
    order.payment_status = "paid"
    _event(db, order, user.id, "cash_received", f"Cash received: ₦{amount/100:,.2f}; change: ₦{(amount-order.total_kobo)/100:,.2f}")

@router.post("/app/{merchant_id}/pos/sale")
async def sale(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = seller(request, db, merchant_id)
    data = await c.form_data(request, login.csrf)
    fingerprint = c.digest(json.dumps({k: str(data.get(k, "")) for k in ("basket", "tendered", "customer_id")}, sort_keys=True))
    key = str(data.get("key", ""))
    previous = replay(db, merchant_id, key, "sale", fingerprint)
    if previous:
        return c.redirect(f"/app/{merchant_id}/pos?sold={previous.order_id}&notice=Sale+already+recorded.")
    try:
        lines = json.loads(data.get("basket", ""))
        if not isinstance(lines, list) or not 1 <= len(lines) <= 40:
            raise ValueError()
        ids = [int(line["id"]) for line in lines]
        if len(set(ids)) != len(ids):
            raise ValueError()
        for line in lines:
            if type(line["qty"]) is not int or not 1 <= line["qty"] <= 1000000 or type(line["price"]) is not int:
                raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, "Review the basket. Use 1–40 unique variants with whole quantities.")
    now = int(time.time())
    location = db.scalar(select(m.Location).where(m.Location.merchant_id == merchant_id))
    order = m.CommerceOrder(merchant_id=merchant_id, location_id=location.id, reference=_reference(db, merchant_id),
        created_by=user.id, created_at=now, updated_at=now, placed_at=now,
        order_status="completed", fulfilment_status="fulfilled")
    order.customer_id, order.customer_name, order.customer_email, order.customer_phone = _customer_snapshot(db, merchant_id, data)
    db.add(order)
    db.flush()
    total = 0
    for line in sorted(lines, key=lambda row: int(row["id"])):
        variant = db.scalar(select(m.Variant).where(m.Variant.id == int(line["id"]), m.Variant.merchant_id == merchant_id).with_for_update())
        if not variant or variant.archived:
            raise HTTPException(409, "A basket item is archived or no longer available.")
        if variant.price_kobo != line["price"]:
            raise HTTPException(409, f"The price of {variant.sku} changed. Reload and review the basket.")
        balance = db.scalar(select(m.Balance).where(m.Balance.merchant_id == merchant_id, m.Balance.variant_id == variant.id).with_for_update())
        qty = line["qty"]
        if not balance or not balance.counted or balance.on_hand-balance.reserved < qty:
            raise HTTPException(409, f"Insufficient available stock for {variant.sku}. No sale was recorded.")
        changed = db.execute(update(m.Balance).where(m.Balance.id == balance.id, m.Balance.version == balance.version,
            m.Balance.on_hand-m.Balance.reserved >= qty).values(on_hand=m.Balance.on_hand-qty, version=m.Balance.version+1))
        if changed.rowcount != 1:
            raise HTTPException(409, "Stock changed. Reload and try again.")
        product = db.get(m.Product, variant.product_id)
        total += qty*variant.price_kobo
        db.add(m.OrderItem(merchant_id=merchant_id, order_id=order.id, variant_id=variant.id, product_name=product.name,
            variant_label=variant.label, sku=variant.sku, quantity=qty, unit_price_kobo=variant.price_kobo,
            line_total_kobo=qty*variant.price_kobo, fulfilled_quantity=qty))
        db.add(m.Movement(merchant_id=merchant_id, location_id=location.id, variant_id=variant.id, actor_id=user.id,
            quantity=-qty, reason="Cash sale " + order.reference, idempotency_key=f"sale:{order.id}:{variant.id}", at=now))
    if total > 2000000000:
        raise HTTPException(400, "Sale total cannot exceed ₦20,000,000.")
    order.subtotal_kobo = order.total_kobo = total
    cash(db, order, user, data.get("tendered", ""))
    _event(db, order, user.id, "sale_completed", "Cash sale completed; goods handed to customer")
    db.add(m.OrderRequest(merchant_id=merchant_id, order_id=order.id, request_key="sale:"+key, kind="sale", request_hash=fingerprint, created_at=now))
    db.commit()
    return c.redirect(f"/app/{merchant_id}/pos?sold={order.id}&notice=Sale+completed.")

@router.post("/app/{merchant_id}/orders/{order_id}/fulfil")
async def fulfil(request: Request, merchant_id: int, order_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    fingerprint = c.digest(json.dumps(dict(data), sort_keys=True))
    key = str(data.get("key", ""))
    previous = replay(db, merchant_id, key, "fulfil", fingerprint)
    if previous:
        if previous.order_id != order_id:
            raise HTTPException(409, "This submission belongs to a different order.")
        return c.redirect(f"/app/{merchant_id}/orders/{order_id}")
    expire_due(db, merchant_id)
    order = db.scalar(select(m.CommerceOrder).where(m.CommerceOrder.id == order_id, m.CommerceOrder.merchant_id == merchant_id).with_for_update())
    if not order:
        raise HTTPException(404, "Order not found.")
    if order.order_status != "placed" or str(order.version) != data.get("version"):
        raise HTTPException(409, "Order changed or is no longer available. Reload it.")
    action = data.get("action")
    if action not in ("pickup", "dispatch", "cancel"):
        raise HTTPException(400, "Choose pickup, dispatch or cancellation.")
    if action == "cancel" and order.payment_status != "unpaid":
        raise HTTPException(409, "Paid items need the returns/refund workflow.")
    items = db.scalars(select(m.OrderItem).where(m.OrderItem.order_id == order.id).order_by(m.OrderItem.variant_id)).all()
    changed_any = False
    for item in items:
        qty = c.quantity_value(data.get("qty_" + str(item.id), "0"))
        remaining = item.quantity-item.fulfilled_quantity-item.cancelled_quantity
        if qty > remaining:
            raise HTTPException(409, "Quantity exceeds the remaining order quantity.")
        if not qty:
            continue
        reservation = db.scalar(select(m.StockReservation).where(m.StockReservation.order_item_id == item.id).with_for_update())
        balance = db.scalar(select(m.Balance).where(m.Balance.merchant_id == merchant_id, m.Balance.variant_id == item.variant_id).with_for_update())
        consume = qty if action != "cancel" else 0
        result = db.execute(update(m.Balance).where(m.Balance.id == balance.id, m.Balance.reserved >= qty).values(
            reserved=m.Balance.reserved-qty, on_hand=m.Balance.on_hand-consume, version=m.Balance.version+1))
        if not reservation or reservation.state != "active" or result.rowcount != 1:
            raise HTTPException(409, "Reservation changed. Reload the order.")
        if consume:
            item.fulfilled_quantity += qty
            db.add(m.Movement(merchant_id=merchant_id, location_id=order.location_id, variant_id=item.variant_id,
                actor_id=user.id, quantity=-qty, reason=action.title()+" "+order.reference,
                idempotency_key=f"fulfil:{key}:{item.id}", at=int(time.time())))
        else:
            item.cancelled_quantity += qty
            order.total_kobo -= qty*item.unit_price_kobo
            order.subtotal_kobo = order.total_kobo
        if item.fulfilled_quantity+item.cancelled_quantity == item.quantity:
            reservation.state = "consumed" if item.fulfilled_quantity else "released"
            reservation.transitioned_at = int(time.time())
        else:
            reservation.quantity = item.quantity-item.fulfilled_quantity-item.cancelled_quantity
        changed_any = True
    if not changed_any:
        raise HTTPException(400, "Enter at least one quantity.")
    if action != "cancel" and order.payment_status == "unpaid":
        cash(db, order, user, data.get("tendered", ""))
        order.reserved_until = 0
    done = all(i.fulfilled_quantity+i.cancelled_quantity == i.quantity for i in items)
    any_fulfilled = any(i.fulfilled_quantity for i in items)
    order.fulfilment_status = ("fulfilled" if any_fulfilled else "cancelled") if done else ("partially_fulfilled" if any_fulfilled else "unfulfilled")
    if done:
        order.order_status = "completed" if any_fulfilled else "cancelled"
    order.version += 1
    order.updated_at = int(time.time())
    _event(db, order, user.id, action, "Line quantities recorded")
    db.add(m.OrderRequest(merchant_id=merchant_id, order_id=order.id, request_key="fulfil:"+key, kind="fulfil", request_hash=fingerprint, created_at=int(time.time())))
    db.commit()
    return c.redirect(f"/app/{merchant_id}/orders/{order.id}?notice=Order+updated.")
