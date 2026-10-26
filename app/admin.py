"""Internal ops dashboard (v1). Internal-only: Cloudflare Access sits in front
of `/admin` in production — zero auth code here, per spec decision 1.

Money copy (reminders, 6pm summary) stays hardcoded v1, per spec decision 2.
Audit actors are real addresses (`admin:<email>`), per spec decision 3.
"""

import datetime as dt

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app import approvals, caps, models, ops_mail

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")

PAGE = 50
VALID_PLANS = ("pilot", "starter", "growth", "partner")
VALID_STAGES = ("lead", "onboarding", "pilot", "live", "churned")
VALID_LEAD_STAGES = ("new", "contacted", "pilot", "converted", "lost")


def _session() -> Session:
    from app.db import SessionLocal

    return SessionLocal()


def operator_actor() -> str:
    addrs = ops_mail.recipients()
    return f"admin:{addrs[0]}" if addrs else "admin:unknown"


def _pending_count(session: Session, shop_id: int) -> int:
    return (
        session.execute(
            select(func.count())
            .select_from(models.Approval)
            .where(models.Approval.shop_id == shop_id, models.Approval.status == "pending")
        ).scalar()
        or 0
    )


def _shop_row(session: Session, shop: models.Shop) -> dict:
    month = caps.month_key()
    cap = caps.cap_status(session, shop)
    spend = caps.mtd_spend(session, shop.id, month)
    margin = caps.margin_status(shop.plan, spend["total_ngn"])
    return {
        "shop": shop,
        "used": cap["used"],
        "cap": cap["cap"],
        "ratio": cap["ratio"],
        "blocked": cap["blocked"],
        "spend": spend,
        "margin": margin,
        "pending": _pending_count(session, shop.id),
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "admin_index.html", {"actor": operator_actor()})


@router.get("/shops", response_class=HTMLResponse)
def shops(request: Request, q: str = ""):
    session = _session()
    try:
        stmt = select(models.Shop).order_by(models.Shop.name)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(models.Shop.name.ilike(like), models.Shop.whatsapp_number.ilike(like))
            )
        rows = [_shop_row(session, s) for s in session.execute(stmt).scalars()]
        return templates.TemplateResponse(
            request, "admin_shops.html", {"rows": rows, "q": q, "actor": operator_actor()}
        )
    finally:
        session.close()


@router.post("/shops")
def create_shop(name: str = Form(...), whatsapp_number: str = Form(...), plan: str = Form("pilot")):
    plan = plan if plan in VALID_PLANS else "pilot"
    session = _session()
    try:
        shop = models.Shop(
            name=name.strip(),
            whatsapp_number=whatsapp_number.strip(),
            plan=plan,
            stage="onboarding",
            stage_changed_at=dt.datetime.now(dt.timezone.utc),
            monthly_cap=caps.PLAN_CAPS.get(plan, 100),
        )
        session.add(shop)
        session.commit()
        shop_id = shop.id
    finally:
        session.close()
    return RedirectResponse(f"/admin/shops/{shop_id}", status_code=303)


@router.get("/shops/{shop_id}", response_class=HTMLResponse)
def shop_detail(request: Request, shop_id: int):
    session = _session()
    try:
        shop = session.get(models.Shop, shop_id)
        if shop is None:
            return HTMLResponse("shop not found", status_code=404)
        row = _shop_row(session, shop)
        pending = session.execute(
            select(models.Approval)
            .where(models.Approval.shop_id == shop_id, models.Approval.status == "pending")
            .order_by(models.Approval.created_at)
        ).scalars()
        changes = session.execute(
            select(models.PlanChange)
            .where(models.PlanChange.shop_id == shop_id)
            .order_by(desc(models.PlanChange.created_at))
            .limit(10)
        ).scalars()
        return templates.TemplateResponse(
            request,
            "admin_shop.html",
            {
                "row": row,
                "pending": list(pending),
                "changes": list(changes),
                "plans": VALID_PLANS,
                "stages": VALID_STAGES,
                "actor": operator_actor(),
            },
        )
    finally:
        session.close()


@router.post("/shops/{shop_id}/profile")
def update_profile(
    shop_id: int,
    plan: str = Form(...),
    approval_limit_ngn: int = Form(...),
    stage: str = Form(...),
    monthly_cap: int = Form(...),
    cap_override_reason: str = Form(""),
    plan_reason: str = Form(""),
):
    session = _session()
    try:
        shop = session.get(models.Shop, shop_id)
        if shop is None:
            return HTMLResponse("shop not found", status_code=404)
        if plan not in VALID_PLANS or stage not in VALID_STAGES:
            return HTMLResponse("bad plan or stage", status_code=400)
        if approval_limit_ngn < 0 or monthly_cap < 0:
            return HTMLResponse("limit and cap must be >= 0", status_code=400)
        if plan != shop.plan:
            session.add(
                models.PlanChange(
                    shop_id=shop.id,
                    from_plan=shop.plan,
                    to_plan=plan,
                    actor=operator_actor(),
                    reason=plan_reason.strip(),
                )
            )
            shop.plan = plan
            if not cap_override_reason.strip():
                shop.monthly_cap = caps.PLAN_CAPS.get(plan, 100)
        shop.approval_limit_ngn = approval_limit_ngn
        if stage != shop.stage:
            shop.stage = stage
            shop.stage_changed_at = dt.datetime.now(dt.timezone.utc)
        shop.monthly_cap = monthly_cap
        shop.cap_override_reason = cap_override_reason.strip() or None
        session.commit()
    finally:
        session.close()
    return RedirectResponse(f"/admin/shops/{shop_id}", status_code=303)


