import pytest
from sqlalchemy.exc import IntegrityError

from app import commerce_models as m
from tests.test_commerce import client, env, product
from app.commerce_barcodes import normalize_barcode
from fastapi import HTTPException


def test_barcode_normalization_and_check_digits():
    assert normalize_barcode("  0012345678905  ", "ean13") == "0012345678905"
    assert normalize_barcode("SKU-0123", "code128") == "SKU-0123"
    for value, kind in [("0012345678906", "ean13"), ("123", "ean13"), ("A B", "unknown"), ("123", "other")]:
        with pytest.raises(HTTPException):
            normalize_barcode(value, kind)


def test_barcodes_preserve_zeroes_and_enforce_active_uniqueness(env):
    assert product(client()).status_code == 303
    with env() as db:
        first = m.VariantBarcode(merchant_id=1, variant_id=1, code="0012345678905", is_primary=True)
        db.add(first)
        db.commit()
        assert first.code == "0012345678905"
        db.add(m.VariantBarcode(merchant_id=1, variant_id=1, code="0012345678905"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(m.VariantBarcode(merchant_id=1, variant_id=1, code="another", is_primary=True))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        first = db.get(m.VariantBarcode, first.id)
        first.archived = True
        db.commit()
        db.add(m.VariantBarcode(merchant_id=1, variant_id=1, code="0012345678905", is_primary=True))
        db.commit()


def test_barcodes_cannot_reference_another_merchants_variant(env):
    assert product(client()).status_code == 303
    with env() as db:
        db.add(m.VariantBarcode(merchant_id=2, variant_id=1, code="123"))
        with pytest.raises(IntegrityError):
            db.commit()
