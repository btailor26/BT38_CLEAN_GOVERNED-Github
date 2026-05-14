#!/bin/bash
# BT38 Failover Orchestrator
# One-button failover from primary to secondary
#
# IMPORTANT: Stage 6 supports VARIANT B (shared database) ONLY.
# Both primary and secondary connect to the SAME Neon PostgreSQL database.
# Variant A (separate databases with promotion) requires Stage 7.
#
# Usage:
#   ./scripts/failover.sh              # Execute full failover
#   ./scripts/failover.sh --dry-run    # Show what would happen
#   ./scripts/failover.sh --skip-health # Skip health check (EMERGENCY ONLY)
#
# Required environment variables:
#   PRIMARY_URL           - Primary instance URL
#   SECONDARY_URL         - Secondary instance URL  
#   CLOUDFLARE_API_TOKEN  - Cloudflare API token
#   CLOUDFLARE_ZONE_ID    - Cloudflare zone ID
#   DNS_RECORD_ID         - DNS record ID
#   DNS_RECORD_NAME       - DNS record name
#   PRIMARY_CNAME         - Primary CNAME target
#   SECONDARY_CNAME       - Secondary CNAME target
#   FLY_APP_NAME          - Fly.io app name

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN=false
SKIP_HEALTH=false
PRIMARY_HEALTH_RETRIES=3

for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            ;;
        --skip-health)
            SKIP_HEALTH=true
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
log_dry() { echo -e "${CYAN}[DRY-RUN]${NC} $1"; }
log_step() { echo -e "${BOLD}[STEP $1]${NC} $2"; }

# Validate required tools
require_tool() {
    if ! command -v "$1" &> /dev/null; then
        log_error "Required tool not found: $1"
        exit 1
    fi
}

# Validate required environment variables
require_env() {
    local var_name="$1"
    local var_value="${!var_name:-}"
    if [ -z "$var_value" ]; then
        log_error "Required environment variable not set: $var_name"
        return 1
    fi
}

validate_all_env() {
    local missing=0
    for var in PRIMARY_URL SECONDARY_URL CLOUDFLARE_API_TOKEN CLOUDFLARE_ZONE_ID DNS_RECORD_ID DNS_RECORD_NAME PRIMARY_CNAME SECONDARY_CNAME FLY_APP_NAME; do
        if ! require_env "$var" 2>/dev/null; then
            echo "  - $var"
            missing=1
        fi
    done
    return $missing
}

echo ""
echo "================================================================"
echo "               BT38 FAILOVER ORCHESTRATOR"
echo "================================================================"
echo ""
echo "DATABASE MODE: VARIANT B (Shared Database)"
echo "Both instances connect to the same Neon PostgreSQL."
echo "Variant A (DB promotion) requires Stage 7."
echo ""

if [ "$DRY_RUN" = true ]; then
    log_dry "DRY RUN MODE - No changes will be made"
    echo ""
fi

# Validate tools
log_info "Checking required tools..."
require_tool curl
require_tool flyctl
log_info "All tools available"

# Validate environment
log_info "Validating environment variables..."
if ! validate_all_env; then
    log_error "Missing required environment variables (see above)"
    exit 1
fi
log_info "All environment variables validated"
echo ""

# ============================================================
# SKIP HEALTH WARNING (Split-Brain Risk)
# ============================================================
if [ "$SKIP_HEALTH" = true ]; then
    echo ""
    echo "================================================================"
    echo -e "${RED}${BOLD}    ⚠️  WARNING: SPLIT-BRAIN RISK  ⚠️${NC}"
    echo "================================================================"
    echo ""
    echo "You are about to skip the primary health check."
    echo ""
    echo "This is DANGEROUS because:"
    echo "  - Primary may still be running and processing requests"
    echo "  - Two active instances = DATA CORRUPTION"
    echo "  - Sync jobs may run on BOTH instances simultaneously"
    echo "  - Push jobs may send conflicting updates to marketplaces"
    echo ""
    echo "Only use --skip-health when you have CONFIRMED that the"
    echo "primary instance is completely unreachable or shut down."
    echo ""
    echo "================================================================"
    echo ""
    echo -n "Type I_ACCEPT_SPLIT_BRAIN_RISK to proceed: "
    read -r RISK_CONFIRM
    
    if [ "$RISK_CONFIRM" != "I_ACCEPT_SPLIT_BRAIN_RISK" ]; then
        log_error "Risk acknowledgment failed. Aborting."
        exit 1
    fi
    echo ""
    log_warn "Split-brain risk acknowledged. Proceeding with caution..."
    echo ""
fi

# ============================================================
# STEP 1: Health Check (Split-Brain Protection)
# ============================================================
log_step "1/4" "Health Check (Split-Brain Protection)"

if [ "$SKIP_HEALTH" = true ]; then
    log_warn "Health check SKIPPED (--skip-health)"
    log_warn "User accepted split-brain risk"
