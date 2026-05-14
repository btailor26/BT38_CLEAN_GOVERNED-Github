# BT38 Inventory System - Deployment Guide

This guide explains how to deploy BT38 on any Docker-capable host (Ubuntu, AWS, GCP, etc.).

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- 2GB RAM minimum
- 10GB disk space

## Quick Start

### 1. Install Docker (Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER
# Log out and back in for group changes
```

### 2. Clone Repository

```bash
git clone <your-repo-url> bt38
cd bt38
```

### 3. Configure Environment

```bash
cp .env.example .env
nano .env  # Fill in required values
```

**Required variables:**
- `SESSION_SECRET` - Random string for Flask sessions
- `DATABASE_URL` - Uses local PostgreSQL by default

**Optional (for marketplace integrations):**
- `AMAZON_*` - Amazon SP-API credentials
- `SENDGRID_*` - Email notifications
- `TWILIO_*` - SMS/WhatsApp notifications

### 4. Create Persistence Directories

```bash
mkdir -p instance logs
```

### 5. Build and Start

```bash
docker compose up -d --build
```

### 6. Verify Deployment

```bash
# Health check
curl http://localhost:5000/health

# System fingerprint
curl http://localhost:5000/api/system/fingerprint

# Sentinel status (if enabled)
curl http://localhost:5000/api/sentinel/status
```

## File Locations

| Path | Purpose |
|------|---------|
| `instance/` | Sentinel control files, workspace data, knowledge vault |
| `logs/` | Application logs |
| `static/uploads/` | User uploaded files (Docker volume) |

## Common Operations

### View Logs

```bash
docker compose logs -f app
```

### Restart Application

```bash
docker compose restart app
```

### Stop Everything

```bash
docker compose down
```

### Stop and Remove Volumes (CAUTION: Data Loss)

```bash
docker compose down -v
```

### Upgrade to New Version

```bash
git pull
docker compose up -d --build
```

## Persistence Verification

Sentinel control switches are persisted in `instance/sentinel_control.json`.

To verify persistence:

```bash
# 1. Toggle a switch via API or UI
curl -X POST http://localhost:5000/api/sentinel/toggle/scope_lock -H "Content-Type: application/json"

# 2. Check current state
curl http://localhost:5000/api/sentinel/status | jq '.switches'

# 3. Restart container
docker compose restart app

# 4. Verify switch persisted
curl http://localhost:5000/api/sentinel/status | jq '.switches'
```

## Troubleshooting

### Container won't start

```bash
docker compose logs app
```

### Database connection issues

```bash
docker compose logs db
docker compose exec db pg_isready -U bt38
```

### Reset database (CAUTION: Data Loss)

```bash
docker compose down -v
docker compose up -d --build
```

## Security Notes

1. **Change `SESSION_SECRET`** - Never use the example value in production
2. **Firewall** - Only expose port 5000 if needed externally
3. **Secrets** - Never commit `.env` to version control
4. **SSL** - Use a reverse proxy (nginx, Traefik) for HTTPS in production

## Architecture

```
┌─────────────────────────────────────────┐
│              Docker Host                │
│                                         │
│  ┌─────────────┐    ┌─────────────┐    │
│  │   BT38 App  │────│  PostgreSQL │    │
│  │   :5000     │    │   :5432     │    │
│  └─────────────┘    └─────────────┘    │
│         │                   │          │
│         ▼                   ▼          │
│   ./instance/         pgdata volume    │
│   ./logs/             (persistent)     │
│   uploads volume                       │
└─────────────────────────────────────────┘
```
