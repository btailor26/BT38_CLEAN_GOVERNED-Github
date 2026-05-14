# BT38 Production Cutover Runbook

**Version:** 1.0  
**Date:** 2025-12-16  
**Architecture:** Variant B (Shared Neon PostgreSQL Database)  
**Status:** DRAFT - Requires Architect Approval

---

## Overview

This runbook documents the procedure for cutting over production traffic from Replit to Fly.io. Both environments share the same Neon PostgreSQL database (Variant B), which simplifies the cutover but requires strict single-writer enforcement to prevent data corruption.

**Production URL:** https://bt38inv.com  
**Current Production:** Replit (34.111.179.208)  
**Target Production:** Fly.io (bt38-prod.fly.dev)

---

## ⚠️ CRITICAL WARNINGS

1. **SINGLE-WRITER RULE**: Only ONE instance may have commercial workers enabled at any time
2. **ZERO TOLERANCE**: Split-brain (both instances writing) = DATA CORRUPTION
3. **NO SHORTCUTS**: Every confirmation phrase must be typed exactly
4. **REVERSIBLE**: This cutover can be reversed within 60 seconds via failback

---

## Section 1: Preconditions Checklist

**ALL conditions must be TRUE before proceeding.**

| # | Precondition | Verification Method | Status |
|---|--------------|---------------------|--------|
| 1 | Staging verified healthy | `curl https://staging.bt38inv.com/health` returns 200 | ☐ |
| 2 | Staging drill completed successfully | Last drill report shows PASS | ☐ |
| 3 | Production app `bt38-prod` created on Fly.io | `flyctl apps list` shows bt38-prod | ☐ |
| 4 | Production app has all required secrets | `flyctl secrets list -a bt38-prod` shows 11+ secrets | ☐ |
| 5 | Production app IS_ACTIVE_PRIMARY=false | Workers disabled until cutover | ☐ |
| 6 | Replit instance healthy | `curl https://bt38inv.com/health` returns 200 | ☐ |
| 7 | Database accessible from both instances | Health endpoints show database=connected | ☐ |
| 8 | No active sync/push jobs running | Check `/admin/queue-status` shows 0 pending | ☐ |
| 9 | Off-peak hours | Not between 09:00-18:00 UK time | ☐ |
| 10 | Team notified | Slack/email sent with ETA | ☐ |
| 11 | Rollback procedure tested | Failback script verified in staging | ☐ |
| 12 | Cloudflare API token valid | Test API call succeeds | ☐ |

**STOP**: If ANY precondition is FALSE, do not proceed.

---

## Section 2: Production Cutover Steps

### Phase A: Prepare (5 minutes)

```
STEP A1: Verify current production DNS
────────────────────────────────────────
Command:
  curl -s "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq '.result[] | select(.name=="bt38inv.com")'

Expected:
  type: A
  content: 34.111.179.208
  proxied: true

Operator confirms: ☐ DNS matches expected
```

```
STEP A2: Verify Fly.io production app is ready (but inactive)
────────────────────────────────────────────────────────────────
Command:
  flyctl status -a bt38-prod
  flyctl secrets list -a bt38-prod

Expected:
  - App status: running
  - Machines: 2+ running
  - IS_ACTIVE_PRIMARY: SET (value=false)

Operator confirms: ☐ App ready but workers disabled
```

```
STEP A3: Final health check - both instances
────────────────────────────────────────────
Commands:
  curl -s https://bt38inv.com/health | jq
  curl -s https://bt38-prod.fly.dev/health | jq

Expected:
  Both return: {"ok": true, "database": "connected"}

Operator confirms: ☐ Both instances healthy
```

### Phase B: Disable Replit Workers (2 minutes)

```
STEP B1: Disable commercial workers on Replit
─────────────────────────────────────────────
Action: Set environment variables on Replit:
  IS_ACTIVE_PRIMARY=false
  ENABLE_SYNC_WORKERS=false
  ENABLE_PUSH_JOBS=false
  ENABLE_SCHEDULERS=false

Verification:
  curl -s https://bt38inv.com/health | jq '.workers'

Expected:
  workers: disabled (or null)

Operator confirms: ☐ Replit workers disabled
```

```
STEP B2: Wait for in-flight jobs to complete
────────────────────────────────────────────
Action: Wait 60 seconds for any in-flight operations to complete

Command:
  sleep 60

Operator confirms: ☐ 60 seconds elapsed
```

