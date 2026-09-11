from __future__ import annotations

import os

import pytest

from services.revolut_billing import (
    RevolutBillingError,
    RevolutMerchantClient,
    RevolutMerchantConfig,
)


class _Response:
    def __init__(self, status_code=200, payload=None, content=b"{}"):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.content = content

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [_Response()])

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def _client(session):
    return RevolutMerchantClient(
        RevolutMerchantConfig(
            secret_key="sk_test_secret",
            api_version="2026-08-17",
            public_key="pk_test_public",
        ),
        session=session,
    )


def test_environment_configuration_fails_closed_without_secret(monkeypatch):
    monkeypatch.delenv("REVOLUT_PRODUCTION_API_SECRET_KEY", raising=False)
    monkeypatch.setenv("REVOLUT_MERCHANT_API_VERSION", "2026-08-17")
    with pytest.raises(RevolutBillingError, match="REVOLUT_PRODUCTION_API_SECRET_KEY"):
        RevolutMerchantConfig.from_environment()


def test_environment_configuration_fails_closed_without_version(monkeypatch):
    monkeypatch.setenv("REVOLUT_PRODUCTION_API_SECRET_KEY", "sk_test")
    monkeypatch.delenv("REVOLUT_MERCHANT_API_VERSION", raising=False)
    with pytest.raises(RevolutBillingError, match="REVOLUT_MERCHANT_API_VERSION"):
        RevolutMerchantConfig.from_environment()


def test_server_headers_use_secret_bearer_and_exact_version_only():
    session = _Session([_Response(200, {"webhooks": []})])
    client = _client(session)

    client.list_webhooks()

    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://merchant.revolut.com/api/webhooks"
    assert kwargs["headers"]["Authorization"] == "Bearer sk_test_secret"
    assert kwargs["headers"]["Revolut-Api-Version"] == "2026-08-17"
    assert "pk_test_public" not in repr(kwargs["headers"])


def test_create_subscription_uses_exact_revolut_contract_and_idempotency_key():
    session = _Session([
        _Response(
            201,
            {
                "id": "subscription-1",
                "state": "pending",
                "customer_id": "customer-1",
                "setup_order_id": "order-1",
            },
        )
    ])
    client = _client(session)

    result = client.create_subscription(
        plan_variation_id="variation-1",
        customer_id="customer-1",
        setup_order_redirect_url="https://bt38.example/billing",
        external_reference="bt38-account-7",
        idempotency_key="bt38-account-7-package-3",
    )

    assert result["id"] == "subscription-1"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://merchant.revolut.com/api/subscriptions"
    assert kwargs["headers"]["Idempotency-Key"] == "bt38-account-7-package-3"
    assert kwargs["json"] == {
        "plan_variation_id": "variation-1",
        "customer_id": "customer-1",
        "setup_order_redirect_url": "https://bt38.example/billing",
        "external_reference": "bt38-account-7",
    }


def test_retrieve_setup_order_uses_order_endpoint():
    session = _Session([_Response(200, {"id": "order-1", "checkout_url": "https://checkout.revolut.com/x"})])
    client = _client(session)

    order = client.retrieve_order("order-1")

    assert order["checkout_url"].startswith("https://checkout.revolut.com/")
    assert session.calls[0][1] == "https://merchant.revolut.com/api/orders/order-1"


def test_provider_error_never_contains_secret_header():
    session = _Session([_Response(401, {"message": "bad credentials", "code": "unauthorised"})])
    client = _client(session)

    with pytest.raises(RevolutBillingError) as raised:
        client.list_webhooks()

    text = str(raised.value)
    assert "sk_test_secret" not in text
    assert "Bearer" not in text
    assert raised.value.status_code == 401
    assert raised.value.provider_code == "unauthorised"


def test_import_and_client_construction_make_no_network_call():
    session = _Session([])
    client = _client(session)
    assert client is not None
    assert session.calls == []
