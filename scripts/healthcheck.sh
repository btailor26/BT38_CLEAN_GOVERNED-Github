#!/bin/bash
# BT38 Health Check Script

set -e

HOST="${1:-localhost}"
PORT="${2:-5000}"

echo "Checking BT38 health at $HOST:$PORT..."

# Health endpoint
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST:$PORT/health")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ /health: OK (HTTP $HTTP_CODE)"
else
    echo "✗ /health: FAILED (HTTP $HTTP_CODE)"
    exit 1
fi

# Fingerprint endpoint
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST:$PORT/api/system/fingerprint")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ /api/system/fingerprint: OK (HTTP $HTTP_CODE)"
else
    echo "✗ /api/system/fingerprint: FAILED (HTTP $HTTP_CODE)"
    exit 1
fi

# Sentinel status
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST:$PORT/api/sentinel/status")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ /api/sentinel/status: OK (HTTP $HTTP_CODE)"
else
    echo "⚠ /api/sentinel/status: HTTP $HTTP_CODE (may require auth)"
fi

echo ""
echo "Health check passed!"