### Phase C: Enable Fly.io Workers (2 minutes)

```
STEP C1: Activate production Fly.io workers
───────────────────────────────────────────
Commands:
  flyctl secrets set IS_ACTIVE_PRIMARY=true -a bt38-prod
  flyctl secrets set ENABLE_SYNC_WORKERS=true -a bt38-prod
  flyctl secrets set ENABLE_PUSH_JOBS=true -a bt38-prod
  flyctl secrets set ENABLE_SCHEDULERS=true -a bt38-prod
  flyctl secrets set FAILOVER_ROLE=primary -a bt38-prod

Verification:
  curl -s https://bt38-prod.fly.dev/health | jq

Expected:
  {"ok": true, "database": "connected", "production": true}

Operator confirms: ☐ Fly.io workers enabled
```

### Phase D: DNS Switch (5 minutes)

```
STEP D1: Switch DNS - Root record (@)
─────────────────────────────────────
Command:
  curl -X PATCH "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records/532c13b367d19d03aad33040f5ccd28c" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json" \
    --data '{"type":"CNAME","name":"bt38inv.com","content":"bt38-prod.fly.dev","ttl":60,"proxied":false}'

Expected response:
  {"success": true, ...}

Operator confirms: ☐ Root DNS switched
```

```
STEP D2: Switch DNS - WWW record
────────────────────────────────
Command:
  curl -X PATCH "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records/3292498f5157098bc36055d1f6e1ef40" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json" \
    --data '{"type":"CNAME","name":"www.bt38inv.com","content":"bt38-prod.fly.dev","ttl":60,"proxied":false}'

Expected response:
  {"success": true, ...}

Operator confirms: ☐ WWW DNS switched
```

```
STEP D3: Wait for DNS propagation
─────────────────────────────────
Action: Wait 60-120 seconds for DNS to propagate

Command:
  sleep 90

Operator confirms: ☐ Propagation wait complete
```

### Phase E: Verification (3 minutes)

```
STEP E1: Verify DNS resolution
──────────────────────────────
Command:
  dig bt38inv.com +short
  dig www.bt38inv.com +short

Expected:
  Both resolve to Fly.io IP addresses (not 34.111.179.208)

Operator confirms: ☐ DNS resolves to Fly.io
```

```
STEP E2: Verify production health via domain
────────────────────────────────────────────
Command:
  curl -s https://bt38inv.com/health | jq

Expected:
  {"ok": true, "database": "connected", "production": true, "env": "prod"}

Operator confirms: ☐ Health check passes
```

```
STEP E3: Verify TLS certificate
───────────────────────────────
Command:
  echo | openssl s_client -servername bt38inv.com -connect bt38inv.com:443 2>/dev/null | openssl x509 -noout -dates

Expected:
  Valid certificate with future expiry date

Operator confirms: ☐ TLS certificate valid
```

```
STEP E4: Application functionality test
───────────────────────────────────────
Action: Log in to application and verify:
  - Dashboard loads
  - Inventory displays correctly
  - Navigation works

Operator confirms: ☐ Application functional
```

---

## Section 3: Failback Steps (Reverse Cutover)

**Use this procedure to revert to Replit if issues are detected.**

### Failback Phase A: Disable Fly.io Workers

```
FAILBACK A1: Disable Fly.io workers
───────────────────────────────────
Commands:
  flyctl secrets set IS_ACTIVE_PRIMARY=false -a bt38-prod
  flyctl secrets set ENABLE_SYNC_WORKERS=false -a bt38-prod
  flyctl secrets set ENABLE_PUSH_JOBS=false -a bt38-prod
  flyctl secrets set ENABLE_SCHEDULERS=false -a bt38-prod
  flyctl secrets set FAILOVER_ROLE=secondary -a bt38-prod

Wait: 60 seconds

Operator confirms: ☐ Fly.io workers disabled
```

### Failback Phase B: Enable Replit Workers

```
FAILBACK B1: Re-enable Replit workers
─────────────────────────────────────
Action: Set environment variables on Replit:
  IS_ACTIVE_PRIMARY=true
  ENABLE_SYNC_WORKERS=true
  ENABLE_PUSH_JOBS=true
  ENABLE_SCHEDULERS=true

Wait: 30 seconds

Operator confirms: ☐ Replit workers re-enabled
```

### Failback Phase C: DNS Revert