@router.post("/shops/{shop_id}/overage")
def sell_overage(shop_id: int):
    session = _session()
    try:
        shop = session.get(models.Shop, shop_id)
        if shop is None:
            return HTMLResponse("shop not found", status_code=404)
        session.add(
            models.OveragePack(
                shop_id=shop.id,
                conversations=caps.OVERAGE_PACK_CONVOS,
                amount_ngn=caps.OVERAGE_PACK_NGN,
                month=caps.month_key(),
            )
        )
        session.commit()
    finally:
        session.close()
    return RedirectResponse(f"/admin/shops/{shop_id}", status_code=303)


@router.get("/shops/{shop_id}/prices", response_class=HTMLResponse)
def prices(request: Request, shop_id: int):
    session = _session()
    try:
        shop = session.get(models.Shop, shop_id)
        if shop is None:
            return HTMLResponse("shop not found", status_code=404)
        items = session.execute(
            select(models.PriceListItem)
            .where(
                models.PriceListItem.shop_id == shop_id,
                models.PriceListItem.is_active.is_(True),
            )
            .order_by(models.PriceListItem.name)
        ).scalars()
        return templates.TemplateResponse(
            request,
            "admin_prices.html",
            {"shop": shop, "items": list(items), "actor": operator_actor()},
        )
    finally:
        session.close()


@router.post("/shops/{shop_id}/prices")
def add_price(
    shop_id: int, name: str = Form(...), unit: str = Form("each"), price_ngn: int = Form(...)
):
    if price_ngn < 0 or not name.strip():
        return HTMLResponse("bad price row", status_code=400)
    session = _session()
    try:
        session.add(
            models.PriceListItem(
                shop_id=shop_id,
                name=name.strip(),
                unit=unit.strip() or "each",
                price_ngn=price_ngn,
            )
        )
        session.commit()
    finally:
        session.close()
    return RedirectResponse(f"/admin/shops/{shop_id}/prices", status_code=303)


@router.post("/shops/{shop_id}/prices/bulk")
def bulk_prices(shop_id: int, bulk: str = Form(...)):
    rows, errors = caps.parse_bulk_prices(bulk)
    session = _session()
    try:
        for row in rows:
            session.add(models.PriceListItem(shop_id=shop_id, **row))
        session.commit()
    finally:
        session.close()
    if errors:
        return HTMLResponse(
            f"added {len(rows)}, rejected lines:<br>" + "<br>".join(errors),
            status_code=400,
        )
    return RedirectResponse(f"/admin/shops/{shop_id}/prices", status_code=303)


@router.post("/shops/{shop_id}/prices/{item_id}/deactivate")
def deactivate_price(shop_id: int, item_id: int):
    """Deactivate only — rows are never hard-deleted (dispute history)."""
    session = _session()
    try:
        item = session.get(models.PriceListItem, item_id)
        if item is None or item.shop_id != shop_id:
            return HTMLResponse("row not found", status_code=404)
        item.is_active = False
        session.commit()
    finally:
        session.close()
    return RedirectResponse(f"/admin/shops/{shop_id}/prices", status_code=303)


@router.get("/approvals", response_class=HTMLResponse)
def approvals_inbox(request: Request, status: str = "pending"):
    session = _session()
    try:
        stmt = (
            select(models.Approval, models.Shop.name)
            .join(models.Shop, models.Shop.id == models.Approval.shop_id)
            .order_by(models.Approval.created_at)
        )
        if status == "pending":
            stmt = stmt.where(models.Approval.status == "pending")
        else:
            stmt = stmt.where(models.Approval.status != "pending").order_by(
                desc(models.Approval.created_at)
            )
        rows = []
        for approval, shop_name in session.execute(stmt):
            age = caps.approval_age_hours(approval)
            rows.append(
                {"a": approval, "shop": shop_name, "age_h": age, "sla": caps.sla_level(age)}
            )
        return templates.TemplateResponse(
            request,
            "admin_approvals.html",
            {"rows": rows, "status": status, "actor": operator_actor()},
        )
    finally:
        session.close()


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: int, decision: str = Form(...)):
    if decision not in ("approved", "rejected"):
        return HTMLResponse("bad decision", status_code=400)
    session = _session()
    try:
        approval = session.get(models.Approval, approval_id)
        if approval is None:
            return HTMLResponse("approval not found", status_code=404)
        approvals.decide_approval(session, approval, decision, operator_actor())
    finally:
        session.close()
    return RedirectResponse("/admin/approvals?status=pending", status_code=303)


