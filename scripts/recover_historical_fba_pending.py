"""Explicit finite runner for historical FBA/AFN Pending lifecycle recovery."""
from __future__ import annotations

import json
import os

from app import app
from services.governed_fba_historical_recovery import recover_historical_pending_fba


if __name__ == "__main__":
    raw_store = str(os.environ.get("BT38_FBA_RECOVERY_STORE_ID") or "").strip()
    raw_limit = str(os.environ.get("BT38_FBA_RECOVERY_LIMIT") or "500").strip()
    store_id = int(raw_store) if raw_store else None
    limit = int(raw_limit)
    with app.app_context():
        result = recover_historical_pending_fba(store_id=store_id, limit=limit)
        print(json.dumps(result, default=str, sort_keys=True))
        if not result.get("success"):
            raise SystemExit(1)
