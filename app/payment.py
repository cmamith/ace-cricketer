"""Razorpay Orders API integration and signature verification.

Do not set an order paid merely because Checkout invokes its success handler.
"""
from __future__ import annotations

import hashlib
import hmac
import httpx


class PaymentProviderError(Exception):
    pass


class RazorpayGateway:
    ENDPOINT = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str):
        self.key_id = key_id
        self.key_secret = key_secret
        self.webhook_secret = webhook_secret

    @property
    def enabled(self) -> bool:
        return bool(self.key_id and self.key_secret and self.webhook_secret)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            with httpx.Client(timeout=12, auth=(self.key_id, self.key_secret)) as client:
                response = client.request(method, self.ENDPOINT + path, **kwargs)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PaymentProviderError("Payment service could not complete the request") from exc

    def create_order(self, total_paise: int, receipt: str) -> str:
        result = self._request(
            "POST", "/orders", json={"amount": total_paise, "currency": "INR", "receipt": receipt}
        )
        if not result.get("id"):
            raise PaymentProviderError("Payment provider returned an invalid order")
        return str(result["id"])

    def get_payment(self, payment_id: str) -> dict:
        return self._request("GET", f"/payments/{payment_id}")

    def verify_checkout(self, saved_order_id: str, payment_id: str, signature: str) -> bool:
        digest = hmac.new(
            self.key_secret.encode(), f"{saved_order_id}|{payment_id}".encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(digest, signature)

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        digest = hmac.new(self.webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, signature)
