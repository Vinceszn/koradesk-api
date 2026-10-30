import time

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import commerce_models as m
from app.commerce_orders import expire_due
from tests.test_commerce import client, env, product


def stocked(c, sku="SHIRT-M", name="Everyday shirt", quantity=5, price="8500.25"):
    response = product(c, sku=sku, name=name, price=price)
    assert response.status_code == 303
    variant_id = int(response.headers.get("x-unused", 0) or 0)
    if not variant_id:
        # Tests create variants in deterministic order in the isolated database.
        page = c.get("/app/1/inventory")
        assert page.status_code == 200
    return sku


def open_stock(c, env, sku, quantity):
    with env() as db:
        variant_id = db.scalar(select(m.Variant.id).where(m.Variant.sku == sku))
    assert c.post(f"/app/1/stock/{variant_id}", data={"csrf": "csrf1", "quantity": str(quantity)}, follow_redirects=False).status_code == 303
    return variant_id


def draft(c, variant_ids, quantities, key="a" * 48, **extra):
    data = {"csrf": "csrf1", "key": key, "variant_id": [str(value) for value in variant_ids],
            "quantity": [str(value) for value in quantities], "customer_id": "",
            "customer_name": "", "customer_email": "", "customer_phone": ""}
    data.update(extra)
    return c.post("/app/1/orders/draft", data=data, follow_redirects=False)


def order_id(env, reference=None):
    with env() as db:
        query = select(m.CommerceOrder.id)
        if reference:
            query = query.where(m.CommerceOrder.reference == reference)
        return db.scalar(query.order_by(m.CommerceOrder.id.desc()))


def test_order_pages_roles_and_tenant_boundaries(env):
    owner = client()
    assert owner.get("/app/1/orders").status_code == 200
    assert owner.get("/app/1/orders/new").status_code == 200
    assert "Orders" in owner.get("/app/1/orders").text
    staff = client(3)
    assert staff.get("/app/1/orders").status_code == 200
    assert staff.get("/app/1/orders/new").status_code == 403
    assert client(2).get("/app/1/orders").status_code == 404
    assert staff.post("/app/1/orders/draft", data={"csrf": "csrf3"}).status_code == 403


def test_draft_retry_keeps_original_order_and_rejects_changed_input(env):
    c = client()
    stocked(c)
    variant_id = open_stock(c, env, "SHIRT-M", 5)
    first = draft(c, [variant_id], [1], customer_name="Ada")
    retry = draft(c, [variant_id], [1], customer_name="Ada")
    assert first.status_code == retry.status_code == 303
    assert retry.headers["location"].split("?")[0] == first.headers["location"].split("?")[0]
    assert draft(c, [variant_id], [1], customer_name="Someone else").status_code == 409
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.CommerceOrder)) == 1


def test_quantity_boundary():
    from fastapi import HTTPException
    from app.commerce_orders import _positive
    assert _positive("1000000") == 1000000
    with pytest.raises(HTTPException):
        _positive("1000001")


def test_background_expiry_drains_multiple_batches(env, monkeypatch):
    from app import commerce_expiry
    counts = iter([100, 100, 3])
    calls = []
    def run_batch(db):
        calls.append(db)
        return next(counts)
    monkeypatch.setattr(commerce_expiry, "SessionLocal", env)
    monkeypatch.setattr(commerce_expiry, "expire_due", run_batch)
    commerce_expiry.release_expired()
    assert len(calls) == 3


def test_merchant_lifespan_starts_and_stops_expiry(monkeypatch):
    from fastapi.testclient import TestClient
    from app import commerce, commerce_expiry
    events = []
    monkeypatch.setattr(commerce_expiry, "start", lambda: events.append("start"))
    monkeypatch.setattr(commerce_expiry, "stop", lambda: events.append("stop"))
    with TestClient(commerce.app) as browser:
        assert browser.get("/health").status_code == 200
        assert events == ["start"]
    assert events == ["start", "stop"]


def test_background_expiry_releases_stock_without_page_visit(env, monkeypatch):
    from app import commerce_expiry
    c = client()
    stocked(c)
    variant_id = open_stock(c, env, "SHIRT-M", 2)
    assert draft(c, [variant_id], [2]).status_code == 303
    created_id = order_id(env)
    assert c.post(f"/app/1/orders/{created_id}/place", data={"csrf": "csrf1", "key": "e" * 48, "version": "1"}, follow_redirects=False).status_code == 303
    with env() as db:
        db.get(m.CommerceOrder, created_id).reserved_until = 10
        db.commit()
    monkeypatch.setattr(commerce_expiry, "SessionLocal", env)
    commerce_expiry.release_expired()
    with env() as db:
        assert db.get(m.CommerceOrder, created_id).order_status == "expired"
        assert db.scalar(select(m.Balance.reserved)) == 0


