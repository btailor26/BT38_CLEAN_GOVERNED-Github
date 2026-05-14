#!/bin/bash
# BT38 Production Cutover Control Panel
# Safe DNS and worker cutover interface for PRODUCTION
#
# DRY-RUN BY DEFAULT - Requires two confirmations for live execution
# PRODUCTION SAFETY - Blocks if any staging-like values detected
#
# Usage:
#   ./scripts/prod-control.sh              # Dry-run mode (default)
#   ./scripts/prod-control.sh --live       # Live mode (requires 2 confirmations)
#
# Required Environment Variables:
#   CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID
#   PROD_ROOT_RECORD_ID, PROD_WWW_RECORD_ID
#   REPLIT_IP, FLY_PROD_HOSTNAME
#   FLY_PROD_APP_NAME
#
# Control flags read from Fly.io:
#   IS_ACTIVE_PRIMARY, ENABLE_SYNC_WORKERS, ENABLE_PUSH_JOBS, ENABLE_SCHEDULERS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_MODE=false
DRY_RUN_FLAG="--dry-run"
STEP_RESULTS=()

# Hardcoded production values (verified from DNS query)
PROD_ROOT_RECORD_ID="${PROD_ROOT_RECORD_ID:-532c13b367d19d03aad33040f5ccd28c}"
PROD_WWW_RECORD_ID="${PROD_WWW_RECORD_ID:-3292498f5157098bc36055d1f6e1ef40}"
REPLIT_IP="${REPLIT_IP:-34.111.179.208}"
FLY_PROD_HOSTNAME="${FLY_PROD_HOSTNAME:-bt38-prod.fly.dev}"
FLY_PROD_APP_NAME="${FLY_PROD_APP_NAME:-bt38-prod}"
PROD_DOMAIN="${PROD_DOMAIN:-bt38inv.com}"

# Parse arguments
for arg in "$@"; do
    case $arg in
        --live)
            LIVE_MODE=true
            DRY_RUN_FLAG=""
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
    echo -e "${RED}${BOLD}RESULT: BLOCKED${NC}"
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
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                                                              ║"
echo "║          BT38 PRODUCTION CUTOVER CONTROL PANEL              ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
if [ "$LIVE_MODE" = true ]; then
    echo -e "  Mode: ${RED}${BOLD}LIVE EXECUTION${NC}"
else
    echo -e "  Mode: ${CYAN}${BOLD}DRY-RUN (default)${NC}"
fi
echo "  Target: PRODUCTION (bt38inv.com)"
echo "  Date: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""
echo "================================================================"

# ============================================================
# PREFLIGHT: Validate required environment variables
# ============================================================
log_step "PREFLIGHT CHECKS"
echo ""

