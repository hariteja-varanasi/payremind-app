from datetime import date
from decimal import Decimal

import pytest

from payremind.core.ageing import AgeingItem, ageing_summary, bucket_for
from payremind.core.phone import normalize_indian_mobile
from payremind.core.schedule import InvoiceState, due_offset
from payremind.core.upi import UpiError, build_upi_link, validate_vpa

T = date(2026, 12, 1)


@pytest.mark.parametrize(
    ("days_late", "bucket"),
    [
        (-5, "not_due"),
        (0, "not_due"),
        (1, "1_30"),
        (30, "1_30"),
        (31, "31_60"),
        (60, "31_60"),
        (61, "61_90"),
        (90, "61_90"),
        (91, "90_plus"),
    ],
)
def test_buckets(days_late, bucket):
    assert bucket_for(date.fromordinal(T.toordinal() - days_late), T) == bucket


def test_ageing_ignores_zero_balance():
    s = ageing_summary(
        [AgeingItem(date(2026, 11, 1), Decimal("10")), AgeingItem(date(2026, 1, 1), Decimal("0"))],
        T,
    )
    assert s["1_30"] == Decimal("10") and s["90_plus"] == 0


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("98450 12345", "+919845012345"),
        ("+91-98450-12345", "+919845012345"),
        ("098450 12345", "+919845012345"),
        ("12345", None),
        ("5845012345", None),
        (None, None),
        (9845012345, "+919845012345"),
    ],
)
def test_phone(raw, out):
    assert normalize_indian_mobile(raw) == out


def test_upi_link_encodes_and_formats():
    link = build_upi_link("shop.name@okaxis", "Ram & Co", Decimal("1500"), "INV/7")
    assert (
        link
        == "upi://pay?pa=shop.name@okaxis&pn=Ram%20%26%20Co&am=1500.00&cu=INR&tn=Invoice%20INV%2F7"
    )


@pytest.mark.parametrize("vpa", ["noat", "a@", "@bank", "x y@bank", "a@b&c=d"])
def test_bad_vpa(vpa):
    with pytest.raises(UpiError):
        validate_vpa(vpa)


@pytest.mark.parametrize("amt", ["0", "-1", "1000000.01"])
def test_bad_amount(amt):
    with pytest.raises(UpiError):
        build_upi_link("a@okaxis", "A", Decimal(amt), "1")


def state(**kw):
    base = dict(
        invoice_id=1,
        due_date=T,
        balance=Decimal("100"),
        has_phone=True,
        opted_out=False,
        active_promise_until=None,
        already_sent_offsets=frozenset(),
    )
    base.update(kw)
    return InvoiceState(**base)


def d(offset):
    return date.fromordinal(T.toordinal() + offset)


def test_schedule_offsets():
    assert due_offset(state(), d(-4)) is None
    assert due_offset(state(), d(-3)) == -3
    assert due_offset(state(), d(0)) == 0
    assert due_offset(state(), d(10)) == 7
    assert due_offset(state(), d(40)) == 15


def test_schedule_skips_sent_and_catches_up_once():
    assert due_offset(state(already_sent_offsets=frozenset({7})), d(8)) is None
    assert due_offset(state(already_sent_offsets=frozenset({-3})), d(9)) == 7


@pytest.mark.parametrize(
    "kw", [{"balance": Decimal("0")}, {"has_phone": False}, {"opted_out": True}]
)
def test_schedule_skip_conditions(kw):
    assert due_offset(state(**kw), d(0)) is None


def test_schedule_promise_pauses_until_date():
    s = state(active_promise_until=d(10))
    assert due_offset(s, d(7)) is None
    assert due_offset(s, d(11)) == 7
