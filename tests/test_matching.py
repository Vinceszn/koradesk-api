"""Unit tests for pure matching logic (no DB, no network)."""

from app.matching import (
    normalize_item_name,
    parse_amount_naira,
    payment_match_score,
    price_lookup,
    should_auto_clear,
)
from app.security import verify_signature


def test_normalize_strips_quantities():
    assert normalize_item_name("3 × 50kg Rice!") == "rice"
    assert normalize_item_name("2 cartons Indomie") == "indomie"


def test_price_lookup_fuzzy():
    catalog = [("50kg rice", 56000), ("Indomie carton", 12250)]
    assert price_lookup("3 bags rice", catalog) == ("50kg rice", 56000)
    assert price_lookup("indomie", catalog) == ("Indomie carton", 12250)
    assert price_lookup("private jet", catalog) is None


def test_parse_amount_naira():
    assert parse_amount_naira("Credit ₦168,000 to 0123456789") == 168000
    assert parse_amount_naira("Transfer of NGN86500.00") == 86500
    assert parse_amount_naira("hello there") is None


def test_payment_match_exact_amount_scores_high():
    score = payment_match_score(168000, "Chinedu", 168000, "Chinedu Stores", True)
    assert score >= 0.85


def test_payment_match_wrong_amount_scores_zero():
    assert payment_match_score(50000, "Chinedu", 168000, "Chinedu Stores", True) == 0.0


def test_screenshot_never_auto_clears():
    assert should_auto_clear(1.0, "screenshot") is False
    assert should_auto_clear(0.9, "alert") is True
    assert should_auto_clear(0.5, "alert") is False


def test_webhook_signature():
    secret, body = "s3cret", b'{"a":1}'
    import hashlib
    import hmac

    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(secret, body, good) is True
    assert verify_signature(secret, body, "sha256=deadbeef") is False
    assert verify_signature(secret, body, None) is False
