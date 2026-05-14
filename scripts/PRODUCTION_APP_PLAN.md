# BT38 Production App Plan (Fly.io)

**Version:** 1.0  
**Date:** 2025-12-16  
**Status:** DRAFT - Requires Architect Approval

---

## 1. Production App Specification

### App Identity

| Property | Value | Notes |
|----------|-------|-------|
| **App Name** | `bt38-prod` | Must contain "prod" for safety checks |
| **Organization** | personal | Same as staging |
| **Primary Region** | `lhr` (London) | Closest to user base |
| **Hostname** | `bt38-prod.fly.dev` | Auto-generated |

### Resource Configuration

| Resource | Staging | Production | Notes |
|----------|---------|------------|-------|
| Machines | 2 | 2-3 | Start with 2, scale if needed |
| CPU | shared-cpu-1x | shared-cpu-2x | More CPU for production load |
| Memory | 512MB | 1024MB | More memory for sync jobs |
| Auto-stop | disabled | disabled | Always running |
| Auto-start | enabled | enabled | Quick recovery |

---

## 2. Fly.io Configuration

### fly.toml for Production

```toml
app = "bt38-prod"
primary_region = "lhr"
kill_signal = "SIGINT"
kill_timeout = "5s"

[build]
  dockerfile = "Dockerfile"

[env]
  APP_ENV = "prod"
  PORT = "5000"
  PYTHONUNBUFFERED = "1"

[http_service]
  internal_port = 5000
  force_https = true
  auto_stop_machines = "off"
  auto_start_machines = true
  min_machines_running = 2
  processes = ["app"]

[[http_service.checks]]
  grace_period = "10s"
  interval = "30s"
  method = "GET"
  path = "/health"
  timeout = "5s"

[[vm]]
  memory = "1gb"
  cpu_kind = "shared"
  cpus = 2
```

---

## 3. Required Secrets

### Secrets Comparison: Staging vs Production

| Secret | Staging Value | Production Value | Diff |
|--------|---------------|------------------|------|
| `APP_ENV` | staging | **prod** | ✗ Different |
| `DATABASE_URL` | (Neon URL) | (Same Neon URL) | ✓ Same |
| `SESSION_SECRET` | (value) | (Same value) | ✓ Same |
| `IS_ACTIVE_PRIMARY` | **false** | **false** (until cutover) | ✓ Same |
| `ENABLE_SYNC_WORKERS` | **false** | **false** (until cutover) | ✓ Same |
| `ENABLE_PUSH_JOBS` | **false** | **false** (until cutover) | ✓ Same |
| `ENABLE_SCHEDULERS` | **false** | **false** (until cutover) | ✓ Same |
| `FAILOVER_ROLE` | secondary | **secondary** (until cutover) | ✓ Same |
| `OPENAI_API_KEY` | (value) | (Same value) | ✓ Same |
| `SENDGRID_API_KEY` | (value) | (Same value) | ✓ Same |
| `SENDGRID_FROM_EMAIL` | (value) | (Same value) | ✓ Same |

### Additional Secrets for Production

| Secret | Purpose | Source |
|--------|---------|--------|
| `AMAZON_LWA_CLIENT_ID` | Amazon SP-API auth | Replit secrets |
| `AMAZON_LWA_CLIENT_SECRET` | Amazon SP-API auth | Replit secrets |
| `AMAZON_REFRESH_TOKEN` | Amazon SP-API auth | Replit secrets |
| `AMAZON_SELLER_ID` | Amazon seller ID | Replit secrets |

### Secrets Setup Commands

```bash
# Create production app
flyctl apps create bt38-prod --org personal

# Set secrets (copy from staging + differences)
flyctl secrets set \
  APP_ENV=prod \
  DATABASE_URL="$DATABASE_URL" \
  SESSION_SECRET="$SESSION_SECRET" \
  IS_ACTIVE_PRIMARY=false \
  ENABLE_SYNC_WORKERS=false \
  ENABLE_PUSH_JOBS=false \
  ENABLE_SCHEDULERS=false \
  FAILOVER_ROLE=secondary \
  OPENAI_API_KEY="$OPENAI_API_KEY" \
  SENDGRID_API_KEY="$SENDGRID_API_KEY" \
  SENDGRID_FROM_EMAIL="$SENDGRID_FROM_EMAIL" \
  AMAZON_LWA_CLIENT_ID="$AMAZON_LWA_CLIENT_ID" \
  AMAZON_LWA_CLIENT_SECRET="$AMAZON_LWA_CLIENT_SECRET" \
  AMAZON_REFRESH_TOKEN="$AMAZON_REFRESH_TOKEN" \
  AMAZON_SELLER_ID="$AMAZON_SELLER_ID" \
  -a bt38-prod
```

---

## 4. Control Flags

### Pre-Cutover State (Standby)

