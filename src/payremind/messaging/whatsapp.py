"""WhatsApp senders. Reminders use a Meta-approved utility template with 4 variables."""

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

TEMPLATE_NAME = "payment_reminder_v1"  # submitted to Meta in "en" and "hi"
OTP_TEMPLATE_NAME = "login_code_v1"  # authentication category, copy-code button


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

    def send_otp(self, to_e164: str, code: str) -> str: ...


class SendError(RuntimeError):
    pass


@dataclass
class FakeSender:
    """Records messages instead of sending. Used in dev and tests."""

    sent: list[ReminderMessage] = field(default_factory=list)
    otps: list[tuple[str, str]] = field(default_factory=list)

    def send(self, msg: ReminderMessage) -> str:
        self.sent.append(msg)
        return f"fake-{len(self.sent)}"

    def send_otp(self, to_e164: str, code: str) -> str:
        self.otps.append((to_e164, code))
        return f"fake-otp-{len(self.otps)}"


class CloudApiSender:
    def __init__(self, token: str, phone_number_id: str, base_url: str, client: httpx.Client):
        self._url = f"{base_url}/{phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = client

    def _post(self, body: dict[str, Any]) -> str:
        resp = self._client.post(self._url, json=body, headers=self._headers, timeout=10)
        if resp.status_code >= 400:
            raise SendError(f"WhatsApp API error {resp.status_code}")
        try:
            return str(resp.json()["messages"][0]["id"])
        except (KeyError, IndexError, ValueError) as exc:
            raise SendError("unexpected WhatsApp API response") from exc

    def send_otp(self, to_e164: str, code: str) -> str:
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_e164.lstrip("+"),
                "type": "template",
                "template": {
                    "name": OTP_TEMPLATE_NAME,
                    "language": {"code": "en"},
                    "components": [
                        {"type": "body", "parameters": [{"type": "text", "text": code}]},
                        {
                            "type": "button",
                            "sub_type": "url",
                            "index": "0",
                            "parameters": [{"type": "text", "text": code}],
                        },
                    ],
                },
            }
        )

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
        return self._post(body)


def make_sender(token: str, phone_number_id: str, base_url: str) -> Sender:
    """Real sender when WhatsApp credentials are configured, otherwise the fake one."""
    if token and phone_number_id:
        return CloudApiSender(token, phone_number_id, base_url, httpx.Client())
    return FakeSender()
