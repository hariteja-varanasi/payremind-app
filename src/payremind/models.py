"""Data model. Every business row carries tenant_id; queries must always filter by it."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from payremind.db import Base
from payremind.security import new_pay_token


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    upi_vpa: Mapped[str] = mapped_column(String(100))  # merchant's own UPI ID; we never hold money
    payee_name: Mapped[str] = mapped_column(String(100))
    api_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Billing (our fee). trial_ends_on NULL means a complimentary beta account with no expiry.
    billing_status: Mapped[str] = mapped_column(String(20), default="trial", server_default="trial")
    trial_ends_on: Mapped[date | None] = mapped_column(Date)
    plan: Mapped[str] = mapped_column(String(20), default="", server_default="")
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Buyer details printed on our GST invoice.
    legal_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    gstin: Mapped[str] = mapped_column(String(15), default="", server_default="")
    state_code: Mapped[str] = mapped_column(String(2), default="", server_default="")
    billing_address: Mapped[str] = mapped_column(String(500), default="", server_default="")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    opted_out: Mapped[bool] = mapped_column(default=False)
    language: Mapped[str] = mapped_column(String(5), default="en", server_default="en")


class InvoiceStatus(enum.StrEnum):
    OPEN = "open"
    PAID = "paid"


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    number: Mapped[str] = mapped_column(String(64))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, native_enum=False), default=InvoiceStatus.OPEN
    )

    # Unguessable token for the public pay page (/p/<token>). Not the invoice id.
    pay_token: Mapped[str] = mapped_column(String(64), unique=True, default=new_pay_token)

    customer: Mapped[Customer] = relationship()


class Promise(Base):
    """A customer's promise to pay by a date. Pauses reminders until then."""

    __tablename__ = "promises"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    promised_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReminderLog(Base):
    """One row per reminder sent. The unique key makes the scheduler idempotent."""

    __tablename__ = "reminder_log"
    __table_args__ = (UniqueConstraint("tenant_id", "invoice_id", "offset_days"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    offset_days: Mapped[int]
    sent_on: Mapped[date] = mapped_column(Date)
    provider_message_id: Mapped[str] = mapped_column(String(128), default="")


class OptOut(Base):
    """A phone number that replied STOP. Applies to every tenant: they share our sender number."""

    __tablename__ = "opt_outs"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_e164: Mapped[str] = mapped_column(String(20), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """A person who signs in to a tenant's dashboard with phone OTP."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    phone_e164: Mapped[str] = mapped_column(String(20), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OtpChallenge(Base):
    """A login code. Only its keyed hash is stored. Times are Unix seconds (UTC)."""

    __tablename__ = "otp_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_e164: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[int] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(default=0)
    consumed: Mapped[bool] = mapped_column(default=False)


class WebSession(Base):
    """A dashboard session. The cookie holds the raw token; only its hash is stored."""

    __tablename__ = "web_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(BigInteger)


class BillingInvoice(Base):
    """Our invoice to a tenant for a subscription charge. Rupees; total includes GST."""

    __tablename__ = "billing_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    issued_on: Mapped[date] = mapped_column(Date)
    razorpay_payment_id: Mapped[str] = mapped_column(String(64), unique=True)
    plan: Mapped[str] = mapped_column(String(20))
    # Buyer snapshot at issue time, so later profile edits don't change old invoices.
    buyer_name: Mapped[str] = mapped_column(String(200))
    buyer_gstin: Mapped[str] = mapped_column(String(15))
    buyer_state_code: Mapped[str] = mapped_column(String(2))
    buyer_address: Mapped[str] = mapped_column(String(500))
    taxable_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cgst: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    sgst: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    igst: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class ProcessedWebhook(Base):
    """Razorpay retries webhooks; the event id makes processing exactly-once."""

    __tablename__ = "processed_webhooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
