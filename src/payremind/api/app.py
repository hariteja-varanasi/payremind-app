from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from payremind import services
from payremind.config import Settings, get_settings
from payremind.db import Base, make_engine, make_sessionmaker
from payremind.importers.excel import ImportFormatError, parse_invoices
from payremind.messaging.whatsapp import FakeSender, Sender
from payremind.models import Invoice, Tenant
from payremind.security import hash_token


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
    today: Callable[[], date] = date.today,
) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)  # replaced by Alembic migrations before beta
    factory: sessionmaker[Session] = make_sessionmaker(engine)
    reminder_sender: Sender = sender or FakeSender()

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
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large")
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
        result = services.run_reminders(session, tenant, today(), reminder_sender)
        return RunOut(sent=result.sent, failed=result.failed)

    return app
