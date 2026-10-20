"""Owner stock operations. A balance update and its ledger entry commit together."""
import json
import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import commerce as c, commerce_models as m
from app.commerce_sprint1 import optional
from app.db import get_session

router = APIRouter()


def number(value, label, minimum=0, maximum=1000000):
    if not re.fullmatch(r"-?\d{1,8}", str(value)):
        raise HTTPException(400, f"{label} must be a whole number.")
    result = int(value)
    if not minimum <= result <= maximum:
        raise HTTPException(400, f"{label} must be between {minimum} and {maximum}.")
    return result


def stock_context(request, db, merchant_id, tab):
    ctx = c.context(request, db, merchant_id, tab)
    page = number(request.query_params.get("page", "1"), "Page", 1, 1000000)
    totals = dict(db.execute(select(m.Movement.variant_id, func.sum(m.Movement.quantity)).where(
        m.Movement.merchant_id == merchant_id).group_by(m.Movement.variant_id)).all())
    ctx.update(
        ledger=totals,
        history_page=page,
        discrepancies=sum(b.on_hand != totals.get(v.id, 0) for _, v, b in ctx["rows"]),
        low_stock=[row for row in ctx["rows"] if row[2].counted and not row[1].archived
                   and row[2].on_hand - row[2].reserved <= row[2].low_stock_threshold],
        suppliers=db.scalars(select(m.Supplier).where(m.Supplier.merchant_id == merchant_id).order_by(m.Supplier.name)).all(),
        history=db.execute(select(m.Movement, m.Variant, m.User, m.StockOperation)
            .join(m.Variant, m.Variant.id == m.Movement.variant_id)
            .join(m.User, m.User.id == m.Movement.actor_id)
            .outerjoin(m.StockOperation, m.StockOperation.movement_id == m.Movement.id)
            .where(m.Movement.merchant_id == merchant_id).order_by(m.Movement.id.desc()).offset((page - 1) * 100).limit(100)).all(),
        reversed_ids=set(db.scalars(select(m.StockOperation.reverses_id).where(
            m.StockOperation.merchant_id == merchant_id, m.StockOperation.reverses_id.is_not(None))).all()))
    return ctx


def inventory_page(request, db, merchant_id, tab):
    ctx = stock_context(request, db, merchant_id, tab)
    return c.templates.TemplateResponse(request, "inventory.html", ctx)


@router.get("/app/{merchant_id}/inventory/{variant_id}")
def stock_form(request: Request, merchant_id: int, variant_id: int, db: Session = Depends(get_session)):
    c.workspace(request, db, merchant_id, owner=True)
    ctx = stock_context(request, db, merchant_id, "inventory")
    row = next((row for row in ctx["rows"] if row[1].id == variant_id), None)
    if not row:
        raise HTTPException(404, "Variant not found.")
    ctx.update(selected=row, operation_key=secrets.token_hex(24))
    return c.templates.TemplateResponse(request, "inventory.html", ctx)


@router.get("/app/{merchant_id}/suppliers/{supplier_id}")
def supplier_form(request: Request, merchant_id: int, supplier_id: int, db: Session = Depends(get_session)):
    c.workspace(request, db, merchant_id, owner=True)
    ctx = stock_context(request, db, merchant_id, "suppliers")
    supplier = next((s for s in ctx["suppliers"] if s.id == supplier_id), None)
    if not supplier:
        raise HTTPException(404, "Supplier not found.")
    ctx["supplier"] = supplier
    return c.templates.TemplateResponse(request, "inventory.html", ctx)


