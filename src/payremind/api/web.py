"""Server-rendered dashboard: phone OTP login, upload, overdue list, promises, mark paid.

Every POST needs the session's CSRF token. Cookies are HttpOnly, SameSite=Lax and Secure
(unless cookie_secure is off for local http development).
"""

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from payremind import auth, services
from payremind.billing.gst import SAC_CODE, STATES, validate_gstin
from payremind.billing.razorpay import BillingError, BillingGateway
from payremind.billing.service import PLANS, billing_ready, can_send
from payremind.config import Settings
from payremind.core.phone import normalize_indian_mobile
from payremind.importers.excel import ImportFormatError, parse_invoices
from payremind.messaging.whatsapp import Sender
from payremind.models import BillingInvoice, Promise, Tenant, WebSession
from payremind.security import hmac_equal

COOKIE = "pr_session"
LEGAL_UPDATED = "26 Nov 2026 (draft)"
TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}
BUCKET_LABELS = [
    ("not_due", "Not yet due"),
    ("1_30", "1–30 days late"),
    ("31_60", "31–60 days late"),
    ("61_90", "61–90 days late"),
    ("90_plus", "90+ days late"),
]
# Fixed flash messages: the query string selects one, so nothing user-supplied is reflected.
FLASH = {
    "paid": "Marked as paid.",
    "promise": "Promise to pay saved. Reminders pause until that date.",
    "bad_date": "Pick a promise date from today onwards.",
    "not_found": "That invoice wasn't found.",
    "details": "Billing details saved.",
    "need_details": "Fill in your billing details first; they go on your GST invoice.",
    "already": "You already have an active subscription.",
    "bad_plan": "Pick one of the plans.",
    "no_billing": "Online billing isn't switched on yet. We'll contact you.",
    "billing_error": "Razorpay didn't respond. Please try again in a minute.",
    "cancelled": "Cancellation requested. You keep access until the end of this billing period.",
}


