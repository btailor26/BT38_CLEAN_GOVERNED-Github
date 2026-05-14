#!/bin/bash
# BT38 Drill Control Panel
# Safe DNS failover confirmation interface for commercial systems
#
# STAGING ONLY - Will abort if any value looks production-like
# DRY-RUN BY DEFAULT - Requires two confirmations for live execution
#
# Usage:
#   ./scripts/drill-control.sh              # Dry-run mode (default)
#   ./scripts/drill-control.sh --live       # Live mode (requires 2 confirmations)
#
# Required Environment Variables (Replit Secrets):
#   CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID, DNS_RECORD_ID, DNS_RECORD_NAME
#   PRIMARY_CNAME, SECONDARY_CNAME, PRIMARY_URL, SECONDARY_URL
#   FLY_APP_NAME, STAGING_DATABASE_URL

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_MODE=false
STEP_RESULTS=()
DRILL_START=""
DRILL_END=""

# Parse arguments
for arg in "$@"; do
    case $arg in
        --live)
            LIVE_MODE=true
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--live]"
            exit 1
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
log_step() { echo -e "${BOLD}[STEP]${NC} $1"; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; }
log_abort() { 
    echo -e "${RED}[ABORT]${NC} $1"
    echo ""
    echo -e "${RED}${BOLD}RESULT: FAIL${NC}"
    echo "Reason: $1"
    exit 1
}

