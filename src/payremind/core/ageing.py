"""Receivables ageing buckets."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

BUCKETS = ("not_due", "1_30", "31_60", "61_90", "90_plus")


@dataclass(frozen=True)
class AgeingItem:
    due_date: date
    balance: Decimal


def bucket_for(due_date: date, today: date) -> str:
    days = (today - due_date).days
    if days <= 0:
        return "not_due"
    if days <= 30:
        return "1_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "90_plus"


def ageing_summary(items: Iterable[AgeingItem], today: date) -> dict[str, Decimal]:
    totals = {b: Decimal("0") for b in BUCKETS}
    for item in items:
        if item.balance > 0:
            totals[bucket_for(item.due_date, today)] += item.balance
    return totals