REQUIRED_VARS=(
    "CLOUDFLARE_API_TOKEN"
    "CLOUDFLARE_ZONE_ID"
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

log_pass "Required environment variables present"

# Validate tools
log_info "Checking required tools..."
MISSING_TOOLS=()
export PATH="$HOME/.fly/bin:$PATH"
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
# SAFETY CHECKS: Block if staging values detected
# ============================================================
log_step "PRODUCTION SAFETY CHECKS"
echo ""

SAFETY_FAILURES=()

# Check 1: App name must contain "prod" NOT "staging"
if [[ "$FLY_PROD_APP_NAME" =~ staging ]]; then
    SAFETY_FAILURES+=("FLY_PROD_APP_NAME='$FLY_PROD_APP_NAME' contains 'staging' - BLOCKED")
elif [[ ! "$FLY_PROD_APP_NAME" =~ prod ]]; then
    SAFETY_FAILURES+=("FLY_PROD_APP_NAME='$FLY_PROD_APP_NAME' does not contain 'prod' - BLOCKED")
else
    log_pass "App name '$FLY_PROD_APP_NAME' contains 'prod'"
fi

# Check 2: Hostname must contain "prod"
if [[ "$FLY_PROD_HOSTNAME" =~ staging ]]; then
    SAFETY_FAILURES+=("FLY_PROD_HOSTNAME='$FLY_PROD_HOSTNAME' contains 'staging' - BLOCKED")
elif [[ ! "$FLY_PROD_HOSTNAME" =~ prod ]]; then
    SAFETY_FAILURES+=("FLY_PROD_HOSTNAME='$FLY_PROD_HOSTNAME' does not contain 'prod' - BLOCKED")
else
    log_pass "Hostname '$FLY_PROD_HOSTNAME' contains 'prod'"
fi

# Check 3: Domain must be production domain
if [[ "$PROD_DOMAIN" =~ staging ]]; then
    SAFETY_FAILURES+=("PROD_DOMAIN='$PROD_DOMAIN' contains 'staging' - BLOCKED")
else
    log_pass "Domain '$PROD_DOMAIN' is production domain"
fi

# Check 4: Record IDs must be valid format
if [[ ! "$PROD_ROOT_RECORD_ID" =~ ^[a-f0-9]{32}$ ]]; then
    SAFETY_FAILURES+=("PROD_ROOT_RECORD_ID='$PROD_ROOT_RECORD_ID' invalid format")
else
    log_pass "Root record ID format valid"
fi

if [[ ! "$PROD_WWW_RECORD_ID" =~ ^[a-f0-9]{32}$ ]]; then
    SAFETY_FAILURES+=("PROD_WWW_RECORD_ID='$PROD_WWW_RECORD_ID' invalid format")
else
    log_pass "WWW record ID format valid"
fi

# Check 5: Replit IP must be valid IPv4
if [[ ! "$REPLIT_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SAFETY_FAILURES+=("REPLIT_IP='$REPLIT_IP' invalid IPv4 format")
else
    log_pass "Replit IP format valid"
fi

# If any safety check failed, abort
if [ ${#SAFETY_FAILURES[@]} -gt 0 ]; then
    echo ""
    log_error "SAFETY CHECKS FAILED:"
    for failure in "${SAFETY_FAILURES[@]}"; do
        echo "  ✗ $failure"
    done
    log_abort "Fix configuration before proceeding."
fi

echo ""
log_pass "All safety checks passed - confirmed PRODUCTION configuration"
echo ""

# ============================================================
# VERIFY PRODUCTION APP EXISTS
# ============================================================
log_step "VERIFYING FLY.IO PRODUCTION APP"
echo ""

APP_STATUS=$(flyctl status -a "$FLY_PROD_APP_NAME" 2>&1 || echo "APP_NOT_FOUND")

if echo "$APP_STATUS" | grep -q "APP_NOT_FOUND\|Could not find App"; then
    log_warn "Production app '$FLY_PROD_APP_NAME' does not exist yet"
    echo ""
    echo "  To create it, run:"
    echo "    flyctl apps create $FLY_PROD_APP_NAME --org personal"
    echo "    flyctl deploy -a $FLY_PROD_APP_NAME --remote-only"
    echo ""
    if [ "$LIVE_MODE" = true ]; then
        log_abort "Production app must exist for live execution"
    else
        log_warn "Continuing dry-run without app verification"
    fi
else
    log_pass "Production app '$FLY_PROD_APP_NAME' exists"
    echo "$APP_STATUS" | head -5 | sed 's/^/  /'
fi

echo ""

# ============================================================
# CHECK CURRENT SECRETS STATE
# ============================================================
log_step "CHECKING CURRENT SECRETS STATE"
echo ""

if command -v flyctl &> /dev/null && flyctl apps list 2>/dev/null | grep -q "$FLY_PROD_APP_NAME"; then
    SECRETS_LIST=$(flyctl secrets list -a "$FLY_PROD_APP_NAME" 2>&1 || echo "SECRETS_ERROR")
    
    if echo "$SECRETS_LIST" | grep -q "SECRETS_ERROR"; then
        log_warn "Could not fetch secrets list"
    else
        # Check required secrets
        REQUIRED_SECRETS=(
            "DATABASE_URL"
            "SESSION_SECRET"
            "IS_ACTIVE_PRIMARY"
            "ENABLE_SYNC_WORKERS"
            "ENABLE_PUSH_JOBS"
            "ENABLE_SCHEDULERS"
        )
        
        MISSING_SECRETS=()
        for secret in "${REQUIRED_SECRETS[@]}"; do
            if ! echo "$SECRETS_LIST" | grep -q "^$secret"; then
                MISSING_SECRETS+=("$secret")
            fi
        done
        
        if [ ${#MISSING_SECRETS[@]} -gt 0 ]; then
            log_warn "Missing secrets on $FLY_PROD_APP_NAME:"
            for secret in "${MISSING_SECRETS[@]}"; do
                echo "    - $secret"
            done
            if [ "$LIVE_MODE" = true ]; then
                log_abort "All required secrets must be set for live execution"
            fi
        else
            log_pass "All required secrets present"
        fi
    fi
else
    log_warn "Cannot verify secrets - app may not exist"
fi

echo ""

# ============================================================
# FETCH CURRENT DNS STATE
# ============================================================
log_step "FETCHING CURRENT DNS STATE"
echo ""

DNS_ROOT=$(curl -s -X GET \
    "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${PROD_ROOT_RECORD_ID}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" 2>/dev/null || echo '{"success":false}')

DNS_WWW=$(curl -s -X GET \
    "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${PROD_WWW_RECORD_ID}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" 2>/dev/null || echo '{"success":false}')

if echo "$DNS_ROOT" | grep -q '"success":true'; then
    ROOT_TYPE=$(echo "$DNS_ROOT" | grep -o '"type":"[^"]*"' | head -1 | cut -d'"' -f4)
    ROOT_CONTENT=$(echo "$DNS_ROOT" | grep -o '"content":"[^"]*"' | head -1 | cut -d'"' -f4)
    ROOT_PROXIED=$(echo "$DNS_ROOT" | grep -o '"proxied":[a-z]*' | head -1 | cut -d':' -f2)
    log_info "Root (@):  $ROOT_TYPE → $ROOT_CONTENT (proxied=$ROOT_PROXIED)"
else
    log_error "Failed to fetch root DNS record"
    if [ "$LIVE_MODE" = true ]; then
        log_abort "DNS fetch failed"
    fi
fi

if echo "$DNS_WWW" | grep -q '"success":true'; then
    WWW_TYPE=$(echo "$DNS_WWW" | grep -o '"type":"[^"]*"' | head -1 | cut -d'"' -f4)
    WWW_CONTENT=$(echo "$DNS_WWW" | grep -o '"content":"[^"]*"' | head -1 | cut -d'"' -f4)
    WWW_PROXIED=$(echo "$DNS_WWW" | grep -o '"proxied":[a-z]*' | head -1 | cut -d':' -f2)
    log_info "WWW:       $WWW_TYPE → $WWW_CONTENT (proxied=$WWW_PROXIED)"
else
    log_error "Failed to fetch WWW DNS record"
    if [ "$LIVE_MODE" = true ]; then
        log_abort "DNS fetch failed"
    fi
fi

echo ""

# ============================================================
# GO/NO-GO DECISION
# ============================================================
echo "================================================================"
echo -e "${BOLD}              GO/NO-GO DECISION SCREEN${NC}"
echo "================================================================"
echo ""
echo "  PRODUCTION CUTOVER SUMMARY"
echo "  ─────────────────────────────────────────────────────"
echo ""
echo "  Domain:           $PROD_DOMAIN"
echo "  Current Target:   $ROOT_CONTENT"
echo "  New Target:       $FLY_PROD_HOSTNAME"
echo ""
echo "  Fly App:          $FLY_PROD_APP_NAME"
echo "  Replit Fallback:  $REPLIT_IP"
echo ""
echo "  DNS Records:"
echo "    Root (@):  $PROD_ROOT_RECORD_ID"
echo "    WWW:       $PROD_WWW_RECORD_ID"
echo ""
echo "  Cloudflare Zone:  $(mask_secret "$CLOUDFLARE_ZONE_ID")"
echo "  Cloudflare Token: $(mask_secret "$CLOUDFLARE_API_TOKEN")"
echo ""
echo "  ─────────────────────────────────────────────────────"
echo ""

# Determine GO/NO-GO
GO_STATUS="GO"
GO_BLOCKERS=()

if [ ${#SAFETY_FAILURES[@]} -gt 0 ]; then
    GO_STATUS="NO-GO"
    GO_BLOCKERS+=("Safety check failures")
fi

if [ ${#MISSING_SECRETS:-0} -gt 0 ] && [ "$LIVE_MODE" = true ]; then
    GO_STATUS="NO-GO"
    GO_BLOCKERS+=("Missing secrets")
fi

if [ "$GO_STATUS" = "GO" ]; then
    echo -e "  ${GREEN}${BOLD}═══════════════════════════════════════════${NC}"
    echo -e "  ${GREEN}${BOLD}                    GO                      ${NC}"
    echo -e "  ${GREEN}${BOLD}═══════════════════════════════════════════${NC}"
else
    echo -e "  ${RED}${BOLD}═══════════════════════════════════════════${NC}"
    echo -e "  ${RED}${BOLD}                  NO-GO                    ${NC}"
    echo -e "  ${RED}${BOLD}═══════════════════════════════════════════${NC}"
    echo ""
    echo "  Blockers:"
    for blocker in "${GO_BLOCKERS[@]}"; do
        echo "    ✗ $blocker"
    done
fi

echo ""
echo "================================================================"
echo ""

if [ "$GO_STATUS" = "NO-GO" ]; then
    log_abort "Cannot proceed due to blockers"
fi

# ============================================================
# DRY-RUN MODE
# ============================================================
if [ "$LIVE_MODE" = false ]; then
    echo -e "${CYAN}${BOLD}DRY-RUN MODE${NC}"
    echo ""
    echo "This will show what WOULD happen without making changes."
    echo ""
    echo "Planned operations:"
    echo ""
    echo "  CUTOVER:"
    echo "    1. Disable Replit workers (manual step)"
    echo "    2. Enable Fly.io workers on $FLY_PROD_APP_NAME"
    echo "    3. Switch DNS: $PROD_DOMAIN → $FLY_PROD_HOSTNAME"
    echo "    4. Switch DNS: www.$PROD_DOMAIN → $FLY_PROD_HOSTNAME"
    echo "    5. Verify health check"
    echo ""
    echo "  FAILBACK (if needed):"
    echo "    1. Disable Fly.io workers"
    echo "    2. Enable Replit workers"
    echo "    3. Revert DNS: $PROD_DOMAIN → $REPLIT_IP"
    echo "    4. Revert DNS: www.$PROD_DOMAIN → $REPLIT_IP"
    echo ""
    echo "================================================================"
    echo ""
    echo -e "${GREEN}${BOLD}DRY-RUN COMPLETE${NC}"
    echo ""
    echo "To execute LIVE, run:"
    echo ""
    echo "    ./scripts/prod-control.sh --live"
    echo ""
    echo "================================================================"
    exit 0
fi

# ============================================================
# LIVE MODE: Two confirmations required
# ============================================================
echo -e "${RED}${BOLD}LIVE EXECUTION MODE${NC}"
echo ""
echo "This will make REAL changes to:"
echo "  • Fly.io production workers"
echo "  • Production DNS records"
echo ""
echo "These changes affect LIVE PRODUCTION TRAFFIC."
echo ""
echo -e "${YELLOW}${BOLD}PHASE 1: Type exactly:${NC}"
echo ""
echo "    CONFIRM_PRODUCTION_CUTOVER"
echo ""
echo -n "Confirmation 1: "
read -r CONFIRMATION1

if [ "$CONFIRMATION1" != "CONFIRM_PRODUCTION_CUTOVER" ]; then
    log_error "Confirmation failed. Expected 'CONFIRM_PRODUCTION_CUTOVER'"
    log_abort "No changes made. Exiting."
fi

log_pass "Phase 1 confirmed"
echo ""
echo -e "${RED}${BOLD}PHASE 2 - FINAL CONFIRMATION${NC}"
echo ""
echo "You are about to:"
echo "  • Enable commercial workers on $FLY_PROD_APP_NAME"
echo "  • Switch $PROD_DOMAIN DNS to $FLY_PROD_HOSTNAME"
echo "  • Switch www.$PROD_DOMAIN DNS to $FLY_PROD_HOSTNAME"
echo ""
echo -e "${YELLOW}${BOLD}To execute LIVE CUTOVER, type exactly:${NC}"
echo ""
echo "    I_AUTHORIZE_PRODUCTION_CUTOVER"
echo ""
echo -n "Confirmation 2: "
read -r CONFIRMATION2

if [ "$CONFIRMATION2" != "I_AUTHORIZE_PRODUCTION_CUTOVER" ]; then
    log_error "Confirmation failed. Expected 'I_AUTHORIZE_PRODUCTION_CUTOVER'"
    log_abort "No changes made. Exiting."
fi

echo ""
log_pass "Both confirmations received. Executing LIVE PRODUCTION CUTOVER..."
echo ""

# ============================================================
# EXECUTE CUTOVER
# ============================================================
echo "================================================================"
log_step "EXECUTING PRODUCTION CUTOVER"
echo "================================================================"
echo ""

# Step 1: Enable Fly.io workers
log_info "Enabling Fly.io production workers..."
flyctl secrets set \
    IS_ACTIVE_PRIMARY=true \
    ENABLE_SYNC_WORKERS=true \
    ENABLE_PUSH_JOBS=true \
    ENABLE_SCHEDULERS=true \
    FAILOVER_ROLE=primary \
    -a "$FLY_PROD_APP_NAME"

record_step "Enable Fly.io workers" "PASS"
log_pass "Fly.io workers enabled"

echo ""
log_info "Waiting 30 seconds for workers to stabilize..."
sleep 30

# Step 2: Switch DNS root
log_info "Switching DNS: $PROD_DOMAIN → $FLY_PROD_HOSTNAME"
DNS_RESULT=$(curl -s -X PATCH \
    "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${PROD_ROOT_RECORD_ID}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{\"type\":\"CNAME\",\"name\":\"$PROD_DOMAIN\",\"content\":\"$FLY_PROD_HOSTNAME\",\"ttl\":60,\"proxied\":false}")

if echo "$DNS_RESULT" | grep -q '"success":true'; then
    record_step "Switch root DNS" "PASS"
    log_pass "Root DNS switched"
else
    record_step "Switch root DNS" "FAIL"
    log_fail "Root DNS switch failed"
fi

# Step 3: Switch DNS www
log_info "Switching DNS: www.$PROD_DOMAIN → $FLY_PROD_HOSTNAME"
DNS_WWW_RESULT=$(curl -s -X PATCH \
    "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${PROD_WWW_RECORD_ID}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{\"type\":\"CNAME\",\"name\":\"www.$PROD_DOMAIN\",\"content\":\"$FLY_PROD_HOSTNAME\",\"ttl\":60,\"proxied\":false}")

if echo "$DNS_WWW_RESULT" | grep -q '"success":true'; then
    record_step "Switch WWW DNS" "PASS"
    log_pass "WWW DNS switched"
else
    record_step "Switch WWW DNS" "FAIL"
    log_fail "WWW DNS switch failed"
fi

echo ""
log_info "Waiting 60 seconds for DNS propagation..."
sleep 60

# Step 4: Verify health
log_info "Verifying production health..."
HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "https://$PROD_DOMAIN/health" 2>/dev/null || echo "000")

if [ "$HEALTH_CODE" = "200" ]; then
    record_step "Health check" "PASS"
    log_pass "Production health check: HTTP $HEALTH_CODE"
else
    record_step "Health check" "FAIL (HTTP $HEALTH_CODE)"
    log_fail "Production health check: HTTP $HEALTH_CODE"
fi

echo ""
echo "================================================================"
echo -e "${BOLD}               CUTOVER COMPLETE${NC}"
echo "================================================================"
echo ""
echo "  Results:"
for result in "${STEP_RESULTS[@]}"; do
    if [[ "$result" =~ PASS ]]; then
        echo -e "  ${GREEN}$result${NC}"
    elif [[ "$result" =~ FAIL ]]; then
        echo -e "  ${RED}$result${NC}"
    else
        echo "  $result"
    fi
done
echo ""

FAIL_COUNT=0
for result in "${STEP_RESULTS[@]}"; do
    if [[ "$result" =~ FAIL ]]; then
        ((FAIL_COUNT++))
    fi
done

if [ "$FAIL_COUNT" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}RESULT: SUCCESS${NC}"
    echo ""
    echo "  Production is now running on Fly.io"
    echo ""
    echo "  CRITICAL: Disable Replit workers NOW:"
    echo "    IS_ACTIVE_PRIMARY=false"
    echo "    ENABLE_SYNC_WORKERS=false"
    echo "    ENABLE_PUSH_JOBS=false"
    echo "    ENABLE_SCHEDULERS=false"
else
    echo -e "  ${RED}${BOLD}RESULT: PARTIAL FAILURE${NC}"
    echo ""
    echo "  Some steps failed. Review and consider failback:"
    echo "    ./scripts/prod-failback.sh"
fi

echo ""
echo "================================================================"
