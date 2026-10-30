"""Periodic unpaid-reservation expiry for the merchant application."""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.db import SessionLocal
from app.commerce_orders import expire_due

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler(daemon=True)


def release_expired():
    try:
        with SessionLocal() as db:
            while expire_due(db) == 100:
                pass
    except Exception:
        log.exception("Unable to expire unpaid stock reservations; the next run will retry")


def start():
    if not scheduler.running:
        scheduler.add_job(release_expired, "interval", seconds=60, id="commerce_expiry",
                          replace_existing=True, coalesce=True, max_instances=1,
                          next_run_time=datetime.now(timezone.utc))
        scheduler.start()


def stop():
    if scheduler.running:
        scheduler.shutdown(wait=False)
