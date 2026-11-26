import hashlib
import hmac
import json

import pytest

from tests.conftest import APP_SECRET, VERIFY_TOKEN, upload


def _post(client, payload, secret=APP_SECRET, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"x-hub-signature-256": sig, "content-type": "application/json"},
    )


def _msg(frm, text=None, button=None, kind=None):
    m = {"from": frm, "type": kind or ("button" if button else "text")}
    if text is not None:
        m["text"] = {"body": text}
    if button is not None:
        m["button"] = {"payload": button}
    return {"entry": [{"changes": [{"value": {"messages": [m]}}]}]}


def test_verify_handshake(client):
    q = {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "42"}
    r = client.get("/webhooks/whatsapp", params=q)
    assert r.status_code == 200 and r.text == "42"
    q["hub.verify_token"] = "wrong"
    assert client.get("/webhooks/whatsapp", params=q).status_code == 403


def test_rejects_bad_or_missing_signature(client):
    assert _post(client, _msg("919845012345", "STOP"), secret="nope").status_code == 401
    r = client.post("/webhooks/whatsapp", content=b"{}")
    assert r.status_code == 401


def test_rejects_bad_payloads(client):
    assert _post(client, None, raw=b"not json").status_code == 400
    assert _post(client, None, raw=b"[1]").status_code == 400
    assert _post(client, None, raw=b"x" * (256 * 1024 + 1)).status_code == 413


@pytest.mark.parametrize(
    "payload",
    [
        _msg("919845012345", "STOP"),
        _msg("919845012345", " Band Karo "),
        _msg("919845012345", button="STOP"),
    ],
)
def test_stop_opts_out_across_tenants(client, auth, sender, payload):
    upload(client, auth["a"])
    upload(client, auth["b"])
    assert _post(client, payload).json() == {"opted_out": 1}
    assert _post(client, payload).json() == {"opted_out": 0}  # idempotent
    client.post("/reminders/run", headers=auth["a"])
    client.post("/reminders/run", headers=auth["b"])
    assert {m.to_e164 for m in sender.sent} == {"+919876543210"}


def test_non_stop_messages_ignored(client):
    for payload in (
        _msg("919845012345", "will pay tomorrow"),
        _msg("919845012345", kind="image"),
        _msg("12345", "STOP"),
        {"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]},
        {"object": "whatsapp_business_account"},
    ):
        assert _post(client, payload).json() == {"opted_out": 0}