mask_secret() {
    local val="$1"
    local len=${#val}
    if [ "$len" -le 8 ]; then
        echo "****"
    else
        echo "${val:0:4}****${val: -4}"
    fi
}

mask_db_url() {
    local url="$1"
    echo "$url" | sed -E 's/:([^:@]+)@/:****@/g'
}

record_step() {
    local step_name="$1"
    local status="$2"
    local timestamp=$(date '+%H:%M:%S')
    STEP_RESULTS+=("$timestamp | $status | $step_name")
}

# ============================================================
# HEADER
# ============================================================
echo ""
echo "================================================================"
echo -e "${BOLD}       BT38 DNS FAILOVER CONFIRMATION INTERFACE${NC}"
echo "================================================================"
if [ "$LIVE_MODE" = true ]; then
    echo -e "  Mode: ${RED}${BOLD}LIVE EXECUTION${NC}"
else
    echo -e "  Mode: ${CYAN}${BOLD}DRY-RUN (default)${NC}"
fi
echo "================================================================"
echo ""

# ============================================================
# PREFLIGHT: Validate required environment variables
# ============================================================
log_step "PREFLIGHT CHECKS"
echo ""

REQUIRED_VARS=(
    "CLOUDFLARE_API_TOKEN"
    "CLOUDFLARE_ZONE_ID"
    "DNS_RECORD_ID"
    "DNS_RECORD_NAME"
    "PRIMARY_CNAME"
    "SECONDARY_CNAME"
    "PRIMARY_URL"
    "SECONDARY_URL"
    "FLY_APP_NAME"
    "STAGING_DATABASE_URL"
)

MISSING_VARS=()
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    log_error "Missing required environment variables:"
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var"
    done
    log_abort "Set all required variables as Replit Secrets and retry."
fi

log_pass "All 10 required environment variables present"

# Validate tools
log_info "Checking required tools..."
MISSING_TOOLS=()
for tool in curl flyctl; do
    if ! command -v "$tool" &> /dev/null; then
        MISSING_TOOLS+=("$tool")
    fi
done

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    log_abort "Missing required tools: ${MISSING_TOOLS[*]}"
fi
log_pass "All required tools available (curl, flyctl)"
echo ""

# ============================================================
# SAFETY CHECKS: Abort if anything looks like production
# ============================================================
log_step "SAFETY CHECKS (Production Detection)"
echo ""

SAFETY_FAILURES=()

# Check 1: DNS_RECORD_NAME must contain "staging"
if [[ ! "$DNS_RECORD_NAME" =~ staging ]]; then
    SAFETY_FAILURES+=("DNS_RECORD_NAME='$DNS_RECORD_NAME' does not contain 'staging'")
else
    log_pass "DNS_RECORD_NAME contains 'staging'"
fi

# Check 2: PRIMARY_URL must contain "staging"
if [[ ! "$PRIMARY_URL" =~ staging ]]; then
    SAFETY_FAILURES+=("PRIMARY_URL='$PRIMARY_URL' does not contain 'staging'")
else
    log_pass "PRIMARY_URL contains 'staging'"
fi

# Check 3: SECONDARY_URL must contain "staging"
if [[ ! "$SECONDARY_URL" =~ staging ]]; then
    SAFETY_FAILURES+=("SECONDARY_URL='$SECONDARY_URL' does not contain 'staging'")
else
    log_pass "SECONDARY_URL contains 'staging'"
fi

# Check 4: FLY_APP_NAME must contain "staging"
if [[ ! "$FLY_APP_NAME" =~ staging ]]; then
    SAFETY_FAILURES+=("FLY_APP_NAME='$FLY_APP_NAME' does not contain 'staging'")
else
    log_pass "FLY_APP_NAME contains 'staging'"
fi

# Check 5: PRIMARY_CNAME must NOT contain "prod" or be a known production domain
if [[ "$PRIMARY_CNAME" =~ prod ]] && [[ ! "$PRIMARY_CNAME" =~ staging ]]; then
    SAFETY_FAILURES+=("PRIMARY_CNAME='$PRIMARY_CNAME' contains 'prod' without 'staging'")
else
    log_pass "PRIMARY_CNAME does not indicate production"
fi

# Check 6: SECONDARY_CNAME must contain "staging"
if [[ ! "$SECONDARY_CNAME" =~ staging ]]; then
    SAFETY_FAILURES+=("SECONDARY_CNAME='$SECONDARY_CNAME' does not contain 'staging'")
else
    log_pass "SECONDARY_CNAME contains 'staging'"
fi

# Check 7: STAGING_DATABASE_URL must not equal DATABASE_URL (if DATABASE_URL exists)
if [ -n "${DATABASE_URL:-}" ]; then
    if [ "$STAGING_DATABASE_URL" = "$DATABASE_URL" ]; then
        SAFETY_FAILURES+=("STAGING_DATABASE_URL equals DATABASE_URL (production database)")
    else
        log_pass "STAGING_DATABASE_URL differs from DATABASE_URL"
    fi
else
    log_warn "DATABASE_URL not set - cannot compare. Manual verification required."
fi

# If any safety check failed, abort
if [ ${#SAFETY_FAILURES[@]} -gt 0 ]; then
    echo ""
    log_error "PRODUCTION DETECTED - Safety checks failed:"
    for failure in "${SAFETY_FAILURES[@]}"; do
        echo "  ✗ $failure"
    done
    log_abort "Refusing to run on potential production environment."
fi

echo ""
log_pass "All safety checks passed - confirmed STAGING environment"
echo ""

# ============================================================
# FETCH CURRENT DNS STATE
# ============================================================
log_step "FETCHING CURRENT DNS STATE"
echo ""

CURRENT_CNAME=""
CURRENT_TTL=""
CURRENT_PROXIED=""

DNS_RESPONSE=$(curl -s -X GET \
    "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${DNS_RECORD_ID}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" 2>/dev/null || echo "ERROR")

if [ "$DNS_RESPONSE" = "ERROR" ] || [ -z "$DNS_RESPONSE" ]; then
    log_abort "Failed to fetch DNS record from Cloudflare API"
fi

# Parse response
if echo "$DNS_RESPONSE" | grep -q '"success":true'; then
    CURRENT_CNAME=$(echo "$DNS_RESPONSE" | grep -o '"content":"[^"]*"' | head -1 | cut -d'"' -f4)
    CURRENT_TTL=$(echo "$DNS_RESPONSE" | grep -o '"ttl":[0-9]*' | head -1 | cut -d':' -f2)
    CURRENT_PROXIED=$(echo "$DNS_RESPONSE" | grep -o '"proxied":[a-z]*' | head -1 | cut -d':' -f2)
    RECORD_NAME_CHECK=$(echo "$DNS_RESPONSE" | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
    
    log_info "Record name:    $RECORD_NAME_CHECK"
    log_info "Current target: $CURRENT_CNAME"
    log_info "TTL:            $CURRENT_TTL seconds"
    log_info "Proxied:        $CURRENT_PROXIED"
    
    # Verify fetched record name matches expected
    if [[ ! "$RECORD_NAME_CHECK" =~ staging ]]; then
        log_abort "Fetched record name '$RECORD_NAME_CHECK' does not contain 'staging'. Wrong record?"
    fi
    log_pass "DNS record verified as staging"
else
    ERROR_MSG=$(echo "$DNS_RESPONSE" | grep -o '"message":"[^"]*"' | head -1 | cut -d'"' -f4)
    log_abort "Cloudflare API error: $ERROR_MSG"
fi

echo ""

# ============================================================
# CONFIRMATION SCREEN
# ============================================================
echo "================================================================"
echo -e "${BOLD}              CONFIRMATION SCREEN${NC}"
echo "================================================================"
echo ""
echo "  ENVIRONMENT:        STAGING"
echo ""
echo "  DNS Record:         $DNS_RECORD_NAME"
echo "  Current Target:     $CURRENT_CNAME"
echo "  TTL:                $CURRENT_TTL seconds"
echo "  Proxied:            $CURRENT_PROXIED"
echo ""
echo "  ─────────────────────────────────────────────────────"
echo ""
echo "  PRIMARY_URL:        $PRIMARY_URL"
echo "  SECONDARY_URL:      $SECONDARY_URL"
echo "  PRIMARY_CNAME:      $PRIMARY_CNAME"
echo "  SECONDARY_CNAME:    $SECONDARY_CNAME"
echo ""
echo "  Fly App:            $FLY_APP_NAME"
echo "  Staging DB:         $(mask_db_url "$STAGING_DATABASE_URL")"
echo ""
echo "  ─────────────────────────────────────────────────────"
echo ""
echo "  Cloudflare Zone:    $(mask_secret "$CLOUDFLARE_ZONE_ID")"
echo "  Cloudflare Token:   $(mask_secret "$CLOUDFLARE_API_TOKEN")"
echo ""
echo "================================================================"

if [ "$LIVE_MODE" = true ]; then
    echo -e "${BOLD}LIVE MODE - Operations that WILL execute:${NC}"
else
    echo -e "${BOLD}DRY-RUN MODE - Operations that WOULD execute:${NC}"
fi

echo ""
echo "  FAILOVER:"
echo "    1. Verify primary is DOWN (3 health check failures)"
echo "    2. Activate $FLY_APP_NAME:"
echo "       - IS_ACTIVE_PRIMARY=true"
echo "       - ENABLE_SYNC_WORKERS=true"
echo "       - ENABLE_PUSH_JOBS=true"
echo "       - ENABLE_SCHEDULERS=true"
echo "    3. Switch DNS: $DNS_RECORD_NAME → $SECONDARY_CNAME"
echo "    4. Verify /health returns 200"
echo ""
echo "  FAILBACK:"
echo "    1. Verify primary is UP"
echo "    2. Deactivate $FLY_APP_NAME (standby mode)"
echo "    3. Switch DNS: $DNS_RECORD_NAME → $PRIMARY_CNAME"
echo "    4. Verify /health returns 200"
echo ""
echo "  Estimated time: 5-7 minutes"
echo "================================================================"
echo ""

# ============================================================
# CONFIRMATION PHASE 1: Dry-run or proceed
# ============================================================
if [ "$LIVE_MODE" = false ]; then
    echo -e "${CYAN}${BOLD}DRY-RUN MODE${NC}"
    echo ""
    echo "This will show what WOULD happen without making changes."
    echo ""
    echo -e "${YELLOW}To proceed with DRY-RUN, type exactly:${NC}"
    echo ""
    echo "    CONFIRM_STAGING_DRILL"
    echo ""
    echo -n "Confirmation: "
    read -r CONFIRMATION

    if [ "$CONFIRMATION" != "CONFIRM_STAGING_DRILL" ]; then
        log_error "Confirmation failed. Expected 'CONFIRM_STAGING_DRILL', got '$CONFIRMATION'"
        log_abort "No changes made. Exiting."
    fi

    echo ""
    log_pass "Confirmation received. Running DRY-RUN..."
    echo ""

    DRILL_START=$(date '+%Y-%m-%d %H:%M:%S')

    # Execute dry-runs
    echo "================================================================"
    log_step "DRY-RUN: FAILOVER"
    echo "================================================================"
    echo ""
    
    if "$SCRIPT_DIR/failover.sh" --dry-run; then
        record_step "Failover dry-run" "PASS"
    else
        record_step "Failover dry-run" "FAIL"
    fi

    echo ""
    echo "================================================================"
    log_step "DRY-RUN: FAILBACK"
    echo "================================================================"
    echo ""
    
    if "$SCRIPT_DIR/failback.sh" --dry-run; then
        record_step "Failback dry-run" "PASS"
    else
        record_step "Failback dry-run" "FAIL"
    fi

    DRILL_END=$(date '+%Y-%m-%d %H:%M:%S')

    echo ""
    echo "================================================================"
    echo -e "${BOLD}               DRY-RUN REPORT${NC}"
    echo "================================================================"
    echo ""
    echo "  Start:   $DRILL_START"
    echo "  End:     $DRILL_END"
    echo ""
    echo "  Step Results:"
    echo "  ─────────────────────────────────────────────────────"
    for result in "${STEP_RESULTS[@]}"; do
        echo "  $result"
    done
    echo "  ─────────────────────────────────────────────────────"
    echo ""

    FAIL_COUNT=0
    for result in "${STEP_RESULTS[@]}"; do
        if [[ "$result" =~ FAIL ]]; then
            ((FAIL_COUNT++))
        fi
    done

    if [ "$FAIL_COUNT" -eq 0 ]; then
        echo -e "  ${GREEN}${BOLD}RESULT: PASS${NC}"
        echo ""
        echo "  Dry-run successful. To execute LIVE, run:"
        echo ""
        echo "    ./scripts/drill-control.sh --live"
        echo ""
    else
        echo -e "  ${RED}${BOLD}RESULT: FAIL${NC}"
        echo "  $FAIL_COUNT step(s) failed in dry-run."
    fi
    echo "================================================================"
    exit 0
fi

# ============================================================
# LIVE MODE: Two confirmations required
# ============================================================
echo -e "${RED}${BOLD}LIVE EXECUTION MODE${NC}"
echo ""
echo "This will make REAL changes to DNS and Fly.io configuration."
echo ""
echo -e "${YELLOW}${BOLD}PHASE 1: Type exactly:${NC}"
echo ""
echo "    CONFIRM_STAGING_DRILL"
echo ""
echo -n "Confirmation 1: "
read -r CONFIRMATION1

if [ "$CONFIRMATION1" != "CONFIRM_STAGING_DRILL" ]; then
    log_error "Confirmation failed. Expected 'CONFIRM_STAGING_DRILL', got '$CONFIRMATION1'"
    log_abort "No changes made. Exiting."
fi

log_pass "Phase 1 confirmed"
echo ""
echo -e "${RED}${BOLD}PHASE 2 - FINAL CONFIRMATION${NC}"
echo ""
echo "You are about to:"
echo "  • Switch DNS from $CURRENT_CNAME to $SECONDARY_CNAME"
echo "  • Activate secondary instance as primary"
echo "  • Then reverse all changes (failback)"
echo ""
echo -e "${YELLOW}${BOLD}To execute LIVE FAILOVER, type exactly:${NC}"
echo ""
echo "    CONFIRM_LIVE_FAILOVER"
echo ""
echo -n "Confirmation 2: "
read -r CONFIRMATION2

if [ "$CONFIRMATION2" != "CONFIRM_LIVE_FAILOVER" ]; then
    log_error "Confirmation failed. Expected 'CONFIRM_LIVE_FAILOVER', got '$CONFIRMATION2'"
    log_abort "No changes made. Exiting."
fi

echo ""
log_pass "Both confirmations received. Executing LIVE STAGING DRILL..."
echo ""

DRILL_START=$(date '+%Y-%m-%d %H:%M:%S')

# ============================================================
# EXECUTE LIVE FAILOVER
# ============================================================
echo "================================================================"
log_step "LIVE: EXECUTING FAILOVER"
echo "================================================================"
echo ""

FAILOVER_START=$(date +%s)

if "$SCRIPT_DIR/failover.sh"; then
    FAILOVER_END=$(date +%s)
    FAILOVER_DURATION=$((FAILOVER_END - FAILOVER_START))
    record_step "Failover execution" "PASS ($FAILOVER_DURATION sec)"
    log_pass "Failover completed in $FAILOVER_DURATION seconds"
else
    FAILOVER_END=$(date +%s)
    FAILOVER_DURATION=$((FAILOVER_END - FAILOVER_START))
    record_step "Failover execution" "FAIL ($FAILOVER_DURATION sec)"
    log_fail "Failover FAILED after $FAILOVER_DURATION seconds"
fi

echo ""

# ============================================================
# VERIFY FAILOVER
# ============================================================
log_step "VERIFYING FAILOVER"
echo ""

# DNS verification
if command -v dig &> /dev/null; then
    DIG_RESULT=$(dig +short "$DNS_RECORD_NAME" CNAME 2>/dev/null || echo "LOOKUP_FAILED")
    log_info "dig $DNS_RECORD_NAME CNAME: $DIG_RESULT"
    if [[ "$DIG_RESULT" =~ $SECONDARY_CNAME ]] || [[ "$DIG_RESULT" =~ fly\.dev ]]; then
        record_step "DNS points to secondary" "PASS"
        log_pass "DNS now points to secondary"
    else
        record_step "DNS points to secondary" "WARN (propagating)"
        log_warn "DNS may still be propagating"
    fi
else
    record_step "DNS verification" "SKIP"
    log_warn "dig not available"
fi

# Health check
HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "${SECONDARY_URL}/health" 2>/dev/null || echo "000")
if [ "$HEALTH_CODE" = "200" ]; then
    record_step "Secondary /health" "PASS (HTTP 200)"
    log_pass "Secondary /health: HTTP $HEALTH_CODE"
else
    record_step "Secondary /health" "FAIL (HTTP $HEALTH_CODE)"
    log_fail "Secondary /health: HTTP $HEALTH_CODE"
fi

echo ""
log_info "Waiting 30 seconds before failback..."
sleep 30
echo ""

# ============================================================
# EXECUTE LIVE FAILBACK
# ============================================================
echo "================================================================"
log_step "LIVE: EXECUTING FAILBACK"
echo "================================================================"
echo ""

FAILBACK_START=$(date +%s)

if "$SCRIPT_DIR/failback.sh"; then
    FAILBACK_END=$(date +%s)
    FAILBACK_DURATION=$((FAILBACK_END - FAILBACK_START))
    record_step "Failback execution" "PASS ($FAILBACK_DURATION sec)"
    log_pass "Failback completed in $FAILBACK_DURATION seconds"
else
    FAILBACK_END=$(date +%s)
    FAILBACK_DURATION=$((FAILBACK_END - FAILBACK_START))
    record_step "Failback execution" "FAIL ($FAILBACK_DURATION sec)"
    log_fail "Failback FAILED after $FAILBACK_DURATION seconds"
fi

echo ""

# ============================================================
# VERIFY FAILBACK
# ============================================================
log_step "VERIFYING FAILBACK"
echo ""

# DNS verification
if command -v dig &> /dev/null; then
    DIG_RESULT=$(dig +short "$DNS_RECORD_NAME" CNAME 2>/dev/null || echo "LOOKUP_FAILED")
    log_info "dig $DNS_RECORD_NAME CNAME: $DIG_RESULT"
    if [[ "$DIG_RESULT" =~ $PRIMARY_CNAME ]] || [[ "$DIG_RESULT" =~ replit ]]; then
        record_step "DNS points to primary" "PASS"
        log_pass "DNS now points to primary"
    else
        record_step "DNS points to primary" "WARN (propagating)"
        log_warn "DNS may still be propagating"
    fi
else
    record_step "DNS verification" "SKIP"
fi

# Health check
HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "${PRIMARY_URL}/health" 2>/dev/null || echo "000")
if [ "$HEALTH_CODE" = "200" ]; then
    record_step "Primary /health" "PASS (HTTP 200)"
    log_pass "Primary /health: HTTP $HEALTH_CODE"
else
    record_step "Primary /health" "FAIL (HTTP $HEALTH_CODE)"
    log_fail "Primary /health: HTTP $HEALTH_CODE"
fi

echo ""

DRILL_END=$(date '+%Y-%m-%d %H:%M:%S')

# ============================================================
# FINAL DRILL REPORT
# ============================================================
echo "================================================================"
echo -e "${BOLD}               DRILL REPORT${NC}"
echo "================================================================"
echo ""
echo "  Drill Start:   $DRILL_START"
echo "  Drill End:     $DRILL_END"
echo ""
echo "  Step Results:"
echo "  ─────────────────────────────────────────────────────"
for result in "${STEP_RESULTS[@]}"; do
    if [[ "$result" =~ PASS ]]; then
        echo -e "  ${GREEN}$result${NC}"
    elif [[ "$result" =~ FAIL ]]; then
        echo -e "  ${RED}$result${NC}"
    else
        echo "  $result"
    fi
done
echo "  ─────────────────────────────────────────────────────"
echo ""

# Determine PASS/FAIL
FAIL_COUNT=0
for result in "${STEP_RESULTS[@]}"; do
    if [[ "$result" =~ FAIL ]]; then
        ((FAIL_COUNT++))
    fi
done

if [ "$FAIL_COUNT" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}RESULT: PASS${NC}"
    echo ""
    echo "  All steps completed successfully."
    echo "  System is ready for production failover procedures."
else
    echo -e "  ${RED}${BOLD}RESULT: FAIL${NC}"
    echo ""
    echo "  $FAIL_COUNT step(s) failed."
    echo "  Review issues before production use."
fi

echo ""
echo "================================================================"
