# BT38 Production DNS Plan

**Version:** 1.0  
**Date:** 2025-12-16  
**Status:** DRAFT - Requires Architect Approval

---

## 1. Current DNS State

### Records to be Modified

| Record | Type | Current Value | Proxied | TTL | Record ID |
|--------|------|---------------|---------|-----|-----------|
| `bt38inv.com` (root/@) | A | `34.111.179.208` | ON | Auto | `532c13b367d19d03aad33040f5ccd28c` |
| `www.bt38inv.com` | A | `34.111.179.208` | ON | Auto | `3292498f5157098bc36055d1f6e1ef40` |

### Records NOT to be Modified

| Record | Type | Current Value | Proxied | Purpose |
|--------|------|---------------|---------|---------|
| `staging.bt38inv.com` | CNAME | `bt38-staging.fly.dev` | OFF | Staging environment |
| `bt38inv.com` | MX | eforward*.registrar-servers.com | - | Email forwarding |
| `bt38inv.com` | TXT | SPF record | - | Email authentication |
| `bt38inv.com` | TXT | Replit verification | - | Domain verification |
| `bt38inv.com` | NS | registrar-servers.com | - | Nameservers |

---

## 2. Target DNS State (After Cutover)

### Production Records

| Record | Type | Target Value | Proxied | TTL |
|--------|------|--------------|---------|-----|
| `bt38inv.com` (root/@) | CNAME | `bt38-prod.fly.dev` | OFF | 60s |
| `www.bt38inv.com` | CNAME | `bt38-prod.fly.dev` | OFF | 60s |

---

## 3. Proxy Mode Recommendation

### Recommendation: **Proxied = OFF (DNS-Only)**

**Rationale:**

1. **TLS Termination**: Fly.io handles TLS termination natively with auto-renewing Let's Encrypt certificates. Cloudflare proxy would add an extra TLS hop.

2. **Connection Optimization**: Fly.io's Anycast network provides global edge connectivity. Cloudflare proxy would route through Cloudflare's network first, potentially adding latency.

3. **WebSocket Support**: Direct connection to Fly.io ensures WebSocket connections work without Cloudflare's WebSocket limitations on certain plans.

4. **Simplified Debugging**: Direct traffic makes it easier to diagnose issues without Cloudflare's interception.

5. **Consistency with Staging**: Staging uses `proxied=false` and works correctly.

### Alternative: Proxied = ON

If Cloudflare proxy is required (e.g., for DDoS protection or WAF), ensure:
- Fly.io SSL mode is set to "Full (Strict)"
- Cloudflare's caching rules don't interfere with dynamic content
- WebSocket paths are explicitly allowed

---

## 4. DNS Change Procedure

### Step 1: Switch Root Record (@)

```bash
# Switch bt38inv.com from A record to CNAME
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/532c13b367d19d03aad33040f5ccd28c" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{
    "type": "CNAME",
    "name": "bt38inv.com",
    "content": "bt38-prod.fly.dev",
    "ttl": 60,
    "proxied": false
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "result": {
    "id": "532c13b367d19d03aad33040f5ccd28c",
    "type": "CNAME",
    "name": "bt38inv.com",
    "content": "bt38-prod.fly.dev",
    "proxied": false,
    "ttl": 60
  }
}
```

### Step 2: Switch WWW Record

```bash
# Switch www.bt38inv.com from A record to CNAME
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/3292498f5157098bc36055d1f6e1ef40" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{
    "type": "CNAME",
    "name": "www.bt38inv.com",
    "content": "bt38-prod.fly.dev",
    "ttl": 60,
    "proxied": false
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "result": {
    "id": "3292498f5157098bc36055d1f6e1ef40",
    "type": "CNAME",
    "name": "www.bt38inv.com",
    "content": "bt38-prod.fly.dev",
    "proxied": false,
    "ttl": 60
  }
}
```

---

## 5. DNS Revert Procedure (Failback)

### Step 1: Revert Root Record (@)

```bash
# Revert bt38inv.com back to A record pointing to Replit
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/532c13b367d19d03aad33040f5ccd28c" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{
    "type": "A",
    "name": "bt38inv.com",
    "content": "34.111.179.208",
    "ttl": 1,
    "proxied": true
  }'
```

### Step 2: Revert WWW Record

```bash
# Revert www.bt38inv.com back to A record pointing to Replit
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/3292498f5157098bc36055d1f6e1ef40" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{
    "type": "A",
    "name": "www.bt38inv.com",
    "content": "34.111.179.208",
    "ttl": 1,
    "proxied": true
  }'
```

---

## 6. Verification Commands

### Verify DNS Resolution

```bash
# Check root domain
dig bt38inv.com +short
dig bt38inv.com CNAME +short

# Check www
dig www.bt38inv.com +short
dig www.bt38inv.com CNAME +short

# Check staging (should remain unchanged)
dig staging.bt38inv.com CNAME +short
```

### Verify via Cloudflare API

```bash
# Fetch all DNS records
curl -s "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" | \
  jq '.result[] | select(.type == "A" or .type == "CNAME") | {name, type, content, proxied}'
```

---

## 7. TLS Certificate Requirements

### Fly.io Production App Certificate

Before DNS switch, ensure Fly.io has certificates for:
- `bt38inv.com`
- `www.bt38inv.com`

```bash
# Add certificates to production app
flyctl certs add bt38inv.com -a bt38-prod
flyctl certs add www.bt38inv.com -a bt38-prod

# Verify certificate status
flyctl certs show bt38inv.com -a bt38-prod
flyctl certs show www.bt38inv.com -a bt38-prod
```

**Note:** Certificate issuance requires DNS to point to Fly.io OR a DNS challenge. For zero-downtime cutover, add certificates BEFORE switching DNS using the ACME DNS challenge option.

---

## 8. Timing Considerations

| Phase | Duration | Notes |
|-------|----------|-------|
| DNS API call | <1 second | Instant at Cloudflare edge |
| Cloudflare propagation | 0-30 seconds | Usually instant with proxied=false |
| Global DNS propagation | 1-5 minutes | Depends on client TTL caching |
| Full propagation | Up to 60 minutes | Conservative estimate |

**Recommendation:** Wait 90 seconds between DNS switch and verification to allow most clients to see the change.

---

## 9. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| DNS API failure | Low | High | Verify credentials before cutover |
| Certificate not ready | Medium | High | Pre-issue certificates 24h before |
| Slow propagation | Medium | Low | Use low TTL (60s) |
| Cached DNS on clients | Medium | Low | Wait for TTL expiry |
| Wrong record ID | Low | Critical | Verify IDs in dry-run |

---

## 10. Approval

| Role | Approved | Date |
|------|----------|------|
| Architect | ☐ | |
| Infrastructure Lead | ☐ | |

---

**Document Control:**
- Created: 2025-12-16
- Cloudflare Zone: bt38inv.com
- Record IDs verified: 2025-12-16
