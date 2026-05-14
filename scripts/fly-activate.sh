#!/bin/bash
# BT38 Fly.io Activate/Deactivate Script
# Activates or deactivates the secondary Fly.io instance
#
# Usage:
#   ./scripts/fly-activate.sh activate              # Make secondary the active primary
#   ./scripts/fly-activate.sh deactivate            # Put secondary back to standby
#   ./scripts/fly-activate.sh activate --dry-run    # Show what would happen
#
# Required environment variables:
#   FLY_APP_NAME  - Fly.io app name (e.g., "bt38-secondary")
#
# Optional:
#   FLY_API_TOKEN - Fly.io API token (if not using flyctl auth)

set -euo pipefail

ACTION="${1:-}"
DRY_RUN=false

if [ "$2" = "--dry-run" ] || [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    if [ "$1" = "--dry-run" ]; then
        ACTION="${2:-}"
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

require_tool flyctl

# Validate required environment variables
require_env() {
    local var_name="$1"
    local var_value="${!var_name:-}"
    if [ -z "$var_value" ]; then
        log_error "Required environment variable not set: $var_name"
        exit 1
    fi
}

echo "=== BT38 Fly.io Activate/Deactivate ==="
echo ""

if [ "$DRY_RUN" = true ]; then
    log_dry "DRY RUN MODE - No changes will be made"
    echo ""
fi

# Validate action
if [ -z "$ACTION" ]; then
    log_error "Action required: activate or deactivate"
    echo "Usage: $0 {activate|deactivate} [--dry-run]"
    exit 1
fi

# Validate environment
require_env FLY_APP_NAME

# Determine flags based on action
case "$ACTION" in
    activate)
        IS_ACTIVE_PRIMARY="true"
        ENABLE_SYNC_WORKERS="true"
        ENABLE_PUSH_JOBS="true"
        ENABLE_SCHEDULERS="true"
        FAILOVER_ROLE="primary"
        ;;
    deactivate)
        IS_ACTIVE_PRIMARY="false"
        ENABLE_SYNC_WORKERS="false"
        ENABLE_PUSH_JOBS="false"
        ENABLE_SCHEDULERS="false"
        FAILOVER_ROLE="secondary"
        ;;
    *)
        log_error "Unknown action: $ACTION (must be 'activate' or 'deactivate')"
        exit 1
        ;;
esac

echo "Configuration:"
echo "  App:                  $FLY_APP_NAME"
echo "  Action:               $ACTION"
echo ""
echo "Flags to set:"
echo "  IS_ACTIVE_PRIMARY:    $IS_ACTIVE_PRIMARY"
echo "  ENABLE_SYNC_WORKERS:  $ENABLE_SYNC_WORKERS"
echo "  ENABLE_PUSH_JOBS:     $ENABLE_PUSH_JOBS"
echo "  ENABLE_SCHEDULERS:    $ENABLE_SCHEDULERS"
echo "  FAILOVER_ROLE:        $FAILOVER_ROLE"
echo ""

# DRY RUN
if [ "$DRY_RUN" = true ]; then
    log_dry "Would execute:"
    echo ""
    echo "  flyctl secrets set -a $FLY_APP_NAME \\"
    echo "    IS_ACTIVE_PRIMARY=$IS_ACTIVE_PRIMARY \\"
    echo "    ENABLE_SYNC_WORKERS=$ENABLE_SYNC_WORKERS \\"
    echo "    ENABLE_PUSH_JOBS=$ENABLE_PUSH_JOBS \\"
    echo "    ENABLE_SCHEDULERS=$ENABLE_SCHEDULERS \\"
    echo "    FAILOVER_ROLE=$FAILOVER_ROLE"
    echo ""
    echo "  flyctl apps restart $FLY_APP_NAME"
    echo ""
    log_dry "No changes made (dry run)"
    exit 0
fi

# CONFIRMATION REQUIRED
echo "=========================================="
log_warn "THIS WILL $( [ "$ACTION" = "activate" ] && echo "ACTIVATE" || echo "DEACTIVATE" ) THE SECONDARY INSTANCE"
echo "=========================================="
echo ""
echo -n "Type CONFIRM to proceed: "
read -r CONFIRMATION

if [ "$CONFIRMATION" != "CONFIRM" ]; then
    log_error "Confirmation failed. Aborting."
    exit 1
fi

echo ""
log_info "Setting environment flags on $FLY_APP_NAME..."

# Set secrets via flyctl
flyctl secrets set -a "$FLY_APP_NAME" \
    IS_ACTIVE_PRIMARY="$IS_ACTIVE_PRIMARY" \
    ENABLE_SYNC_WORKERS="$ENABLE_SYNC_WORKERS" \
    ENABLE_PUSH_JOBS="$ENABLE_PUSH_JOBS" \
    ENABLE_SCHEDULERS="$ENABLE_SCHEDULERS" \
    FAILOVER_ROLE="$FAILOVER_ROLE"

log_info "Restarting $FLY_APP_NAME..."

flyctl apps restart "$FLY_APP_NAME"

echo ""
log_info "$ACTION complete!"
echo ""
log_warn "Wait 30-60 seconds for the app to restart and stabilize"
echo ""
echo "Verify with: flyctl status -a $FLY_APP_NAME"
