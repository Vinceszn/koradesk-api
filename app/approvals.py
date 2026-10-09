"""One decision writer, two triggers (WhatsApp tap, admin inbox).

Both paths write the same `approvals` row + audit fields. Only the actor
differs: WhatsApp sender vs `admin:<email>` (real addresses from day one).
"""

import datetime as dt
import json

from sqlalchemy.orm import Session

from app import costs, models


def decide_approval(
    session: Session, approval: models.Approval, decision: str, actor: str
) -> models.Approval:
    """Apply approve/reject. Idempotent: non-pending rows are returned untouched."""
    if approval.status != "pending" or decision not in ("approved", "rejected"):
        return approval
    approval.status = decision
    approval.decided_by = actor
    approval.decided_at = dt.datetime.now(dt.timezone.utc)
    session.commit()
    if decision == "approved":
        try:
            payload = json.loads(approval.payload_json or "{}")
        except ValueError:
            payload = {}
        if approval.kind == "order_draft" and payload.get("order_id"):
            order = session.get(models.Order, payload["order_id"])
            if order is not None:
                order.status = "confirmed"
                session.commit()
        # payment_match approvals intentionally change nothing else on decide:
        # matching stays a human follow-up (same as the WhatsApp tap path).
    shop_id = approval.shop_id
    costs.log_meta_message(session, shop_id)
    return approval
