import httpx
import pytest

from payremind.messaging.whatsapp import CloudApiSender, ReminderMessage, SendError

MSG = ReminderMessage("+919845012345", "Sharma", "INV-1", "₹1,000.00", "upi://pay?pa=a@okaxis")


def make(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CloudApiSender("tok", "123", "https://graph.example/v21.0", client)


def test_sends_template():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = req.content
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    assert make(handler).send(MSG) == "wamid.1"
    assert seen["url"] == "https://graph.example/v21.0/123/messages"
    assert seen["auth"] == "Bearer tok"
    assert b'"to":"919845012345"' in seen["body"]


@pytest.mark.parametrize(
    "resp",
    [httpx.Response(500), httpx.Response(200, json={"x": 1}), httpx.Response(200, text="no")],
)
def test_errors(resp):
    with pytest.raises(SendError):
        make(lambda req: resp).send(MSG)


def test_sends_otp_template():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = req.content
        return httpx.Response(200, json={"messages": [{"id": "wamid.2"}]})

    assert make(handler).send_otp("+919845012345", "123456") == "wamid.2"
    assert b'"name":"login_code_v1"' in seen["body"]
    assert seen["body"].count(b'"text":"123456"') == 2


def test_hindi_language_code():
    seen = {}

    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    msg = ReminderMessage("+919845012345", "S", "1", "₹1", "https://x/p/y", language="hi")
    make(handler).send(msg)
    assert b'"language":{"code":"hi"}' in seen["body"]


def test_make_sender():
    from payremind.messaging.whatsapp import CloudApiSender, FakeSender, make_sender

    assert isinstance(make_sender("", "", "https://x"), FakeSender)
    assert isinstance(make_sender("t", "1", "https://x"), CloudApiSender)


def test_dev_log_sender(caplog):
    from payremind.messaging.whatsapp import LogSender, make_sender

    s = make_sender("", "", "https://x", dev_log=True)
    assert isinstance(s, LogSender)
    with caplog.at_level("WARNING", logger="payremind.dev"):
        s.send_otp("+919845012345", "123456")
        s.send(MSG)
    assert "login code for +919845012345: 123456" in caplog.text
    assert "INV-1" in caplog.text and s.otps and s.sent
    # never used when real credentials exist
    assert not isinstance(make_sender("t", "1", "https://x", dev_log=True), LogSender)