@router.get("/shops/{shop_id}/{tab}", response_class=HTMLResponse)
def money_tab(request: Request, shop_id: int, tab: str, status: str = "", page: int = 1):
    if tab not in ("orders", "invoices", "payments", "messages"):
        return HTMLResponse("bad tab", status_code=404)
    session = _session()
    try:
        shop = session.get(models.Shop, shop_id)
        if shop is None:
            return HTMLResponse("shop not found", status_code=404)
        model = {
            "orders": models.Order,
            "invoices": models.Invoice,
            "payments": models.Payment,
            "messages": models.MessageLog,
        }[tab]
        stmt = (
            select(model)
            .where(model.shop_id == shop_id)
            .order_by(desc(model.created_at))
            .limit(PAGE)
            .offset((max(page, 1) - 1) * PAGE)
        )
        if status and hasattr(model, "status"):
            stmt = stmt.where(model.status == status)
        rows = list(session.execute(stmt).scalars())
        return templates.TemplateResponse(
            request,
            "admin_money.html",
            {
                "shop": shop,
                "tab": tab,
                "rows": rows,
                "status": status,
                "page": page,
                "actor": operator_actor(),
            },
        )
    finally:
        session.close()


@router.get("/costs", response_class=HTMLResponse)
def costs_page(request: Request, month: str = ""):
    session = _session()
    try:
        month = month or caps.month_key()
        rows, totals = [], {"meta": 0.0, "ai": 0.0, "price": 0}
        for shop in session.execute(select(models.Shop).order_by(models.Shop.name)).scalars():
            spend = caps.mtd_spend(session, shop.id, month)
            margin = caps.margin_status(shop.plan, spend["total_ngn"])
            convos = caps.mtd_conversations(session, shop.id, month)
            rows.append({"shop": shop, "spend": spend, "margin": margin, "convos": convos})
            totals["meta"] += spend["meta_ngn"]
            totals["ai"] += spend["ai_ngn"]
            totals["price"] += margin["price"]
        return templates.TemplateResponse(
            request,
            "admin_costs.html",
            {"rows": rows, "totals": totals, "month": month, "actor": operator_actor()},
        )
    finally:
        session.close()


@router.get("/leads", response_class=HTMLResponse)
def leads(request: Request):
    session = _session()
    try:
        rows = list(
            session.execute(select(models.Lead).order_by(desc(models.Lead.created_at))).scalars()
        )
        return templates.TemplateResponse(
            request,
            "admin_leads.html",
            {"rows": rows, "stages": VALID_LEAD_STAGES, "actor": operator_actor()},
        )
    finally:
        session.close()


@router.post("/leads")
def create_lead(
    name: str = Form(""),
    business: str = Form(""),
    contact: str = Form(...),
    source: str = Form("whatsapp"),
    plan_interest: str = Form("starter"),
):
    if not contact.strip():
        return HTMLResponse("contact is required", status_code=400)
    if plan_interest not in VALID_PLANS:
        plan_interest = "starter"
    session = _session()
    try:
        lead = models.Lead(
            name=name.strip(),
            business=business.strip(),
            contact=contact.strip(),
            source=source.strip() or "whatsapp",
            plan_interest=plan_interest,
        )
        session.add(lead)
        session.commit()
        lead_id = lead.id
    finally:
        session.close()
    ops_mail.send_mail(
        f"new lead: {business.strip() or contact.strip()}",
        f"name: {name.strip()}\nbusiness: {business.strip()}\ncontact: {contact.strip()}\n"
        f"source: {source.strip()}\nplan interest: {plan_interest}\nlead id: {lead_id}",
    )
    return RedirectResponse("/admin/leads", status_code=303)


@router.post("/leads/{lead_id}/stage")
def lead_stage(lead_id: int, stage: str = Form(...)):
    if stage not in VALID_LEAD_STAGES:
        return HTMLResponse("bad stage", status_code=400)
    session = _session()
    try:
        lead = session.get(models.Lead, lead_id)
        if lead is None:
            return HTMLResponse("lead not found", status_code=404)
        lead.stage = stage
        session.commit()
    finally:
        session.close()
    return RedirectResponse("/admin/leads", status_code=303)


@router.post("/leads/{lead_id}/convert")
def convert_lead(lead_id: int):
    session = _session()
    try:
        lead = session.get(models.Lead, lead_id)
        if lead is None:
            return HTMLResponse("lead not found", status_code=404)
        if lead.shop_id:
            return RedirectResponse(f"/admin/shops/{lead.shop_id}", status_code=303)
        plan = lead.plan_interest if lead.plan_interest in VALID_PLANS else "starter"
        shop = models.Shop(
            name=lead.business or lead.name or lead.contact,
            whatsapp_number=lead.contact,
            plan=plan,
            stage="onboarding",
            stage_changed_at=dt.datetime.now(dt.timezone.utc),
            monthly_cap=caps.PLAN_CAPS.get(plan, 100),
        )
        session.add(shop)
        session.flush()
        lead.shop_id = shop.id
        lead.stage = "converted"
        session.commit()
        shop_id = shop.id
    finally:
        session.close()
    return RedirectResponse(f"/admin/shops/{shop_id}", status_code=303)
