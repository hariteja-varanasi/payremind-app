"""Decide which reminders are due today. Pure logic, no I/O."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# Days relative to due date: 3 before, due day, 7 and 15 days late.
DEFAULT_OFFSETS: tuple[int, ...] = (-3, 0, 7, 15)


@dataclass(frozen=True)
class InvoiceState:
    invoice_id: int
    due_date: date
    balance: Decimal
    has_phone: bool
    opted_out: bool
    active_promise_until: date | None
    already_sent_offsets: frozenset[int]


def due_offset(
    state: InvoiceState, today: date, offsets: tuple[int, ...] = DEFAULT_OFFSETS
) -> int | None:
    """Return the offset to send today, or None.

    Picks the latest offset that has been reached and not yet sent, so a reminder missed
    because the job did not run is still sent once, without sending older ones as well.
    """
    if state.balance <= 0 or not state.has_phone or state.opted_out:
        return None
    if state.active_promise_until is not None and today <= state.active_promise_until:
        return None
    days = (today - state.due_date).days
    reached = [o for o in offsets if o <= days]
    if not reached:
        return None
    latest = max(reached)
    if latest in state.already_sent_offsets:
        return None
    return latest
