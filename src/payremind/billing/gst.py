"""GST helpers for our own subscription invoices. Pure logic, no I/O.

Verify with a CA before going live: registration timing, SAC code and invoice format.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

GST_RATE = Decimal("0.18")
SAC_CODE = "998314"  # IT design and development services / SaaS; confirm with your CA
_GSTIN_RE = re.compile(r"^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TWO = Decimal("0.01")

# GST state codes (first two digits of a GSTIN).
STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan",
    "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh",
}  # fmt: skip


def gstin_checksum_ok(gstin: str) -> bool:
    total = 0
    for i, ch in enumerate(gstin[:14]):
        product = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _CHARS[(36 - total % 36) % 36] == gstin[14]


def validate_gstin(raw: str) -> str:
    gstin = raw.strip().upper()
    if not _GSTIN_RE.fullmatch(gstin) or gstin[:2] not in STATES:
        raise ValueError("GSTIN should look like 29ABCDE1234F1Z5")
    if not gstin_checksum_ok(gstin):
        raise ValueError("GSTIN check digit doesn't match; please re-check it")
    return gstin


@dataclass(frozen=True)
class TaxSplit:
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total: Decimal


def split_inclusive(total: Decimal, supplier_registered: bool, intra_state: bool) -> TaxSplit:
    """Split a GST-inclusive amount. Intra-state: CGST + SGST 9% each. Inter-state: IGST 18%."""
    total = total.quantize(TWO, ROUND_HALF_UP)
    zero = Decimal("0.00")
    if not supplier_registered:
        return TaxSplit(total, zero, zero, zero, total)
    taxable = (total / (1 + GST_RATE)).quantize(TWO, ROUND_HALF_UP)
    tax = total - taxable
    if intra_state:
        cgst = (tax / 2).quantize(TWO, ROUND_HALF_UP)
        return TaxSplit(taxable, cgst, tax - cgst, zero, total)
    return TaxSplit(taxable, zero, zero, tax, total)


def financial_year(d: date) -> str:
    """Indian FY label, e.g. 2026-27 for dates from 1 Apr 2026 to 31 Mar 2027."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def invoice_number(d: date, sequence: int) -> str:
    # GST rules cap invoice numbers at 16 characters and require one series per FY.
    return f"PR/{financial_year(d)}/{sequence:05d}"
