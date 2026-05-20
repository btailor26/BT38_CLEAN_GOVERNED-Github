from flask_login import login_required, current_user
from flask_login import login_required
import os
import logging
import time
import subprocess
import sys
try:
    import fcntl
except ImportError:
    fcntl = None
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from extensions import db, login_manager

# NEVER-AGAIN PROTECTION: Fail fast if critical modules have syntax errors
# This prevents unclosed triple-quote blocks from crashing the app at runtime
CRITICAL_MODULES = ['routes.py', 'sync_service.py', 'amazon_service.py', 'ebay_service.py']

def validate_syntax_on_startup():
    """Compile-check critical modules before Flask loads them."""
    for module in CRITICAL_MODULES:
        module_path = os.path.join(os.path.dirname(__file__), module)
        if os.path.exists(module_path):
            result = subprocess.run(
                [sys.executable, '-m', 'py_compile', module_path],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                error_msg = f"FATAL: Syntax error in {module}:\n{result.stderr}"
                logging.error(error_msg)
                raise SyntaxError(error_msg)
    logging.info("Startup syntax check passed for all critical modules")

validate_syntax_on_startup()

# App version for cache busting and deployment verification
# Update this with each deployment to ensure templates are refreshed
APP_VERSION = f"1.0.{int(time.time())}"  # Dynamic versioning based on startup time

# Environment configuration - DEV MODE ONLY (production deployment disabled)
APP_ENV = os.getenv("APP_ENV", "dev").lower()  # Default to dev for localhost-only development
IS_PRODUCTION = APP_ENV == "prod"
IS_DEVELOPMENT = APP_ENV == "dev"
IS_STAGING = APP_ENV == "staging"

# Staging safety: PUSH_ENABLED controls whether write operations are allowed
# Default: True in prod/dev, False in staging
PUSH_ENABLED = os.getenv("PUSH_ENABLED", "true" if not IS_STAGING else "false").lower() == "true"
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "read-write" if not IS_STAGING else "read-only").lower()

# ============================================================================
# SENTINEL-2: UNLOCK MODES
# ============================================================================
# SENTINEL_MODE controls what Sentinel can do:
#   LOCKED  - No input, no execution (default)
#   OBSERVE - Read-only observation (current staging behavior)
#   PLAN    - Accept command submissions for validation (NO execution)
#   EXECUTE - NOT ENABLED (blocked at code level)
SENTINEL_MODE = os.getenv("SENTINEL_MODE", "OBSERVE").upper()
VALID_SENTINEL_MODES = ["LOCKED", "OBSERVE", "PLAN"]
if SENTINEL_MODE not in VALID_SENTINEL_MODES:
    logging.warning(f"Invalid SENTINEL_MODE '{SENTINEL_MODE}', defaulting to OBSERVE")
    SENTINEL_MODE = "OBSERVE"
# HARD BLOCK: EXECUTE mode is never allowed
if SENTINEL_MODE == "EXECUTE":
    logging.error("SENTINEL_MODE=EXECUTE is BLOCKED - forcing LOCKED")
    SENTINEL_MODE = "OBSERVE"

# [STAGE5] Single-Writer Failover Guards
# These flags control whether this instance can perform commercial actions
FAILOVER_ROLE = os.getenv("FAILOVER_ROLE", "primary").lower()
IS_ACTIVE_PRIMARY = os.getenv("IS_ACTIVE_PRIMARY", "true").lower() == "true"
ENABLE_SYNC_WORKERS = os.getenv("ENABLE_SYNC_WORKERS", "true").lower() == "true"
ENABLE_PUSH_JOBS = os.getenv("ENABLE_PUSH_JOBS", "true").lower() == "true"
ENABLE_SCHEDULERS = os.getenv("ENABLE_SCHEDULERS", "true").lower() == "true"

# Configure logging
log_level = logging.DEBUG if IS_DEVELOPMENT else logging.INFO
logging.basicConfig(level=log_level)

# Create the app
app = Flask(__name__)

# === BT38 FORCE SQLITE (DEV ONLY) ===
import os
# DATABASE_URL must never be removed here.
# Production uses DATABASE_URL. Local dev may use DEV_DATABASE_URL or explicit SQLite dev fallback.


