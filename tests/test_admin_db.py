"""DB-backed tests for money paths (SQLite, no network, no Postgres).

Uses its own in-memory engine — never touches app.db's engine.
"""

import datetime as dt
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import approvals, caps, models
from app.db import Base
from app.scheduler import check_margins, check_stuck_approvals


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _shop(session, **kw):
    args = {"name": "S", "whatsapp_number": "234800000001", "plan": "starter", "monthly_cap": 300}
    args.update(kw)
    shop = models.Shop(**args)
    session.add(shop)
    session.commit()
    return shop


def test_touch_conversation_counts_one_window(session):
    shop = _shop(session)
    c1 = caps.touch_conversation(session, shop.id, "cust-a")
    c2 = caps.touch_conversation(session, shop.id, "cust-a")
    assert c1.id == c2.id
    assert c2.messages == 2
    caps.touch_conversation(session, shop.id, "cust-b")
    assert caps.mtd_conversations(session, shop.id) == 2


def test_effective_cap_adds_packs(session):
    from app import models as m

    shop = _shop(session)
    assert caps.effective_cap(session, shop) == 300
    session.add(
        m.OveragePack(shop_id=shop.id, conversations=100, amount_ngn=5000, month=caps.month_key())
    )
    session.commit()
    assert caps.effective_cap(session, shop) == 400


def test_decide_approves_order_and_actor(session):
    shop = _shop(session)
    order = models.Order(shop_id=shop.id, customer_name="c", total_ngn=90000, status="draft")
    session.add(order)
    session.commit()
    approval = models.Approval(
        shop_id=shop.id,
        kind="order_draft",
        payload_json=json.dumps({"order_id": order.id}),
        status="pending",
    )
    session.add(approval)
    session.commit()
    approvals.decide_approval(session, approval, "approved", "admin:hello@koradesk.com")
    session.refresh(order)
    assert order.status == "confirmed"
    assert approval.decided_by == "admin:hello@koradesk.com"
    # idempotent: second decision changes nothing
    approvals.decide_approval(session, approval, "rejected", "admin:other@x.com")
    assert approval.status == "approved"
    assert approval.decided_by == "admin:hello@koradesk.com"


def test_sla_escalates_once_per_level(session):
    shop = _shop(session)
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=30)
    approval = models.Approval(
        shop_id=shop.id, kind="order_draft", payload_json="{}", status="pending", created_at=old
    )
    session.add(approval)
    session.commit()
    assert check_stuck_approvals(session) == {"amber": 0, "red": 1}
    session.refresh(approval)
    assert approval.escalated and approval.escalated_red
    assert check_stuck_approvals(session) == {"amber": 0, "red": 0}


def test_margin_alert_fires_once_per_month(session):
    shop = _shop(session)
    session.add(
        models.CostLedger(
            shop_id=shop.id,
            day=caps.month_key() + "-05",
            meta_cost_ngn=12000,
            ai_cost_ngn=1000,
            messages=10,
        )
    )
    session.commit()
    month = caps.month_key()
    assert check_margins(session, month) == ["S"]
    assert check_margins(session, month) == []


def test_first_cost_row_no_crash(session):
    """Regression: fresh ledger rows used to crash on None + 1."""
    from app import costs

    shop = _shop(session)
    costs.log_meta_message(session, shop.id)
    costs.log_ai_conversation(session, shop.id)
    spend = caps.mtd_spend(session, shop.id)
    assert spend["total_ngn"] > 0
