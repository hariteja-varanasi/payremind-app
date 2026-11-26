"""WhatsApp senders. Reminders use a Meta-approved utility template with 4 variables."""

from dataclasses import dataclass, field
from typing import Protocol

import httpx

TEMPLATE_NAME = "payment_reminder_v1"


@dataclass(frozen=True)
class ReminderMessage:
    to_e164: str
    customer_name: str
    invoice_number: str
    amount_text: str
    pay_link: str
    language: str = "en"


class Sender(Protocol):
    def send(self, msg: ReminderMessage) -> str: ...


class SendError(RuntimeError):
    pass


@dataclass
class FakeSender:
    """Records messages instead of sending. Used in dev and tests."""

    sent: list[ReminderMessage] = field(default_factory=list)

    def send(self, msg: ReminderMessage) -> str:
        self.sent.append(msg)
        return f"fake-{len(self.sent)}"


class CloudApiSender:
    def __init__(self, token: str, phone_number_id: str, base_url: str, client: httpx.Client):
        self._url = f"{base_url}/{phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = client

    def send(self, msg: ReminderMessage) -> str:
        body = {
            "messaging_product": "whatsapp",
            "to": msg.to_e164.lstrip("+"),
            "type": "template",
            "template": {
                "name": TEMPLATE_NAME,
                "language": {"code": msg.language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": v}
                            for v in (
                                msg.customer_name,
                                msg.invoice_number,
                                msg.amount_text,
                                msg.pay_link,
                            )
                        ],
                    }
                ],
            },
        }
        resp = self._client.post(self._url, json=body, headers=self._headers, timeout=10)
        if resp.status_code >= 400:
            raise SendError(f"WhatsApp API error {resp.status_code}")
        try:
            return str(resp.json()["messages"][0]["id"])
        except (KeyError, IndexError, ValueError) as exc:
            raise SendError("unexpected WhatsApp API response") from exc
