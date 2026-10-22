"""Account mail delivery. Preview files never become public web assets."""
import os
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit
from app.config import settings

def configuration():
    mode = os.getenv("COMMERCE_MAIL_MODE", "disabled")
    origin = os.getenv("COMMERCE_PUBLIC_URL", "").rstrip("/")
    parsed = urlsplit(origin)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or not parsed.hostname:
        raise RuntimeError("Configure a public origin for account links.")
    if mode == "file" and settings.env == "dev" and parsed.hostname in ("127.0.0.1","localhost") and parsed.scheme == "http":
        return mode, origin
    if mode == "smtp" and parsed.scheme == "https" and os.getenv("COMMERCE_SMTP_HOST") and os.getenv("COMMERCE_MAIL_FROM"):
        return mode, origin
    raise RuntimeError("Account email delivery is not configured.")

def send_account_mail(email, purpose, token):
    mode, origin = configuration()
    message = EmailMessage()
    message["From"] = os.getenv("COMMERCE_MAIL_FROM", "preview@localhost")
    message["To"] = email
    message["Subject"] = "Verify your Kora email" if purpose in ("verify", "email") else "Reset your Kora password"
    link = origin + "/account/" + ("email-confirm" if purpose == "email" else purpose) + "/" + token
    message.set_content(("Confirm your email address" if purpose in ("verify", "email") else "Choose a new password") +
                        " using this single-use link:\n\n" + link +
                        "\n\nThis link expires in 30 minutes. If you did not request it, ignore this email.")
    deliver(message, mode)


def send_security_notice(email, text):
    mode, _ = configuration()
    message = EmailMessage()
    message["From"] = os.getenv("COMMERCE_MAIL_FROM", "preview@localhost")
    message["To"] = email
    message["Subject"] = "Kora account security notice"
    message.set_content(text)
    deliver(message, mode)


def deliver(message, mode):
    if mode == "file":
        directory = Path(os.getenv("COMMERCE_MAIL_DIRECTORY", "work/mailbox"))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (uuid.uuid4().hex + ".eml")).write_bytes(message.as_bytes())
        return
    with smtplib.SMTP(os.environ["COMMERCE_SMTP_HOST"], int(os.getenv("COMMERCE_SMTP_PORT", "587")), timeout=15) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        if os.getenv("COMMERCE_SMTP_USER"):
            smtp.login(os.environ["COMMERCE_SMTP_USER"], os.environ["COMMERCE_SMTP_PASSWORD"])
        smtp.send_message(message)
