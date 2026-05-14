# DEV vs PROD Environment Workflow Guide

This document explains how to use the Development (DEV) and Production (PROD) environments for the Multi-Channel Inventory Management System.

## Overview

The system supports two completely separate environments:
- **DEV**: Your private lab for testing and development
- **PROD**: The published application for live use by additional users

## Environment Configuration

### Environment Variables

The application uses `APP_ENV` to determine which mode it's running in:

```bash
APP_ENV=dev   # Development mode (default when running locally)
APP_ENV=prod  # Production mode (set by Replit deployment)
```

### Database Configuration

Each environment uses its own database:

- **DEV**: Uses `DEV_DATABASE_URL` if set, otherwise falls back to `DATABASE_URL` or local SQLite
- **PROD**: Uses `DATABASE_URL` (must be set in Replit deployment)

This ensures your development data stays separate from production data.

## Development (DEV) Mode

### How to Run DEV Mode

Simply start the application directly:

```bash
python app.py
```

Or use the Replit "Run" button, which defaults to DEV mode.

### DEV Mode Characteristics

- **Environment**: `APP_ENV=dev`, `production=false`
- **Database**: Uses `DEV_DATABASE_URL` or local SQLite (`inventory_dev.db`)
- **Background Sync**: DISABLED by default - you must manually trigger sync jobs
- **Logging**: Verbose DEBUG level logging, including SQL queries
- **URL**: Replit "Open in Browser" DEV URL (port 5000)
- **Session Cookies**: Standard Lax mode for local testing
- **Use Case**: Safe experimentation, testing new features, debugging

### Manual Sync in DEV

Since background sync is disabled in DEV mode, you can trigger syncs manually through:
1. The web interface (Store management page → Manual Sync button)
2. Direct API calls to sync endpoints

### DEV Endpoints to Check

```bash
# Health check
curl http://127.0.0.1:5000/health

# System diagnostics
curl http://127.0.0.1:5000/api/diagnostics/system

# eBay health check
curl http://127.0.0.1:5000/api/diagnostics/ebay/health

# Amazon health check
curl http://127.0.0.1:5000/api/diagnostics/amazon/health
```

Expected response for health check in DEV:
```json
{
  "ok": true,
  "env": "dev",
  "production": false,
  "database": "connected",
  "stores": {
    "total": 2,
    "active": 2
  }
}
```

## Production (PROD) Mode

### How to Set Up PROD Mode

1. **Configure Environment Variable** in Replit Secrets:
   ```
   APP_ENV=prod
   ```

2. **Set Production Database**:
   ```
   DATABASE_URL=<your_production_postgresql_url>
   ```

3. **Set Session Secret**:
   ```
   SESSION_SECRET=<random_secure_string>
   ```

4. **Publish the Application** using Replit's "Publish" button

### PROD Mode Characteristics

- **Environment**: `APP_ENV=prod`, `production=true`
- **Database**: Uses `DATABASE_URL` (production PostgreSQL)
- **Background Sync**: ENABLED - runs every 30 seconds for active stores
- **Logging**: INFO level - cleaner, production-ready logs
- **URL**: Published Replit URL (e.g., `https://your-app.replit.app`)
- **Session Cookies**: Secure mode (HTTPS required, SameSite=None for iframe support)
- **Use Case**: Live multi-user environment, real marketplace syncing

### PROD Endpoints to Monitor

```bash
# Health check
curl https://your-app.replit.app/health

# System diagnostics
curl https://your-app.replit.app/api/diagnostics/system

# eBay health check
curl https://your-app.replit.app/api/diagnostics/ebay/health

# Amazon health check
curl https://your-app.replit.app/api/diagnostics/amazon/health
```

Expected response for health check in PROD:
```json
{
  "ok": true,
  "env": "prod",
  "production": true,
  "database": "connected",
  "stores": {
    "total": 3,
    "active": 3
  }
}
```

## Safety Features

### Automatic Protections

1. **Session Secret Enforcement**: PROD mode requires `SESSION_SECRET` to be set, fails fast if missing
2. **Database Separation**: DEV and PROD use different databases
3. **Background Sync**: Only runs in PROD to prevent accidental syncs during development
4. **Watchdog System**: Automatically cleans up stuck sync jobs every 60 seconds in both modes

