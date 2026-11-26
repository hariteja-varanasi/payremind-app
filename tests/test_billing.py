import hashlib
import hmac
import json
import re
from datetime import date

import httpx
import pytest

from payremind.billing.razorpay import BillingError, RazorpayClient, make_gateway
from payremind.billing.service import can_send
from payremind.models import BillingInvoice, Tenant
from tests.conftest import CSV, RZP_SECRET
from tests.test_auth_web import csrf_of, login

DETAILS = {"legal_name": "A Traders Pvt Ltd", "state_code": "29", "billing_address": "MG Road"}


def rzp(client, event, sub_id="sub_fake1", event_id="evt_1", payment=None, secret=RZP_SECRET):
    payload = {"event": event, "payload": {"subscription": {"entity": {"id": sub_id}}}}
    if payment is not None:
        payload["payload"]["payment"] = {"entity": payment}
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
    )


def tenant(app_and_tokens, tid=1):
    app, _ = app_and_tokens
    with app.state.session_factory() as s:
        return s.get(Tenant, tid)


def subscribe(client, sender, plan="starter", details=DETAILS):
    login(client, sender)
    csrf = csrf_of(client)
    client.post("/app/billing/details", data={"csrf": csrf, **details})
    return client.post("/app/billing/subscribe", data={"csrf": csrf, "plan": plan}), csrf


def test_subscribe_flow_and_charge_issues_gst_invoice(client, sender, gateway, app_and_tokens):
    r, _ = subscribe(client, sender)
    assert 'href="https://rzp.io/i/fake1"' in r.text
    assert gateway.created == [("plan_starter", 1)]
    t = tenant(app_and_tokens)
    assert t.razorpay_subscription_id == "sub_fake1" and t.plan == "starter"

    payment = {"id": "pay_1", "amount": 117882, "currency": "INR", "created_at": 1796000000}
    r = rzp(client, "subscription.charged", payment=payment)
    assert r.json()["result"] == "status active, invoice PR/2026-27/00001"
    assert rzp(client, "subscription.charged", payment=payment).json()["result"] == "duplicate"
    # same payment re-sent under a new event id still yields one invoice
    rzp(client, "subscription.charged", payment=payment, event_id="evt_2")

    page = client.get("/app/billing").text
    assert "PR/2026-27/00001" in page and "Cancel at end of period" in page
    inv_id = re.search(r"/app/billing/invoices/(\d+)", page).group(1)
    inv = client.get(f"/app/billing/invoices/{inv_id}").text
    assert "Tax Invoice" in inv and "CGST 9%" in inv and "₹89.91" in inv and "₹999.00" in inv
    assert "998314" in inv and "A Traders Pvt Ltd" in inv and "Karnataka (29)" in inv
    app, _ = app_and_tokens
    with app.state.session_factory() as s:
        assert s.query(BillingInvoice).count() == 1


def test_inter_state_buyer_gets_igst(client, sender):
    details = {**DETAILS, "state_code": "27", "gstin": "27AAPFU0939F1ZV"}
    subscribe(client, sender, plan="growth", details=details)
    rzp(client, "subscription.charged", payment={"id": "pay_9", "amount": 294882})
    page = client.get("/app/billing").text
    inv_id = re.search(r"/app/billing/invoices/(\d+)", page).group(1)
    inv = client.get(f"/app/billing/invoices/{inv_id}").text
    assert "IGST 18%" in inv and "CGST" not in inv and "27AAPFU0939F1ZV" in inv
    assert "Growth plan" in inv


def test_billing_details_validation(client, sender):
    login(client, sender)
    csrf = csrf_of(client)
    post = lambda **kw: client.post("/app/billing/details", data={"csrf": csrf, **DETAILS, **kw})  # noqa: E731
    assert post(state_code="99").status_code == 422
    assert post(legal_name=" ").status_code == 422
    assert "check digit" in post(gstin="29AAGCB7383J1Z5").text
    assert "must match your state" in post(gstin="27AAPFU0939F1ZV").text
    r = post(gstin="29aagcb7383j1z4")
    assert "Billing details saved" in r.text and 'value="29AAGCB7383J1Z4"' in r.text


