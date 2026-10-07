"""APScheduler jobs: reminders, 6pm summaries, retention purge."""

import asyncio
import datetime as dt

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete, func, select

from app import costs, models, whatsapp
from app.config import settings
from app.db import SessionLocal
from app.pipelines import payments

scheduler = BackgroundScheduler()


def _reminders_job() -> None:
    session = SessionLocal()
    try:
        asyncio.run(payments.send_reminders(session))
    finally:
        session.close()


def _summary_job() -> None:
    """6pm owner summary: today's confirmed sales + open invoices."""
    session = SessionLocal()
    try:
        today = dt.datetime.now(dt.timezone.utc).date()
        for shop in session.execute(select(models.Shop)).scalars():
            sales = (
                session.execute(
                    select(func.coalesce(func.sum(models.Order.total_ngn), 0)).where(
                        models.Order.shop_id == shop.id,
                        models.Order.status == "confirmed",
                        func.date(models.Order.created_at) == today,
                    )
                ).scalar()
                or 0
            )
            open_count = (
                session.execute(
                    select(func.count())
                    .select_from(models.Invoice)
                    .where(models.Invoice.shop_id == shop.id, models.Invoice.status == "open")
                ).scalar()
                or 0
            )
            asyncio.run(
                whatsapp.send_text(
                    shop.whatsapp_number,
                    f"Today: ₦{sales:,} confirmed sales. {open_count} invoices still open. Full breakdown in Books.",
                )
            )
            costs.log_meta_message(session, shop.id)
    finally:
        session.close()


def _purge_job() -> None:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * settings.retention_months)
    session = SessionLocal()
    try:
        session.execute(delete(models.MessageLog).where(models.MessageLog.created_at < cutoff))
        session.commit()
    finally:
        session.close()


def start() -> None:
    scheduler.add_job(_reminders_job, "cron", hour=9, minute=0)
    scheduler.add_job(
        _summary_job, "cron", hour=settings.daily_summary_hour, minute=5
    )
    scheduler.add_job(_purge_job, "cron", day=1, hour=3, minute=0)
    scheduler.start()
