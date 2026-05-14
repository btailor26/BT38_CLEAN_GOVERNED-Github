# DEV Environment Setup Guide

This guide explains how to create a separate DEV environment for safe testing without affecting your PRODUCTION inventory system.

## Quick Reference

- **PROD URL**: Will be `https://<your-repl-name>.replit.app` after publishing
- **Toggle Environment**: Set `APP_ENV` secret to either `prod` or `dev`
- **Current ENV**: `/health` endpoint shows current environment

## Step 1: Fork/Clone This Replit Project

1. Click the three dots (⋯) menu at the top of this Replit
2. Select "Fork" or "Duplicate"
3. Rename the clone to something clear like: `inventory-manager-dev`

## Step 2: Configure DEV Environment

In your new DEV Replit project, set these Secrets/Environment variables:

### Required DEV Configuration

```bash
APP_ENV=dev
DATABASE_URL=<separate-dev-database-url>
```

### Optional: Use SQLite for DEV (No External DB Needed)

If you don't want to set up a separate PostgreSQL database for DEV:

```bash
APP_ENV=dev
DATABASE_URL=sqlite:///dev_inventory.db
```

### Remove or Blank Live Credentials

**IMPORTANT**: To prevent DEV from hitting real marketplaces:

1. Remove these secrets or set them to empty strings:
   - `AMAZON_LWA_CLIENT_ID`
   - `AMAZON_LWA_CLIENT_SECRET`
   - `AMAZON_REFRESH_TOKEN`
   - eBay credentials (App ID, Dev ID, Cert ID, User Token)

2. OR use sandbox credentials if available

## Step 3: Verify DEV Behavior

### What DEV Mode Does

When `APP_ENV=dev`:

- **Background sync is DISABLED** - No automatic marketplace syncing
- **Logging level is DEBUG** - More detailed logs for troubleshooting
- **Manual sync only** - You can manually trigger syncs for testing

### Test Your DEV Environment

1. Run the DEV Replit
2. Visit `/health` endpoint:

```bash
curl https://your-dev-repl.replit.dev/health
```

Expected response:
```json
{
  "ok": true,
  "env": "dev",
  "production": false,
  "database": "connected",
  ...
}
```

## Step 4: Add Visual ENV Indicator (Optional)

Add this to `templates/base.html` header to see which environment you're in:

```html
{% if config.APP_ENV == 'dev' %}
<div class="alert alert-warning text-center mb-0" style="border-radius: 0;">
    ⚠️ DEVELOPMENT ENVIRONMENT ⚠️
</div>
{% endif %}
```

## Working with PROD and DEV

### DEV Workflow

1. Make changes in DEV environment
2. Test thoroughly with test data
3. Verify with `/health` endpoint (`"env": "dev"`)
4. Once satisfied, apply changes to PROD

### Deploying Changes to PROD

1. **From DEV Replit**: Copy code changes
2. **In PROD Replit**: Paste and test
3. **Verify**: Check `/health` shows `"env": "prod"`
4. **Re-publish**: Click "Publish" to update live PROD app

## Environment Comparison

| Feature | PROD (`APP_ENV=prod`) | DEV (`APP_ENV=dev`) |
|---------|----------------------|---------------------|
| Background Sync | ✅ Enabled | ❌ Disabled |
| Real API Calls | ✅ Live eBay/Amazon | ❌ Blocked/Stubbed |
| Database | Production DB | Separate Dev DB |
| Logging Level | INFO | DEBUG |
| Auto-Push | ✅ Enabled | ❌ Disabled |
| URL | `.replit.app` | `-dev.replit.dev` |

## Troubleshooting

### DEV still hitting live APIs?

Check that API credentials are removed from DEV Secrets panel.

### Background sync running in DEV?

Verify `/health` returns `"env": "dev"` and restart the app.

### Want to test sync in DEV?

You can manually trigger sync jobs through the UI, but they won't execute real API calls if credentials are removed.

## Safety Tips

1. **Always check `/health`** before making changes to confirm which environment you're in
2. **Use different browsers** for PROD and DEV to avoid confusion
3. **Never copy PROD database to DEV** - use test data only
4. **Keep credentials separate** - PROD keys should never be in DEV

---

**Current Status**: PROD environment is configured and running. Follow steps above to create your DEV environment.
