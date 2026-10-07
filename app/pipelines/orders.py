"""Orders pipeline: voice/text/photo → extracted lines → draft → approval.

AI extraction (Whisper + mini-LLM) plugs in at `transcribe_voice` and
`extract_lines`. Both currently return deterministic stubs so the full loop —
ingest, draft, approval buttons, ledger write — runs end to end without keys.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import costs, models, whatsapp
from app.matching import price_lookup


async def transcribe_voice(media_bytes: bytes) -> str:
    """Phase 1: self-hosted faster-whisper + Naija fine-tune. Stub for now."""
    _ = media_bytes
    return "3 bags rice, 2 cartons indomie, 1 gallon oil"


async def extract_lines(text: str) -> list[dict]:
    """Phase 1: mini-LLM JSON extraction. Stub returns demo lines."""
    _ = text
    return [
        {"item": "50kg rice", "qty": 3, "unit": "bags"},
        {"item": "Indomie carton", "qty": 2, "unit": "cartons"},
        {"item": "25L cooking oil", "qty": 1, "unit": "gallons"},
    ]


def price_lines(session: Session, shop_id: int, lines: list[dict]) -> tuple[list[dict], int]:
    catalog = [
        (name, price)
        for name, price in session.execute(
            select(models.PriceListItem.name, models.PriceListItem.price_ngn).where(
                models.PriceListItem.shop_id == shop_id
            )
        ).all()
    ]
    priced, total = [], 0
    for line in lines:
        match = price_lookup(line["item"], catalog)
        if match is None:
            priced.append({**line, "price_ngn": None, "unmatched": True})
            continue
        name, price = match
        line_total = price * int(line.get("qty", 1))
        total += line_total
        priced.append({**line, "matched": name, "price_ngn": price, "line_total": line_total})
    return priced, total


def format_draft(customer: str, priced: list[dict], total: int, ref: str) -> str:
    rows = []
    for line in priced:
        if line.get("unmatched"):
            rows.append(f"• {line['qty']} × {line['item']} — price missing, please confirm")
        else:
            rows.append(f"• {line['qty']} × {line['matched']} — ₦{line['line_total']:,}")
    return (
        f"Order draft for {customer} ({ref}):\n"
        + "\n".join(rows)
        + f"\nTotal ₦{total:,}. Reply YES to confirm."
    )


async def handle_customer_message(
    session: Session,
    shop: models.Shop,
    sender: str,
    customer: str,
    text: str,
    voice_bytes: bytes | None = None,
) -> None:
    if voice_bytes is not None:
        text = await transcribe_voice(voice_bytes)
    lines = await extract_lines(text)
    costs.log_ai_conversation(session, shop.id)
    priced, total = price_lines(session, shop.id, lines)

    order = models.Order(
        shop_id=shop.id,
        customer_name=customer,
        lines_json=json.dumps(priced),
        total_ngn=total,
        status="draft",
    )
    session.add(order)
    session.commit()

    needs_approval = total >= shop.approval_limit_ngn or any(
        line.get("unmatched") for line in priced
    )
    if needs_approval:
        approval = models.Approval(
            shop_id=shop.id,
            kind="order_draft",
            payload_json=json.dumps({"order_id": order.id, "total_ngn": total}),
            status="pending",
        )
        session.add(approval)
        session.commit()
        await whatsapp.send_approval(
            sender,
            f"Order draft ₦{total:,}",
            format_draft(customer, priced, total, f"OD-{order.id}"),
            approve_id=f"approve:order:{approval.id}",
            reject_id=f"reject:order:{approval.id}",
        )
    else:
        order.status = "confirmed"
        session.commit()
        await whatsapp.send_text(
            sender, format_draft(customer, priced, total, f"OD-{order.id}")
        )
    costs.log_meta_message(session, shop.id)
