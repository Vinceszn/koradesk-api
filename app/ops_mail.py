"""Ops mail: stuck approvals, margin alerts, new leads.

Recipients come from ADMIN_EMAILS (comma-separated, one address for now).
Add more recipients any time via env — no code change, no redeploy of logic.

Transport is plain SMTP from env. If SMTP_HOST is empty (local dev), mail is
logged instead of sent so nothing silently disappears.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("kora.ops_mail")


def parse_recipients(raw: str) -> list[str]:
    """Split on commas, strip, drop empties, dedupe (order kept)."""
    seen: set[str] = set()
    out: list[str] = []
    for chunk in (raw or "").split(","):
        addr = chunk.strip()
        if addr and addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def recipients() -> list[str]:
    return parse_recipients(settings.admin_emails)


def send_mail(subject: str, body: str, to: list[str] | None = None) -> bool:
    """Send to `to` (default: ADMIN_EMAILS). True if sent OR dev-logged."""
    dest = to or recipients()
    if not dest:
        log.warning("ops mail dropped (no recipients): %s", subject)
        return False
    if not settings.smtp_host:
        log.info("ops mail [dev-logged] to=%s subject=%s\n%s", dest, subject, body)
        return True
    msg = EmailMessage()
    msg["Subject"] = f"[Kora Ops] {subject}"
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(dest)
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.send_message(msg)
    except Exception:  # noqa: BLE001 — alerting must never crash the app
        log.exception("ops mail failed to=%s subject=%s", dest, subject)
        return False
    return True
