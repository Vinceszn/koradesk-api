import secrets

import pytest
from sqlalchemy import func, select

from app import commerce_models as m
from tests.test_commerce import client, product
from tests.test_commerce import env as env


def setup(c, quantity=10):
    assert product(c).status_code == 303
    assert (
        c.post(
            "/app/1/stock/1", data={"csrf": "csrf1", "quantity": quantity}, follow_redirects=False
        ).status_code
        == 303
    )
    assert (
        c.post(
            "/app/1/suppliers",
            data={"csrf": "csrf1", "name": "Trusted supplier", "email": "sales@example.com"},
            follow_redirects=False,
        ).status_code
        == 303
    )


def payload(**values):
    data = dict(
        csrf="csrf1",
        key=secrets.token_hex(24),
        kind="receive",
        quantity="5",
        supplier_id="1",
        unit_cost="123.45",
        reference="INV-123",
        reason="Delivery checked",
    )
    data.update(values)
    return data


def change(c, data, merchant=1, variant=1):
    return c.post(f"/app/{merchant}/inventory/{variant}/change", data=data, follow_redirects=False)


def assert_stock(env, expected, entries):
    with env() as db:
        assert db.scalar(select(m.Balance.on_hand)) == expected
        assert db.scalar(select(func.sum(m.Movement.quantity))) == expected
        assert db.scalar(select(func.count()).select_from(m.Movement)) == entries


def test_receive_replay_and_supplier_snapshot(env):
    c = client()
    setup(c)
    data = payload()
    assert change(c, data).status_code == 303
    assert change(c, data).status_code == 303
    assert change(c, dict(data, quantity="6")).status_code == 409
    assert_stock(env, 15, 2)
    c.post(
        "/app/1/suppliers/1", data={"csrf": "csrf1", "name": "Renamed supplier", "archived": "yes"}
    )
    with env() as db:
        op = db.scalar(select(m.StockOperation))
        assert op.unit_cost_kobo == 12345 and op.reference == "INV-123"
        assert op.supplier_name == "Trusted supplier"
    assert change(c, payload()).status_code == 404
    assert "Trusted supplier" in c.get("/app/1/inventory").text
    assert "Renamed supplier" in c.get("/app/1/suppliers").text
    assert_stock(env, 15, 2)


def test_adjust_recount_stale_and_reverse(env):
    c = client()
    setup(c)
    assert change(c, payload(kind="adjust", quantity="-3", reason="Damaged")).status_code == 303
    with env() as db:
        version = db.scalar(select(m.Balance.version))
    assert change(c, payload(kind="recount", quantity="9", version=version)).status_code == 303
    assert change(c, payload(kind="recount", quantity="11", version=version)).status_code == 409
    # Recounting the same total still records the audit event.
    assert change(c, payload(kind="recount", quantity="9", version=version + 1)).status_code == 303
    assert (
        change(
            c, payload(kind="reverse", reverses_id="2", reason="Damage entry was wrong")
        ).status_code
        == 303
    )
    assert change(c, payload(kind="reverse", reverses_id="2")).status_code == 409
    assert change(c, payload(kind="reverse", reverses_id="5")).status_code == 400
    assert change(c, payload(kind="reverse", reverses_id="1")).status_code == 400
    assert_stock(env, 12, 5)
    page = c.get("/app/1/inventory")
    assert (
        page.status_code == 200 and "All balances match" in page.text and "Reverses #2" in page.text
    )
    assert "-3" in c.get("/app/1").text and "+-3" not in c.get("/app/1").text


def test_reserved_and_insufficient_stock_rollback(env):
    c = client()
    setup(c)
    with env() as db:
        db.scalar(select(m.Balance)).reserved = 8
        db.commit()
    assert change(c, payload(kind="adjust", quantity="-3")).status_code == 409
    assert change(c, payload(kind="recount", quantity="7", version=2)).status_code == 409
    assert change(c, payload(quantity="1000000")).status_code == 409
    assert_stock(env, 10, 1)
    assert change(c, payload(quantity="5")).status_code == 303
    assert change(c, payload(kind="adjust", quantity="-7")).status_code == 303
    assert change(c, payload(kind="reverse", reverses_id=2)).status_code == 409
    assert_stock(env, 8, 3)


@pytest.mark.parametrize(
    "values",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"quantity": "1.5"},
        {"unit_cost": "NaN"},
        {"unit_cost": "-1"},
        {"unit_cost": "0.001"},
        {"reason": ""},
        {"kind": "unknown"},
        {"key": "bad"},
        {"kind": "adjust", "quantity": "0"},
        {"kind": "recount", "quantity": "-1", "version": 2},
    ],
)
def test_validation_leaves_no_changes(env, values):
    c = client()
    setup(c)
    assert change(c, payload(**values)).status_code == 400
    assert_stock(env, 10, 1)