elif [ "$DRY_RUN" = true ]; then
    log_dry "Would check health of primary ($PRIMARY_HEALTH_RETRIES attempts) and secondary"
    log_dry "  Primary must FAIL all $PRIMARY_HEALTH_RETRIES attempts before failover proceeds"
    log_dry "  Secondary must be HEALTHY"
else
    # Check if PRIMARY is DOWN (required for safe failover)
    log_info "Checking if PRIMARY is down ($PRIMARY_HEALTH_RETRIES attempts)..."
    
    if "$SCRIPT_DIR/health-check.sh" primary "$PRIMARY_HEALTH_RETRIES" 2>/dev/null; then
        echo ""
        log_error "PRIMARY IS STILL HEALTHY!"
        log_error "Failover is only safe when primary is confirmed DOWN."
        log_error ""
        log_error "To prevent split-brain:"
        log_error "  1. Shut down primary first, OR"
        log_error "  2. Wait for primary to fail all $PRIMARY_HEALTH_RETRIES health checks"
        log_error ""
        log_error "If you are CERTAIN primary is unreachable, use:"
        log_error "  ./scripts/failover.sh --skip-health"
        exit 1
    fi
    
    log_info "Primary confirmed DOWN after $PRIMARY_HEALTH_RETRIES attempts"
    echo ""
    
    # Check if SECONDARY is UP (required to failover to it)
    log_info "Checking if SECONDARY is healthy..."
    
    if ! "$SCRIPT_DIR/health-check.sh" secondary 1; then
        log_error "Secondary is not healthy! Cannot failover."
        log_error "Fix secondary before attempting failover."
        exit 1
    fi
    
    log_info "Secondary is healthy, proceeding with failover"
fi

echo ""

# ============================================================
# STEP 2: Activate Secondary
# ============================================================
log_step "2/4" "Activate Secondary Instance"

if [ "$DRY_RUN" = true ]; then
    log_dry "Would activate secondary via fly-activate.sh"
    "$SCRIPT_DIR/fly-activate.sh" activate --dry-run 2>/dev/null || true
else
    log_info "Activating secondary instance..."
    "$SCRIPT_DIR/fly-activate.sh" activate
    
    log_info "Waiting 30 seconds for secondary to stabilize..."
    sleep 30
    
    # Verify secondary is still healthy after activation
    log_info "Verifying secondary after activation..."
    if ! "$SCRIPT_DIR/health-check.sh" secondary 1; then
        log_error "Secondary became unhealthy after activation!"
        log_error "Manual intervention required."
        exit 1
    fi
fi

echo ""

# ============================================================
# STEP 3: Switch DNS
# ============================================================
log_step "3/4" "Switch DNS to Secondary"

if [ "$DRY_RUN" = true ]; then
    log_dry "Would switch DNS to secondary via dns-switch.sh"
    "$SCRIPT_DIR/dns-switch.sh" secondary --dry-run 2>/dev/null || true
else
    log_info "Switching DNS to secondary..."
    "$SCRIPT_DIR/dns-switch.sh" secondary
    
    log_info "Waiting 60 seconds for DNS propagation..."
    sleep 60
fi

echo ""

# ============================================================
# STEP 4: Verify Failover
# ============================================================
log_step "4/4" "Verify Failover"

if [ "$DRY_RUN" = true ]; then
    log_dry "Would verify DNS resolution and health"
else
    log_info "Verifying DNS resolution..."
    echo ""
    if command -v dig &> /dev/null; then
        echo "  dig $DNS_RECORD_NAME +short:"
        dig "$DNS_RECORD_NAME" +short || echo "  (lookup failed)"
    else
        echo "  (dig not available, skipping DNS verification)"
    fi
    echo ""
    
    log_info "Verifying secondary health via production URL..."
    if [ -n "$PRIMARY_URL" ]; then
        HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${PRIMARY_URL}/health" 2>/dev/null || echo "000")
        if [ "$HEALTH_CODE" = "200" ]; then
            log_info "Production URL is healthy (HTTP $HEALTH_CODE)"
        else
            log_warn "Production URL returned HTTP $HEALTH_CODE (may still be propagating)"
        fi
    fi
fi

echo ""
echo "================================================================"
echo "                   FAILOVER COMPLETE"
echo "================================================================"
echo ""
echo "DATABASE MODE: VARIANT B (Shared Database)"
echo "Secondary is now serving traffic using the SAME database."
echo ""
log_info "Secondary is now the active primary"
echo ""
log_warn "CRITICAL: Disable the original primary instance NOW"
log_warn "to prevent split-brain (both writing to same DB)."
echo ""
echo "Post-failover checklist:"
echo "  [ ] IMMEDIATELY disable original primary workers"
echo "  [ ] Verify application functionality"
echo "  [ ] Check sync jobs are running on secondary"
echo "  [ ] Monitor for errors in logs"
echo "  [ ] Update team about failover status"
echo ""
