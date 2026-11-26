"""Gate: one tenant must never read, change or message another tenant's data."""

from tests.conftest import upload


def _a_invoice_id(client, auth):
    upload(client, auth["a"])
    return client.get("/invoices", headers=auth["a"]).json()[0]["id"]


def test_b_sees_nothing_of_a(client, auth):
    _a_invoice_id(client, auth)
    assert client.get("/invoices", headers=auth["b"]).json() == []
    assert all(float(v) == 0 for v in client.get("/ageing", headers=auth["b"]).json().values())


def test_b_cannot_promise_on_a_invoice(client, auth):
    inv_id = _a_invoice_id(client, auth)
    r = client.post(
        f"/invoices/{inv_id}/promises",
        headers=auth["b"],
        json={"promised_date": "2026-12-10", "amount": "1"},
    )
    assert r.status_code == 404


def test_b_cannot_mark_a_invoice_paid(client, auth):
    inv_id = _a_invoice_id(client, auth)
    assert client.post(f"/invoices/{inv_id}/paid", headers=auth["b"]).status_code == 404
    assert len(client.get("/invoices", headers=auth["a"]).json()) == 3


def test_b_reminder_run_sends_nothing_for_a(client, auth, sender):
    _a_invoice_id(client, auth)
    assert client.post("/reminders/run", headers=auth["b"]).json()["sent"] == 0
    assert sender.sent == []


def test_same_invoice_number_in_two_tenants(client, auth):
    upload(client, auth["a"])
    assert upload(client, auth["b"]).json()["created"] == 3
    upload(client, auth["b"], "Customer,Invoice No,Due Date,Balance\nZ,INV-1,31-10-2026,0\n")
    assert len(client.get("/invoices", headers=auth["a"]).json()) == 3


def test_b_reminders_use_b_upi(client, auth, sender):
    upload(client, auth["b"])
    client.post("/reminders/run", headers=auth["b"])
    assert all("pa=b@okhdfc" in m.pay_link for m in sender.sent)
