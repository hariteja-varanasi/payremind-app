"""Dummy data for demos. Every name, number and UPI ID here is made up.

Phone numbers use the +91 99999 0xxxx range. Demo mode never sends WhatsApp messages, so these
numbers are never contacted.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from payremind.billing.service import Supplier, issue_invoice
from payremind.models import (
    BillingInvoice,
    Customer,
    Invoice,
    InvoiceStatus,
    OtpChallenge,
    Promise,
    ReminderLog,
    Tenant,
    User,
    WebSession,
)
from payremind.security import hash_token, new_token

DEMO_PHONE = "+919999900001"
DEMO_NAME = "Sharma Distributors"


@dataclass(frozen=True)
class DemoInvoice:
    customer: str
    phone: str | None
    language: str
    number: str
    due_in_days: int  # negative = overdue
    amount: str
    balance: str | None = None  # None = same as amount; "0" = paid
    promise_in_days: int | None = None
    reminders_sent: tuple[int, ...] = ()


INVOICES = [
    DemoInvoice("Gupta Kirana Stores", "+919999910001", "en", "SD/26-27/0412", -48, "18450"),
    DemoInvoice("Shree Ganesh Traders", "+919999910002", "en", "SD/26-27/0398", -35, "42300",
                reminders_sent=(-3, 0, 7, 15)),
    DemoInvoice("Lakshmi Medicals", "+919999910003", "en", "SD/26-27/0455", -22, "9875",
                promise_in_days=4, reminders_sent=(-3, 0, 7, 15)),
    DemoInvoice("Balaji Hardware", "+919999910004", "en", "SD/26-27/0461", -16, "27600", "12600",
                reminders_sent=(-3, 0, 7)),
    DemoInvoice("Verma General Store", "+919999910005", "hi", "SD/26-27/0470", -9, "6340",
                reminders_sent=(-3, 0)),
    DemoInvoice("Om Sai Provisions", "+919999910006", "hi", "SD/26-27/0478", -7, "15200"),
    DemoInvoice("Mehta Electricals", "+919999910007", "en", "SD/26-27/0483", -3, "33980",
                reminders_sent=(-3, 0)),
    DemoInvoice("Sai Krishna Agencies", "+919999910008", "en", "SD/26-27/0490", 0, "11250",
                reminders_sent=(-3,)),
    DemoInvoice("Royal Bakery", "+919999910009", "en", "SD/26-27/0494", 3, "4800"),
    DemoInvoice("Annapurna Caterers", "+919999910010", "en", "SD/26-27/0497", 6, "21600"),
    DemoInvoice("Patel Textiles", "+919999910011", "en", "SD/26-27/0501", 12, "56700"),
    DemoInvoice("Kumar Auto Parts", None, "en", "SD/26-27/0376", -95, "38900"),
    DemoInvoice("New India Pharma", "+919999910013", "en", "SD/26-27/0352", -72, "64150",
                promise_in_days=-5, reminders_sent=(-3, 0, 7, 15)),
    DemoInvoice("Raj Stationers", "+919999910014", "en", "SD/26-27/0440", -20, "7425", "0",
                reminders_sent=(-3, 0, 7)),
    DemoInvoice("Fresh Mart Supermarket", "+919999910015", "en", "SD/26-27/0449", -12, "29300",
                "0", reminders_sent=(-3, 0, 7)),
    DemoInvoice("Gupta Kirana Stores", "+919999910001", "en", "SD/26-27/0488", 9, "12780"),
]  # fmt: skip


def _remove_demo(session: Session) -> None:
    tenant = session.scalar(select(Tenant).where(Tenant.name == DEMO_NAME))
    if tenant is None:
        return
    tid = tenant.id
    user_ids = list(session.scalars(select(User.id).where(User.tenant_id == tid)))
    for model in (ReminderLog, Promise, BillingInvoice, WebSession):
        session.execute(delete(model).where(model.tenant_id == tid))
    session.execute(delete(Invoice).where(Invoice.tenant_id == tid))
    session.execute(delete(Customer).where(Customer.tenant_id == tid))
    if user_ids:
        session.execute(delete(User).where(User.id.in_(user_ids)))
    session.execute(delete(OtpChallenge).where(OtpChallenge.phone_e164 == DEMO_PHONE))
    session.execute(delete(Tenant).where(Tenant.id == tid))
    session.commit()


def seed_demo(session: Session, today: date, supplier: Supplier) -> Tenant:
    """(Re)create the demo business with invoices dated relative to today."""
    _remove_demo(session)
    tenant = Tenant(
        name=DEMO_NAME,
        upi_vpa="sharmadistributors@okicici",
        payee_name=DEMO_NAME,
        api_token_hash=hash_token(new_token()),  # unknown to anyone: demo uses the web login
        billing_status="active",
        plan="growth",
        legal_name="Sharma Distributors Private Limited",
        state_code="29",
        billing_address="14, 2nd Cross, Chickpet, Bengaluru, Karnataka 560053",
        razorpay_subscription_id=None,
    )
    session.add(tenant)
    session.flush()
    session.add(User(tenant_id=tenant.id, phone_e164=DEMO_PHONE))

    customers: dict[str, Customer] = {}
    for d in INVOICES:
        cust = customers.get(d.customer)
        if cust is None:
            cust = Customer(
                tenant_id=tenant.id, name=d.customer, phone_e164=d.phone, language=d.language
            )
            session.add(cust)
            session.flush()
            customers[d.customer] = cust
        due = today + timedelta(days=d.due_in_days)
        balance = Decimal(d.balance if d.balance is not None else d.amount)
        inv = Invoice(
            tenant_id=tenant.id,
            customer_id=cust.id,
            number=d.number,
            invoice_date=due - timedelta(days=30),
            due_date=due,
            amount=Decimal(d.amount),
            balance=balance,
            status=InvoiceStatus.OPEN if balance > 0 else InvoiceStatus.PAID,
        )
        session.add(inv)
        session.flush()
        if d.promise_in_days is not None:
            session.add(
                Promise(
                    tenant_id=tenant.id,
                    invoice_id=inv.id,
                    promised_date=today + timedelta(days=d.promise_in_days),
                    amount=balance,
                    note="Promised on call",
                )
            )
        for offset in d.reminders_sent:
            session.add(
                ReminderLog(
                    tenant_id=tenant.id,
                    invoice_id=inv.id,
                    offset_days=offset,
                    sent_on=due + timedelta(days=offset),
                    provider_message_id="demo",
                )
            )
    # One paid month of our own fee, so the billing page shows a GST invoice.
    issue_invoice(
        session,
        tenant,
        f"pay_demo_{tenant.id}",
        294882,
        today - timedelta(days=3),
        supplier,
    )
    session.commit()
    return tenant