```
FAILBACK C1: Revert DNS - Root record (@)
─────────────────────────────────────────
Command:
  curl -X PATCH "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records/532c13b367d19d03aad33040f5ccd28c" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json" \
    --data '{"type":"A","name":"bt38inv.com","content":"34.111.179.208","ttl":1,"proxied":true}'

Operator confirms: ☐ Root DNS reverted
```

```
FAILBACK C2: Revert DNS - WWW record
────────────────────────────────────
Command:
  curl -X PATCH "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records/3292498f5157098bc36055d1f6e1ef40" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json" \
    --data '{"type":"A","name":"www.bt38inv.com","content":"34.111.179.208","ttl":1,"proxied":true}'

Operator confirms: ☐ WWW DNS reverted
```

```
FAILBACK C3: Verify Replit is serving traffic
─────────────────────────────────────────────
Command:
  curl -s https://bt38inv.com/health | jq

Wait: 60-120 seconds for DNS propagation

Operator confirms: ☐ Replit serving traffic
```

---

## Section 4: Operator Confirmation Phrases

**Each phrase must be typed EXACTLY as shown.**

| Phase | Phrase | Purpose |
|-------|--------|---------|
| Pre-cutover | `PRECONDITIONS_VERIFIED` | Confirm all preconditions are TRUE |
| Phase B | `REPLIT_WORKERS_DISABLED` | Confirm Replit is read-only |
| Phase C | `FLYIO_WORKERS_ENABLED` | Confirm Fly.io is active primary |
| Phase D | `DNS_SWITCH_AUTHORIZED` | Authorize DNS changes |
| Phase E | `CUTOVER_COMPLETE` | Confirm successful cutover |
| Failback | `FAILBACK_AUTHORIZED` | Authorize emergency revert |

---

## Section 5: Post-Cutover Verification Checklist

| # | Check | Command/Action | Expected | Status |
|---|-------|----------------|----------|--------|
| 1 | Production URL loads | `curl https://bt38inv.com` | HTTP 200/302 | ☐ |
| 2 | Health endpoint | `curl https://bt38inv.com/health` | ok=true | ☐ |
| 3 | Database connected | Health shows database=connected | Yes | ☐ |
| 4 | Login works | Manual login test | Success | ☐ |
| 5 | Dashboard loads | Navigate to /dashboard | Renders | ☐ |
| 6 | Inventory visible | Check /warehouse | Data shows | ☐ |
| 7 | Fly.io workers active | Check logs for sync activity | Jobs running | ☐ |
| 8 | Replit workers stopped | Replit health shows workers=off | Confirmed | ☐ |
| 9 | TLS certificate valid | Browser shows secure | Padlock shown | ☐ |
| 10 | No error logs | `flyctl logs -a bt38-prod` | No ERRORs | ☐ |

---

## Section 6: Abort Conditions

**STOP IMMEDIATELY if any of these occur:**

| Condition | Action |
|-----------|--------|
| Database connection fails on Fly.io | DO NOT proceed. Fix database first. |
| Health check returns error | DO NOT proceed. Debug health endpoint. |
| DNS API call fails | STOP. Verify Cloudflare credentials. |
| Both instances have workers enabled | EMERGENCY: Disable one immediately. |
| Application shows errors after switch | Initiate FAILBACK procedure. |
| TLS certificate invalid | Initiate FAILBACK. Check Fly.io certs. |
| Users report data issues | Initiate FAILBACK. Investigate data. |

---

## Section 7: Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Primary Operator | (configured in team) | First responder |
| Infrastructure Lead | (configured in team) | DNS/Fly.io issues |
| Database Admin | (configured in team) | PostgreSQL issues |
| Architect | (configured in team) | Critical decisions |

---

## Section 8: Rollback Decision Matrix

| Symptom | Severity | Action | Max Time |
|---------|----------|--------|----------|
| Minor UI glitch | Low | Monitor, do not rollback | - |
| Slow response times | Medium | Monitor 5 min, then decide | 10 min |
| Database errors | High | Immediate failback | 2 min |
| Data corruption detected | Critical | Immediate failback + page team | 1 min |
| Complete outage | Critical | Immediate failback | 1 min |

---

## Approval

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Architect | | | ☐ Approved |
| Infrastructure Lead | | | ☐ Approved |
| Operations | | | ☐ Approved |

---

**Document Control:**
- Created: 2025-12-16
- Last Updated: 2025-12-16
- Next Review: After first production cutover
