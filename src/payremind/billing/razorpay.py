"""Minimal Razorpay Subscriptions client. Customers pay on Razorpay's hosted page (short_url)."""

from dataclasses import dataclass, field
from typing import Protocol

import httpx

API = "https://api.razorpay.com/v1"


class BillingError(RuntimeError):
    pass


@dataclass(frozen=True)
class CreatedSubscription:
    id: str
    short_url: str


class BillingGateway(Protocol):
    def create_subscription(self, plan_id: str, tenant_id: int) -> CreatedSubscription: ...

    def cancel_subscription(self, subscription_id: str) -> None: ...


class RazorpayClient:
    def __init__(self, key_id: str, key_secret: str, client: httpx.Client, base: str = API):
        self._auth = (key_id, key_secret)
        self._client = client
        self._base = base

    def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        resp = self._client.post(f"{self._base}{path}", json=body, auth=self._auth, timeout=15)
        if resp.status_code >= 400:
            raise BillingError(f"Razorpay error {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise BillingError("unexpected Razorpay response") from exc
        if not isinstance(data, dict):
            raise BillingError("unexpected Razorpay response")
        return data

    def create_subscription(self, plan_id: str, tenant_id: int) -> CreatedSubscription:
        data = self._post(
            "/subscriptions",
            {
                "plan_id": plan_id,
                "total_count": 120,  # monthly for up to 10 years; customer can cancel any time
                "customer_notify": 1,
                "notes": {"tenant_id": str(tenant_id)},
            },
        )
        sub_id, url = data.get("id"), data.get("short_url")
        if not isinstance(sub_id, str) or not isinstance(url, str):
            raise BillingError("unexpected Razorpay response")
        return CreatedSubscription(sub_id, url)

    def cancel_subscription(self, subscription_id: str) -> None:
        self._post(f"/subscriptions/{subscription_id}/cancel", {"cancel_at_cycle_end": 1})


@dataclass
class FakeGateway:
    created: list[tuple[str, int]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)

    def create_subscription(self, plan_id: str, tenant_id: int) -> CreatedSubscription:
        self.created.append((plan_id, tenant_id))
        n = len(self.created)
        return CreatedSubscription(f"sub_fake{n}", f"https://rzp.io/i/fake{n}")

    def cancel_subscription(self, subscription_id: str) -> None:
        self.cancelled.append(subscription_id)


def make_gateway(key_id: str, key_secret: str) -> BillingGateway | None:
    if key_id and key_secret:
        return RazorpayClient(key_id, key_secret, httpx.Client())
    return None
