# ZeinaGuard Pro - Deployment Guide

## Overview

ZeinaGuard Pro is a full-stack Wireless Intrusion Prevention System (WIPS) built with:
- **Frontend**: Next.js 16 + React 19 (Vercel)
- **Backend**: Flask + PostgreSQL + TimescaleDB (Railway/Render)
- **Real-time**: Socket.io + Redis (Redis Cloud)

This guide covers production deployment for graduation projects and enterprise deployments.

## Pre-Deployment Checklist

- [ ] All tests passing
- [ ] Environment variables configured
- [ ] Database backups enabled
- [ ] SSL certificates obtained
- [ ] Security headers configured
- [ ] Rate limiting enabled
- [ ] Monitoring and alerting setup
- [ ] Disaster recovery plan documented

## Deployment Architecture

```
┌─────────────────────────────────────────┐
│       Users/Clients                      │
└────────────────┬────────────────────────┘
                 │ HTTPS
    ┌────────────┴────────────┐
    │                         │
┌───▼──────────────┐   ┌─────▼─────────┐
│  Next.js on      │   │  Socket.io    │
│  Vercel          │   │  Connection   │
│  (Frontend)      │   │               │
└───┬──────────────┘   └─────┬─────────┘
    │                        │
    │ HTTPS                  │ WSS
    └───────────┬────────────┘
                │
         ┌──────▼──────────────────┐
         │  Flask Backend           │
         │  (Railway/Render)        │
         │  Port 5000               │
         └──────┬────────┬──────────┘
                │        │
        ┌───────▼─┐  ┌───▼────────────────┐
        │          │  │                    │
   ┌────▼────┐  ┌─▼──▼─────┐  ┌──────────▼──┐
   │PostgreSQL│  │TimescaleDB│  │Redis (Cache)│
   │  (Neon)  │  │ Extension │  │ (Redis Cloud│
   └──────────┘  └───────────┘  └─────────────┘
```

## Step 1: Prepare for Deployment

### 1.1 Create Production Secrets

```bash
# Generate secure JWT secret
openssl rand -hex 32
# Output: abc123def456...

# Generate random database password
openssl rand -base64 32
# Output: abc123def456...
```

### 1.2 Set Environment Variables

Copy `.env.production` to your platform:

**Vercel (Frontend):**
```bash
vercel env add NEXT_PUBLIC_API_URL
# Value: https://api.zeinaguard.com

vercel env add NEXT_PUBLIC_SOCKET_URL
# Value: https://api.zeinaguard.com
```

**Railway/Render (Backend):**
```bash
# Set in platform dashboard or via CLI
export DATABASE_URL=postgresql://...
export JWT_SECRET_KEY=...
export REDIS_URL=redis://...
```

## Step 2: Backend Deployment (Flask + PostgreSQL)

### Option A: Railway.app (Recommended)

**1. Install Railway CLI:**
```bash
npm i -g @railway/cli
railway login
```

**2. Create PostgreSQL Database:**
```bash
railway add
# Select: PostgreSQL
# Confirm creation
```

**3. Enable TimescaleDB Extension:**
```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
```

**4. Deploy Backend:**
```bash
cd backend
railway add
# Select: Python
railway up
```

**5. Configure Environment:**
```bash
railway env set JWT_SECRET_KEY=your_secret_key
railway env set REDIS_URL=redis://...
railway env set DATABASE_URL=postgresql://...
```

### Option B: Render.com

**1. Create Account & Connect GitHub**

**2. Create PostgreSQL Database:**
```
Dashboard → PostgreSQL → Create
- Instance: Standard
- Region: US (East)
- PostgreSQL Version: 15
```

**3. Create Web Service:**
```
Dashboard → New → Web Service
- Repository: your-repo
- Environment: Python
- Start Command: gunicorn --worker-class eventlet -w 1 backend.app:app
```

**4. Add Environment Variables:**
```
DATABASE_URL=<from PostgreSQL service>
JWT_SECRET_KEY=<your-secret>
REDIS_URL=<from external Redis service>
```

**5. Deploy:**
```bash
git push origin main
# Auto-deploys on push
```

### Option C: AWS Lightsail

**1. Create Container:**
```bash
aws lightsail create-container-service \
  --service-name zeinaguard-backend \
  --power micro
```

**2. Create RDS PostgreSQL:**
```bash
aws rds create-db-instance \
  --db-instance-identifier zeinaguard-db \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --master-username admin
```

**3. Enable TimescaleDB:**
```bash
# Connect to RDS instance
psql -U admin -h zeinaguard-db.xxx.rds.amazonaws.com -d postgres
CREATE EXTENSION timescaledb;
```

**4. Deploy Container:**
```bash
aws lightsail create-container-service-deployment \
  --service-name zeinaguard-backend \
  --containers '[{"name":"backend","image":"your-registry/zeinaguard:latest"}]'
```

## Step 3: Frontend Deployment (Next.js)

### Deploy to Vercel (Recommended)

**1. Connect Repository:**
```bash
vercel
# Follow interactive prompts
```

**2. Configure Build Settings:**
```
Framework Preset: Next.js
Build Command: npm run build
Output Directory: .next
```

