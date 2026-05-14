#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:5000}"
KEY="${TASK_API_KEY:-dev-key-123}"
SKU="${SKU:-AMZ-SH-MH-DV-01}"
QTY="${QTY:-10}"
jq_(){ python -m json.tool 2>/dev/null || cat; }

echo "== Feeds scope probe =="
curl -s "$BASE/api/diagnostics/amazon/feeds-scope" -H "X-Task-Key: $KEY" | jq_
echo; echo "== Push $SKU qty=$QTY =="
curl -s -X POST "$BASE/api/sync/amazon/sku/$SKU?qty=$QTY" -H "X-Task-Key: $KEY" | jq_
echo; echo "== Latest feed status =="
curl -s "$BASE/api/diagnostics/amazon/feed/last" -H "X-Task-Key: $KEY" | jq_
