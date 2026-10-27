"""APScheduler jobs: reminders, 6pm summaries, retention purge."""

import asyncio
import datetime as dt

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete, func, select

from app import caps, costs, models, ops_mail, whatsapp
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


def check_stuck_approvals(session=None) -> dict:
    """Page ops on SLA breaches. Hourly. Each approval mails once per level."""
    own = session is None
    session = session or SessionLocal()
    try:
        now = dt.datetime.now(dt.timezone.utc)
        amber, red = [], []
        for approval in session.execute(
            select(models.Approval).where(models.Approval.status == "pending")
        ).scalars():
            age = caps.approval_age_hours(approval, now)
            level = caps.sla_level(age)
            if level == "red" and not approval.escalated_red:
                approval.escalated_red = True
                approval.escalated = True
                red.append((approval, age))
            elif level == "amber" and not approval.escalated:
                approval.escalated = True
                amber.append((approval, age))
        session.commit()
        sent = {"amber": 0, "red": 0}
        if amber:
            lines = [
                f"#{a.id} {a.kind} shop={a.shop_id} age={age:.1f}h payload={a.payload_json[:120]}"
                for a, age in amber
            ]
            if ops_mail.send_mail(
                f"{len(amber)} approvals waiting >2h",
                "Stuck approvals (amber):\n" + "\n".join(lines),
            ):
                sent["amber"] = len(amber)
        if red:
            lines = [
                f"#{a.id} {a.kind} shop={a.shop_id} age={age:.1f}h payload={a.payload_json[:120]}"
                for a, age in red
            ]
            if ops_mail.send_mail(
                f"URGENT: {len(red)} approvals waiting >24h",
                "Money is waiting (red):\n" + "\n".join(lines),
            ):
                sent["red"] = len(red)
        return sent
    finally:
        if own:
            session.close()


def check_margins(session=None, month: str | None = None) -> list[str]:
    """Mail pricing-review alerts for sub-40% margin shops. Once per month each."""
    own = session is None
    session = session or SessionLocal()
    try:
        month = month or caps.month_key()
        alerted = []
        for shop in session.execute(select(models.Shop)).scalars():
            spend = caps.mtd_spend(session, shop.id, month)
            margin = caps.margin_status(shop.plan, spend["total_ngn"])
            if margin["flag"] != "red":
                continue
            exists = session.execute(
                select(models.OpsAlert).where(
                    models.OpsAlert.kind == "margin",
                    models.OpsAlert.shop_id == shop.id,
                    models.OpsAlert.period == month,
                )
            ).scalar_one_or_none()
            if exists:
                continue
            if ops_mail.send_mail(
                f"margin review: {shop.name} at {(margin['margin'] or 0) * 100:.1f}%",
                f"Shop: {shop.name} (plan {shop.plan} ₦{margin['price']:,})\n"
                f"Month: {month}\nSpend: ₦{spend['total_ngn']:,.0f} "
                f"(Meta ₦{spend['meta_ngn']:,.0f} + AI ₦{spend['ai_ngn']:,.0f})\n"
                f"Margin: {(margin['margin'] or 0) * 100:.1f}% — below the 40% floor.\n"
                "Per pricing rules: review pricing before next month.",
            ):
                session.add(models.OpsAlert(kind="margin", shop_id=shop.id, period=month))
                session.commit()
                alerted.append(shop.name)
        return alerted
    finally:
        if own:
            session.close()


def start() -> None:
    scheduler.add_job(_reminders_job, "cron", hour=9, minute=0)
    scheduler.add_job(_summary_job, "cron", hour=settings.daily_summary_hour, minute=5)
    scheduler.add_job(_purge_job, "cron", day=1, hour=3, minute=0)
    scheduler.add_job(check_stuck_approvals, "interval", hours=1)
    scheduler.add_job(check_margins, "interval", days=1)
    scheduler.start()
