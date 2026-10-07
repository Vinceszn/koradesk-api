"""Webhook entrypoint: verify handshake, idempotent ingest, route, approve."""

import datetime as dt
import json

from fastapi import Depends, FastAPI, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import costs, models, whatsapp
from app.config import settings
from app.db import get_session, init_db
from app.pipelines import orders, payments
from app.scheduler import start as start_scheduler
from app.security import verify_signature

app = FastAPI(title="Kora Desk API")


@app.on_event("startup")
def on_startup() -> None:
    if settings.env == "dev":
        init_db()
    start_scheduler()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "env": settings.env}


@app.get("/webhook/receive")
def verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
) -> Response:
    if hub_mode == "subscribe" and hub_verify_token == settings.verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="forbidden", status_code=403)


def _shop_for(session: Session, business_number: str) -> models.Shop | None:
    return session.execute(
        select(models.Shop).where(models.Shop.whatsapp_number == business_number)
    ).scalar_one_or_none()


async def _handle_button(
    session: Session, shop: models.Shop, sender: str, button_id: str
) -> None:
    try:
        action, kind, approval_id = button_id.split(":")
    except ValueError:
        return
    approval = session.get(models.Approval, int(approval_id or 0))
    if approval is None or approval.status != "pending":
        return
    approval.status = "approved" if action == "approve" else "rejected"
    approval.decided_by = sender
    approval.decided_at = dt.datetime.now(dt.timezone.utc)
    session.commit()
    if approval.status == "approved" and kind == "order":
        payload = json.loads(approval.payload_json)
        order = session.get(models.Order, payload.get("order_id"))
        if order is not None:
            order.status = "confirmed"
            session.commit()
    await whatsapp.send_text(
        sender,
        "Approved. Logged and queued." if approval.status == "approved" else "Rejected. Nothing moved — tell me what to change.",
    )
    costs.log_meta_message(session, shop.id)


@app.post("/webhook/receive")
async def receive(request: Request, session: Session = Depends(get_session)) -> dict:
    raw = await request.body()
    if not verify_signature(settings.app_secret, raw, request.headers.get("X-Hub-Signature-256")):
        return {"ok": False, "error": "bad signature"}
    payload = json.loads(raw or b"{}")

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            business_number = value.get("metadata", {}).get("display_phone_number", "")
            shop = _shop_for(session, business_number)
            for message in value.get("messages", []):
                meta_id = message.get("id", "")
                try:
                    session.add(
                        models.MessageLog(
                            shop_id=shop.id if shop else None,
                            meta_message_id=meta_id,
                            direction="in",
                            kind=message.get("type", "text"),
                            body=json.dumps(message)[:2000],
                        )
                    )
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    continue  # Meta retried a webhook we already handled
                if shop is None:
                    continue
                sender = message.get("from", "")
                await whatsapp.mark_read(meta_id)
                msg_type = message.get("type")
                if msg_type == "button" or (
                    msg_type == "interactive"
                    and message.get("interactive", {}).get("type") == "button_reply"
                ):
                    button_id = (
                        message.get("button", {}).get("payload", "")
                        or message.get("interactive", {}).get("button_reply", {}).get("id", "")
                    )
                    await _handle_button(session, shop, sender, button_id)
                elif msg_type == "text":
                    await orders.handle_customer_message(
                        session,
                        shop,
                        sender,
                        customer=sender,
                        text=message.get("text", {}).get("body", ""),
                    )
                elif msg_type == "audio":
                    await whatsapp.send_text(
                        sender, "Voice note received — transcription plugs in at Phase 1."
                    )
                    costs.log_meta_message(session, shop.id)
                elif msg_type == "image":
                    await payments.handle_bank_alert(
                        session, shop, sender, "[screenshot received]", source="screenshot"
                    )
                else:
                    await whatsapp.send_text(
                        sender, "I can read text, voice notes, and photos. Try one of those."
                    )
                    costs.log_meta_message(session, shop.id)
    return {"ok": True}
