import base64
import hashlib
import hmac
import io
import json
import secrets
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import segno
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from payremind import services
from payremind.api.web import register_web
from payremind.billing.razorpay import BillingGateway, make_gateway
from payremind.billing.service import Supplier, can_send, handle_event
from payremind.config import Settings, get_settings
from payremind.core.phone import normalize_indian_mobile
from payremind.core.upi import build_upi_link
from payremind.db import make_engine, make_sessionmaker
from payremind.importers.excel import ImportFormatError, parse_invoices
from payremind.messaging.whatsapp import Sender, make_sender
from payremind.models import Invoice, Tenant
from payremind.security import hash_token, hmac_equal, valid_meta_signature

IST = ZoneInfo("Asia/Kolkata")


def today_ist() -> date:
    return datetime.now(IST).date()


def unix_now() -> int:
    return int(time.time())


STOP_WORDS = {"stop", "unsubscribe", "stop reminders", "band karo", "बंद करो"}
TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
}


def _qr_svg_b64(data: str) -> str:
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=5, border=2)
    return base64.b64encode(buf.getvalue()).decode()


def _stop_senders(payload: dict[str, Any]) -> list[str]:
    """Extract phone numbers that sent a STOP text or tapped a STOP quick-reply button."""
    phones: list[str] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            for msg in (change.get("value") or {}).get("messages", []) or []:
                kind = msg.get("type")
                if kind == "text":
                    text = (msg.get("text") or {}).get("body", "")
                elif kind == "button":
                    text = (msg.get("button") or {}).get("payload", "")
                else:
                    continue
                if str(text).strip().lower() in STOP_WORDS:
                    phone = normalize_indian_mobile(msg.get("from"))
                    if phone:
                        phones.append(phone)
    return phones


class InvoiceOut(BaseModel):
    id: int
    number: str
    customer: str
    due_date: date
    balance: Decimal
    days_overdue: int


class ImportOut(BaseModel):
    created: int
    updated: int
    errors: list[str]


class PromiseIn(BaseModel):
    promised_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    note: str = Field(default="", max_length=500)


class RunOut(BaseModel):
    sent: int
    failed: int