| Flag | Value | Meaning |
|------|-------|---------|
| `IS_ACTIVE_PRIMARY` | `false` | Workers disabled |
| `ENABLE_SYNC_WORKERS` | `false` | Sync jobs disabled |
| `ENABLE_PUSH_JOBS` | `false` | Push jobs disabled |
| `ENABLE_SCHEDULERS` | `false` | Scheduled tasks disabled |
| `FAILOVER_ROLE` | `secondary` | Standby mode |

### Post-Cutover State (Active Primary)

| Flag | Value | Meaning |
|------|-------|---------|
| `IS_ACTIVE_PRIMARY` | `true` | Workers enabled |
| `ENABLE_SYNC_WORKERS` | `true` | Sync jobs running |
| `ENABLE_PUSH_JOBS` | `true` | Push jobs running |
| `ENABLE_SCHEDULERS` | `true` | Scheduled tasks running |
| `FAILOVER_ROLE` | `primary` | Active primary |

### Activation Command

```bash
# Activate production (ONLY after DNS switch authorized)
flyctl secrets set \
  IS_ACTIVE_PRIMARY=true \
  ENABLE_SYNC_WORKERS=true \
  ENABLE_PUSH_JOBS=true \
  ENABLE_SCHEDULERS=true \
  FAILOVER_ROLE=primary \
  -a bt38-prod
```

### Deactivation Command (Failback)

```bash
# Deactivate production (for failback to Replit)
flyctl secrets set \
  IS_ACTIVE_PRIMARY=false \
  ENABLE_SYNC_WORKERS=false \
  ENABLE_PUSH_JOBS=false \
  ENABLE_SCHEDULERS=false \
  FAILOVER_ROLE=secondary \
  -a bt38-prod
```

---

## 5. Deployment Steps

### Step 1: Create App

```bash
flyctl apps create bt38-prod --org personal
```

### Step 2: Set Secrets

```bash
# Set all required secrets (see Section 3)
flyctl secrets set ... -a bt38-prod
```

### Step 3: Deploy

```bash
# Deploy from same codebase as staging
flyctl deploy -a bt38-prod --remote-only
```

### Step 4: Verify Deployment

```bash
# Check app status
flyctl status -a bt38-prod

# Check health
curl https://bt38-prod.fly.dev/health

# Check machines
flyctl machines list -a bt38-prod
```

### Step 5: Add TLS Certificates

```bash
# Add production domain certificates
flyctl certs add bt38inv.com -a bt38-prod
flyctl certs add www.bt38inv.com -a bt38-prod

# Check certificate status
flyctl certs list -a bt38-prod
```

---

## 6. Scaling Configuration

### Initial Scale

```bash
# Scale to 2 machines in LHR
flyctl scale count 2 --region lhr -a bt38-prod
```

### Production Scale (if needed)

```bash
# Scale up for high traffic
flyctl scale count 3 --region lhr -a bt38-prod

# Scale memory
flyctl scale memory 2048 -a bt38-prod
```

### Auto-scaling (Future)

```toml
# Add to fly.toml for auto-scaling
[http_service]
  min_machines_running = 2
  max_machines_running = 5
```

---

## 7. Monitoring & Logging

### View Logs

```bash
# Stream production logs
flyctl logs -a bt38-prod

# Filter for errors
flyctl logs -a bt38-prod | grep -i error
```

### Health Checks

```bash
# Manual health check
curl https://bt38-prod.fly.dev/health

# Watch health status
watch -n 5 'curl -s https://bt38-prod.fly.dev/health | jq'
```

### Metrics Dashboard

Access at: https://fly.io/apps/bt38-prod/metrics

---

## 8. Production vs Staging Differences

| Aspect | Staging | Production |
|--------|---------|------------|
| App name | bt38-staging | bt38-prod |
| APP_ENV | staging | prod |
| Workers | Always OFF | ON after cutover |
| DNS | staging.bt38inv.com | bt38inv.com, www |
| Machine size | shared-cpu-1x, 512MB | shared-cpu-2x, 1GB |
| Machine count | 2 | 2-3 |
| TLS domains | staging.bt38inv.com | bt38inv.com, www |
| Purpose | Testing, failover drill | Live production |

---

## 9. Pre-Flight Checklist

Before creating production app:

| # | Check | Status |
|---|-------|--------|
| 1 | Staging verified healthy | ☐ |
| 2 | All secrets available | ☐ |
| 3 | Dockerfile unchanged | ☐ |
| 4 | fly.toml configured for prod | ☐ |
| 5 | Database URL confirmed | ☐ |
| 6 | Amazon API credentials ready | ☐ |
| 7 | TLS certificate plan reviewed | ☐ |
| 8 | Architect approval received | ☐ |

---

## 10. Approval

| Role | Approved | Date |
|------|----------|------|
| Architect | ☐ | |
| Infrastructure Lead | ☐ | |

---

**Document Control:**
- Created: 2025-12-16
- Based on: bt38-staging configuration
- Fly.io organization: personal
