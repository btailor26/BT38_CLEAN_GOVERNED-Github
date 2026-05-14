#!/usr/bin/env bash
set -euo pipefail
BASE="https://inventory-sync-bhavtee.repl.co"
SKU="AMZ-KJ-MN-X6"
echo "=== HEALTH ==="; curl -s "$BASE/health" || true; echo; echo
LOG="$(ls -t /tmp/logs/Start_application_*.log 2>/dev/null | head -n1 || true)"
if [ -n "$LOG" ]; then
  echo "Using log file: $LOG"
  echo "-- recent Amazon lines --"
  grep -iE "amazon|feed|ASIN|FBM|AFN|BUYABLE|quantity|QuotaExceeded|Unauthorized|AccessDenied|InvalidSignature|price|marketplace" "$LOG" | tail -n 100 || true
  echo; echo "-- recent lines for SKU=$SKU --"
  grep -i "$SKU" "$LOG" | tail -n 40 || true
else
  echo "No workflow log in /tmp/logs yet."
fi
echo
echo "=== DIAGNOSTICS ENDPOINTS (if available) ==="
for path in "/api/diagnostics/amazon/sku/$SKU" "/_debug/logs/1" "/_debug/store/1"; do
  echo "GET $BASE$path"
  curl -s "$BASE$path" || true
  echo; echo
done