def test_draft_captures_customer_item_and_price_snapshots(env):
    c = client()
    stocked(c)
    variant_id = open_stock(c, env, "SHIRT-M", 8)
    with env() as db:
        customer = m.Customer(merchant_id=1, name="Ada Customer", email="ada@customer.test", phone="08010000000")
        db.add(customer)
        db.commit()
        customer_id = customer.id
    response = draft(c, [variant_id], [2], customer_id=str(customer_id))
    assert response.status_code == 303
    created_id = order_id(env)
    with env() as db:
        order = db.get(m.CommerceOrder, created_id)
        item = db.scalar(select(m.OrderItem).where(m.OrderItem.order_id == created_id))
        assert (order.customer_name, order.customer_email, order.customer_phone) == ("Ada Customer", "ada@customer.test", "08010000000")
        assert order.total_kobo == 1_700_050
        assert (item.product_name, item.variant_label, item.sku, item.unit_price_kobo, item.quantity) == (
            "Everyday shirt", "Olive / M", "SHIRT-M", 850_025, 2)
        db.get(m.Customer, customer_id).name = "Renamed customer"
        db.get(m.Variant, variant_id).price_kobo = 999
        db.commit()
    page = c.get(f"/app/1/orders/{created_id}")
    assert page.status_code == 200
    assert "Ada Customer" in page.text and "Renamed customer" not in page.text
    assert "₦17,000.50" in page.text
    response = c.post(f"/app/1/orders/{created_id}/place",
        data={"csrf": "csrf1", "key": "9" * 48, "version": "1"})
    assert response.status_code == 409 and "price" in response.text and "review the new total" in response.text
    with env() as db:
        assert db.get(m.CommerceOrder, created_id).order_status == "draft"
        assert db.scalar(select(func.count()).select_from(m.StockReservation)) == 0


def test_place_and_cancel_are_atomic_and_idempotent(env):
    c = client()
    stocked(c)
    variant_id = open_stock(c, env, "SHIRT-M", 5)
    assert draft(c, [variant_id], [3]).status_code == 303
    created_id = order_id(env)
    with env() as db:
        version = db.get(m.CommerceOrder, created_id).version
    place_data = {"csrf": "csrf1", "key": "b" * 48, "version": str(version)}
    path = f"/app/1/orders/{created_id}/place"
    assert c.post(path, data=place_data, follow_redirects=False).status_code == 303
    assert c.post(path, data=place_data, follow_redirects=False).status_code == 303
    with env() as db:
        order = db.get(m.CommerceOrder, created_id)
        assert order.order_status == "placed" and order.reserved_until > int(time.time())
        assert db.scalar(select(m.Balance.reserved).where(m.Balance.variant_id == variant_id)) == 3
        assert db.scalar(select(func.count()).select_from(m.StockReservation)) == 1
        assert db.scalar(select(func.count()).select_from(m.OrderRequest).where(m.OrderRequest.kind == "place")) == 1
        cancel_version = order.version
    stale = c.post(f"/app/1/orders/{created_id}/cancel",
        data={"csrf": "csrf1", "key": "8" * 48, "version": str(cancel_version - 1)})
    assert stale.status_code == 409 and "changed in another tab" in stale.text
    cancel_data = {"csrf": "csrf1", "key": "c" * 48, "version": str(cancel_version)}
    cancel_path = f"/app/1/orders/{created_id}/cancel"
    assert c.post(cancel_path, data=cancel_data, follow_redirects=False).status_code == 303
    assert c.post(cancel_path, data=cancel_data, follow_redirects=False).status_code == 303
    with env() as db:
        order = db.get(m.CommerceOrder, created_id)
        reservation = db.scalar(select(m.StockReservation))
        assert (order.order_status, order.fulfilment_status, reservation.state) == ("cancelled", "cancelled", "released")
        assert db.scalar(select(m.Balance.reserved).where(m.Balance.variant_id == variant_id)) == 0
        assert db.scalar(select(func.count()).select_from(m.OrderRequest).where(m.OrderRequest.kind == "cancel")) == 1


