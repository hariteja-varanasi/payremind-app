"""Use cases. Every function takes the tenant explicitly and scopes every query to it."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from payremind.billing.service import can_send
from payremind.core.ageing import AgeingItem, ageing_summary
from payremind.core.schedule import InvoiceState, due_offset
from payremind.importers.excel import ImportedRow
from payremind.messaging.whatsapp import ReminderMessage, Sender, SendError
from payremind.models import (
    Customer,
    Invoice,
    InvoiceStatus,
    OptOut,
    Promise,
    ReminderLog,
    Tenant,
)


class NotFound(LookupError):
    pass


@dataclass(frozen=True)
class ImportStats:
    created: int
    updated: int


def import_rows(session: Session, tenant: Tenant, rows: list[ImportedRow]) -> ImportStats:
    customers = {
        c.name: c for c in session.scalars(select(Customer).where(Customer.tenant_id == tenant.id))
    }
    created = updated = 0
    for row in rows:
        cust = customers.get(row.customer)
        if cust is None:
            cust = Customer(
                tenant_id=tenant.id,
                name=row.customer,
                phone_e164=row.phone,
                language=row.language,
            )
            session.add(cust)
            session.flush()
            customers[row.customer] = cust
        else:
            if row.phone:
                cust.phone_e164 = row.phone
            cust.language = row.language
        inv = session.scalar(
            select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.number == row.number)
        )
        status = InvoiceStatus.OPEN if row.balance > 0 else InvoiceStatus.PAID
        if inv is None:
            session.add(
                Invoice(
                    tenant_id=tenant.id,
                    customer_id=cust.id,
                    number=row.number,
                    invoice_date=row.invoice_date,
                    due_date=row.due_date,
                    amount=row.amount,
                    balance=row.balance,
                    status=status,
                )
            )
            created += 1
        else:
            inv.customer_id = cust.id
            inv.due_date = row.due_date
            inv.amount = row.amount
            inv.balance = row.balance
            inv.status = status
            updated += 1
    session.commit()
    return ImportStats(created, updated)


def get_invoice(session: Session, tenant: Tenant, invoice_id: int) -> Invoice:
    inv = session.scalar(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == tenant.id)
    )
    if inv is None:
        raise NotFound("invoice not found")
    return inv


def list_invoices(
    session: Session, tenant: Tenant, today: date, overdue_only: bool = False
) -> list[Invoice]:
    q = select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.status == InvoiceStatus.OPEN)
    if overdue_only:
        q = q.where(Invoice.due_date < today)
    return list(session.scalars(q.order_by(Invoice.due_date, Invoice.id)))


def ageing(session: Session, tenant: Tenant, today: date) -> dict[str, Decimal]:
    invoices = list_invoices(session, tenant, today)
    return ageing_summary((AgeingItem(i.due_date, i.balance) for i in invoices), today)


def add_promise(
    session: Session,
    tenant: Tenant,
    invoice_id: int,
    promised_date: date,
    amount: Decimal,
    note: str = "",
) -> Promise:
    inv = get_invoice(session, tenant, invoice_id)
    promise = Promise(
        tenant_id=tenant.id,
        invoice_id=inv.id,
        promised_date=promised_date,
        amount=amount,
        note=note[:500],
    )
    session.add(promise)
    session.commit()
    return promise


def mark_paid(session: Session, tenant: Tenant, invoice_id: int) -> Invoice:
    inv = get_invoice(session, tenant, invoice_id)
    inv.balance = Decimal("0")
    inv.status = InvoiceStatus.PAID
    session.commit()
    return inv


@dataclass(frozen=True)
class RunResult:
    sent: int
    failed: int


def pay_url(base_url: str, invoice: Invoice) -> str:
    return f"{base_url.rstrip('/')}/p/{invoice.pay_token}"


def record_opt_out(session: Session, phone_e164: str) -> bool:
    """Store a STOP reply. Returns False if the number had already opted out."""
    if session.scalar(select(OptOut).where(OptOut.phone_e164 == phone_e164)) is not None:
        return False
    session.add(OptOut(phone_e164=phone_e164))
    session.commit()
    return True


def get_invoice_by_pay_token(session: Session, token: str) -> tuple[Invoice, Tenant]:
    inv = session.scalar(select(Invoice).where(Invoice.pay_token == token))
    if inv is None:
        raise NotFound("invoice not found")
    tenant = session.get(Tenant, inv.tenant_id)
    if tenant is None:  # pragma: no cover  (FK makes this impossible)
        raise NotFound("invoice not found")
    return inv, tenant


def run_reminders(
    session: Session, tenant: Tenant, today: date, sender: Sender, base_url: str
) -> RunResult:
    sent = failed = 0
    opted_out_phones = set(session.scalars(select(OptOut.phone_e164)))
    for inv in list_invoices(session, tenant, today):
        logs = session.scalars(
            select(ReminderLog.offset_days).where(
                ReminderLog.tenant_id == tenant.id, ReminderLog.invoice_id == inv.id
            )
        )
        latest_promise = session.scalar(
            select(Promise.promised_date)
            .where(Promise.tenant_id == tenant.id, Promise.invoice_id == inv.id)
            .order_by(Promise.promised_date.desc())
            .limit(1)
        )
        cust = inv.customer
        state = InvoiceState(
            invoice_id=inv.id,
            due_date=inv.due_date,
            balance=inv.balance,
            has_phone=bool(cust.phone_e164),
            opted_out=cust.opted_out or cust.phone_e164 in opted_out_phones,
            active_promise_until=latest_promise,
            already_sent_offsets=frozenset(logs),
        )
        offset = due_offset(state, today)
        if offset is None or cust.phone_e164 is None:
            continue
        msg = ReminderMessage(
            to_e164=cust.phone_e164,
            customer_name=cust.name,
            invoice_number=inv.number,
            amount_text=f"₹{inv.balance:,.2f}",
            pay_link=pay_url(base_url, inv),
            language=cust.language,
        )
        try:
            message_id = sender.send(msg)
        except SendError:
            failed += 1
            continue
        session.add(
            ReminderLog(
                tenant_id=tenant.id,
                invoice_id=inv.id,
                offset_days=offset,
                sent_on=today,
                provider_message_id=message_id,
            )
        )
        session.commit()
        sent += 1
    return RunResult(sent, failed)


@dataclass(frozen=True)
class DailyRunResult:
    tenants: int
    sent: int
    failed: int


def run_all_tenants(session: Session, today: date, sender: Sender, base_url: str) -> DailyRunResult:
    """The daily job: run reminders for every tenant in good standing.

    Safe to re-run (ReminderLog is unique). `tenants` counts the businesses actually run.
    """
    sent = failed = count = 0
    for tenant in list(session.scalars(select(Tenant).order_by(Tenant.id))):
        if not can_send(tenant, today):
            continue
        result = run_reminders(session, tenant, today, sender, base_url)
        sent += result.sent
        failed += result.failed
        count += 1
    return DailyRunResult(count, sent, failed)
