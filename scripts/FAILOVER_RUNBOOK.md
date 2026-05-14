# BT38 Failover Runbook

## Overview

This runbook documents the one-button failover process from the primary instance (Replit) to the secondary instance (Fly.io).

---

## IMPORTANT: Database Mode

### Stage 6 Supports VARIANT B (Shared Database) ONLY

Both primary and secondary instances connect to the **SAME Neon PostgreSQL database**.

| Aspect | Variant B (Current) |
|--------|---------------------|
| Database | Shared Neon PostgreSQL |
| Failover Complexity | Low (DNS switch only) |
| Data Consistency | Guaranteed (single DB) |
| Split-Brain Risk | Prevented by single-writer guards |
| RPO | 0 (same database) |
| RTO | 2-3 minutes |

### Variant A (Separate Databases) = Stage 7

Variant A with database promotion and replication requires a **separate Stage 7 implementation** including:
- Database promotion scripts
- DATABASE_URL swap procedures
- Replication verification
- Data consistency checks

**Do NOT attempt Variant A with Stage 6 scripts.**

---

## Prerequisites

### Required Environment Variables

```bash
# Instance URLs
export PRIMARY_URL="https://bt38.yourdomain.com"
export SECONDARY_URL="https://bt38-secondary.fly.dev"

# Cloudflare DNS
export CLOUDFLARE_API_TOKEN="your-token-here"
export CLOUDFLARE_ZONE_ID="your-zone-id"
export DNS_RECORD_ID="your-record-id"
export DNS_RECORD_NAME="bt38"
export PRIMARY_CNAME="bt38-primary.replit.app"
export SECONDARY_CNAME="bt38-secondary.fly.dev"

# Fly.io
export FLY_APP_NAME="bt38-secondary"
```

### Tool Dependencies

| Tool | Purpose | Required |
|------|---------|----------|
| `curl` | HTTP requests | Yes |
| `dig` | DNS verification | Optional |
| `flyctl` | Fly.io CLI (authenticated) | Yes |

---

## Split-Brain Protection

### How Failover Prevents Split-Brain

1. **Primary must FAIL 3 health checks** before failover proceeds
2. This ensures primary is truly unreachable
3. Secondary activation only happens after confirming primary is down
4. `--skip-health` requires explicit risk acknowledgment

### The `--skip-health` Warning

Using `--skip-health` displays:

```
================================================================
    ⚠️  WARNING: SPLIT-BRAIN RISK  ⚠️
================================================================

You are about to skip the primary health check.

This is DANGEROUS because:
  - Primary may still be running and processing requests
  - Two active instances = DATA CORRUPTION
  - Sync jobs may run on BOTH instances simultaneously
  - Push jobs may send conflicting updates to marketplaces

Type I_ACCEPT_SPLIT_BRAIN_RISK to proceed:
```

**Only use in genuine emergencies when you have manually verified primary is down.**

---

## Failover Procedure

### Option 1: One-Button Failover (Recommended)

```bash
# Dry run first
./scripts/failover.sh --dry-run

# Execute failover (requires primary to be DOWN)
./scripts/failover.sh
```

### Option 2: Emergency Failover (Skip Health)

```bash
# Only when primary is confirmed unreachable externally
./scripts/failover.sh --skip-health
```

### Option 3: Manual Step-by-Step

```bash
# Step 1: Check health (primary should FAIL)
./scripts/health-check.sh primary 3

# Step 2: Check secondary is healthy
./scripts/health-check.sh secondary

# Step 3: Activate secondary
./scripts/fly-activate.sh activate

# Step 4: Wait for stabilization (30s)
sleep 30

# Step 5: Switch DNS
./scripts/dns-switch.sh secondary

# Step 6: Verify
./scripts/health-check.sh secondary
dig bt38.yourdomain.com +short
```

---

## Failback Procedure

### Option 1: One-Button Failback

```bash
# Dry run first
./scripts/failback.sh --dry-run

# Execute failback
./scripts/failback.sh
```

### Option 2: Manual Step-by-Step

