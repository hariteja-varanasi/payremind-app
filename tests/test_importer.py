import io
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook

from payremind.importers.excel import ImportFormatError, parse_invoices
from tests.conftest import CSV


def test_csv_happy_path():
    r = parse_invoices(CSV.encode(), "x.csv")
    assert r.errors == []
    assert [x.number for x in r.rows] == ["INV-1", "INV-2", "INV-3"]
    assert r.rows[0].amount == Decimal("1000.00")
    assert r.rows[0].phone == "+919845012345"
    assert r.rows[2].phone is None


def test_xlsx_with_tally_title_rows():
    wb = Workbook()
    ws = wb.active
    ws.append(["My Company Pvt Ltd"])
    ws.append(["Bills Receivable"])
    ws.append(["Ledger", "Ref No", "Due On", "Pending Amount"])
    ws.append(["Sharma", "B-1", datetime(2026, 11, 1), "1,200.50 Dr"])
    ws.append([None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    r = parse_invoices(buf.getvalue(), "Bills.XLSX")
    assert r.errors == []
    row = r.rows[0]
    assert row.due_date == date(2026, 11, 1) == row.invoice_date
    assert row.balance == row.amount == Decimal("1200.50")


def test_row_errors_are_reported_not_fatal():
    csv = (
        "Customer,Invoice No,Due Date,Balance\n"
        "A,1,31-13-2026,10\n"
        "B,2,01-12-2026,abc\n"
        ",3,01-12-2026,1\n"
        "C,4,01-12-2026,-5\n"
        "D,5,2026-12-01,NaN\n"
        "E,6,01/12/2026,7\n"
        "F,6,01/12/2026,7\n"
    )
    r = parse_invoices(csv.encode(), "x.csv")
    assert [x.number for x in r.rows] == ["6"]
    assert len(r.errors) == 6
    assert r.errors[0].startswith("row 2:")


def test_missing_columns():
    with pytest.raises(ImportFormatError, match="header row"):
        parse_invoices(b"name,amount\nA,1\n", "x.csv")


def test_unsupported_type():
    with pytest.raises(ImportFormatError, match="only"):
        parse_invoices(b"x", "x.pdf")


def test_row_limit():
    csv = "Customer,Invoice No,Due Date,Balance\n" + "A,1,01-12-2026,1\n" * 3
    with pytest.raises(ImportFormatError, match="too many"):
        parse_invoices(csv.encode(), "x.csv", max_rows=2)


def test_language_column():
    csv = (
        "Customer,Invoice No,Due Date,Balance,Language\n"
        "A,1,01-12-2026,10,Hindi\nB,2,01-12-2026,10,\nC,3,01-12-2026,10,हिंदी\nD,4,01-12-2026,10,ta\n"
    )
    r = parse_invoices(csv.encode(), "x.csv")
    assert [x.language for x in r.rows] == ["hi", "en", "hi"]
    assert "unsupported language 'ta'" in r.errors[0]
