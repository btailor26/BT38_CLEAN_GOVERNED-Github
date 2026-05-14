#!/bin/bash
# BT38 Failback Script
# Reverts failover: deactivates secondary and switches DNS back to primary
#
# IMPORTANT: Stage 6 supports VARIANT B (shared database) ONLY.
# Both primary and secondary connect to the SAME Neon PostgreSQL database.
# Variant A (separate databases with promotion) requires Stage 7.
#
# Usage:
#   ./scripts/failback.sh              # Execute full failback
#   ./scripts/failback.sh --dry-run    # Show what would happen
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

for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
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
echo "               BT38 FAILBACK TO PRIMARY"
echo "================================================================"
echo ""
echo "DATABASE MODE: VARIANT B (Shared Database)"
echo "Both instances connect to the same Neon PostgreSQL."
echo "No database migration needed for failback."
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
# STEP 1: Verify Primary Health
# ============================================================
log_step "1/4" "Verify Primary Health"

if [ "$DRY_RUN" = true ]; then
    log_dry "Would check health of primary"
    log_dry "  Primary: $PRIMARY_URL/health"
else
    log_info "Checking primary instance health..."
    
    if ! "$SCRIPT_DIR/health-check.sh" primary 3; then
        log_error "Primary is not healthy! Cannot failback."
        log_error "Fix primary before attempting failback."
        exit 1
    fi
    
    log_info "Primary is healthy, proceeding with failback"
fi

echo ""

# ============================================================
# STEP 2: Deactivate Secondary FIRST (prevent split-brain)
# ============================================================
log_step "2/4" "Deactivate Secondary Instance (Split-Brain Prevention)"

if [ "$DRY_RUN" = true ]; then
    log_dry "Would deactivate secondary via fly-activate.sh"
    "$SCRIPT_DIR/fly-activate.sh" deactivate --dry-run 2>/dev/null || true
else
    log_info "Deactivating secondary instance BEFORE DNS switch..."
    log_info "(This prevents both instances from being active simultaneously)"
    "$SCRIPT_DIR/fly-activate.sh" deactivate
    
    log_info "Waiting 15 seconds for secondary to stop processing..."
    sleep 15
fi

echo ""

# ============================================================
# STEP 3: Switch DNS to Primary
# ============================================================
log_step "3/4" "Switch DNS to Primary"

if [ "$DRY_RUN" = true ]; then
    log_dry "Would switch DNS to primary via dns-switch.sh"
    "$SCRIPT_DIR/dns-switch.sh" primary --dry-run 2>/dev/null || true
else
    log_info "Switching DNS to primary..."
    "$SCRIPT_DIR/dns-switch.sh" primary
    
    log_info "Waiting 60 seconds for DNS propagation..."
    sleep 60
fi

echo ""

# ============================================================
# STEP 4: Verify Failback
# ============================================================
log_step "4/4" "Verify Failback"

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
    
    log_info "Verifying primary health via production URL..."
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
echo "                   FAILBACK COMPLETE"
echo "================================================================"
echo ""
echo "DATABASE MODE: VARIANT B (Shared Database)"
echo "Primary is now serving traffic. No data migration needed."
echo ""
log_info "Primary is now the active instance"
log_info "Secondary has been returned to standby mode"
echo ""
echo "Post-failback checklist:"
echo "  [ ] Verify application functionality on primary"
echo "  [ ] Check sync jobs are running on primary"
echo "  [ ] Monitor for errors in logs"
echo "  [ ] Verify secondary is in standby (no push jobs)"
echo "  [ ] Update team about failback status"
echo ""
