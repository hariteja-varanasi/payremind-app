from decimal import Decimal

from payremind.cli import invite, main
from tests.conftest import upload


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_auth_required(client):
    assert client.get("/invoices").status_code == 401
    assert client.get("/invoices", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_import_list_and_ageing(client, auth):
    r = upload(client, auth["a"])
    assert r.json() == {"created": 3, "updated": 0, "errors": []}
    overdue = client.get("/invoices?overdue=true", headers=auth["a"]).json()
    assert [i["number"] for i in overdue] == ["INV-3", "INV-1"]
    assert overdue[1]["days_overdue"] == 31
    assert len(client.get("/invoices", headers=auth["a"]).json()) == 3
    ageing = client.get("/ageing", headers=auth["a"]).json()
    assert Decimal(ageing["31_60"]) == 1000 and Decimal(ageing["90_plus"]) == 2500


def test_reimport_updates(client, auth):
    upload(client, auth["a"])
    r = upload(
        client, auth["a"], "Customer,Invoice No,Due Date,Balance\nNew Name,INV-1,31-10-2026,0\n"
    )
    assert r.json()["updated"] == 1
    numbers = [i["number"] for i in client.get("/invoices", headers=auth["a"]).json()]
    assert "INV-1" not in numbers


def test_upload_rejections(client, auth):
    assert upload(client, auth["a"], "x", "a.pdf").status_code == 422
    assert (
        upload(client, auth["a"], "not a zip", "a.xlsx").json()["detail"] == "could not read file"
    )
    big = "x" * (5 * 1024 * 1024 + 10)
    assert upload(client, auth["a"], big, "a.csv").status_code == 413


def test_reminders_send_once_with_upi_link(client, auth, sender):
    upload(client, auth["a"])
    r = client.post("/reminders/run", headers=auth["a"]).json()
    # INV-1 is 31 days late (offset 15). INV-2 is due in 3 days (offset -3). INV-3 has no phone.
    assert r == {"sent": 2, "failed": 0}
    first = sender.sent[0]
    assert first.to_e164 == "+919845012345"
    assert first.pay_link.startswith("https://pay.example.in/p/")
    assert first.amount_text == "₹1,000.00"
    assert client.post("/reminders/run", headers=auth["a"]).json()["sent"] == 0


def test_promise_pauses_reminders(client, auth, sender):
    upload(client, auth["a"])
    inv = client.get("/invoices?overdue=true", headers=auth["a"]).json()[1]
    r = client.post(
        f"/invoices/{inv['id']}/promises",
        headers=auth["a"],
        json={"promised_date": "2026-12-10", "amount": "1000"},
    )
    assert r.status_code == 201
    client.post("/reminders/run", headers=auth["a"])
    assert [m.invoice_number for m in sender.sent] == ["INV-2"]


def test_promise_validation(client, auth):
    upload(client, auth["a"])
    inv = client.get("/invoices", headers=auth["a"]).json()[0]
    r = client.post(
        f"/invoices/{inv['id']}/promises",
        headers=auth["a"],
        json={"promised_date": "2026-12-10", "amount": "-1"},
    )
    assert r.status_code == 422


def test_mark_paid(client, auth):
    upload(client, auth["a"])
    inv = client.get("/invoices", headers=auth["a"]).json()[0]
    r = client.post(f"/invoices/{inv['id']}/paid", headers=auth["a"])
    assert Decimal(r.json()["balance"]) == 0
    assert len(client.get("/invoices", headers=auth["a"]).json()) == 2


def test_failed_send_is_retried_next_run(client, auth, sender, monkeypatch):
    from payremind.messaging.whatsapp import SendError

    upload(client, auth["a"])
    real = sender.send

    def boom(msg):
        raise SendError("down")

    monkeypatch.setattr(sender, "send", boom)
    assert client.post("/reminders/run", headers=auth["a"]).json() == {"sent": 0, "failed": 2}
    monkeypatch.setattr(sender, "send", real)
    assert client.post("/reminders/run", headers=auth["a"]).json()["sent"] == 2


def test_cli(tmp_path, monkeypatch, capsys):
    from payremind.config import get_settings

    monkeypatch.setenv("PAYREMIND_DATABASE_URL", f"sqlite:///{tmp_path}/c.db")
    get_settings.cache_clear()
    try:
        assert main(["migrate"]) == 0
        assert "up to date" in capsys.readouterr().out
        tenant_id, token = invite("X", "x@okaxis", "X", "98450 11111")
        assert tenant_id == 1 and len(token) > 30
        assert (
            main(
                [
                    "invite",
                    "--name",
                    "Y",
                    "--upi",
                    "y@okaxis",
                    "--payee",
                    "Y",
                    "--owner-phone",
                    "9845022222",
                ]
            )
            == 0
        )
        assert "token (shown once)" in capsys.readouterr().out
        assert main(["add-user", "--tenant", "1", "--phone", "9845033333"]) == 0
        assert main(["add-user", "--tenant", "9", "--phone", "9845044444"]) == 2
        assert main(["add-user", "--tenant", "1", "--phone", "123"]) == 2
        assert (
            main(
                ["invite", "--name", "Z", "--upi", "z@okaxis", "--payee", "Z", "--owner-phone", "1"]
            )
            == 2
        )
        assert "invalid Indian mobile" in capsys.readouterr().err
        assert main(["run-reminders"]) == 0
        assert "2 businesses, 0 sent, 0 failed (dry run" in capsys.readouterr().out
    finally:
        get_settings.cache_clear()


def test_hindi_customers_get_hindi_reminders(client, auth, sender):
    csv = (
        "Customer,Mobile,Invoice No,Due Date,Balance,Language\n"
        "Verma,9845012345,H-1,24-11-2026,100,hi\n"
    )
    upload(client, auth["a"], csv)
    client.post("/reminders/run", headers=auth["a"])
    assert sender.sent[0].language == "hi"
    # re-import can switch the language back
    upload(client, auth["a"], csv.replace(",hi\n", ",en\n").replace("H-1", "H-2"))
    from payremind.models import Customer

    with client.app.state.session_factory() as s:
        assert s.query(Customer).one().language == "en"


def test_daily_run_covers_all_tenants(client, auth, sender, app_and_tokens):
    from payremind.services import run_all_tenants
    from tests.conftest import BASE_URL, TODAY

    upload(client, auth["a"])
    upload(client, auth["b"])
    app, _ = app_and_tokens
    with app.state.session_factory() as s:
        r = run_all_tenants(s, TODAY, sender, BASE_URL)
        assert (r.tenants, r.sent, r.failed) == (2, 4, 0)
        assert run_all_tenants(s, TODAY, sender, BASE_URL).sent == 0  # idempotent