def create_app(
    settings: Settings | None = None,
    sender: Sender | None = None,
    today: Callable[[], date] = today_ist,
    now: Callable[[], int] = unix_now,
    gateway: BillingGateway | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url, settings.db_schema)
    # Schema is managed by Alembic: run `payremind migrate` before starting the app.
    factory: sessionmaker[Session] = make_sessionmaker(engine)
    reminder_sender: Sender = sender or make_sender(
        settings.whatsapp_token,
        settings.whatsapp_phone_number_id,
        settings.whatsapp_api_base,
        settings.dev_log_messages,
    )
    secret_key = settings.secret_key or secrets.token_hex(32)
    billing_gateway = gateway or make_gateway(
        settings.razorpay_key_id, settings.razorpay_key_secret
    )
    supplier = Supplier(settings.supplier_gstin, settings.supplier_state_code)

    app = FastAPI(title="PayRemind", docs_url=None, redoc_url=None)
    app.state.session_factory = factory

    def get_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    def current_tenant(
        session: Annotated[Session, Depends(get_session)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> Tenant:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
        token = authorization.removeprefix("Bearer ").strip()
        tenant = session.scalar(select(Tenant).where(Tenant.api_token_hash == hash_token(token)))
        if tenant is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
        return tenant

    SessionDep = Annotated[Session, Depends(get_session)]
    TenantDep = Annotated[Tenant, Depends(current_tenant)]

    def to_out(inv: Invoice, now: date) -> InvoiceOut:
        return InvoiceOut(
            id=inv.id,
            number=inv.number,
            customer=inv.customer.name,
            due_date=inv.due_date,
            balance=inv.balance,
            days_overdue=max(0, (now - inv.due_date).days),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/imports", response_model=ImportOut)
    async def upload(file: UploadFile, session: SessionDep, tenant: TenantDep) -> ImportOut:
        content = await file.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file too large")
        try:
            parsed = parse_invoices(content, file.filename or "", settings.max_import_rows)
        except ImportFormatError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        except Exception as exc:  # corrupt xlsx etc.; never echo internals
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "could not read file"
            ) from exc
        stats = services.import_rows(session, tenant, parsed.rows)
        return ImportOut(created=stats.created, updated=stats.updated, errors=parsed.errors)

    @app.get("/invoices", response_model=list[InvoiceOut])
    def invoices(session: SessionDep, tenant: TenantDep, overdue: bool = False) -> list[InvoiceOut]:
        now = today()
        return [to_out(i, now) for i in services.list_invoices(session, tenant, now, overdue)]

    @app.get("/ageing")
    def ageing(session: SessionDep, tenant: TenantDep) -> dict[str, Decimal]:
        return services.ageing(session, tenant, today())

    @app.post("/invoices/{invoice_id}/promises", status_code=status.HTTP_201_CREATED)
    def promise(
        invoice_id: int, body: PromiseIn, session: SessionDep, tenant: TenantDep
    ) -> dict[str, int]:
        try:
            p = services.add_promise(
                session, tenant, invoice_id, body.promised_date, body.amount, body.note
            )
        except services.NotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found") from exc
        return {"id": p.id}

    @app.post("/invoices/{invoice_id}/paid", response_model=InvoiceOut)
    def paid(invoice_id: int, session: SessionDep, tenant: TenantDep) -> InvoiceOut:
        try:
            inv = services.mark_paid(session, tenant, invoice_id)
        except services.NotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found") from exc
        return to_out(inv, today())

    @app.post("/reminders/run", response_model=RunOut)
    def run(session: SessionDep, tenant: TenantDep) -> RunOut:
        if not can_send(tenant, today()):
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "subscription inactive")
        result = services.run_reminders(
            session, tenant, today(), reminder_sender, settings.public_base_url
        )
        return RunOut(sent=result.sent, failed=result.failed)

    @app.get("/p/{token}", response_class=HTMLResponse, include_in_schema=False)
    def pay_page(token: str, session: SessionDep) -> HTMLResponse:
        not_found = HTMLResponse("Not found", status_code=404, headers=PAGE_HEADERS)
        if not 16 <= len(token) <= 64:
            return not_found
        try:
            inv, tenant = services.get_invoice_by_pay_token(session, token)
        except services.NotFound:
            return not_found
        paid = inv.balance <= 0
        upi_link = qr = ""
        if not paid:
            upi_link = build_upi_link(tenant.upi_vpa, tenant.payee_name, inv.balance, inv.number)
            qr = _qr_svg_b64(upi_link)
        html = TEMPLATES.get_template("pay.html").render(
            payee=tenant.payee_name,
            vpa=tenant.upi_vpa,
            number=inv.number,
            due=inv.due_date.strftime("%d %b %Y"),
            amount=f"{inv.balance:,.2f}",
            paid=paid,
            upi_link=upi_link,
            qr_b64=qr,
        )
        return HTMLResponse(html, headers=PAGE_HEADERS)

    @app.get("/webhooks/whatsapp", include_in_schema=False)
    # Empty query defaults below are not passwords.
    def webhook_verify(  # nosec B107
        mode: Annotated[str, Query(alias="hub.mode")] = "",
        verify_token: Annotated[str, Query(alias="hub.verify_token")] = "",
        challenge: Annotated[str, Query(alias="hub.challenge", max_length=100)] = "",
    ) -> PlainTextResponse:
        expected = settings.whatsapp_verify_token
        if (
            mode == "subscribe"
            and expected
            and challenge.isdigit()
            and hmac_equal(verify_token, expected)
        ):
            return PlainTextResponse(challenge)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "verification failed")

    @app.post("/webhooks/whatsapp", include_in_schema=False)
    async def webhook_receive(request: Request, session: SessionDep) -> dict[str, int]:
        body = await request.body()
        if len(body) > 256 * 1024:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too large")
        signature = request.headers.get("x-hub-signature-256")
        if not valid_meta_signature(body, signature, settings.whatsapp_app_secret):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid json") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid payload")
        added = sum(services.record_opt_out(session, p) for p in _stop_senders(payload))
        return {"opted_out": added}

    @app.post("/webhooks/razorpay", include_in_schema=False)
    async def razorpay_webhook(request: Request, session: SessionDep) -> dict[str, str]:
        body = await request.body()
        if len(body) > 256 * 1024:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too large")
        secret = settings.razorpay_webhook_secret
        signature = request.headers.get("x-razorpay-signature", "")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not secret or not hmac_equal(expected, signature):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid json") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid payload")
        event_id = request.headers.get("x-razorpay-event-id", "")
        return {"result": handle_event(session, event_id, payload, supplier)}

    register_web(app, factory, settings, secret_key, reminder_sender, now, today, billing_gateway)
    return app
