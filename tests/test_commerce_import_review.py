import base64
import html
import re

from sqlalchemy import func, select
from app import commerce_models as m
from tests.test_commerce import env, client, product


CSV = b'name,variant,sku,price,barcode\nCoffee,250 g,COFFEE-250,4500,0012345678905\nTea,Standard,TEA-1,2000,\n'


def preview(c, raw=CSV, csrf="csrf1", merchant=1):
    return c.post(f"/app/{merchant}/import/preview", data={"csrf":csrf}, files={"file":("catalogue.csv",raw,"text/csv")})


def payload(response):
    return html.unescape(re.search(r'name="payload" value="([^"]+)"',response.text).group(1))


def confirm(c, raw=CSV):
    return c.post('/app/1/import/confirm',data={"csrf":"csrf1","payload":base64.b64encode(raw).decode(),"filename":"catalogue.csv"},follow_redirects=False)


def test_review_does_not_write_and_confirm_revalidates(env):
    c=client()
    response=preview(c)
    assert response.status_code==200 and 'Ready to add' in response.text
    assert base64.b64decode(payload(response))==CSV
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Variant))==0
    assert confirm(c).status_code==303
    assert confirm(c).status_code==303
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Variant))==2
        assert db.scalar(select(func.count()).select_from(m.Movement))==0
        assert db.scalar(select(m.VariantBarcode.code))=='0012345678905'
    assert 'Skip unchanged' in preview(c).text


def test_all_invalid_rows_visible_and_nothing_committed(env):
    c=client()
    raw=b'name,variant,sku,price\nGood,Standard,ONE,10\nBad,Standard,TWO,-1\nDuplicate,Standard,ONE,20\n'
    response=preview(c,raw)
    assert response.status_code==400
    assert 'Price must be' in response.text and 'appears more than once' in response.text
    assert 'Confirm import' not in response.text
    assert confirm(c,raw).status_code==400
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Variant))==0


def test_changes_between_review_and_confirmation_are_rejected_atomically(env):
    c=client()
    assert preview(c).status_code==200
    product(c,name='Different coffee',sku='COFFEE-250',price='1')
    response=confirm(c)
    assert response.status_code==400 and 'different details' in response.text
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Variant))==1
        assert db.scalar(select(func.count()).select_from(m.VariantBarcode))==0


def test_review_enforces_tenant_role_csrf_and_payload_boundaries(env):
    assert preview(client(3),csrf='csrf3').status_code==403
    assert preview(client(2),csrf='csrf2').status_code==404
    assert preview(client(),csrf='wrong').status_code==403
    c=client()
    assert c.post('/app/1/import/confirm',data={"csrf":"csrf1","payload":"invalid%%%"}).status_code==400
    bad=b'name,variant,sku,price,barcode\nOne,Standard,ONE,10,ABC\nTwo,Standard,TWO,20,ABC\n'
    assert preview(c,bad).status_code==400
    assert confirm(c,bad).status_code==400
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Variant))==0


def test_selected_stock_history_is_scoped_to_variant_and_merchant(env):
    c=client()
    product(c,sku='FIRST')
    product(c,name='Second product',sku='SECOND')
    c.post('/app/1/stock/1',data={"csrf":"csrf1","quantity":"4"})
    c.post('/app/1/stock/2',data={"csrf":"csrf1","quantity":"8"})
    page=c.get('/app/1/inventory/1')
    history=page.text.split('id="stock-history"',1)[1]
    assert 'FIRST' in history and 'SECOND' not in history
    assert client(2).get('/app/2/inventory/1').status_code==404


def test_duplicate_product_returns_useful_conflict_without_erroring_in_preferences(env):
    c=client()
    assert product(c).status_code==303
    response=product(c)
    assert response.status_code==409
    assert 'already exists' in response.text
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Variant))==1
