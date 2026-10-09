"""Per-shop spend ledger. Pricing review depends on this data existing."""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import settings


def today_key() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def _row(session: Session, shop_id: int | None, day: str) -> models.CostLedger:
    row = session.execute(
        select(models.CostLedger).where(
            models.CostLedger.shop_id == shop_id, models.CostLedger.day == day
        )
    ).scalar_one_or_none()
    if row is None:
        row = models.CostLedger(
            shop_id=shop_id, day=day, messages=0, meta_cost_ngn=0, ai_cost_ngn=0
        )
        session.add(row)
        session.flush()
    return row


def log_meta_message(session: Session, shop_id: int | None, count: int = 1) -> None:
    row = _row(session, shop_id, today_key())
    row.messages += count
    row.meta_cost_ngn = float(row.meta_cost_ngn) + settings.meta_cost_per_msg_ngn * count
    session.commit()


def log_ai_conversation(session: Session, shop_id: int | None) -> None:
    row = _row(session, shop_id, today_key())
    row.ai_cost_ngn = float(row.ai_cost_ngn) + settings.ai_cost_per_conversation_ngn
    session.commit()
