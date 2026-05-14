#!/bin/bash
# BT38 Health Check Script
# Checks health of primary and/or secondary instances
#
# Usage:
#   ./scripts/health-check.sh primary
#   ./scripts/health-check.sh secondary
#   ./scripts/health-check.sh both
#
# Required environment variables:
#   PRIMARY_URL    - Primary instance URL (e.g., https://bt38.yourdomain.com)
#   SECONDARY_URL  - Secondary instance URL (e.g., https://bt38-secondary.fly.dev)

set -euo pipefail

TARGET="${1:-both}"
TIMEOUT=10
RETRIES="${2:-1}"  # Number of retries (used by failover.sh)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

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
        exit 1
    fi
}

check_health() {
    local name="$1"
    local url="$2"
    local retries="${3:-1}"
    
    if [ -z "$url" ]; then
        log_error "$name URL not set"
        return 1
    fi
    
    local health_url="${url}/health"
    
    for ((i=1; i<=retries; i++)); do
        log_info "Checking $name (attempt $i/$retries): $health_url"
        
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$health_url" 2>/dev/null || echo "000")
        
        if [ "$http_code" = "200" ]; then
            log_info "$name is HEALTHY (HTTP $http_code)"
            return 0
        else
            log_warn "$name attempt $i failed (HTTP $http_code)"
            if [ "$i" -lt "$retries" ]; then
                sleep 5
            fi
        fi
    done
    
    log_error "$name is UNHEALTHY after $retries attempts"
    return 1
}

echo "=== BT38 Health Check ==="
echo "Target: $TARGET"
echo "Retries: $RETRIES"
echo ""

PRIMARY_HEALTHY=false
SECONDARY_HEALTHY=false

case "$TARGET" in
    primary)
        require_env PRIMARY_URL
        if check_health "Primary" "$PRIMARY_URL" "$RETRIES"; then
            PRIMARY_HEALTHY=true
        fi
        ;;
    secondary)
        require_env SECONDARY_URL
        if check_health "Secondary" "$SECONDARY_URL" "$RETRIES"; then
            SECONDARY_HEALTHY=true
        fi
        ;;
    both)
        require_env PRIMARY_URL
        require_env SECONDARY_URL
        if check_health "Primary" "$PRIMARY_URL" "$RETRIES"; then
            PRIMARY_HEALTHY=true
        fi
        echo ""
        if check_health "Secondary" "$SECONDARY_URL" "$RETRIES"; then
            SECONDARY_HEALTHY=true
        fi
        ;;
    *)
        log_error "Unknown target: $TARGET"
        echo "Usage: $0 {primary|secondary|both} [retries]"
        exit 1
        ;;
esac

echo ""
echo "=== Health Check Summary ==="

if [ "$TARGET" = "both" ]; then
    echo "Primary:   $( [ "$PRIMARY_HEALTHY" = true ] && echo "✅ HEALTHY" || echo "❌ UNHEALTHY" )"
    echo "Secondary: $( [ "$SECONDARY_HEALTHY" = true ] && echo "✅ HEALTHY" || echo "❌ UNHEALTHY" )"
    
    if [ "$PRIMARY_HEALTHY" = true ] && [ "$SECONDARY_HEALTHY" = true ]; then
        exit 0
    elif [ "$SECONDARY_HEALTHY" = true ]; then
        log_warn "Primary is down but secondary is available for failover"
        exit 2
    else
        log_error "Both instances are unhealthy!"
        exit 1
    fi
elif [ "$TARGET" = "primary" ]; then
    [ "$PRIMARY_HEALTHY" = true ] && exit 0 || exit 1
else
    [ "$SECONDARY_HEALTHY" = true ] && exit 0 || exit 1
fi
