#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:5000}"
KEY="${TASK_API_KEY:-dev-key-123}"
SKU="${SKU:-AMZ-SH-MH-DV-01}"
QTY="${QTY:-10}"

jq_(){ python -m json.tool 2>/dev/null || cat; }

echo "=== 1) HEALTH ==="
curl -s "$BASE/health" | jq_

echo; echo "=== 2) STORES ==="
curl -s "$BASE/admin/stores" -H "X-Task-Key: $KEY" | jq_

echo; echo "=== 3) PRECHECK (identifies blockers) ==="
PRE="$(curl -s "$BASE/api/diagnostics/amazon/sku-precheck/$SKU" -H "X-Task-Key: $KEY")"
echo "$PRE" | jq_

# Check if precheck passed
OK="$(echo "$PRE" | python -c "import json,sys; d=json.load(sys.stdin); print('true' if d.get('ok') else 'false')" 2>/dev/null || echo 'false')"
PRICE="$(echo "$PRE" | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('price','0'))" 2>/dev/null || echo '0')"

echo; echo "=== 4) AUTO-FIX (price=0) & PUSH ==="
if [ "$OK" = "false" ]; then
  HAS_PRICE_BLOCKER="$(echo "$PRE" | python -c "import json,sys; d=json.load(sys.stdin); print(any('price' in str(r).lower() for r in d.get('reasons',[])))" 2>/dev/null || echo 'False')"
  if [ "$HAS_PRICE_BLOCKER" = "True" ]; then
    echo "Price blocker detected → setting price to 9.99 and pushing…"
    curl -s -X POST "$BASE/api/admin/amazon/set-price-and-push/$SKU?price=9.99" \
      -H "X-Task-Key: $KEY" | jq_
  else
    echo "Precheck failed (not price-related). Skipping auto-push."
  fi
else
  echo "Precheck OK → pushing with qty=$QTY…"
  curl -s -X POST "$BASE/api/sync/amazon/sku/$SKU?qty=$QTY" \
    -H "X-Task-Key: $KEY" | jq_
fi

echo; echo "=== 5) LATEST FEED STATUS ==="
curl -s "$BASE/api/diagnostics/amazon/feed/last" -H "X-Task-Key: $KEY" | jq_

echo; echo "=== 6) LOGS (tail) ==="
LOG="$(ls -t /tmp/logs/Start_application_*.log 2>/dev/null | head -n1 || echo '')"
if [ -n "$LOG" ] && [ -f "$LOG" ]; then
  echo "LOG=$LOG"
  grep -E "AMZ|$SKU|Throttle guard|backing off for|create_feed|feedId|FATAL|QuotaExceeded|Unauthorized|BUYABLE|quantity" "$LOG" 2>/dev/null | tail -n 100 || echo "No matching logs found."
else
  echo "No workflow log yet."
fi

echo; cat <<'TIP'

=== 7) INTERPRETATION ===
PASS if:
- Health ok:true, DB connected
- Precheck ok:true (no price/qty blockers)
- Push JSON shows ok:true, or a feed submission happened
- Feed status: IN_PROGRESS or DONE (if SP-API Feeds scope is configured)

If you see "Unauthorized" in feed status/result → SP-API Feeds scope is missing for your app (re-authorize in Seller Central).
If "QuotaExceeded" → throttle will back off automatically; try again after a few minutes.
TIP
