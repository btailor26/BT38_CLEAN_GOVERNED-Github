#!/usr/bin/env python3
"""Manual Amazon feed encryption check.

This file is intentionally not a pytest test. It must not execute marketplace or
legacy Amazon code during pytest collection. Run manually only when explicitly
needed.
"""

from __future__ import annotations

import os

__test__ = False


def main() -> int:
    from amazon_service import AmazonService

    service = AmazonService(
        store_id=27,
        refresh_token=os.environ.get("AMAZON_REFRESH_TOKEN"),
        client_id=os.environ.get("AMAZON_LWA_CLIENT_ID"),
        client_secret=os.environ.get("AMAZON_LWA_CLIENT_SECRET"),
        seller_id=os.environ.get("AMAZON_SELLER_ID"),
        marketplace_id="A1F83G8C2ARO7P",
    )

    test_sku = "FBA-CR-RV-URU-200ml"
    test_quantity = 19

    print("Testing Amazon feed encryption...")
    print(f"SKU: {test_sku}, Quantity: {test_quantity}")
    print("=" * 60)

    success, message = service.push_quantity_update(test_sku, test_quantity)

    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
    print(f"Message: {message}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