### Data Integrity

- **DEV changes never affect PROD**: Completely separate databases
- **Warehouse Authority**: The warehouse is always the single source of truth for stock
- **No Accidental Overwrites**: Marketplace imports never overwrite warehouse quantities

## Common Workflows

### Testing New Features in DEV

1. Start DEV mode: `python app.py`
2. Check health: `curl http://127.0.0.1:5000/health`
3. Verify your existing data is intact (should show >0 items)
4. Make and test your changes
5. Manually trigger sync if needed
6. Verify everything works

### Deploying to PROD

1. Test thoroughly in DEV first
2. Set `APP_ENV=prod` in Replit Secrets
3. Verify `DATABASE_URL` points to production database
4. Publish the application
5. Check health endpoint to verify PROD mode
6. Monitor background sync logs

### Switching Between Environments

**To go from PROD back to DEV:**
1. Stop the published app (or leave it running - they're independent)
2. Run `python app.py` locally
3. DEV mode automatically activates with local database

**To go from DEV to PROD:**
1. Ensure `APP_ENV=prod` is set in Replit deployment secrets
2. Publish the application
3. PROD mode automatically activates with production database

## Environment Variables Reference

### Required for Both Environments

```bash
SESSION_SECRET=<random_secure_string>  # Required in PROD, optional in DEV
```

### DEV-Specific (Optional)

```bash
DEV_DATABASE_URL=<postgresql_or_sqlite_url>  # Optional, defaults to local SQLite
```

### PROD-Specific (Required)

```bash
APP_ENV=prod                   # REQUIRED - triggers production mode
DATABASE_URL=<postgresql_url>  # REQUIRED - production database
```

### Marketplace Credentials (Both Environments)

#### eBay
Stored per-store in the database:
- App ID (api_key)
- Dev ID (api_secret)
- Cert ID (api_cert)
- User Token (user_token)
- Site ID (site_id, e.g., 3 for UK)
- Sandbox flag (sandbox, should be `false` for production)

#### Amazon SP-API
Global environment variables:
```bash
AMAZON_LWA_CLIENT_ID=<lwa_client_id>
AMAZON_LWA_CLIENT_SECRET=<lwa_client_secret>
AMAZON_REFRESH_TOKEN=<refresh_token>
AMAZON_SELLER_ID=<seller_id>
```

## Troubleshooting

### "How do I know which mode I'm in?"

Check the health endpoint:
```bash
curl http://localhost:5000/health
```

Look for `"env": "dev"` or `"env": "prod"`.

### "Background sync is not running in DEV"

This is **intentional**. DEV mode disables background sync to give you full control. Trigger syncs manually when needed.

### "My DEV data disappeared"

If using local SQLite, check that `inventory_dev.db` exists. If you set `DEV_DATABASE_URL`, ensure it points to your dev database.

### "PROD is using the wrong database"

Check `DATABASE_URL` in Replit Secrets. It should point to your production PostgreSQL database, not the dev database.

### "Amazon 'Draft' status preventing API use"

Even if Amazon shows your app as "Draft" in the developer portal, the SP-API should work for **your own seller account** as long as:
1. All credentials are set correctly
2. The app has the required roles/permissions granted
3. Test the connection using `/api/diagnostics/amazon/health`

To resolve "Draft" status:
- Complete your Amazon Developer Profile
- Provide app description and use case
- Provide your published Replit URL
- Show Amazon that the app is functioning (use health check endpoints as proof)

## Best Practices

1. **Always develop in DEV first** - Never make changes directly in PROD
2. **Test thoroughly** - Use the diagnostics endpoints to verify everything works
3. **Monitor PROD** - Check sync logs and health endpoints regularly
4. **Keep databases separate** - Never point PROD to DEV database or vice versa
5. **Document changes** - Update this file when you add new features or workflows

## Support

If you encounter issues:
1. Check the health endpoint for the environment
2. Review the sync logs for errors
3. Use the diagnostics endpoints to identify problems
4. Check that all required environment variables are set correctly
