import pytest
from fastapi.testclient import TestClient

from payremind.api.app import create_app
from payremind.billing.service import Supplier
from payremind.config import DEMO_SUPPLIER_GSTIN, Settings
from payremind.demo import DEMO_NAME, seed_demo
from payremind.messaging.whatsapp import LogSender
from payremind.models import Customer, Invoice, Tenant
from tests.conftest import TODAY, upload


@pytest.fixture
def demo(app_and_tokens, database_url):
    settings = Settings(
        database_url=database_url, demo_mode=True, secret_key="k", cookie_secure=False
    )
    sender = LogSender()
    app = create_app(settings, sender=sender, today=lambda: TODAY)
    with app.state.session_factory() as s:
        seed_demo(s, TODAY, Supplier(settings.supplier_gstin, "29"))
    return TestClient(app), sender, app


def test_demo_settings_refuse_real_keys():
    with pytest.raises(ValueError, match="demo_mode cannot be used"):
        Settings(demo_mode=True, whatsapp_token="t")
    with pytest.raises(ValueError, match="demo_mode cannot be used"):
        Settings(demo_mode=True, razorpay_key_id="rzp_live")
    s = Settings(demo_mode=True)
    assert s.dev_log_messages and s.supplier_gstin == DEMO_SUPPLIER_GSTIN


def test_one_click_demo_login_and_dashboard(demo):
    c, _, _ = demo
    login = c.get("/login").text
    assert "Open the demo business" in login and "DEMO · dummy data" in login
    r = c.post("/login/demo", follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/app").text
    assert "Sharma Distributors" in page and "Shree Ganesh Traders" in page
    assert "Raj Stationers" not in page  # paid
    assert "by " in page  # an active promise is shown
    assert "WhatsApp outbox" in page


def test_outbox_shows_would_be_messages_per_tenant(demo, auth):
    c, sender, _ = demo
    c.post("/login/demo")
    assert "No messages yet" in c.get("/app/outbox").text
    import re

    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/app").text).group(1)
    r = c.post("/app/reminders/run", data={"csrf": csrf})
    sent = int(re.search(r"Sent (\d+) reminders", r.text).group(1))
    assert sent >= 3
    box = c.get("/app/outbox").text
    assert "this is a reminder that payment for invoice" in box
    assert "नमस्ते Om Sai Provisions" in box  # Hindi template
    assert "Lakshmi Medicals" not in box  # active promise
    assert "Kumar Auto Parts" not in box  # no phone
    # another business's messages never show in the demo outbox
    upload(c, auth["a"])
    c.post("/reminders/run", headers=auth["a"])
    assert "Sharma Traders" not in c.get("/app/outbox").text


def test_reseed_resets_demo_and_leaves_others(demo, auth):
    c, _, app = demo
    upload(c, auth["a"])
    with app.state.session_factory() as s:
        seed_demo(s, TODAY, Supplier(DEMO_SUPPLIER_GSTIN, "29"))
        demo_t = s.query(Tenant).filter_by(name=DEMO_NAME).one()
        assert s.query(Tenant).filter_by(name=DEMO_NAME).count() == 1
        assert s.query(Invoice).filter_by(tenant_id=demo_t.id).count() == 16
        assert s.query(Customer).filter_by(tenant_id=1).count() == 3  # tenant A untouched
    billing = c.post("/login/demo") and c.get("/app/billing").text
    assert "PR/2026-27/" in billing and "Growth" in billing


def test_demo_routes_hidden_outside_demo_mode(client, sender):
    assert client.post("/login/demo").status_code == 404
    assert "Open the demo business" not in client.get("/login").text
    from tests.test_auth_web import login

    login(client, sender)
    assert client.get("/app/outbox").status_code == 404


def test_demo_login_without_seed(app_and_tokens, database_url):
    c = TestClient(
        create_app(
            Settings(database_url=database_url, demo_mode=True, secret_key="k", cookie_secure=False)
        )
    )
    r = c.post("/login/demo")
    assert r.status_code == 503 and "seed-demo" in r.text


def test_seed_cli(tmp_path, monkeypatch, capsys):
    from payremind.cli import main
    from payremind.config import get_settings

    monkeypatch.setenv("PAYREMIND_DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    get_settings.cache_clear()
    try:
        main(["migrate"])
        assert main(["seed-demo"]) == 2
        assert "only runs with PAYREMIND_DEMO_MODE" in capsys.readouterr().err
        monkeypatch.setenv("PAYREMIND_DEMO_MODE", "true")
        get_settings.cache_clear()
        assert main(["seed-demo"]) == 0
        assert main(["seed-demo"]) == 0
        assert "other businesses untouched" in capsys.readouterr().out
    finally:
        get_settings.cache_clear()