def page(name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    return HTMLResponse(
        TEMPLATES.get_template(name).render(**ctx), status_code=status_code, headers=HEADERS
    )


def register_web(
    app: FastAPI,
    factory: sessionmaker[Session],
    settings: Settings,
    secret_key: str,
    sender: Sender,
    now: Callable[[], int],
    today: Callable[[], date],
    gateway: BillingGateway | None = None,
) -> None:
    def get_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]

    def web_user(
        session: SessionDep, pr_session: Annotated[str | None, Cookie()] = None
    ) -> tuple[WebSession, Tenant]:
        loaded = auth.load_session(session, pr_session, now())
        if loaded is None:
            raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
        return loaded

    WebUser = Annotated[tuple[WebSession, Tenant], Depends(web_user)]

    def check_csrf(ws: WebSession, token: str) -> None:
        if not hmac_equal(ws.csrf_token, token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid form token")

    def back(flash: str) -> RedirectResponse:
        return RedirectResponse(f"/app?m={flash}", status_code=status.HTTP_303_SEE_OTHER)

    def dashboard(
        session: Session,
        ws: WebSession,
        tenant: Tenant,
        flash: str | None = None,
        errors: list[str] | None = None,
    ) -> HTMLResponse:
        current = today()
        invoices = services.list_invoices(session, tenant, current)
        promises: dict[int, date] = {}
        for inv_id, promised in session.execute(
            select(Promise.invoice_id, Promise.promised_date)
            .where(Promise.tenant_id == tenant.id)
            .order_by(Promise.promised_date)
        ):
            promises[inv_id] = promised  # latest date wins
        rows = []  # list_invoices orders by due date, so the most overdue come first
        for inv in invoices:
            p = promises.get(inv.id)
            rows.append(
                {
                    "id": inv.id,
                    "customer": inv.customer,
                    "number": inv.number,
                    "due_date": inv.due_date,
                    "days_late": (current - inv.due_date).days,
                    "balance": inv.balance,
                    "promise": p if p is not None and p >= current else None,
                }
            )
        return page(
            "dashboard.html",
            tenant=tenant,
            csrf=ws.csrf_token,
            ageing=services.ageing(session, tenant, current),
            buckets=BUCKET_LABELS,
            invoices=rows,
            flash=flash,
            errors=errors or [],
            can_send=can_send(tenant, current),
            trial_ends_on=tenant.trial_ends_on if tenant.billing_status == "trial" else None,
        )

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
    def privacy() -> HTMLResponse:
        return page("privacy.html", updated=LEGAL_UPDATED)

    @app.get("/terms", response_class=HTMLResponse, include_in_schema=False)
    def terms() -> HTMLResponse:
        return page("terms.html", updated=LEGAL_UPDATED)

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def login_form() -> HTMLResponse:
        return page("login.html")

    @app.post("/login", response_class=HTMLResponse, include_in_schema=False)
    def login(session: SessionDep, phone: Annotated[str, Form(max_length=20)]) -> HTMLResponse:
        normalized = normalize_indian_mobile(phone)
        if normalized is None:
            return page("login.html", 422, flash="Enter a 10-digit Indian mobile number.")
        auth.request_otp(session, normalized, now(), sender, secret_key)
        return page("verify.html", phone=normalized)

    @app.post("/login/verify", include_in_schema=False)
    def verify(
        session: SessionDep,
        phone: Annotated[str, Form(max_length=20)],
        code: Annotated[str, Form(max_length=10)],
    ) -> Response:
        normalized = normalize_indian_mobile(phone)
        new = None
        if normalized is not None and code.strip().isdigit():
            new = auth.verify_otp(
                session, normalized, code, now(), secret_key, settings.session_days
            )
        if new is None:
            return page(
                "verify.html",
                401,
                phone=normalized or "",
                flash="That code didn't work. Check it, or request a new one.",
            )
        resp = RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
        resp.set_cookie(
            COOKIE,
            new.token,
            max_age=settings.session_days * 86400,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
        )
        return resp

    @app.post("/logout", include_in_schema=False)
    def logout(
        session: SessionDep, user: WebUser, csrf: Annotated[str, Form()]
    ) -> RedirectResponse:
        ws, _ = user
        check_csrf(ws, csrf)
        auth.end_session(session, ws)
        resp = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/app", response_class=HTMLResponse, include_in_schema=False)
    def app_home(session: SessionDep, user: WebUser, m: str = "") -> HTMLResponse:
        ws, tenant = user
        return dashboard(session, ws, tenant, FLASH.get(m))

    @app.post("/app/upload", response_class=HTMLResponse, include_in_schema=False)
    async def app_upload(
        session: SessionDep, user: WebUser, file: UploadFile, csrf: Annotated[str, Form()]
    ) -> HTMLResponse:
        ws, tenant = user
        check_csrf(ws, csrf)
        content = await file.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            return dashboard(session, ws, tenant, "That file is too large (5 MB limit).")
        try:
            parsed = parse_invoices(content, file.filename or "", settings.max_import_rows)
        except ImportFormatError as exc:
            return dashboard(session, ws, tenant, f"Couldn't import: {exc}")
        except Exception:
            return dashboard(session, ws, tenant, "Couldn't read that file.")
        stats = services.import_rows(session, tenant, parsed.rows)
        msg = f"Imported {stats.created} new and updated {stats.updated} invoices."
        if parsed.errors:
            msg += f" {len(parsed.errors)} rows were skipped:"
        return dashboard(session, ws, tenant, msg, parsed.errors[:50])

    @app.post("/app/invoices/{invoice_id}/paid", include_in_schema=False)
    def app_paid(
        invoice_id: int, session: SessionDep, user: WebUser, csrf: Annotated[str, Form()]
    ) -> RedirectResponse:
        ws, tenant = user
        check_csrf(ws, csrf)
        try:
            services.mark_paid(session, tenant, invoice_id)
        except services.NotFound:
            return back("not_found")
        return back("paid")

    @app.post("/app/invoices/{invoice_id}/promise", include_in_schema=False)
    def app_promise(
        invoice_id: int,
        session: SessionDep,
        user: WebUser,
        csrf: Annotated[str, Form()],
        promised_date: Annotated[date, Form()],
    ) -> RedirectResponse:
        ws, tenant = user
        check_csrf(ws, csrf)
        if promised_date < today():
            return back("bad_date")
        try:
            inv = services.get_invoice(session, tenant, invoice_id)
            services.add_promise(session, tenant, inv.id, promised_date, inv.balance)
        except services.NotFound:
            return back("not_found")
        return back("promise")

    @app.post("/app/reminders/run", response_class=HTMLResponse, include_in_schema=False)
    def app_run(session: SessionDep, user: WebUser, csrf: Annotated[str, Form()]) -> HTMLResponse:
        ws, tenant = user
        check_csrf(ws, csrf)
        if not can_send(tenant, today()):
            return dashboard(session, ws, tenant, "Reminders are paused: subscription inactive.")
        result = services.run_reminders(session, tenant, today(), sender, settings.public_base_url)
        msg = f"Sent {result.sent} reminders."
        if result.failed:
            msg += f" {result.failed} failed and will be retried next run."
        return dashboard(session, ws, tenant, msg)

    def billing_back(flash: str) -> RedirectResponse:
        return RedirectResponse(f"/app/billing?m={flash}", status_code=status.HTTP_303_SEE_OTHER)

    def billing_page(
        session: Session, ws: WebSession, tenant: Tenant, flash: str | None = None, code: int = 200
    ) -> HTMLResponse:
        invoices = list(
            session.scalars(
                select(BillingInvoice)
                .where(BillingInvoice.tenant_id == tenant.id)
                .order_by(BillingInvoice.id.desc())
            )
        )
        return page(
            "billing.html",
            code,
            tenant=tenant,
            csrf=ws.csrf_token,
            plans=PLANS.values(),
            states=sorted(STATES.items(), key=lambda kv: kv[1]),
            invoices=invoices,
            flash=flash,
            ready=billing_ready(tenant),
            enabled=gateway is not None,
            subscribed=tenant.billing_status in {"active", "past_due"},
            can_send=can_send(tenant, today()),
        )

    @app.get("/app/billing", response_class=HTMLResponse, include_in_schema=False)
    def billing_home(session: SessionDep, user: WebUser, m: str = "") -> HTMLResponse:
        ws, tenant = user
        return billing_page(session, ws, tenant, FLASH.get(m))

    @app.post("/app/billing/details", response_class=HTMLResponse, include_in_schema=False)
    def billing_details(
        session: SessionDep,
        user: WebUser,
        csrf: Annotated[str, Form()],
        legal_name: Annotated[str, Form(max_length=200)],
        state_code: Annotated[str, Form(max_length=2)],
        billing_address: Annotated[str, Form(max_length=500)],
        gstin: Annotated[str, Form(max_length=20)] = "",
    ) -> Response:
        ws, tenant = user
        check_csrf(ws, csrf)
        if state_code not in STATES or not legal_name.strip() or not billing_address.strip():
            return billing_page(session, ws, tenant, "Name, state and address are required.", 422)
        clean_gstin = ""
        if gstin.strip():
            try:
                clean_gstin = validate_gstin(gstin)
            except ValueError as exc:
                return billing_page(session, ws, tenant, str(exc), 422)
            if clean_gstin[:2] != state_code:
                return billing_page(
                    session, ws, tenant, "The GSTIN's first two digits must match your state.", 422
                )
        tenant.legal_name = legal_name.strip()
        tenant.state_code = state_code
        tenant.billing_address = billing_address.strip()
        tenant.gstin = clean_gstin
        session.commit()
        return billing_back("details")

    @app.post("/app/billing/subscribe", response_class=HTMLResponse, include_in_schema=False)
    def billing_subscribe(
        session: SessionDep,
        user: WebUser,
        csrf: Annotated[str, Form()],
        plan: Annotated[str, Form(max_length=20)],
    ) -> Response:
        ws, tenant = user
        check_csrf(ws, csrf)
        plan_ids = {
            "starter": settings.razorpay_plan_starter,
            "growth": settings.razorpay_plan_growth,
        }
        if plan not in PLANS:
            return billing_back("bad_plan")
        if gateway is None or not plan_ids[plan]:
            return billing_back("no_billing")
        if tenant.billing_status in {"active", "past_due"}:
            return billing_back("already")
        if not billing_ready(tenant):
            return billing_back("need_details")
        try:
            sub = gateway.create_subscription(plan_ids[plan], tenant.id)
        except BillingError:
            return billing_back("billing_error")
        tenant.razorpay_subscription_id = sub.id
        tenant.plan = plan
        session.commit()
        # A link, not a redirect: CSP form-action 'self' would block a cross-site redirect.
        return page("checkout.html", tenant=tenant, plan=PLANS[plan], url=sub.short_url)

    @app.post("/app/billing/cancel", include_in_schema=False)
    def billing_cancel(
        session: SessionDep, user: WebUser, csrf: Annotated[str, Form()]
    ) -> RedirectResponse:
        ws, tenant = user
        check_csrf(ws, csrf)
        if gateway is None or not tenant.razorpay_subscription_id:
            return billing_back("no_billing")
        try:
            gateway.cancel_subscription(tenant.razorpay_subscription_id)
        except BillingError:
            return billing_back("billing_error")
        return billing_back("cancelled")

    @app.get(
        "/app/billing/invoices/{invoice_id}", response_class=HTMLResponse, include_in_schema=False
    )
    def billing_invoice(invoice_id: int, session: SessionDep, user: WebUser) -> HTMLResponse:
        _, tenant = user
        inv = session.scalar(
            select(BillingInvoice).where(
                BillingInvoice.id == invoice_id, BillingInvoice.tenant_id == tenant.id
            )
        )
        if inv is None:
            return page("base.html", 404, flash="Invoice not found.")
        return page(
            "gst_invoice.html",
            inv=inv,
            plan=PLANS.get(inv.plan),
            supplier=settings,
            sac=SAC_CODE,
            buyer_state=STATES.get(inv.buyer_state_code, ""),
            supplier_state=STATES.get(settings.supplier_state_code, ""),
        )