def test_multi_item_failure_rolls_back_every_reservation(env):
    c = client()
    stocked(c, sku="ONE", name="First")
    stocked(c, sku="TWO", name="Second", price="1200")
    first = open_stock(c, env, "ONE", 4)
    second = open_stock(c, env, "TWO", 1)
    assert draft(c, [first, second], [2, 2]).status_code == 303
    created_id = order_id(env)
    with env() as db:
        version = db.get(m.CommerceOrder, created_id).version
    response = c.post(f"/app/1/orders/{created_id}/place",
        data={"csrf": "csrf1", "key": "d" * 48, "version": str(version)})
    assert response.status_code == 409 and "Nothing was reserved" in response.text
    with env() as db:
        assert db.get(m.CommerceOrder, created_id).order_status == "draft"
        assert list(db.scalars(select(m.Balance.reserved).order_by(m.Balance.variant_id))) == [0, 0]
        assert db.scalar(select(func.count()).select_from(m.StockReservation)) == 0
        assert db.scalar(select(func.count()).select_from(m.OrderRequest).where(m.OrderRequest.kind == "place")) == 0


def test_final_unit_can_only_be_reserved_once(env):
    c = client()
    stocked(c)
    variant_id = open_stock(c, env, "SHIRT-M", 1)
    assert draft(c, [variant_id], [1], key="1" * 48).status_code == 303
    first = order_id(env)
    assert draft(c, [variant_id], [1], key="2" * 48).status_code == 303
    second = order_id(env)
    with env() as db:
        versions = {row.id: row.version for row in db.scalars(select(m.CommerceOrder))}
    assert c.post(f"/app/1/orders/{first}/place", data={"csrf": "csrf1", "key": "3" * 48, "version": versions[first]}).status_code == 200
    response = c.post(f"/app/1/orders/{second}/place", data={"csrf": "csrf1", "key": "4" * 48, "version": versions[second]})
    assert response.status_code == 409
    with env() as db:
        assert db.get(m.CommerceOrder, first).order_status == "placed"
        assert db.get(m.CommerceOrder, second).order_status == "draft"
        assert db.scalar(select(m.Balance.reserved)) == 1


def test_expiry_releases_once_and_paid_order_is_not_expired(env):
    c = client()
    stocked(c)
    variant_id = open_stock(c, env, "SHIRT-M", 3)
    assert draft(c, [variant_id], [2]).status_code == 303
    created_id = order_id(env)
    with env() as db:
        version = db.get(m.CommerceOrder, created_id).version
    assert c.post(f"/app/1/orders/{created_id}/place",
        data={"csrf": "csrf1", "key": "e" * 48, "version": version}, follow_redirects=False).status_code == 303
    with env() as db:
        db.get(m.CommerceOrder, created_id).reserved_until = 10
        db.commit()
        assert expire_due(db, merchant_id=1, now=20) == 1
        assert expire_due(db, merchant_id=1, now=20) == 0
    with env() as db:
        order = db.get(m.CommerceOrder, created_id)
        assert order.order_status == "expired"
        assert db.scalar(select(m.Balance.reserved)) == 0
        assert db.scalar(select(m.StockReservation.state)) == "expired"
        assert db.scalar(select(func.count()).select_from(m.OrderEvent).where(m.OrderEvent.event_type == "expired")) == 1
        assert db.scalar(select(func.count()).select_from(m.OrderRequest).where(m.OrderRequest.kind == "expire")) == 1


def test_order_edit_conflict_and_database_tenant_constraint(env):
    c = client()
    stocked(c)
    variant_id = open_stock(c, env, "SHIRT-M", 3)
    assert draft(c, [variant_id], [1]).status_code == 303
    created_id = order_id(env)
    response = c.post(f"/app/1/orders/{created_id}/draft", data={"csrf": "csrf1", "key": "f" * 48,
        "version": "999", "variant_id": str(variant_id), "quantity": "1", "customer_id": "",
        "customer_name": "", "customer_email": "", "customer_phone": ""})
    assert response.status_code == 409 and "changed in another tab" in response.text
    with env() as db:
        other = m.CommerceOrder(merchant_id=2, location_id=2, reference="KD-FOREIGN", created_by=2,
            created_at=1, updated_at=1)
        db.add(other)
        db.flush()
        db.add(m.OrderItem(merchant_id=2, order_id=other.id, variant_id=variant_id, product_name="No",
            variant_label="No", sku="NO", quantity=1, unit_price_kobo=1, line_total_kobo=1))
        with pytest.raises(IntegrityError):
            db.commit()
