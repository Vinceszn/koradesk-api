import re

import pytest
from sqlalchemy import func, select

from app import commerce_models as m
from tests.test_commerce import client, product
from tests.test_commerce import env as env


def upload(c, text):
    return c.post(
        "/app/1/import",
        data={"csrf": "csrf1"},
        files={"file": ("catalogue.csv", text, "text/csv")},
        follow_redirects=False,
    )


@pytest.mark.parametrize(
    "text",
    [
        " PRICE , SKU , Variant , Name \n100,NEW,M,Shirt\n",
        "\ufeffname,variant,sku,price\nShirt,M,NEW,100\n",
        "sep=;\nname;variant;sku;price\nShirt;M;NEW;100\n",
        "name\tvariant\tsku\tprice\nShirt\tM\tNEW\t100\n",
        "name,variant,sku,price,archived\nShirt,M,NEW,100,false\n",
        "name,variant,sku,price\nShirt,M,NEW,100\n".encode("utf-16"),
    ],
)
def test_spreadsheet_csv_formats(env, text):
    assert upload(client(), text).status_code == 303
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Variant)) == 1
        balance = db.scalar(select(m.Balance))
        assert balance.on_hand == 0 and not balance.counted


def test_export_roundtrip_skips_identical_without_changing_stock(env):
    c = client()
    product(c)
    c.post("/app/1/stock/1", data={"csrf": "csrf1", "quantity": 12})
    exported = c.get("/app/1/catalogue/export").content
    response = upload(c, exported)
    assert response.status_code == 303 and "Skipped+1" in response.headers["location"]
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Variant)) == 1
        assert db.scalar(select(m.Balance.on_hand)) == 12
        assert db.scalar(select(func.count()).select_from(m.Movement)) == 1


def test_import_errors_preserve_form_and_rollback(env):
    c = client()
    product(c)
    for text, message in [
        ("name,variant,sku,price\nNew,M,NEW,100\nChanged,M,SHIRT-M,10\n", "CSV row 3"),
        ("name,variant,sku,price,quantity\nShirt,M,NEW,100,20\n", "Record quantities in Inventory"),
        ("name,variant,sku,price\nShirt,M,NEW,100\nShirt,L,NEW,100\n", "appears more than once"),
        ("name,variant,sku,price,archived\nShirt,M,NEW,100,invalid\n", "archived must"),
    ]:
        result = upload(c, text)
        assert result.status_code == 400
        assert (
            message in result.text
            and 'id="catalogue-import"' in result.text
            and 'role="alert"' in result.text
        )
        with env() as db:
            assert db.scalar(select(func.count()).select_from(m.Variant)) == 1
    assert (
        c.get("/app/1/import", follow_redirects=False)
        .headers["location"]
        .endswith("#catalogue-import")
    )
    assert client(3).get("/app/1/import").status_code == 403


def test_invitation_replacement_acceptance_removal_and_revoke(env):
    c = client()

    def invite(email):
        response = c.post("/app/1/invite", data={"csrf": "csrf1", "email": email})
        assert "Invitation ready" in response.text
        return re.search(r"/invite/([A-Za-z0-9_-]+)", response.text).group(1)

    old = invite("user2@example.com")
    current = invite("user2@example.com")
    assert c.get("/invite/" + old).status_code == 404
    assert (
        client(2)
        .post("/invite/" + current, data={"csrf": "csrf2"}, follow_redirects=False)
        .status_code
        == 303
    )
    with env() as db:
        membership = db.scalar(
            select(m.Membership).where(m.Membership.user_id == 2, m.Membership.merchant_id == 1)
        )
        member_id = membership.id
    assert (
        c.post(
            f"/app/1/members/{member_id}/remove", data={"csrf": "csrf1"}, follow_redirects=False
        ).status_code
        == 303
    )
    assert client(2).get("/app/1").status_code == 404
    raw = invite("future@example.com")
    with env() as db:
        invite_id = db.scalar(
            select(m.Invitation.id).where(m.Invitation.email == "future@example.com")
        )
    c.post(f"/app/1/invites/{invite_id}/revoke", data={"csrf": "csrf1"})
    assert c.get("/invite/" + raw).status_code == 404
    assert "Create invitation" not in client(3).get("/app/1/team").text