**3. Set Environment Variables:**
```bash
vercel env add NEXT_PUBLIC_API_URL https://api.zeinaguard.com
```

**4. Deploy:**
```bash
vercel --prod
```

### Custom Domain:

```bash
vercel domains add zeinaguard.com
# Add DNS records as shown
```

## Step 4: Real-Time Services

### Redis Setup (Redis Cloud)

**1. Create Account:** https://redis.com/try-free/

**2. Create Database:**
- Region: US
- Plan: Free tier (25MB)

**3. Copy Connection String:**
```
redis://default:password@host:port
```

**4. Add to Environment:**
```
REDIS_URL=redis://default:password@host:port
```

## Step 5: SSL/TLS Certificates

### Automatic (Recommended):
- **Vercel**: Automatic HTTPS on all deployments
- **Railway**: Automatic SSL certificates
- **Render**: Automatic SSL with Let's Encrypt

### Manual Setup:

```bash
# Install certbot
sudo apt-get install certbot python3-certbot-nginx

# Generate certificate
sudo certbot certonly --standalone -d api.zeinaguard.com

# Renew automatically
sudo systemctl enable certbot.timer
```

## Step 6: Security Hardening

### 1. Enable Firewall Rules

```bash
# UFW (Ubuntu)
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

### 2. Configure CORS

Backend (`app.py`):
```python
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://zeinaguard.com"],
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})
```

### 3. Enable Security Headers

Already configured in `security.py`:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Strict-Transport-Security
- Content-Security-Policy

### 4. Rate Limiting

Backend automatically applies:
- 60 requests/minute per IP
- 1000 requests/hour per IP
- Configurable per endpoint

### 5. Database Backups

**Automated Backups:**

Railway:
```
Settings → Backups → Enable Automatic Backups
```

Render:
```
Dashboard → PostgreSQL → Backups → Enabled
```

## Step 7: Monitoring & Logging

### Application Monitoring

**Option 1: Sentry (Error Tracking)**
```bash
pip install sentry-sdk
```

Backend (`app.py`):
```python
import sentry_sdk
sentry_sdk.init("https://your-key@sentry.io/project-id")
```

**Option 2: DataDog**
```bash
pip install datadog
```

### Log Aggregation

**Vercel (Frontend logs):**
```
Dashboard → Deployments → Logs
```

**Railway/Render (Backend logs):**
```
Dashboard → Logs tab
```

## Step 8: CI/CD Pipeline

### GitHub Actions Workflow

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy ZeinaGuard Pro

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          cd backend
          pip install -r requirements.txt
          pytest tests/

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to Railway
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
        run: |
          npm install -g @railway/cli
          railway up
      
      - name: Deploy to Vercel
        env:
          VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}
        run: |
          npm i -g vercel
          vercel --prod --token $VERCEL_TOKEN
```

## Step 9: Performance Optimization

### Frontend (Next.js):
- Enable static export where possible
- Image optimization with `next/image`
- Code splitting and lazy loading
- CDN distribution via Vercel

### Backend (Flask):
- Database connection pooling
- Redis caching for frequent queries
- Query optimization with indices
- Gzip compression

```python
# Backend optimization
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 20,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
}
```

## Step 10: Backup & Disaster Recovery

### Database Backups:

```bash
# Manual PostgreSQL backup
pg_dump postgresql://user:pass@host:port/db > backup.sql

# Restore from backup
psql postgresql://user:pass@host:port/db < backup.sql
```

### Configuration Backups:

```bash
# Backup environment variables
vercel env pull .env.production.local
git add .env.production.local
git commit -m "Backup environment"
```

## Troubleshooting

### 502 Bad Gateway
```bash
# Check backend service
railway status
# or
render logs backend
```

### WebSocket Connection Failed
```bash
# Verify Socket.io configuration
# Check CORS settings
# Verify Redis connection
redis-cli ping
```

### Database Connection Issues
```bash
# Test connection
psql $DATABASE_URL
# Check TimescaleDB extension
\dx
```

## Production Checklist

- [ ] SSL certificates installed and valid
- [ ] Environment variables configured securely
- [ ] Database backups enabled
- [ ] Monitoring and alerting active
- [ ] Rate limiting enabled
- [ ] Security headers configured
- [ ] CORS properly configured
- [ ] Logging aggregation working
- [ ] Database indices optimized
- [ ] CI/CD pipeline working
- [ ] Health checks configured
- [ ] Incident response plan documented

## Support & Resources

- **Railway Docs**: https://docs.railway.app
- **Render Docs**: https://render.com/docs
- **Vercel Docs**: https://vercel.com/docs
- **Flask-SQLAlchemy**: https://flask-sqlalchemy.palletsprojects.com
- **Socket.io**: https://socket.io/docs/

## Post-Deployment

After deployment, test all features:

1. **Login**: admin/admin123
2. **Dashboard**: Check metrics loading
3. **Threats**: Simulate threat and verify real-time update
4. **Sensors**: Check sensor status
5. **Command Palette**: Press Cmd+K and test commands

---

**Version**: 1.0.0
**Last Updated**: 2026-03-03
