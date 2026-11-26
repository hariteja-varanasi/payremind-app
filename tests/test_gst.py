from datetime import date
from decimal import Decimal

import pytest

from payremind.billing.gst import financial_year, invoice_number, split_inclusive, validate_gstin


@pytest.mark.parametrize("g", ["27AAPFU0939F1ZV", "29AAGCB7383J1Z4", " 29aagcb7383j1z4 "])
def test_valid_gstins(g):
    assert validate_gstin(g) == g.strip().upper()


@pytest.mark.parametrize(
    ("g", "msg"),
    [
        ("29AAGCB7383J1Z5", "check digit"),
        ("ABC", "look like"),
        ("99AAGCB7383J1Z4", "look like"),
        ("25AAGCB7383J1Z4", "look like"),
    ],
)
def test_invalid_gstins(g, msg):
    with pytest.raises(ValueError, match=msg):
        validate_gstin(g)


def test_split_intra_state():
    s = split_inclusive(Decimal("1178.82"), supplier_registered=True, intra_state=True)
    assert (s.taxable_value, s.cgst, s.sgst, s.igst) == (
        Decimal("999.00"),
        Decimal("89.91"),
        Decimal("89.91"),
        Decimal("0.00"),
    )
    assert s.taxable_value + s.cgst + s.sgst == s.total


def test_split_inter_state_and_odd_paise():
    s = split_inclusive(Decimal("2948.83"), supplier_registered=True, intra_state=False)
    assert s.igst == Decimal("449.82") and s.taxable_value + s.igst == s.total
    odd = split_inclusive(Decimal("100.01"), True, True)
    assert odd.taxable_value + odd.cgst + odd.sgst == odd.total


def test_unregistered_supplier_charges_no_gst():
    s = split_inclusive(Decimal("999"), supplier_registered=False, intra_state=True)
    assert s.total == s.taxable_value == Decimal("999.00") and s.cgst == s.igst == 0


@pytest.mark.parametrize(
    ("d", "fy"),
    [(date(2026, 4, 1), "2026-27"), (date(2027, 3, 31), "2026-27"), (date(2099, 12, 1), "2099-00")],
)
def test_financial_year(d, fy):
    assert financial_year(d) == fy


def test_invoice_number_fits_16_chars():
    n = invoice_number(date(2026, 12, 1), 99999)
    assert n == "PR/2026-27/99999" and len(n) <= 16
