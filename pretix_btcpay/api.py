import hashlib
import hmac
import logging
from typing import Any

import requests

from pretix.base.payment import PaymentException

logger = logging.getLogger(__name__)

WEBHOOK_EVENTS = [
    "InvoiceSettled",
    "InvoiceProcessing",
    "InvoiceExpired",
    "InvoiceInvalid",
    "InvoiceReceivedPayment",
    "InvoicePaymentSettled",
]


class BTCPayError(PaymentException):
    pass


class BTCPayAPI:
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = self.url + path
        headers = {"Authorization": f"token {self.api_key}"}
        try:
            response = requests.request(
                method, url, headers=headers, timeout=15, **kwargs
            )
            response.raise_for_status()
        except requests.RequestException as e:
            raise BTCPayError(
                "We had trouble communicating with the payment provider. "
                "Please try again and get in touch with us if this problem persists."
            ) from e
        if not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise BTCPayError("Unexpected response from payment provider.")
        return data

    def create_invoice(
        self,
        store_id: str,
        *,
        amount: str,
        currency: str,
        order_id: str,
        metadata: dict[str, Any] | None = None,
        redirect_url: str | None = None,
        expiry_minutes: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "amount": amount,
            "currency": currency,
            "metadata": {
                "orderId": order_id,
            },
        }
        if metadata:
            payload["metadata"].update(metadata)
        checkout: dict[str, Any] = {}
        if redirect_url:
            checkout["redirectURL"] = redirect_url
            checkout["redirectAutomatically"] = True
        if expiry_minutes:
            checkout["expirationMinutes"] = expiry_minutes
        if checkout:
            payload["checkout"] = checkout
        return self._request(
            "POST",
            f"/api/v1/stores/{store_id}/invoices",
            json=payload,
        )

    def get_invoice(self, store_id: str, invoice_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/stores/{store_id}/invoices/{invoice_id}",
        )

    def list_webhooks(self, store_id: str) -> list[dict[str, Any]]:
        url = self.url + f"/api/v1/stores/{store_id}/webhooks"
        headers = {"Authorization": f"token {self.api_key}"}
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
        except requests.RequestException as e:
            raise BTCPayError(
                "We had trouble communicating with the payment provider. "
                "Please try again and get in touch with us if this problem persists."
            ) from e
        data = response.json()
        if not isinstance(data, list):
            raise BTCPayError("Unexpected response from payment provider.")
        return data

    def create_webhook(
        self,
        store_id: str,
        url: str,
        events: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "url": url,
            "enabled": True,
            "automaticRedelivery": True,
            "authorizedEvents": (
                {"everything": True}
                if not events
                else {"everything": False, "specificEvents": events}
            ),
        }
        return self._request(
            "POST",
            f"/api/v1/stores/{store_id}/webhooks",
            json=payload,
        )

    def delete_webhook(self, store_id: str, webhook_id: str) -> None:
        self._request(
            "DELETE",
            f"/api/v1/stores/{store_id}/webhooks/{webhook_id}",
        )

    @staticmethod
    def verify_signature(secret: str, raw_body: bytes, sig_header: str | None) -> bool:
        if not sig_header:
            return False
        expected = "sha256=" + hmac.new(
            secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)