# SECURITY: Require SESSION_SECRET in production - fail fast if missing
session_secret = os.environ.get("SESSION_SECRET")
if not session_secret:
    if IS_PRODUCTION:
        raise RuntimeError("CRITICAL: SESSION_SECRET environment variable must be set in production")
    else:
        logging.warning("SESSION_SECRET not set - using dev fallback (NOT SAFE FOR PRODUCTION)")
        session_secret = "dev-secret-key-change-in-production"

app.secret_key = session_secret
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Store environment in app config for access throughout the app
app.config["APP_ENV"] = APP_ENV
app.config["IS_PRODUCTION"] = IS_PRODUCTION
app.config["IS_DEVELOPMENT"] = IS_DEVELOPMENT
app.config["IS_STAGING"] = IS_STAGING
app.config["PUSH_ENABLED"] = PUSH_ENABLED
app.config["EXECUTION_MODE"] = EXECUTION_MODE
app.config["SENTINEL_MODE"] = SENTINEL_MODE

# Session configuration - use standard Flask sessions for compatibility
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes

# ============================================================================
# SESSION COOKIE ISOLATION - CRITICAL FOR STAGING/PRODUCTION SEPARATION
# ============================================================================
# Each environment gets a UNIQUE cookie name to prevent session leakage
# Cookie DOMAIN is set dynamically based on request host (see after_request)

# Environment-scoped cookie name (prevents cross-environment session sharing)
app.config['SESSION_COOKIE_NAME'] = f"bt38_session_{APP_ENV}"

# Cookie domain: Set to None by default - will be set dynamically per-request
# This allows the app to work on BOTH:
# - Custom domains (bt38inv.com, staging.bt38inv.com)
# - Replit preview domains (*.replit.dev)
app.config['SESSION_COOKIE_DOMAIN'] = None  # Dynamic - see after_request handler

# Store the current environment in session for mismatch detection
app.config['BT38_SESSION_ENV'] = APP_ENV

# Session cookie settings
app.config['SESSION_COOKIE_SECURE'] = True  # Required for SameSite=None
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Required for cross-site iframe (Replit wrapper)
app.config['SESSION_COOKIE_HTTPONLY'] = True

# Template configuration - force reload to ensure new templates are picked up after deployment
app.config['TEMPLATES_AUTO_RELOAD'] = True  # Always reload templates on change
app.jinja_env.auto_reload = True  # Force Jinja2 to check template modification times

# Configure the database - DEV and PROD both use PostgreSQL for parity
if IS_DEVELOPMENT:
    dev_db_url = os.environ.get("DEV_DATABASE_URL") or os.environ.get("DATABASE_URL") or "sqlite:///C:/Users/btail/_ARCHIVE_OLD_BT38/BT38/instance/bt38_ims_local.db"

    if not dev_db_url:
        raise RuntimeError(
            "DEV cannot start: No database URL configured. "
            "Set DEV_DATABASE_URL or DATABASE_URL to a PostgreSQL connection string."
        )

    if dev_db_url.startswith("sqlite"):
        allow_sqlite = os.environ.get("ALLOW_SQLITE_DEV", "false").lower() == "true"
        if not allow_sqlite:
            raise RuntimeError(
                "DEV cannot use SQLite. DEV must match PROD (PostgreSQL). "
                "Set DEV_DATABASE_URL to Postgres, or set ALLOW_SQLITE_DEV=true (temporary only)."
            )
        logging.critical("⚠️  SQLITE DEV OVERRIDE ENABLED — GOVERNANCE BYPASS ACTIVE")

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///C:/Users/btail/_ARCHIVE_OLD_BT38/BT38/instance/bt38_ims_local.db"
    logging.info(f"DEV MODE: Using database: {dev_db_url.split('@')[-1] if '@' in dev_db_url else 'configured'}")
else:
    prod_db_url = os.environ.get("DATABASE_URL")
    if not prod_db_url:
        raise RuntimeError("CRITICAL: DATABASE_URL must be set in production environment")
    app.config["SQLALCHEMY_DATABASE_URI"] = prod_db_url
    logging.info("PROD MODE: Using DATABASE_URL")

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
    "echo": IS_DEVELOPMENT,
}
app.config["SQLALCHEMY_ECHO"] = IS_DEVELOPMENT

db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'governed.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

@login_manager.unauthorized_handler
def unauthorized():
    from flask import flash, redirect, url_for, request
    import logging
    logging.info(f"[UNAUTH] Custom handler called for path: {request.path}")
    flash(login_manager.login_message, login_manager.login_message_category)
    return redirect(url_for('governed.login', next=request.path))