```bash
# Step 1: Check primary health
./scripts/health-check.sh primary 3

# Step 2: Deactivate secondary FIRST (prevent split-brain)
./scripts/fly-activate.sh deactivate

# Step 3: Wait for secondary to stop (15s)
sleep 15

# Step 4: Switch DNS back to primary
./scripts/dns-switch.sh primary

# Step 5: Wait for propagation (60s)
sleep 60

# Step 6: Verify
./scripts/health-check.sh primary
```

---

## Emergency Procedures

### Manual DNS Rollback

If scripts fail, use Cloudflare dashboard directly:
1. Go to Cloudflare Dashboard → DNS
2. Find the bt38 CNAME record
3. Change content to `bt38-primary.replit.app`
4. Set TTL to 1 minute
5. Save

### Manual Fly.io Deactivation

```bash
flyctl secrets set -a bt38-secondary \
    IS_ACTIVE_PRIMARY=false \
    ENABLE_SYNC_WORKERS=false \
    ENABLE_PUSH_JOBS=false \
    ENABLE_SCHEDULERS=false \
    FAILOVER_ROLE=secondary

flyctl apps restart bt38-secondary
```

---

## Verification Checklist

### Post-Failover Verification

| Check | Command | Expected |
|-------|---------|----------|
| DNS resolution | `dig bt38.yourdomain.com +short` | Shows `bt38-secondary.fly.dev` |
| Health endpoint | `curl https://bt38.yourdomain.com/health` | HTTP 200 |
| Login works | Manual test | Can log in |
| Dashboard loads | Manual test | Data displays correctly |
| Sync jobs running | Check `/admin/system-activity` | Jobs processing |
| Push jobs working | Check sync_jobs table | Status = success |
| **Original primary disabled** | Check Replit | Workers stopped |

### Post-Failback Verification

| Check | Command | Expected |
|-------|---------|----------|
| DNS resolution | `dig bt38.yourdomain.com +short` | Shows primary IP/CNAME |
| Health endpoint | `curl https://bt38.yourdomain.com/health` | HTTP 200 |
| Secondary standby | Check Fly.io logs | Shows `[STAGE5]...DISABLED` |
| Primary workers | Check Replit logs | Sync dispatcher started |

---

## Timing Expectations

| Phase | Duration | Notes |
|-------|----------|-------|
| Health check (3 attempts) | 30-45s | 10s timeout + 5s between |
| Activate secondary | 30-60s | Includes restart |
| DNS propagation | 60-120s | TTL is 60s |
| **Full failover** | **2-3 min** | Total time |
| **Full failback** | **2-3 min** | Total time |

---

## Troubleshooting

### "Primary is still healthy" Error

The failover script requires primary to **FAIL** health checks. This is intentional split-brain protection.

Solutions:
1. Wait for primary to actually become unreachable
2. Manually stop primary first
3. Use `--skip-health` only if you're certain primary is down

### Secondary Won't Activate

1. Check Fly.io status: `flyctl status -a bt38-secondary`
2. Check logs: `flyctl logs -a bt38-secondary`
3. Verify DATABASE_URL is correct
4. Check secrets are set: `flyctl secrets list -a bt38-secondary`

### DNS Not Switching

1. Verify CLOUDFLARE_API_TOKEN is valid
2. Check CLOUDFLARE_ZONE_ID matches your domain
3. Verify DNS_RECORD_ID is correct
4. Try Cloudflare dashboard directly

### Missing Environment Variable Errors

All scripts validate required environment variables before execution.
Set all variables listed in Prerequisites before running.

---

## Script Reference

| Script | Purpose | Requires CONFIRM | --dry-run |
|--------|---------|------------------|-----------|
| `health-check.sh` | Check instance health | No | No |
| `dns-switch.sh` | Change DNS CNAME | Yes | Yes |
| `fly-activate.sh` | Activate/deactivate Fly.io | Yes | Yes |
| `failover.sh` | Full failover orchestration | Yes (multiple) | Yes |
| `failback.sh` | Full failback orchestration | Yes (multiple) | Yes |

---

## Contact

For emergencies requiring manual intervention:
- Cloudflare Dashboard: https://dash.cloudflare.com
- Fly.io Dashboard: https://fly.io/dashboard
- Replit Dashboard: https://replit.com

---

Last Updated: December 2025
