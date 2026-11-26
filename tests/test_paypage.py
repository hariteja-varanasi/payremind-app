from tests.conftest import upload


def _links(client, auth, sender):
    upload(client, auth["a"])
    client.post("/reminders/run", headers=auth["a"])
    return [m.pay_link.removeprefix("https://pay.example.in") for m in sender.sent]


def test_pay_page_shows_upi_button_and_qr(client, auth, sender):
    path = _links(client, auth, sender)[0]
    r = client.get(path)
    assert r.status_code == 200
    assert 'href="upi://pay?pa=a@okaxis&amp;pn=A%20Co&amp;am=1000.00' in r.text
    assert "data:image/svg+xml;base64," in r.text
    assert "₹1,000.00" in r.text and "INV-1" in r.text
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert r.headers["cache-control"] == "no-store"


def test_pay_page_after_paid(client, auth, sender):
    path = _links(client, auth, sender)[0]
    inv = client.get("/invoices?overdue=true", headers=auth["a"]).json()[1]
    client.post(f"/invoices/{inv['id']}/paid", headers=auth["a"])
    r = client.get(path)
    assert "marked as paid" in r.text and "upi://" not in r.text


def test_pay_page_unknown_or_malformed_token(client):
    assert client.get("/p/" + "x" * 32).status_code == 404
    assert client.get("/p/short").status_code == 404
    assert client.get("/p/" + "x" * 65).status_code == 404


def test_pay_page_escapes_merchant_text(client, app_and_tokens, auth, sender):
    from payremind.models import Tenant

    app, _ = app_and_tokens
    with app.state.session_factory() as s:
        t = s.get(Tenant, 1)
        t.payee_name = "<script>x</script>"
        s.commit()
    r = client.get(_links(client, auth, sender)[0])
    assert "<script>" not in r.text and "&lt;script&gt;" in r.text


def test_pay_token_is_not_the_invoice_id(client, auth, sender):
    paths = _links(client, auth, sender)
    assert all(len(p.removeprefix("/p/")) >= 30 for p in paths)
    assert len(set(paths)) == len(paths)
