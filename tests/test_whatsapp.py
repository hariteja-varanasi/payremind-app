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
