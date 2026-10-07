"""Payments pipeline: reminders out, alerts/screenshots in, fuzzy match.

Screenshot-only claims NEVER auto-clear (fraud vector) — they queue for
approval. Virtual-account webhooks (Paystack/Moniepoint, Phase 2) become the
primary signal; this fuzzy path stays as the fallback.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import costs, models, whatsapp
from app.matching import AUTO_CLEAR_THRESHOLD, parse_amount_naira, payment_match_score


def open_invoices(session: Session, shop_id: int) -> list[models.Invoice]:
    return list(
        session.execute(
            select(models.Invoice)
            .where(models.Invoice.shop_id == shop_id, models.Invoice.status == "open")
            .order_by(models.Invoice.created_at)
        ).scalars()
    )


async def handle_bank_alert(
    session: Session,
    shop: models.Shop,
    sender: str,
    alert_text: str,
    source: str = "alert",
) -> None:
    from app.matching import should_auto_clear

    amount = parse_amount_naira(alert_text)
    if amount is None:
        await whatsapp.send_text(
            sender, "I saw a transfer alert but could not read the amount. Please forward it as text."
        )
        costs.log_meta_message(session, shop.id)
        return

    best, best_score = None, 0.0
    for invoice in open_invoices(session, shop.id):
        score = payment_match_score(
            amount, sender, invoice.amount_ngn, "", same_day=True
        )
        if score > best_score:
            best, best_score = invoice, score

    payment = models.Payment(
        shop_id=shop.id,
        amount_ngn=amount,
        sender_hint=sender,
        source=source,
        status="unmatched",
    )
    session.add(payment)

    if best is not None and should_auto_clear(best_score, source):
        best.status = "paid"
        payment.invoice_id = best.id
        payment.status = "matched"
        session.commit()
        await whatsapp.send_text(
            sender,
            f"Matched ₦{amount:,} → Invoice {best.reference}. Receipt sent, books updated.",
        )
    else:
        session.commit()
        approval = models.Approval(
            shop_id=shop.id,
            kind="payment_match",
            payload_json=f'{{"payment_id": {payment.id}, "score": {best_score}}}',
            status="pending",
        )
        session.add(approval)
        session.commit()
        hint = f" Closest open invoice: {best.reference} (₦{best.amount_ngn:,})." if best else ""
        await whatsapp.send_approval(
            sender,
            f"Unmatched ₦{amount:,}",
            f"I could not confidently match ₦{amount:,}.{hint} Approve a manual match?",
            approve_id=f"approve:payment:{approval.id}",
            reject_id=f"reject:payment:{approval.id}",
        )
    costs.log_meta_message(session, shop.id)


async def send_reminders(session: Session) -> int:
    """Daily nudge for open invoices. Counts against the payment message budget."""
    from app import whatsapp as wa

    sent = 0
    for shop in session.execute(select(models.Shop)).scalars():
        for invoice in open_invoices(session, shop.id):
            await wa.send_text(
                shop.whatsapp_number,
                f"Reminder: Invoice {invoice.reference} · ₦{invoice.amount_ngn:,} is still open. Want me to nudge the customer?",
            )
            costs.log_meta_message(session, shop.id)
            sent += 1
    return sent
