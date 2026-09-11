"""Governed Revolut Merchant API client for BT38 subscription billing.

This module is deliberately side-effect free at import time.  It does not create
customers, subscriptions, orders or webhooks on startup.  Callers must make an
explicit customer/admin action before any provider write occurs.

Revolut is payment authority.  BT38 package/account models remain entitlement and
workspace authority; only non-secret provider identifiers may be persisted there.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping

import requests


DEFAULT_BASE_URL = "https://merchant.revolut.com"
_SECRET_ENV = "REVOLUT_PRODUCTION_API_SECRET_KEY"
_PUBLIC_ENV = "REVOLUT_PRODUCTION_API_PUBLIC_KEY"
_VERSION_ENV = "REVOLUT_MERCHANT_API_VERSION"


class RevolutBillingError(RuntimeError):
    """Provider/configuration failure safe to surface without secret material."""

    def __init__(self, message: str, *, status_code: int | None = None, provider_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code


@dataclass(frozen=True)
class RevolutMerchantConfig:
    secret_key: str
    api_version: str
    base_url: str = DEFAULT_BASE_URL
    public_key: str = ""

    @classmethod
    def from_environment(cls) -> "RevolutMerchantConfig":
        secret_key = str(os.getenv(_SECRET_ENV) or "").strip()
        api_version = str(os.getenv(_VERSION_ENV) or "").strip()
        public_key = str(os.getenv(_PUBLIC_ENV) or "").strip()
        base_url = str(os.getenv("REVOLUT_MERCHANT_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")

        if not secret_key:
            raise RevolutBillingError(f"{_SECRET_ENV} is not configured.")
        if not api_version:
            raise RevolutBillingError(f"{_VERSION_ENV} is not configured.")
        if not base_url.startswith("https://"):
            raise RevolutBillingError("Revolut Merchant base URL must use HTTPS.")

        return cls(
            secret_key=secret_key,
            api_version=api_version,
            base_url=base_url,
            public_key=public_key,
        )


class RevolutMerchantClient:
    """Small exact-request client for the Revolut Merchant API.

    No retries are performed here for provider writes.  A caller may safely retry
    an idempotent write only when it supplies the same Idempotency-Key and payload.
    """

    def __init__(
        self,
        config: RevolutMerchantConfig | None = None,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = (5.0, 20.0),
    ) -> None:
        self.config = config or RevolutMerchantConfig.from_environment()
        self.session = session or requests.Session()
        self.timeout = timeout

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.config.secret_key}",
            "Revolut-Api-Version": self.config.api_version,
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = str(idempotency_key)
        return headers

    @staticmethod
    def _safe_provider_error(response: requests.Response) -> tuple[str, str | None]:
        provider_code = None
        message = f"Revolut Merchant API returned HTTP {response.status_code}."
        try:
            payload = response.json()
        except ValueError:
            return message, provider_code
        if isinstance(payload, Mapping):
            provider_code = str(payload.get("code") or payload.get("error") or "").strip() or None
            detail = str(payload.get("message") or payload.get("detail") or "").strip()
            if detail:
                message = f"Revolut Merchant API rejected the request: {detail[:300]}"
        return message, provider_code

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        path = "/" + str(path or "").lstrip("/")
        url = f"{self.config.base_url}{path}"
        headers = self._headers(idempotency_key=idempotency_key)
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        try:
            response = self.session.request(
                method.upper(),
                url,
                headers=headers,
                json=dict(json_body) if json_body is not None else None,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            # Never include request headers or config in the exception text.
            raise RevolutBillingError("Revolut Merchant API could not be reached.") from exc

        if response.status_code not in expected:
            message, provider_code = self._safe_provider_error(response)
            raise RevolutBillingError(
                message,
                status_code=response.status_code,
                provider_code=provider_code,
            )

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise RevolutBillingError("Revolut Merchant API returned an invalid JSON response.") from exc

    # Customer authority is Revolut; callers should persist the returned id before
    # making a subscription write so a retry never creates duplicate customers.
    def create_customer(self, *, full_name: str, email: str, phone: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "full_name": str(full_name or "").strip(),
            "email": str(email or "").strip().lower(),
        }
        if not payload["full_name"]:
            raise ValueError("full_name is required")
        if not payload["email"]:
            raise ValueError("email is required")
        if phone:
            payload["phone"] = str(phone).strip()
        return self._request("POST", "/api/customers", json_body=payload, expected=(201,))

    def retrieve_customer(self, customer_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/customers/{str(customer_id).strip()}", expected=(200,))

    def create_subscription(
        self,
        *,
        plan_variation_id: str,
        customer_id: str,
        setup_order_redirect_url: str,
        external_reference: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "plan_variation_id": str(plan_variation_id).strip(),
            "customer_id": str(customer_id).strip(),
            "setup_order_redirect_url": str(setup_order_redirect_url).strip(),
            "external_reference": str(external_reference).strip(),
        }
        if not all(payload.values()):
            raise ValueError("plan variation, customer, redirect URL and external reference are required")
        if not str(idempotency_key or "").strip():
            raise ValueError("idempotency_key is required")
        return self._request(
            "POST",
            "/api/subscriptions",
            json_body=payload,
            idempotency_key=idempotency_key,
            expected=(201,),
        )

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/subscriptions/{str(subscription_id).strip()}", expected=(200,))

    def retrieve_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/orders/{str(order_id).strip()}", expected=(200,))

    def change_plan(self, *, subscription_id: str, plan_variation_id: str, scheduled: str = "at_cycle_end") -> None:
        if scheduled not in {"at_cycle_end", "immediate"}:
            raise ValueError("scheduled must be 'at_cycle_end' or 'immediate'")
        self._request(
            "POST",
            f"/api/subscriptions/{str(subscription_id).strip()}/change-plan",
            json_body={
                "plan_variation_id": str(plan_variation_id).strip(),
                "scheduled": scheduled,
            },
            expected=(204,),
        )

    def cancel_subscription(self, subscription_id: str) -> None:
        self._request(
            "POST",
            f"/api/subscriptions/{str(subscription_id).strip()}/cancel",
            expected=(204,),
        )

    def list_webhooks(self) -> dict[str, Any]:
        return self._request("GET", "/api/webhooks", expected=(200,))

    def create_webhook(self, *, url: str, events: list[str]) -> dict[str, Any]:
        clean_events = [str(event).strip() for event in events if str(event).strip()]
        if not clean_events:
            raise ValueError("At least one Revolut webhook event is required")
        return self._request(
            "POST",
            "/api/webhooks",
            json_body={"url": str(url).strip(), "events": clean_events},
            expected=(200,),
        )


def configured_revolut_client() -> RevolutMerchantClient:
    """Build the production client lazily so startup never performs a provider call."""
    return RevolutMerchantClient(RevolutMerchantConfig.from_environment())
