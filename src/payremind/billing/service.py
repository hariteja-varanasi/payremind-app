"""Subscription state, webhook handling and GST invoice issue for our own fee."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from payremind.billing.gst import financial_year, invoice_number, split_inclusive
from payremind.models import BillingInvoice, ProcessedWebhook, Tenant

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    monthly_price: Decimal  # before GST
    blurb: str


PLANS = {
    "starter": Plan("starter", "Starter", Decimal("999"), "Up to 200 customers"),
    "growth": Plan("growth", "Growth", Decimal("2499"), "Up to 1,000 customers, Hindi + English"),
}

GOOD_STANDING = {"active", "past_due"}  # past_due: Razorpay is still retrying the charge
STATUS_FOR_EVENT = {
    "subscription.authenticated": "active",
    "subscription.activated": "active",
    "subscription.charged": "active",
    "subscription.resumed": "active",
    "subscription.pending": "past_due",
    "subscription.halted": "halted",
    "subscription.paused": "paused",
    "subscription.cancelled": "cancelled",
    "subscription.completed": "cancelled",
}


def can_send(tenant: Tenant, today: date) -> bool:
    """Whether this business's reminders may go out today."""
    if tenant.billing_status in GOOD_STANDING:
        return True
    if tenant.billing_status == "trial":
        return tenant.trial_ends_on is None or today <= tenant.trial_ends_on
    return False


def billing_ready(tenant: Tenant) -> bool:
    """Buyer details needed on a GST invoice are filled in."""
    return bool(tenant.legal_name and tenant.state_code and tenant.billing_address)


def _get(d: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


@dataclass(frozen=True)
class Supplier:
    gstin: str
    state_code: str


def issue_invoice(
    session: Session,
    tenant: Tenant,
    payment_id: str,
    amount_paise: int,
    issued_on: date,
    supplier: Supplier,
) -> BillingInvoice:
    existing = session.scalar(
        select(BillingInvoice).where(BillingInvoice.razorpay_payment_id == payment_id)
    )
    if existing is not None:
        return existing
    total = Decimal(amount_paise) / 100
    split = split_inclusive(
        total,
        supplier_registered=bool(supplier.gstin),
        intra_state=tenant.state_code == supplier.state_code,
    )
    fy_prefix = f"PR/{financial_year(issued_on)}/"
    count = session.scalar(
        select(func.count())
        .select_from(BillingInvoice)
        .where(BillingInvoice.number.like(f"{fy_prefix}%"))
    )
    inv = BillingInvoice(
        tenant_id=tenant.id,
        number=invoice_number(issued_on, (count or 0) + 1),
        issued_on=issued_on,
        razorpay_payment_id=payment_id,
        plan=tenant.plan,
        buyer_name=tenant.legal_name or tenant.name,
        buyer_gstin=tenant.gstin,
        buyer_state_code=tenant.state_code,
        buyer_address=tenant.billing_address,
        taxable_value=split.taxable_value,
        cgst=split.cgst,
        sgst=split.sgst,
        igst=split.igst,
        total=split.total,
    )
    session.add(inv)
    session.flush()
    return inv


def handle_event(
    session: Session, event_id: str, payload: dict[str, Any], supplier: Supplier
) -> str:
    """Apply one verified Razorpay webhook. Returns a short outcome for logs and tests."""
    if not event_id or len(event_id) > 64:
        return "ignored: no event id"
    if session.scalar(select(ProcessedWebhook).where(ProcessedWebhook.event_id == event_id)):
        return "duplicate"
    event = payload.get("event")
    status = STATUS_FOR_EVENT.get(str(event))
    sub_id = _get(payload, "payload", "subscription", "entity", "id")
    if status is None or not isinstance(sub_id, str):
        outcome = "ignored"
    else:
        tenant = session.scalar(select(Tenant).where(Tenant.razorpay_subscription_id == sub_id))
        if tenant is None:
            outcome = "ignored: unknown subscription"
        else:
            tenant.billing_status = status
            outcome = f"status {status}"
            payment = _get(payload, "payload", "payment", "entity") or {}
            pay_id, amount = payment.get("id"), payment.get("amount")
            if (
                event == "subscription.charged"
                and isinstance(pay_id, str)
                and isinstance(amount, int)
                and amount > 0
                and payment.get("currency", "INR") == "INR"
            ):
                created = payment.get("created_at")
                issued = (
                    datetime.fromtimestamp(created, IST).date()
                    if isinstance(created, int)
                    else datetime.now(IST).date()
                )
                inv = issue_invoice(session, tenant, pay_id, amount, issued, supplier)
                outcome += f", invoice {inv.number}"
    session.add(ProcessedWebhook(event_id=event_id))
    try:
        session.commit()
    except IntegrityError:  # a concurrent retry of the same event won the race
        session.rollback()
        return "duplicate"
    return outcome
