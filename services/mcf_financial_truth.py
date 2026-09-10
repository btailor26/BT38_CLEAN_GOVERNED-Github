"""Amazon MCF financial truth readback.

Rate cards remain estimate/reference information. This module is deliberately
read-only: it asks Amazon Finances for order-specific financial evidence and
returns candidate evidence without manufacturing or persisting an actual MCF
cost. Persistence is only valid after exact MCF identity and Amazon monetary
authority are proven.
"""
from __future__ import annotations

from typing import Any

import requests

from services.governed_amazon_tracking_readback import (
    SP_API_EU_ENDPOINT,
    _lwa_access_token,
    _request_headers,
)

FINANCES_TRANSACTIONS_PATH = "/finances/2024-06-19/transactions"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _finance_payload(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    nested = body.get("payload")
    return nested if isinstance(nested, dict) else body


def _identifier_pairs(value: Any) -> list[tuple[str, str]]:
    """Collect Amazon identifiers without guessing undocumented enum values."""
    pairs: list[tuple[str, str]] = []
    if isinstance(value, dict):
        name = _text(
            value.get("relatedIdentifierName")
            or value.get("itemRelatedIdentifierName")
            or value.get("name")
        )
        identifier = _text(
            value.get("relatedIdentifierValue")
            or value.get("itemRelatedIdentifierValue")
            or value.get("value")
        )
        if name and identifier:
            pairs.append((name.upper(), identifier))
        for child in value.values():
            pairs.extend(_identifier_pairs(child))
    elif isinstance(value, list):
        for child in value:
            pairs.extend(_identifier_pairs(child))
    return pairs


def list_amazon_financial_evidence(*, store: Any, amazon_order_id: str) -> dict[str, Any]:
    """Read Amazon Transaction View evidence for one exact Amazon order.

    This does not calculate an MCF fee and does not write to BT38 or Amazon.
    """
    order_id = _text(amazon_order_id)
    if not order_id:
        return {
            "success": False,
            "reason": "exact_amazon_order_id_required",
            "financial_authority": "pending_amazon_financial_truth",
            "transactions": [],
        }

    access_token = _lwa_access_token(store)
    response = requests.get(
        f"{SP_API_EU_ENDPOINT}{FINANCES_TRANSACTIONS_PATH}",
        params={
            "relatedIdentifierName": "ORDER_ID",
            "relatedIdentifierValue": order_id,
        },
        headers=_request_headers(access_token),
        timeout=30,
    )
    if response.status_code >= 400:
        return {
            "success": False,
            "reason": "amazon_finances_transactions_read_failed",
            "status_code": response.status_code,
            "error": response.text[:1000],
            "financial_authority": "pending_amazon_financial_truth",
            "transactions": [],
        }

    body = _finance_payload(response.json() or {})
    rows = [row for row in (body.get("transactions") or []) if isinstance(row, dict)]
    exact_rows = []
    for row in rows:
        identifiers = _identifier_pairs(row.get("relatedIdentifiers") or [])
        if any(name == "ORDER_ID" and value == order_id for name, value in identifiers):
            exact_rows.append(row)

    return {
        "success": True,
        "reason": None,
        "amazon_order_id": order_id,
        "financial_authority": (
            "amazon_order_specific_financial_evidence"
            if exact_rows
            else "pending_amazon_financial_truth"
        ),
        "transactions": exact_rows,
        "next_token": _text(body.get("nextToken")) or None,
    }