@router.post("/app/{merchant_id}/suppliers")
@router.post("/app/{merchant_id}/suppliers/{supplier_id}")
async def save_supplier(request: Request, merchant_id: int, supplier_id: int = 0, db: Session = Depends(get_session)):
    _, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    supplier = db.scalar(select(m.Supplier).where(m.Supplier.id == supplier_id, m.Supplier.merchant_id == merchant_id)) if supplier_id else m.Supplier(merchant_id=merchant_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found.")
    supplier.name = c.clean(data.get("name", ""), "Supplier name")
    supplier.email = c.email_value(data["email"]) if data.get("email") else ""
    supplier.phone = optional(data.get("phone"), "Phone", 40)
    supplier.notes = optional(data.get("notes"), "Notes", 500)
    supplier.archived = data.get("archived") == "yes"
    db.add(supplier)
    db.commit()
    return c.redirect(f"/app/{merchant_id}/suppliers?notice=Supplier+saved.")


@router.post("/app/{merchant_id}/inventory/{variant_id}/threshold")
async def threshold(request: Request, merchant_id: int, variant_id: int, db: Session = Depends(get_session)):
    _, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    result = db.execute(update(m.Balance).where(m.Balance.merchant_id == merchant_id, m.Balance.variant_id == variant_id)
                        .values(low_stock_threshold=number(data.get("threshold"), "Low-stock threshold")))
    if result.rowcount != 1:
        raise HTTPException(404, "Variant not found.")
    db.commit()
    return c.redirect(f"/app/{merchant_id}/inventory?notice=Low-stock+threshold+saved.")


@router.post("/app/{merchant_id}/inventory/{variant_id}/change")
async def change_stock(request: Request, merchant_id: int, variant_id: int, db: Session = Depends(get_session)):
    user, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    kind = str(data.get("kind", ""))
    if kind not in ("receive", "adjust", "recount", "reverse"):
        raise HTTPException(400, "Choose a stock operation.")
    key = str(data.get("key", ""))
    if not re.fullmatch(r"[a-f0-9]{48}", key):
        raise HTTPException(400, "Reload the stock form before saving.")
    reason = c.clean(data.get("reason", ""), "Reason", 120)
    # Include all meaningful input in the replay fingerprint, never CSRF secrets.
    payload = {field: str(data.get(field, "")) for field in ("kind", "quantity", "version", "supplier_id", "unit_cost", "reference", "reverses_id")}
    payload.update(variant_id=variant_id, reason=reason)
    fingerprint = c.digest(json.dumps(payload, sort_keys=True))
    existing = db.scalar(select(m.Movement).where(m.Movement.merchant_id == merchant_id, m.Movement.idempotency_key == "stock:" + key))
    if existing:
        operation = db.get(m.StockOperation, existing.id)
        if not operation or operation.request_hash != fingerprint:
            raise HTTPException(409, "This submission was already used for a different stock change.")
        return c.redirect(f"/app/{merchant_id}/inventory?notice=Stock+change+already+recorded.")
    balance = db.scalar(select(m.Balance).where(m.Balance.merchant_id == merchant_id, m.Balance.variant_id == variant_id).with_for_update())
    variant = db.scalar(select(m.Variant).where(m.Variant.id == variant_id, m.Variant.merchant_id == merchant_id).with_for_update())
    if not balance or not variant:
        raise HTTPException(404, "Variant not found.")
    if not balance.counted:
        raise HTTPException(409, "Record opening stock first, including a zero count if appropriate.")
    ledger_total = db.scalar(select(func.coalesce(func.sum(m.Movement.quantity), 0)).where(
        m.Movement.merchant_id == merchant_id, m.Movement.variant_id == variant_id))
    if ledger_total != balance.on_hand:
        raise HTTPException(409, "This balance differs from its stock history. Ask support to investigate before changing stock.")
    supplier, cost, original, reference = None, None, None, optional(data.get("reference"), "Reference", 120)
    if kind == "receive":
        if variant.archived:
            raise HTTPException(409, "Restore this variant before receiving stock.")
        supplier_id = number(data.get("supplier_id"), "Supplier", 1, 2147483647)
        supplier = db.scalar(select(m.Supplier).where(m.Supplier.id == supplier_id, m.Supplier.merchant_id == merchant_id, m.Supplier.archived.is_(False)).with_for_update())
        if not supplier:
            raise HTTPException(404, "Active supplier not found.")
        cost = c.price_value(data.get("unit_cost", ""))
        delta = number(data.get("quantity"), "Received quantity", 1)
    elif kind == "adjust":
        delta = number(data.get("quantity"), "Adjustment", -1000000)
        if delta == 0:
            raise HTTPException(400, "An adjustment must add or remove units.")
    elif kind == "recount":
        version = number(data.get("version"), "Stock version", 1, 2147483647)
        if version != balance.version:
            raise HTTPException(409, "Stock changed while you counted. Reload and count again.")
        delta = number(data.get("quantity"), "Physical count") - balance.on_hand
    else:
        original_id = number(data.get("reverses_id"), "Original movement", 1, 2147483647)
        original = db.scalar(select(m.Movement).where(m.Movement.id == original_id, m.Movement.merchant_id == merchant_id, m.Movement.variant_id == variant_id))
        metadata = db.get(m.StockOperation, original_id)
        if not original or not metadata or metadata.kind == "reverse":
            raise HTTPException(400, "Only a receiving, adjustment or recount entry can be reversed. Use a recount to correct opening stock.")
        if db.scalar(select(m.StockOperation).where(m.StockOperation.reverses_id == original_id)):
            raise HTTPException(409, "This movement has already been reversed.")
        delta = -original.quantity
    target = balance.on_hand + delta
    if not balance.reserved <= target <= 1000000:
        raise HTTPException(409, "This change would remove reserved stock, make stock negative, or exceed 1,000,000 units.")
    # CAS complements row locking and protects SQLite; a stale writer must retry.
    result = db.execute(update(m.Balance).where(m.Balance.id == balance.id, m.Balance.version == balance.version,
        m.Balance.reserved <= target).values(on_hand=target, version=balance.version + 1))
    if result.rowcount != 1:
        raise HTTPException(409, "Stock changed. Reload before trying again.")
    movement = m.Movement(merchant_id=merchant_id, location_id=balance.location_id, variant_id=variant_id,
        actor_id=user.id, quantity=delta, reason=reason, idempotency_key="stock:" + key, at=int(time.time()))
    db.add(movement)
    db.flush()
    db.add(m.StockOperation(movement_id=movement.id, merchant_id=merchant_id, kind=kind, request_hash=fingerprint,
        supplier_id=supplier.id if supplier else None, supplier_name=supplier.name if supplier else "",
        unit_cost_kobo=cost, reference=reference, reverses_id=original.id if original else None))
    db.commit()
    return c.redirect(f"/app/{merchant_id}/inventory?notice=Stock+change+recorded.")
