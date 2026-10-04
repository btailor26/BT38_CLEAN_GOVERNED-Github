"""Governed one-shot Packlink post-deploy exception recovery.

DB selection only: exact Packlink shipments past persisted latest delivery promise
and not DB-proven Delivered. Provider access is one /track read per selected
shipment. No polling, marketplace write, broad provider scan, worker or scheduler.
"""
from __future__ import annotations

import json

from app import app
from services.fbm_packlink_callback import recover_packlink_past_delivery_promise


def main() -> int:
    with app.app_context():
        result = recover_packlink_past_delivery_promise()
    print("PACKLINK_POST_DEPLOY_RECOVERY " + json.dumps(result, default=str, sort_keys=True))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