def test_stock_permissions_csrf_and_foreign_ids(env):
    c = client()
    setup(c)
    for path in ("inventory/1", "suppliers", "suppliers/1"):
        assert client(2).get("/app/1/" + path).status_code == 404
        assert client(3).get("/app/1/" + path).status_code == 403
    assert client(3).get("/app/1/inventory").status_code == 200
    for path in ("inventory/1/change", "inventory/1/threshold", "suppliers", "suppliers/1"):
        assert client(3).post("/app/1/" + path, data={"csrf": "csrf3"}).status_code == 403
    assert change(c, payload(csrf="wrong")).status_code == 403
    assert change(client(2), payload(csrf="csrf2"), merchant=2).status_code == 404
    assert (
        c.post("/app/1/inventory/1/threshold", data={"csrf": "bad", "threshold": 8}).status_code
        == 403
    )
    assert (
        client(2)
        .post("/app/2/inventory/1/threshold", data={"csrf": "csrf2", "threshold": 8})
        .status_code
        == 404
    )
    assert (
        client(2).post("/app/2/suppliers/1", data={"csrf": "csrf2", "name": "Intruder"}).status_code
        == 404
    )
    client(2).post("/app/2/suppliers", data={"csrf": "csrf2", "name": "Other supplier"})
    assert change(c, payload(supplier_id=2)).status_code == 404
    assert_stock(env, 10, 1)


def test_low_stock_archive_and_uncounted(env):
    c = client()
    setup(c)
    assert (
        c.post("/app/1/inventory/1/threshold", data={"csrf": "csrf1", "threshold": 10}).status_code
        == 200
    )
    assert "Low stock · ≤ 10" in c.get("/app/1/inventory").text
    assert (
        c.post("/app/1/inventory/1/threshold", data={"csrf": "csrf1", "threshold": -1}).status_code
        == 400
    )
    c.post("/app/1/variants/1/archive", data={"csrf": "csrf1", "action": "archive"})
    assert change(c, payload()).status_code == 409
    assert "Low stock · ≤ 10" not in c.get("/app/1/inventory").text
    assert change(c, payload(kind="adjust", quantity="-1")).status_code == 303
    product(c, sku="NEW")
    assert change(c, payload(), variant=2).status_code == 409
    assert "Start with an opening count" in c.get("/app/1/inventory/2").text


def test_reconciliation_detects_corruption_and_blocks_changes(env):
    c = client()
    setup(c)
    with env() as db:
        db.scalar(select(m.Balance)).on_hand = 20
        db.commit()
    assert "Differences found" in c.get("/app/1/inventory").text
    assert change(c, payload()).status_code == 409
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Movement)) == 1


def test_stock_pages_empty_and_populated(env):
    c = client()
    assert c.get("/app/1/inventory").status_code == 200
    assert c.get("/app/1/suppliers").status_code == 200
    setup(c)
    assert c.get("/app/1/inventory/1").status_code == 200
    assert c.get("/app/1/suppliers/1").status_code == 200
    assert c.get("/app/1/suppliers/999").status_code == 404
    assert c.get("/app/1/inventory/999").status_code == 404
    assert c.get("/app/1/inventory?page=-1").status_code == 400


def test_old_history_is_accessible_and_reconciled(env):
    c = client()
    setup(c)
    with env() as db:
        for i in range(101):
            db.add(
                m.Movement(
                    merchant_id=1,
                    location_id=1,
                    variant_id=1,
                    actor_id=1,
                    quantity=0,
                    reason=f"Audit {i}",
                    idempotency_key=f"audit:{i}",
                    at=100 + i,
                )
            )
        db.commit()
    first = c.get("/app/1/inventory").text
    second = c.get("/app/1/inventory?page=2").text
    assert "Older entries" in first and "Opening physical count" not in first
    assert "Opening physical count" in second and "Newer entries" in second
    assert "All balances match" in first


def test_metadata_failure_rolls_back_balance_and_movement(env):
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError

    c = client()
    setup(c)

    def reject_metadata(session, *_):
        if any(isinstance(row, m.StockOperation) for row in session.new):
            raise IntegrityError(
                "simulated metadata constraint failure", {}, Exception("constraint")
            )

    event.listen(env.class_, "before_flush", reject_metadata)
    try:
        assert change(c, payload()).status_code == 409
    finally:
        event.remove(env.class_, "before_flush", reject_metadata)
    assert_stock(env, 10, 1)
