"""Import outstanding invoices from .xlsx or .csv exports (Excel, Tally, Busy, Vyapar)."""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook

from payremind.core.phone import normalize_indian_mobile

# Accepted header spellings, lower-cased and stripped.
ALIASES: dict[str, tuple[str, ...]] = {
    "customer": ("customer", "party", "party name", "customer name", "buyer", "ledger"),
    "phone": ("phone", "mobile", "whatsapp", "contact", "mobile no", "phone number"),
    "number": ("invoice", "invoice no", "invoice number", "bill no", "ref no", "voucher no"),
    "invoice_date": ("invoice date", "date", "bill date"),
    "due_date": ("due date", "due on", "due"),
    "amount": ("amount", "invoice amount", "bill amount", "total"),
    "balance": ("balance", "pending", "outstanding", "pending amount", "balance due"),
}
REQUIRED = ("customer", "number", "due_date", "balance")


@dataclass(frozen=True)
class ImportedRow:
    customer: str
    phone: str | None
    number: str
    invoice_date: date
    due_date: date
    amount: Decimal
    balance: Decimal


@dataclass
class ImportResult:
    rows: list[ImportedRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ImportFormatError(ValueError):
    pass


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def _parse_money(value: Any) -> Decimal:
    text = str(value).replace(",", "").replace("₹", "").strip()
    if text.lower().endswith(("dr", "cr")):
        text = text[:-2].strip()
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"unrecognised amount {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"unrecognised amount {value!r}")
    return amount.quantize(Decimal("0.01"))


def _map_headers(header: list[Any]) -> dict[str, int]:
    normalised = [str(h).strip().lower() if h is not None else "" for h in header]
    mapping: dict[str, int] = {}
    for key, names in ALIASES.items():
        for idx, h in enumerate(normalised):
            if h in names:
                mapping[key] = idx
                break
    missing = [k for k in REQUIRED if k not in mapping]
    if missing:
        raise ImportFormatError(f"missing columns: {', '.join(missing)}")
    return mapping


def _read_rows(content: bytes, filename: str) -> list[list[Any]]:
    name = filename.lower()
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return [list(r) for r in csv.reader(io.StringIO(text))]
    if name.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    raise ImportFormatError("only .xlsx and .csv files are supported")


def _cell(row: list[Any], mapping: dict[str, int], key: str) -> Any:
    idx = mapping.get(key)
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def parse_invoices(content: bytes, filename: str, max_rows: int = 5000) -> ImportResult:
    rows = _read_rows(content, filename)
    # Skip leading blank or title rows (Tally exports have company name lines on top).
    start = -1
    mapping: dict[str, int] | None = None
    for idx, header in enumerate(rows[:15]):
        try:
            mapping = _map_headers(header)
        except ImportFormatError:
            continue
        start = idx
        break
    if mapping is None:
        raise ImportFormatError(
            "could not find a header row with customer, invoice no, due date and balance"
        )
    data = rows[start + 1 :]
    if len(data) > max_rows:
        raise ImportFormatError(f"too many rows ({len(data)}); limit is {max_rows}")

    result = ImportResult()
    seen: set[str] = set()
    for line_no, row in enumerate(data, start=start + 2):
        if not any(c not in (None, "") for c in row):
            continue
        try:
            customer = str(_cell(row, mapping, "customer") or "").strip()
            number = str(_cell(row, mapping, "number") or "").strip()
            if not customer or not number:
                raise ValueError("customer and invoice number are required")
            if number in seen:
                raise ValueError(f"duplicate invoice number {number!r}")
            due = _parse_date(_cell(row, mapping, "due_date"))
            inv_raw = _cell(row, mapping, "invoice_date")
            inv_date = _parse_date(inv_raw) if inv_raw not in (None, "") else due
            balance = _parse_money(_cell(row, mapping, "balance"))
            amt_raw = _cell(row, mapping, "amount")
            amount = _parse_money(amt_raw) if amt_raw not in (None, "") else balance
            if balance < 0 or amount < 0:
                raise ValueError("amounts cannot be negative")
            phone = normalize_indian_mobile(_cell(row, mapping, "phone"))
        except ValueError as exc:
            result.errors.append(f"row {line_no}: {exc}")
            continue
        seen.add(number)
        result.rows.append(
            ImportedRow(customer[:200], phone, number[:64], inv_date, due, amount, balance)
        )
    return result