def test_subscribe_guards(client, sender, gateway):
    login(client, sender)
    csrf = csrf_of(client)
    sub = lambda plan="starter": client.post(  # noqa: E731
        "/app/billing/subscribe", data={"csrf": csrf, "plan": plan}
    )
    assert "Fill in your billing details first" in sub().text
    assert "Pick one of the plans" in sub("gold").text
    client.post("/app/billing/details", data={"csrf": csrf, **DETAILS})
    sub()
    rzp(client, "subscription.activated")
    assert "already have an active subscription" in sub().text
    assert len(gateway.created) == 1
    assert (
        client.post("/app/billing/subscribe", data={"csrf": "x", "plan": "starter"}).status_code
        == 403
    )


def test_gateway_error_and_cancel(client, sender, gateway, monkeypatch):
    login(client, sender)
    csrf = csrf_of(client)
    assert "isn&#39;t switched on" in client.post("/app/billing/cancel", data={"csrf": csrf}).text

    def boom(*a):
        raise BillingError("down")

    client.post("/app/billing/details", data={"csrf": csrf, **DETAILS})
    monkeypatch.setattr(gateway, "create_subscription", boom)
    r = client.post("/app/billing/subscribe", data={"csrf": csrf, "plan": "starter"})
    assert "Razorpay didn&#39;t respond" in r.text
    monkeypatch.undo()
    client.post("/app/billing/subscribe", data={"csrf": csrf, "plan": "starter"})
    r = client.post("/app/billing/cancel", data={"csrf": csrf})
    assert "Cancellation requested" in r.text and gateway.cancelled == ["sub_fake1"]
    monkeypatch.setattr(gateway, "cancel_subscription", boom)
    assert "didn&#39;t respond" in client.post("/app/billing/cancel", data={"csrf": csrf}).text


@pytest.mark.parametrize(
    ("event", "status", "sends"),
    [
        ("subscription.pending", "past_due", True),
        ("subscription.halted", "halted", False),
        ("subscription.cancelled", "cancelled", False),
        ("subscription.paused", "paused", False),
    ],
)
def test_status_events_gate_reminders(client, sender, auth, app_and_tokens, event, status, sends):
    subscribe(client, sender)
    assert rzp(client, event).json()["result"] == f"status {status}"
    assert tenant(app_and_tokens).billing_status == status
    from tests.conftest import upload

    upload(client, auth["a"])
    r = client.post("/reminders/run", headers=auth["a"])
    assert (r.status_code == 200) is sends
    csrf = csrf_of(client)
    page = client.post("/app/reminders/run", data={"csrf": csrf}).text
    assert ("paused" in page) is not sends


