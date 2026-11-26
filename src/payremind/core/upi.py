"""Build UPI deep links (NPCI upi://pay) that pay the merchant's own VPA directly."""

import re
from decimal import Decimal
from urllib.parse import quote

_VPA_RE = re.compile(r"^[a-zA-Z0-9.\-_]{1,256}@[a-zA-Z][a-zA-Z0-9.\-]{1,63}$")
MAX_AMOUNT = Decimal("1000000.00")


class UpiError(ValueError):
    pass


def validate_vpa(vpa: str) -> str:
    if not _VPA_RE.fullmatch(vpa):
        raise UpiError(f"invalid UPI ID: {vpa!r}")
    return vpa


def build_upi_link(vpa: str, payee_name: str, amount: Decimal, reference: str) -> str:
    validate_vpa(vpa)
    if amount <= 0 or amount > MAX_AMOUNT:
        raise UpiError("amount must be between 0 and 10 lakh")
    amt = amount.quantize(Decimal("0.01"))
    params = {
        "pa": vpa,
        "pn": payee_name[:50],
        "am": f"{amt:.2f}",
        "cu": "INR",
        "tn": f"Invoice {reference}"[:80],
    }
    query = "&".join(f"{k}={quote(v, safe='@.')}" for k, v in params.items())
    return f"upi://pay?{query}"
