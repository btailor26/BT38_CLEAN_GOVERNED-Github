#!/bin/bash
# BT38 Database Migration Script
# EXPLICIT EXECUTION ONLY — Never run automatically
#
# Usage:
#   ./scripts/db-migrate.sh              # Apply migrations to local DB
#   ./scripts/db-migrate.sh --dry-run    # Show what would be applied
#
# SAFETY: This script REFUSES to run against production databases.

set -e

DRY_RUN=false
if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    echo "=== DRY RUN MODE — No changes will be made ==="
fi

# Ensure we're in the app directory
cd "$(dirname "$0")/.."

echo "=== BT38 Database Migration ==="
echo ""

# ============================================================
# PRODUCTION SAFETY CHECKS
# ============================================================

# Extract host from DATABASE_URL
DB_HOST=$(echo "${DATABASE_URL:-}" | sed -E 's/.*@([^:\/]+).*/\1/')
APP_ENV_VALUE="${APP_ENV:-unknown}"

echo "DATABASE_URL: ${DATABASE_URL:-<not set>}"
echo "Detected DB host: ${DB_HOST:-<unknown>}"
echo "APP_ENV: ${APP_ENV_VALUE}"
echo ""

# SAFETY CHECK 1: APP_ENV must be dev or local
if [ "$APP_ENV_VALUE" != "dev" ] && [ "$APP_ENV_VALUE" != "local" ]; then
    echo "❌ BLOCKED: APP_ENV must be 'dev' or 'local'"
    echo "   Current APP_ENV: ${APP_ENV_VALUE}"
    echo "   This script cannot run against production environments."
    exit 1
fi

# SAFETY CHECK 2: DB host must be 'db' (docker) or 'localhost'
if [ "$DB_HOST" != "db" ] && [ "$DB_HOST" != "localhost" ] && [ "$DB_HOST" != "127.0.0.1" ]; then
    echo "❌ BLOCKED: DATABASE_URL host must be 'db', 'localhost', or '127.0.0.1'"
    echo "   Detected host: ${DB_HOST}"
    echo "   This script cannot run against remote databases."
    exit 1
fi

echo "✅ Safety checks passed (local environment confirmed)"
echo ""

# ============================================================
# MIGRATION EXECUTION
# ============================================================

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would execute: db.create_all()"
    echo "[DRY RUN] This creates any missing tables based on models.py"
    exit 0
fi

# Confirm before proceeding
echo "You are about to apply migrations to:"
echo "  Host: ${DB_HOST}"
echo "  Environment: ${APP_ENV_VALUE}"
echo ""
read -p "Type 'yes' to confirm: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Applying migrations..."

# Use Python to run create_all
python3 -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('Migration complete.')
"

echo "=== Migration Complete ==="