def test_webhook_rejections_and_ignores(client, sender):
    assert rzp(client, "subscription.activated", secret="wrong").status_code == 401
    body = b"not json"
    sig = hmac.new(RZP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    h = {"x-razorpay-signature": sig, "x-razorpay-event-id": "e"}
    assert client.post("/webhooks/razorpay", content=body, headers=h).status_code == 400
    body = b"[]"
    h["x-razorpay-signature"] = hmac.new(RZP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert client.post("/webhooks/razorpay", content=body, headers=h).status_code == 400
    assert client.post("/webhooks/razorpay", content=b"x" * 262145).status_code == 413
    assert rzp(client, "payment.captured", event_id="e1").json()["result"] == "ignored"
    r = rzp(client, "subscription.activated", sub_id="sub_unknown", event_id="e2")
    assert r.json()["result"] == "ignored: unknown subscription"
    assert rzp(client, "subscription.activated", event_id="").json()["result"].startswith("ignored")


def test_trial_expiry_gates_daily_run(client, auth, sender, app_and_tokens):
    from payremind.services import run_all_tenants
    from tests.conftest import BASE_URL, TODAY, upload

    upload(client, auth["a"])
    upload(client, auth["b"])
    app, _ = app_and_tokens
    with app.state.session_factory() as s:
        s.get(Tenant, 1).trial_ends_on = date(2026, 11, 30)
        s.get(Tenant, 2).trial_ends_on = date(2026, 12, 31)
        s.commit()
        r = run_all_tenants(s, TODAY, sender, BASE_URL)
    assert (r.tenants, r.sent) == (1, 2)
    login(client, sender)
    assert "Reminders are paused" in client.get("/app").text


def test_trial_banner(client, sender, app_and_tokens):
    app, _ = app_and_tokens
    with app.state.session_factory() as s:
        s.get(Tenant, 1).trial_ends_on = date(2026, 12, 31)
        s.commit()
    login(client, sender)
    assert "Free trial until 31 Dec 2026" in client.get("/app").text
    assert "Free trial until 31 Dec 2026" in client.get("/app/billing").text


def test_can_send_rules():
    t = Tenant(billing_status="trial", trial_ends_on=None)
    assert can_send(t, date(2030, 1, 1))
    t.billing_status = "unknown"
    assert not can_send(t, date(2030, 1, 1))


def test_invoice_isolation(client, sender, app_and_tokens):
    subscribe(client, sender)
    rzp(client, "subscription.charged", payment={"id": "pay_1", "amount": 117882})
    app, _ = app_and_tokens
    with app.state.session_factory() as s:
        inv = s.query(BillingInvoice).one()
        inv.tenant_id = 2
        s.commit()
        inv_id = inv.id
    assert client.get(f"/app/billing/invoices/{inv_id}").status_code == 404


def test_unregistered_supplier_invoice(client, sender, app_and_tokens, database_url, gateway):
    from fastapi.testclient import TestClient

    from payremind.api.app import create_app
    from payremind.config import Settings
    from tests.conftest import TODAY

    settings = Settings(
        database_url=database_url,
        secret_key="k",
        cookie_secure=False,
        razorpay_webhook_secret=RZP_SECRET,
        razorpay_plan_starter="p",
    )
    c = TestClient(create_app(settings, sender=sender, today=lambda: TODAY, gateway=gateway))
    subscribe(c, sender)
    rzp(c, "subscription.charged", payment={"id": "pay_u", "amount": 99900})
    page = c.get("/app/billing").text
    inv_id = re.search(r"/app/billing/invoices/(\d+)", page).group(1)
    inv = c.get(f"/app/billing/invoices/{inv_id}").text
    assert "Not registered under GST" in inv and "Tax Invoice" not in inv and "GST 9%" not in inv


def test_billing_disabled_without_gateway(app_and_tokens, database_url, sender):
    from fastapi.testclient import TestClient

    from payremind.api.app import create_app
    from payremind.config import Settings

    c = TestClient(
        create_app(
            Settings(database_url=database_url, secret_key="k", cookie_secure=False), sender=sender
        )
    )
    login(c, sender)
    csrf = csrf_of(c)
    assert "billing isn't switched on yet" in c.get("/app/billing").text
    r = c.post("/app/billing/subscribe", data={"csrf": csrf, "plan": "starter"})
    assert "switched on yet" in r.text


def test_legal_pages_are_public_and_marked_draft(client):
    for path in ("/privacy", "/terms"):
        r = client.get(path)
        assert r.status_code == 200 and "DRAFT, not yet reviewed by a lawyer" in r.text


def _client(handler):
    return RazorpayClient("rzp_test_k", "s", httpx.Client(transport=httpx.MockTransport(handler)))


def test_razorpay_client_create_and_cancel():
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"id": "sub_1", "status": "cancelled"})
        return httpx.Response(200, json={"id": "sub_1", "short_url": "https://rzp.io/i/x"})

    c = _client(handler)
    sub = c.create_subscription("plan_1", 7)
    assert (sub.id, sub.short_url) == ("sub_1", "https://rzp.io/i/x")
    body = json.loads(seen[0].content)
    assert body["plan_id"] == "plan_1" and body["notes"] == {"tenant_id": "7"}
    assert seen[0].headers["authorization"].startswith("Basic ")
    c.cancel_subscription("sub_1")
    assert str(seen[1].url) == "https://api.razorpay.com/v1/subscriptions/sub_1/cancel"


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(400),
        httpx.Response(200, text="x"),
        httpx.Response(200, json=[1]),
        httpx.Response(200, json={"id": 1}),
    ],
)
def test_razorpay_client_errors(resp):
    with pytest.raises(BillingError):
        _client(lambda req: resp).create_subscription("p", 1)


def test_make_gateway():
    assert make_gateway("", "") is None
    assert isinstance(make_gateway("k", "s"), RazorpayClient)
    assert CSV  # keep import used
