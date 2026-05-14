#!/bin/bash
# BT38 DNS Switch Script (Cloudflare)
# Switches DNS CNAME to point to primary or secondary instance
#
# Usage:
#   ./scripts/dns-switch.sh primary              # Switch to primary
#   ./scripts/dns-switch.sh secondary            # Switch to secondary
#   ./scripts/dns-switch.sh primary --dry-run    # Show what would happen
#
# Required environment variables:
#   CLOUDFLARE_API_TOKEN  - Cloudflare API token with Zone:DNS:Edit permission
#   CLOUDFLARE_ZONE_ID    - Zone ID from Cloudflare dashboard
#   DNS_RECORD_ID         - Record ID of the CNAME to update
#   DNS_RECORD_NAME       - Record name (e.g., "bt38" for bt38.yourdomain.com)
#   PRIMARY_CNAME         - Primary target (e.g., "bt38-primary.replit.app")
#   SECONDARY_CNAME       - Secondary target (e.g., "bt38-secondary.fly.dev")

set -euo pipefail

TARGET="${1:-}"
DRY_RUN=false

if [ "$2" = "--dry-run" ] || [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    if [ "$1" = "--dry-run" ]; then
        TARGET="${2:-}"
    fi
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_dry() { echo -e "${CYAN}[DRY-RUN]${NC} $1"; }

# Validate required tools
require_tool() {
    if ! command -v "$1" &> /dev/null; then
        log_error "Required tool not found: $1"
        exit 1
    fi
}

require_tool curl

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
    for var in CLOUDFLARE_API_TOKEN CLOUDFLARE_ZONE_ID DNS_RECORD_ID DNS_RECORD_NAME PRIMARY_CNAME SECONDARY_CNAME; do
        if ! require_env "$var" 2>/dev/null; then
            echo "  - $var"
            missing=1
        fi
    done
    return $missing
}

echo "=== BT38 DNS Switch (Cloudflare) ==="
echo ""

if [ "$DRY_RUN" = true ]; then
    log_dry "DRY RUN MODE - No changes will be made"
    echo ""
fi

# Validate target
if [ -z "$TARGET" ]; then
    log_error "Target required: primary or secondary"
    echo "Usage: $0 {primary|secondary} [--dry-run]"
    exit 1
fi

# Validate environment variables
log_info "Validating environment variables..."
if ! validate_all_env; then
    log_error "Missing required environment variables (see above)"
    exit 1
fi
log_info "All environment variables validated"
echo ""

# Determine target CNAME
case "$TARGET" in
    primary)
        NEW_CNAME="$PRIMARY_CNAME"
        ;;
    secondary)
        NEW_CNAME="$SECONDARY_CNAME"
        ;;
    *)
        log_error "Unknown target: $TARGET (must be 'primary' or 'secondary')"
        exit 1
        ;;
esac

echo "Configuration:"
echo "  Record:     $DNS_RECORD_NAME"
echo "  Target:     $TARGET"
echo "  New CNAME:  $NEW_CNAME"
echo "  TTL:        60 seconds"
echo "  Proxied:    false"
echo ""

# DRY RUN - show what would happen and exit
if [ "$DRY_RUN" = true ]; then
    log_dry "Would PATCH Cloudflare DNS record:"
    echo ""
    echo "  API Endpoint: https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${DNS_RECORD_ID}"
    echo ""
    echo "  Request Body:"
    echo "  {"
    echo "    \"type\": \"CNAME\","
    echo "    \"name\": \"$DNS_RECORD_NAME\","
    echo "    \"content\": \"$NEW_CNAME\","
    echo "    \"ttl\": 60,"
    echo "    \"proxied\": false"
    echo "  }"
    echo ""
    log_dry "No changes made (dry run)"
    exit 0
fi

# CONFIRMATION REQUIRED
echo "=========================================="
log_warn "THIS WILL CHANGE PRODUCTION DNS"
echo "=========================================="
echo ""
echo "You are about to switch DNS to: $TARGET"
echo "New CNAME target: $NEW_CNAME"
echo ""
echo -n "Type CONFIRM to proceed: "
read -r CONFIRMATION

if [ "$CONFIRMATION" != "CONFIRM" ]; then
    log_error "Confirmation failed. Aborting."
    exit 1
fi

echo ""
log_info "Switching DNS to $TARGET..."

# Execute Cloudflare API call
RESPONSE=$(curl -s -X PATCH \
    "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${DNS_RECORD_ID}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{
        \"type\": \"CNAME\",
        \"name\": \"${DNS_RECORD_NAME}\",
        \"content\": \"${NEW_CNAME}\",
        \"ttl\": 60,
        \"proxied\": false
    }")

# Check response
SUCCESS=$(echo "$RESPONSE" | grep -o '"success":true' || echo "")

if [ -n "$SUCCESS" ]; then
    log_info "DNS switch successful!"
    echo ""
    echo "New configuration:"
    echo "  $DNS_RECORD_NAME → $NEW_CNAME"
    echo ""
    log_warn "DNS propagation may take 60-120 seconds"
    echo ""
    echo "Verify with: dig $DNS_RECORD_NAME +short"
else
    log_error "DNS switch failed!"
    echo "Response: $RESPONSE"
    exit 1
fi
