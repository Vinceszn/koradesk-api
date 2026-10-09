"""Plan caps, margin math, SLA helpers. Pure where possible (unit-tested)."""

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models

# Seeded monthly conversation caps per plan (spec data delta 2).
PLAN_CAPS = {"pilot": 100, "starter": 300, "growth": 1200, "partner": 150}
PLAN_PRICES_NGN = {"pilot": 0, "starter": 15000, "growth": 45000, "partner": 8000}

OVERAGE_PACK_NGN = 5000
OVERAGE_PACK_CONVOS = 100

MARGIN_RED_BELOW = 0.40
SLA_AMBER_HOURS = 2
SLA_RED_HOURS = 24


def month_key(when: dt.datetime | None = None) -> str:
    when = when or dt.datetime.now(dt.timezone.utc)
    return when.strftime("%Y-%m")


def _month_range(month: str) -> tuple[dt.datetime, dt.datetime]:
    """Portable month bounds (works on SQLite and Postgres — no substr on dates)."""
    year, mon = (int(p) for p in month.split("-"))
    start = dt.datetime(year, mon, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=dt.timezone.utc)
    return start, end


def effective_cap(session: Session, shop: models.Shop, month: str | None = None) -> int:
    """Base cap (override wins over plan seed) + overage packs sold this month."""
    month = month or month_key()
    base = shop.monthly_cap if shop.monthly_cap is not None else PLAN_CAPS.get(shop.plan, 100)
    packs = (
        session.execute(
            select(func.coalesce(func.sum(models.OveragePack.conversations), 0)).where(
                models.OveragePack.shop_id == shop.id, models.OveragePack.month == month
            )
        ).scalar()
        or 0
    )
    return base + packs


def mtd_conversations(session: Session, shop_id: int, month: str | None = None) -> int:
    """Conversations whose 24h window started this month."""
    start, end = _month_range(month or month_key())
    return (
        session.execute(
            select(func.count())
            .select_from(models.Conversation)
            .where(
                models.Conversation.shop_id == shop_id,
                models.Conversation.window_start >= start,
                models.Conversation.window_start < end,
            )
        ).scalar()
        or 0
    )


def cap_status(session: Session, shop: models.Shop) -> dict:
    used = mtd_conversations(session, shop.id)
    cap = effective_cap(session, shop)
    ratio = (used / cap) if cap else 1.0
    return {"used": used, "cap": cap, "ratio": ratio, "blocked": cap > 0 and used >= cap}


def touch_conversation(session: Session, shop_id: int, customer_key: str) -> models.Conversation:
    """Get-or-create the current 24h window for this customer. THE cap counter."""
    now = dt.datetime.now(dt.timezone.utc)
    row = session.execute(
        select(models.Conversation)
        .where(
            models.Conversation.shop_id == shop_id,
            models.Conversation.customer_key == customer_key,
            models.Conversation.window_start > now - dt.timedelta(hours=24),
        )
        .order_by(models.Conversation.window_start.desc())
    ).scalar_one_or_none()
    if row is None:
        row = models.Conversation(
            shop_id=shop_id, customer_key=customer_key, window_start=now, messages=0
        )
        session.add(row)
    row.messages += 1
    session.commit()
    return row


def mtd_spend(session: Session, shop_id: int, month: str | None = None) -> dict:
    month = month or month_key()
    start_day, end_day = f"{month}-01", _month_range(month)[1].strftime("%Y-%m-%d")
    meta, ai = (
        session.execute(
            select(
                func.coalesce(func.sum(models.CostLedger.meta_cost_ngn), 0),
                func.coalesce(func.sum(models.CostLedger.ai_cost_ngn), 0),
            ).where(
                models.CostLedger.shop_id == shop_id,
                models.CostLedger.day >= start_day,
                models.CostLedger.day < end_day,
            )
        ).one()
    )
    return {"meta_ngn": float(meta), "ai_ngn": float(ai), "total_ngn": float(meta) + float(ai)}


def margin_status(plan: str, spend_ngn: float) -> dict:
    """Margin vs plan price. Pilot (price 0) is unmeasurable — never red."""
    price = PLAN_PRICES_NGN.get(plan, 0)
    if not price:
        return {"price": 0, "margin": None, "flag": "grey"}
    margin = (price - spend_ngn) / price
    flag = "green" if margin >= MARGIN_RED_BELOW else "red"
    return {"price": price, "margin": margin, "flag": flag}


def approval_age_hours(approval: models.Approval, now: dt.datetime | None = None) -> float:
    now = now or dt.datetime.now(dt.timezone.utc)
    created = approval.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=dt.timezone.utc)
    return (now - created).total_seconds() / 3600


def sla_level(age_hours: float) -> str:
    if age_hours >= SLA_RED_HOURS:
        return "red"
    if age_hours >= SLA_AMBER_HOURS:
        return "amber"
    return "ok"


def parse_bulk_prices(text: str) -> tuple[list[dict], list[str]]:
    """Parse `name | unit | price` lines. Returns (rows, error_lines)."""
    rows, errors = [], []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            errors.append(line)
            continue
        name, unit, price_raw = parts
        try:
            price = int(price_raw.replace(",", "").replace("₦", "").strip())
        except ValueError:
            errors.append(line)
            continue
        if not name or price < 0:
            errors.append(line)
            continue
        rows.append({"name": name, "unit": unit or "each", "price_ngn": price})
    return rows, errors
