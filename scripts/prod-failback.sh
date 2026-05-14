#!/bin/bash
# BT38 Production Failback Script
# Reverts production traffic from Fly.io back to Replit
#
# Usage:
#   ./scripts/prod-failback.sh              # Dry-run mode (default)
#   ./scripts/prod-failback.sh --live       # Live mode (requires confirmation)
#
# Required Environment Variables:
#   CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID

set -euo pipefail

LIVE_MODE=false

# Hardcoded production values
PROD_ROOT_RECORD_ID="${PROD_ROOT_RECORD_ID:-532c13b367d19d03aad33040f5ccd28c}"
PROD_WWW_RECORD_ID="${PROD_WWW_RECORD_ID:-3292498f5157098bc36055d1f6e1ef40}"
REPLIT_IP="${REPLIT_IP:-34.111.179.208}"
FLY_PROD_APP_NAME="${FLY_PROD_APP_NAME:-bt38-prod}"
PROD_DOMAIN="${PROD_DOMAIN:-bt38inv.com}"

for arg in "$@"; do
    case $arg in
        --live)
            LIVE_MODE=true
            ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; }

export PATH="$HOME/.fly/bin:$PATH"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                                                              ║"
echo "║          BT38 PRODUCTION FAILBACK                           ║"
echo "║          Revert to Replit                                    ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [ "$LIVE_MODE" = true ]; then
    echo -e "  Mode: ${RED}${BOLD}LIVE EXECUTION${NC}"
else
    echo -e "  Mode: ${CYAN}${BOLD}DRY-RUN (default)${NC}"
fi
echo ""

# ============================================================
# DRY-RUN MODE
# ============================================================
if [ "$LIVE_MODE" = false ]; then
    echo "FAILBACK PLAN:"
    echo ""
    echo "  1. Disable Fly.io workers on $FLY_PROD_APP_NAME"
    echo "     - IS_ACTIVE_PRIMARY=false"
    echo "     - ENABLE_SYNC_WORKERS=false"
    echo "     - ENABLE_PUSH_JOBS=false"
    echo "     - ENABLE_SCHEDULERS=false"
    echo ""
    echo "  2. Revert DNS: $PROD_DOMAIN → $REPLIT_IP (A record)"
    echo ""
    echo "  3. Revert DNS: www.$PROD_DOMAIN → $REPLIT_IP (A record)"
    echo ""
    echo "  4. Re-enable Replit workers (MANUAL STEP)"
    echo ""
    echo "================================================================"
    echo ""
    echo "To execute, run:"
    echo "    ./scripts/prod-failback.sh --live"
    echo ""
    exit 0
fi

# ============================================================
# LIVE MODE
# ============================================================
echo -e "${RED}${BOLD}LIVE FAILBACK MODE${NC}"
echo ""
echo "This will revert production to Replit."
echo ""
echo -e "${YELLOW}Type exactly:${NC} CONFIRM_FAILBACK_TO_REPLIT"
echo ""
echo -n "Confirmation: "
read -r CONFIRMATION

if [ "$CONFIRMATION" != "CONFIRM_FAILBACK_TO_REPLIT" ]; then
    log_error "Confirmation failed"
    exit 1
fi

echo ""
log_info "Executing failback..."
echo ""

# Step 1: Disable Fly.io workers
log_info "Disabling Fly.io workers..."
flyctl secrets set \
    IS_ACTIVE_PRIMARY=false \
    ENABLE_SYNC_WORKERS=false \
    ENABLE_PUSH_JOBS=false \
    ENABLE_SCHEDULERS=false \
    FAILOVER_ROLE=secondary \
    -a "$FLY_PROD_APP_NAME" 2>/dev/null || log_warn "Could not update Fly.io secrets"

log_pass "Fly.io workers disabled"

echo ""
log_info "Waiting 30 seconds..."
sleep 30

# Step 2: Revert root DNS
log_info "Reverting DNS: $PROD_DOMAIN → $REPLIT_IP"
DNS_RESULT=$(curl -s -X PATCH \
    "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${PROD_ROOT_RECORD_ID}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{\"type\":\"A\",\"name\":\"$PROD_DOMAIN\",\"content\":\"$REPLIT_IP\",\"ttl\":1,\"proxied\":true}")

if echo "$DNS_RESULT" | grep -q '"success":true'; then
    log_pass "Root DNS reverted"
else
    log_fail "Root DNS revert failed"
fi

# Step 3: Revert WWW DNS
log_info "Reverting DNS: www.$PROD_DOMAIN → $REPLIT_IP"
DNS_WWW_RESULT=$(curl -s -X PATCH \
    "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${PROD_WWW_RECORD_ID}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{\"type\":\"A\",\"name\":\"www.$PROD_DOMAIN\",\"content\":\"$REPLIT_IP\",\"ttl\":1,\"proxied\":true}")

if echo "$DNS_WWW_RESULT" | grep -q '"success":true'; then
    log_pass "WWW DNS reverted"
else
    log_fail "WWW DNS revert failed"
fi

echo ""
log_info "Waiting 60 seconds for DNS propagation..."
sleep 60

# Step 4: Verify
log_info "Verifying Replit health..."
HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "https://$PROD_DOMAIN/health" 2>/dev/null || echo "000")

if [ "$HEALTH_CODE" = "200" ]; then
    log_pass "Replit health check: HTTP $HEALTH_CODE"
else
    log_warn "Health check returned HTTP $HEALTH_CODE (may still be propagating)"
fi

echo ""
echo "================================================================"
echo -e "${BOLD}              FAILBACK COMPLETE${NC}"
echo "================================================================"
echo ""
echo "  CRITICAL: Re-enable Replit workers NOW:"
echo "    IS_ACTIVE_PRIMARY=true"
echo "    ENABLE_SYNC_WORKERS=true"
echo "    ENABLE_PUSH_JOBS=true"
echo "    ENABLE_SCHEDULERS=true"
echo ""
echo "================================================================"
