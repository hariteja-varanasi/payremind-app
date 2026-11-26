import re

from tests.conftest import NOW, PHONE_A, upload


def _code(sender, phone=PHONE_A):
    return [c for p, c in sender.otps if p == phone][-1]


def login(client, sender, phone="90000 00001"):
    r = client.post("/login", data={"phone": phone})
    assert r.status_code == 200
    r = client.post(
        "/login/verify", data={"phone": phone, "code": _code(sender)}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/app"
    return r


def csrf_of(client):
    return re.search(r'name="csrf" value="([^"]+)"', client.get("/app").text).group(1)


def test_login_flow_sets_hardened_cookie(client, sender):
    r = login(client, sender)
    cookie = r.headers["set-cookie"]
    assert "pr_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    page = client.get("/app")
    assert page.status_code == 200 and "Sign out" in page.text
    assert "form-action 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"


def test_unknown_phone_looks_the_same_and_sends_nothing(client, sender):
    r = client.post("/login", data={"phone": "9123456789"})
    assert r.status_code == 200 and "If +919123456789 is registered" in r.text
    assert sender.otps == []


def test_invalid_phone_rejected(client):
    assert client.post("/login", data={"phone": "12"}).status_code == 422
    assert "Sign in" in client.get("/login").text


def test_wrong_code_then_lockout_after_five_attempts(client, sender):
    client.post("/login", data={"phone": PHONE_A})
    good = _code(sender)
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        r = client.post("/login/verify", data={"phone": PHONE_A, "code": bad})
        assert r.status_code == 401
    r = client.post("/login/verify", data={"phone": PHONE_A, "code": good})
    assert r.status_code == 401  # locked even with the right code


def test_code_expires(client, sender, clock):
    client.post("/login", data={"phone": PHONE_A})
    clock.t = NOW + 301
    r = client.post("/login/verify", data={"phone": PHONE_A, "code": _code(sender)})
    assert r.status_code == 401


def test_code_single_use(client, sender):
    login(client, sender)
    client.cookies.clear()
    r = client.post("/login/verify", data={"phone": PHONE_A, "code": _code(sender)})
    assert r.status_code == 401


def test_non_numeric_code_and_bad_phone_on_verify(client):
    assert client.post("/login/verify", data={"phone": PHONE_A, "code": "abc"}).status_code == 401
    assert client.post("/login/verify", data={"phone": "x", "code": "123456"}).status_code == 401


def test_otp_rate_limit(client, sender, clock):
    for _ in range(5):
        client.post("/login", data={"phone": PHONE_A})
    assert len(sender.otps) == 3
    clock.t = NOW + 15 * 60 + 1
    client.post("/login", data={"phone": PHONE_A})
    assert len(sender.otps) == 4


def test_otp_send_failure_is_silent(client, sender, monkeypatch):
    from payremind.messaging.whatsapp import SendError

    def boom(*a):
        raise SendError("down")

    monkeypatch.setattr(sender, "send_otp", boom)
    assert client.post("/login", data={"phone": PHONE_A}).status_code == 200


def test_dashboard_requires_login(client):
    r = client.get("/app", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    client.cookies.set("pr_session", "garbage")
    assert client.get("/app", follow_redirects=False).status_code == 303
    assert client.get("/", follow_redirects=False).headers["location"] == "/app"


def test_session_expires(client, sender, clock):
    login(client, sender)
    clock.t = NOW + 7 * 86400 + 1
    assert client.get("/app", follow_redirects=False).status_code == 303


def test_logout_needs_csrf_and_ends_session(client, sender):
    login(client, sender)
    assert client.post("/logout", data={"csrf": "wrong"}).status_code == 403
    r = client.post("/logout", data={"csrf": csrf_of(client)}, follow_redirects=False)
    assert r.headers["location"] == "/login"
    assert client.get("/app", follow_redirects=False).status_code == 303


def _web_upload(client, csrf, content, name="o.csv"):
    return client.post("/app/upload", data={"csrf": csrf}, files={"file": (name, content.encode())})


def test_dashboard_upload_and_actions(client, sender):
    from tests.conftest import CSV

    login(client, sender)
    csrf = csrf_of(client)
    r = _web_upload(client, csrf, CSV + "Bad,,X,,,\n")
    assert "Imported 3 new and updated 0 invoices. 1 rows were skipped" in r.text
    assert "Sharma Traders" in r.text and "31 days late" in r.text and "no phone" in r.text
    assert "₹1,000" in r.text

    inv_id = re.search(r"/app/invoices/(\d+)/paid", r.text).group(1)
    r = client.post(
        f"/app/invoices/{inv_id}/promise", data={"csrf": csrf, "promised_date": "2026-12-20"}
    )
    assert "Promise to pay saved" in r.text and "by 20 Dec" in r.text
    r = client.post(
        f"/app/invoices/{inv_id}/promise", data={"csrf": csrf, "promised_date": "2026-11-01"}
    )
    assert "Pick a promise date" in r.text

    r = client.post("/app/reminders/run", data={"csrf": csrf})
    assert "Sent 2 reminders." in r.text  # INV-1 and INV-2; INV-3 has no phone

    r = client.post(f"/app/invoices/{inv_id}/paid", data={"csrf": csrf})
    assert "Marked as paid." in r.text
    assert (
        client.post("/app/invoices/999999/paid", data={"csrf": csrf}).text.count("wasn&#39;t found")
        == 1
    )
    r = client.post(
        "/app/invoices/999999/promise", data={"csrf": csrf, "promised_date": "2026-12-20"}
    )
    assert "wasn&#39;t found" in r.text


def test_dashboard_upload_errors(client, sender):
    login(client, sender)
    csrf = csrf_of(client)
    assert "Couldn&#39;t import: only" in _web_upload(client, csrf, "x", "a.pdf").text
    assert "Couldn&#39;t read that file" in _web_upload(client, csrf, "zz", "a.xlsx").text
    big = "x" * (5 * 1024 * 1024 + 10)
    assert "too large" in _web_upload(client, csrf, big).text


def test_dashboard_run_reports_failures(client, sender, monkeypatch):
    from payremind.messaging.whatsapp import SendError
    from tests.conftest import CSV

    login(client, sender)
    csrf = csrf_of(client)
    _web_upload(client, csrf, CSV)

    def boom(msg):
        raise SendError("down")

    monkeypatch.setattr(sender, "send", boom)
    r = client.post("/app/reminders/run", data={"csrf": csrf})
    assert "2 failed and will be retried" in r.text


def test_every_dashboard_post_checks_csrf(client, sender):
    login(client, sender)
    for path, data in [
        ("/app/invoices/1/paid", {}),
        ("/app/invoices/1/promise", {"promised_date": "2026-12-20"}),
        ("/app/reminders/run", {}),
    ]:
        assert client.post(path, data={"csrf": "nope", **data}).status_code == 403
    r = client.post("/app/upload", data={"csrf": "nope"}, files={"file": ("a.csv", b"x")})
    assert r.status_code == 403


def test_flash_is_not_reflected(client, sender):
    login(client, sender)
    r = client.get("/app?m=<script>alert(1)</script>")
    assert "alert(1)" not in r.text


def test_web_tenant_isolation(client, auth, sender):
    upload(client, auth["b"])
    b_ids = [i["id"] for i in client.get("/invoices", headers=auth["b"]).json()]
    login(client, sender)  # signs in as tenant A
    csrf = csrf_of(client)
    page = client.get("/app").text
    assert "Sharma Traders" not in page
    for inv_id in b_ids:
        r = client.post(f"/app/invoices/{inv_id}/paid", data={"csrf": csrf})
        assert "wasn&#39;t found" in r.text
    assert len(client.get("/invoices", headers=auth["b"]).json()) == 3
