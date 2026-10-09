"""Unit tests for admin-dashboard helpers (no DB, no network)."""

from app import caps
from app.ops_mail import parse_recipients


def test_recipients_single_default():
    assert parse_recipients("hello@koradesk.com") == ["hello@koradesk.com"]


def test_recipients_multiple_dedupe_and_trim():
    assert parse_recipients("a@x.com, b@x.com ,a@x.com,, ") == ["a@x.com", "b@x.com"]


def test_recipients_empty():
    assert parse_recipients("") == []


class _Scalar:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def one(self):
        return self.value


class _Session:
    """Pops a scalar per execute() call, in order: usage query, then packs query."""

    def __init__(self, *scalars, one=None):
        self._scalars = list(scalars)
        self._one = one

    def execute(self, *a, **k):
        if self._one is not None:
            return _Scalar(self._one)
        return _Scalar(self._scalars.pop(0) if self._scalars else None)


class _Shop:
    def __init__(self, plan="starter", monthly_cap=300, id=1):
        self.plan = plan
        self.monthly_cap = monthly_cap
        self.id = id


def test_effective_cap_base_plus_packs():
    assert caps.effective_cap(_Session(None), _Shop()) == 300
    assert caps.effective_cap(_Session(200), _Shop()) == 500


def test_cap_status_blocked_at_100_percent():
    assert caps.cap_status(_Session(300, 0), _Shop())["blocked"] is True
    assert caps.cap_status(_Session(299, 0), _Shop())["blocked"] is False
    assert caps.cap_status(_Session(350, 100), _Shop())["blocked"] is False


def test_margin_green_and_red():
    ok = caps.margin_status("starter", 5000)
    assert ok["flag"] == "green" and ok["price"] == 15000
    bad = caps.margin_status("starter", 12000)
    assert bad["flag"] == "red"
    assert round(bad["margin"], 3) == round((15000 - 12000) / 15000, 3)


def test_margin_pilot_never_red():
    assert caps.margin_status("pilot", 999999)["flag"] == "grey"


def test_sla_levels():
    assert caps.sla_level(0.5) == "ok"
    assert caps.sla_level(3) == "amber"
    assert caps.sla_level(30) == "red"


def test_bulk_price_parse():
    rows, errors = caps.parse_bulk_prices("50kg rice | bags | 56000\nbad line\nSugar | packs | abc")
    assert rows == [{"name": "50kg rice", "unit": "bags", "price_ngn": 56000}]
    assert errors == ["bad line", "Sugar | packs | abc"]


def test_bulk_price_blank_unit_defaults():
    rows, errors = caps.parse_bulk_prices("Salt |  | 500")
    assert rows == [{"name": "Salt", "unit": "each", "price_ngn": 500}]
    assert errors == []
