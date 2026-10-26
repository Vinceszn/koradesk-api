"""Webhook entrypoint: verify handshake, idempotent ingest, route, approve."""

import json

from fastapi import Depends, FastAPI, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import approvals, caps, costs, models, whatsapp
from app.admin import router as admin_router
from app.config import settings
from app.db import get_session, init_db
from app.pipelines import orders, payments
from app.scheduler import start as start_scheduler
from app.security import verify_signature

app = FastAPI(title="Kora Desk API")
app.include_router(admin_router)


@app.on_event("startup")
def on_startup() -> None:
    if settings.env == "dev":
        init_db()
    start_scheduler()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "env": settings.env}


@app.get("/favicon.ico")
def favicon_ico() -> Response:
    return Response(status_code=204)


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


async def _handle_button(session: Session, shop: models.Shop, sender: str, button_id: str) -> None:
    try:
        action, _kind, approval_id = button_id.split(":")
    except ValueError:
        return
    approval = session.get(models.Approval, int(approval_id or 0))
    if approval is None:
        return
    before = approval.status
    approvals.decide_approval(
        session, approval, "approved" if action == "approve" else "rejected", actor=sender
    )
    if before == "pending" and approval.status != "pending":
        await whatsapp.send_text(
            sender,
            "Approved. Logged and queued."
            if approval.status == "approved"
            else "Rejected. Nothing moved — tell me what to change.",
        )
        costs.log_meta_message(session, shop.id)


def _capped(session: Session, shop: models.Shop, sender: str) -> bool:
    """Cap gate in the send path: count the window, block billable sends at 100%."""
    caps.touch_conversation(session, shop.id, sender)
    return caps.cap_status(session, shop)["blocked"]


async def _send_capped_notice(sender: str, shop: models.Shop) -> None:
    await whatsapp.send_text(
        sender,
        f"Kora Desk is paused for {shop.name}: this month's message allowance is used up. "
        "Your shop owner has been notified — service resumes on renewal or top-up.",
    )


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
                    button_id = message.get("button", {}).get("payload", "") or message.get(
                        "interactive", {}
                    ).get("button_reply", {}).get("id", "")
                    await _handle_button(session, shop, sender, button_id)
                    continue
                if _capped(session, shop, sender):
                    await _send_capped_notice(sender, shop)
                    costs.log_meta_message(session, shop.id)
                    continue
                if msg_type == "text":
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
