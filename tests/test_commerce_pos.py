import json
from sqlalchemy import select, func
from app import commerce_models as m
from tests.test_commerce import env, client, product
from tests.test_commerce_orders import open_stock, draft, order_id

def setup(c, env):
    assert product(c).status_code == 303
    return open_stock(c, env, "SHIRT-M", 5)

def sale(c, variant, key="a"*48, qty=2, price=850025, tendered="20000"):
    return c.post("/app/1/pos/sale", data={"csrf":"csrf1","key":key,"basket":json.dumps([{"id":variant,"qty":qty,"price":price}]),"tendered":tendered,"customer_id":""}, follow_redirects=False)

def test_cash_sale_is_atomic_and_retry_safe(env):
    c=client();v=setup(c, env)
    assert c.get("/app/1/pos").status_code == 200
    assert sale(c,v).status_code == 303
    assert sale(c,v).status_code == 303
    assert sale(c,v,qty=3).status_code == 409
    with env() as db:
        assert db.scalar(select(m.Balance.on_hand)) == 3
        assert db.scalar(select(func.sum(m.Movement.quantity))) == 3
        assert db.scalar(select(func.count()).select_from(m.CashSale)) == 1
        order=db.scalar(select(m.CommerceOrder))
        assert (order.order_status,order.payment_status,order.fulfilment_status)==("completed","paid","fulfilled")

def test_sale_failure_rolls_back_and_staff_needs_capability(env):
    c=client();v=setup(c,env)
    assert sale(c,v,price=1).status_code == 409
    assert sale(c,v,tendered="1").status_code == 400
    assert sale(c,v,qty=6).status_code == 409
    assert client(3).get("/app/1/pos").status_code == 403
    with env() as db:
        assert db.scalar(select(m.Balance.on_hand)) == 5
        assert db.scalar(select(func.count()).select_from(m.CommerceOrder)) == 0
        member=db.scalar(select(m.Membership).where(m.Membership.user_id==3))
        member_id=member.id
    assert c.post(f"/app/1/cashier/{member_id}",data={"csrf":"csrf1","enabled":"yes"},follow_redirects=False).status_code==303
    assert client(3).get("/app/1/pos").status_code==200
    assert client(2).get("/app/1/pos").status_code==404

def test_partial_cancel_then_pickup_and_dispatch_reconcile(env):
    c=client();v=setup(c,env)
    assert draft(c,[v],[4]).status_code==303
    oid=order_id(env)
    assert c.post(f"/app/1/orders/{oid}/place",data={"csrf":"csrf1","key":"b"*48,"version":"1"},follow_redirects=False).status_code==303
    with env() as db:
        item_id=db.scalar(select(m.OrderItem.id))
    def action(kind,qty,key,version,tendered="30000"):
        return c.post(f"/app/1/orders/{oid}/fulfil",data={"csrf":"csrf1","key":key*48,"version":str(version),"action":kind,f"qty_{item_id}":str(qty),"tendered":tendered},follow_redirects=False)
    assert action("cancel",1,"c",2).status_code==303
    assert action("pickup",1,"d",3).status_code==303
    assert action("pickup",1,"d",3).status_code==303
    assert action("cancel",1,"e",4).status_code==409
    assert action("dispatch",2,"f",4).status_code==303
    with env() as db:
        item=db.get(m.OrderItem,item_id)
        assert (item.fulfilled_quantity,item.cancelled_quantity)==(3,1)
        b=db.scalar(select(m.Balance));assert (b.on_hand,b.reserved)==(2,0)
        assert db.scalar(select(func.sum(m.Movement.quantity)))==2
        assert db.get(m.CommerceOrder,oid).order_status=="completed"

def test_barcode_assignment_permissions_duplicates_and_lookup(env):
    c=client();v=setup(c,env)
    data={"csrf":"csrf1","variant_id":v,"code":"0012345678905","symbology":"ean13","primary":"yes"}
    assert c.post("/app/1/pos/barcodes",data=data,follow_redirects=False).status_code==303
    assert c.post("/app/1/pos/barcodes",data=data).status_code==409
    assert client(3).post("/app/1/pos/barcodes",data=dict(data,csrf="csrf3")).status_code==403
    assert 'data-code="0012345678905"' in c.get("/app/1/pos").text
    with env() as db:bid=db.scalar(select(m.VariantBarcode.id))
    assert c.post(f"/app/1/pos/barcodes/{bid}/archive",data={"csrf":"csrf1"},follow_redirects=False).status_code==303
    assert 'data-code="0012345678905"' not in c.get("/app/1/pos").text

def test_sale_keeps_final_unit_and_reservations_safe(env):
    c=client();v=setup(c,env)
    with env() as db:
        balance=db.scalar(select(m.Balance));balance.reserved=4;db.commit()
    assert sale(c,v,qty=1).status_code==303
    assert sale(c,v,key="b"*48,qty=1).status_code==409
    with env() as db:
        b=db.scalar(select(m.Balance));assert (b.on_hand,b.reserved)==(4,4)
