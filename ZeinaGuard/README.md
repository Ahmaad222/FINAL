```
 _   _           _           ____                 _                                  _   
| | | |_ __   __| | ___ _ __|  _ \  _____   _____| | ___  _ __  _ __ ___   ___ _ __ | |_ 
| | | | '_ \ / _` |/ _ \ '__| | | |/ _ \ \ / / _ \ |/ _ \| '_ \| '_ ` _ \ / _ \ '_ \| __|
| |_| | | | | (_| |  __/ |  | |_| |  __/\ V /  __/ | (_) | |_) | | | | | |  __/ | | | |_ 
 \___/|_| |_|\__,_|\___|_|  |____/ \___| \_/ \___|_|\___/| .__/|_| |_| |_|\___|_| |_|\__|
                                                         |_|                               
```
![](https://github.com/Ln0rag/ZeinaGuard/blob/main/screenshot.png)

# ZeinaGuard- Enterprise Wireless Intrusion Prevention System

A comprehensive enterprise-grade **Wireless Intrusion Prevention System (WIPS)** for real-time wireless network monitoring, threat detection, and prevention.

## Overview

ZeinaGuard Pro combines a modern web dashboard with a Flask backend API for comprehensive network security. It detects rogue access points, unauthorized devices, and network anomalies with sub-second latency.

### Key Features

- **Real-time Network Monitoring** – Live packet capture and analysis
- **Threat Detection** – Intrusion detection algorithms
- **WebSocket Communication** – Real-time updates via Socket.IO
- **Enterprise Dashboard** – Metrics, gauges, charts, and feeds
- **Role-based Access Control (RBAC)** – Multi-user support
- **Time-series Storage** – TimescaleDB for threat event history
- **Message Queue** – Redis for async processing and WebSocket pub/sub

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS, Radix UI, Recharts, Socket.IO client |
| **Backend** | Flask, SQLAlchemy, JWT, Flask-SocketIO |
| **Database** | PostgreSQL 16 + TimescaleDB |
| **Cache** | Redis 7 |
| **DevOps** | Docker Compose |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Node.js 20+ and pnpm (for local development)
- Python 3.11+ (for local backend development)

### Option 1: Docker (Recommended)

```bash
# Clone and enter project
git clone https://github.com/Ln0rag/ZeinaGuard.git
cd ZeinaGuard
chmod +x ./scripts/start-docker.sh
./scripts/start-docker.sh

# Stop
docker-compose down
docker-compose stop
```

### Option 2: Manual Start

```bash
docker compose up -d
# Or: docker-compose up -d
```

### Default Credentials (PgAdmin / DB only)

| Service | Username | Password |
|---------|----------|----------|
| **PgAdmin** | admin@zeinaguard.local | admin_password_change_me |
| **PostgreSQL** | zeinaguard_user | secure_password_change_me |

The dashboard opens directly with no sign-in required.

---

## Service URLs

| Service | URL | Purpose |
|---------|-----|---------|
| **Dashboard** | http://localhost:3000 | Web UI |
| **API & WebSocket** | http://localhost:5000 | REST API and Socket.IO |
| **PgAdmin** | http://localhost:5050 | Database management |
| **PostgreSQL** | localhost:5432 | Database |
| **Redis** | localhost:6379 | Cache / message queue |

---

## Project Structure

```
ZeinaGuard/
├── app/                    # Next.js App Router
│   ├── dashboard/          # Main dashboard
│   ├── threats/            # Threat feed + simulator
│   ├── sensors/            # Sensor management
│   ├── alerts/             # Alert configuration
│   └── incidents/          # Incident response
├── components/             # React components
├── hooks/                  # use-socket, use-auth, etc.
├── lib/                    # API client, utils
├── backend/                # Flask application
│   ├── app.py              # Main app + Socket.IO
│   ├── auth.py             # JWT authentication
│   ├── models.py           # SQLAlchemy models
│   ├── routes.py           # API blueprints
│   └── websocket_server.py # Socket.IO handlers
├── scripts/
│   ├── start-docker.sh     # Docker startup script
│   ├── init-db.sql         # Schema
│   └── init-timescale.sql  # TimescaleDB setup
├── docker-compose.yml
├── Dockerfile.flask
└── Dockerfile.nextjs
```

---

## Local Development

### Frontend

```bash
pnpm install
pnpm run dev
# http://localhost:5000 (Next.js dev port)
```

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
# Set FLASK_PORT=5000, DATABASE_URL, REDIS_URL in .env
flask run
# Or: python app.py
```

---

## Configuration

Copy `.env.example` to `.env` and adjust:

```env
# Frontend (API and Socket.IO share port 5000)
NEXT_PUBLIC_API_URL=http://localhost:5000
NEXT_PUBLIC_SOCKET_URL=http://localhost:5000

# Backend
FLASK_PORT=5000
DATABASE_URL=postgresql://zeinaguard_user:secure_password_change_me@localhost:5432/zeinaguard_db
REDIS_URL=redis://:redis_password_change_me@localhost:6379/0
JWT_SECRET_KEY=your_jwt_secret_key_change_me
```

---

## Docker Commands

```bash
# Start
docker compose up -d

# Logs
docker compose logs -f

# Stop
docker compose down

# Stop and remove volumes
docker compose down -v

# Rebuild
docker compose build --no-cache
```

---

## API Overview

- **Threats**: `GET /api/threats`, `POST /api/threats/{id}/block`, `POST /api/threats/demo/simulate-threat`
- **Sensors**: `GET /api/sensors`
- **Alerts**: `GET /api/alerts`, `POST /api/alerts/{id}/acknowledge`
- **Dashboard**: `GET /api/dashboard/overview`, `/threat-timeline`, `/sensor-health`
- **Health**: `GET /health`, `GET /api/status`

Use JWT in `Authorization: Bearer <token>` header for protected routes.

---

## Testing Lifecycle

### 1. Start services
```bash
./scripts/start-docker.sh
```

### 2. E2E health check
```bash
./scripts/test-e2e.sh
```

### 3. Manual checklist
- [ ] Home redirects to `/dashboard`
- [ ] Dashboard loads
- [ ] Navigate to Incidents, Sensors, Alerts, Threats
- [ ] WebSocket: simulate threat on `/threats` and verify real-time update

### 4. API smoke test
```bash
curl -s http://localhost:5000/health
curl -s http://localhost:5000/api/dashboard/overview
```

---

## Troubleshooting

### Port already in use

Change ports in `docker-compose.yml` or stop conflicting services.

### Database connection refused

Ensure PostgreSQL is healthy: `docker compose ps`. Reset with `docker compose down -v && docker compose up -d`.

### WebSocket not connecting

Verify `NEXT_PUBLIC_SOCKET_URL` points to the API URL (same port as REST). Check backend logs: `docker compose logs -f flask-backend`.

### Frontend build errors

```bash
docker compose build --no-cache next-frontend
```

---

## System Resilience

ZeinaGuard Pro is designed to remain operational even when components fail or go offline.

### Sensor Disconnection Handling

**Scenario**: Raspberry Pi sensors go offline or lose connectivity.

**Frontend Behavior**:
- **Network Map Empty State**: Displays a professional "No Sensors Connected" UI with:
  - Wifi-off icon and descriptive message
  - "Retry Connection" button for manual refresh
  - "Toggle Mock Data" button for testing
  - Sensor status indicators (all showing offline)
- **No Graph Crash**: ReactFlow graph is never rendered with empty data; instead, the empty state UI takes over
- **Error Recovery**: If an error occurs, displays error boundary fallback with reload option

**Backend Behavior**:
- **Graceful Empty Response**: `/api/topology` endpoint returns HTTP 200 with empty structure:
  ```json
  {
    "nodes": [],
    "edges": [],
    "metadata": { "total_nodes": 0, ... }
  }
  ```
- **No 500 Errors**: All exceptions are caught and converted to graceful responses
- **Resilience Message**: User sees "No active sensors detected. Please ensure your Raspberry Pi units are online."

### Error Boundary Protection

The Topology page is wrapped in a React Error Boundary that catches any unexpected rendering errors:
- **Error State**: Shows centered error UI with:
  - Alert icon and "Something went wrong" message
  - Error details in monospace font
  - "Reload Page" button for recovery
- **Dashboard Stability**: Error in topology doesn't crash entire dashboard
- **User Feedback**: Toast notifications inform users of state changes

### Testing Resilience

To verify offline/zero-sensor handling:

1. **Mock Data Toggle**:
   - In the Network Map, top-right controls show "Mock Data" button
   - Toggle between mock data (simulated sensors) and real data (actual backend)
   - Useful for testing without live sensors

2. **Inspect Empty State**:
   - When no sensors are available, click "Retry Connection" to test refresh behavior
   - Observe sensor status list showing all offline

3. **Error Simulation**:
   - Network Map displays gracefully when API is unavailable
   - Empty state shows helpful guidance message

### Monitoring Offline States

**Dashboard Integration**:
- Sensor count on dashboard home page reflects online sensors
- Topology shows visual indicator when sensors are offline
- Alerts tab notifies when sensors disconnect

**Alerts Generated**:
- Sensor offline alerts appear when connection is lost
- Topology update failures logged for debugging

### Recovery Procedures

**If Sensors Go Offline**:
1. Check Raspberry Pi power and network connectivity
2. Restart sensors from Settings tab
3. Click "Retry Connection" on Network Map
4. Check System Logs for detailed error information

**If Dashboard Topology Crashes**:
1. Browser reload button will recover from error boundary
2. Check browser console for error details (F12 Developer Tools)
3. Verify backend API is responding: `curl http://localhost:8000/api/topology`

### Production Considerations

- Always deploy topology mock data as fallback
- Monitor sensor connectivity health metrics
- Set up alerts for sensor disconnection events
- Regular testing of failover and recovery procedures
- Keep logs of topology state changes for audit trail

---

## Alerting & Notifications User Guide

ZeinaGuard Pro includes a comprehensive notification system to keep you informed of threats, sensor status changes, and system updates.

### Accessing Notifications

**Bell Icon**: Located in the top-right corner of the navbar
- Shows unread notification count (red badge)
- Click to open notification panel
- Displays last 20 notifications with timestamps

### Notification Types

| Type | Color | Sound | Examples |
|------|-------|-------|----------|
| **Info** | Blue | Subtle ping (800Hz) | System updates, routine events |
| **Warning** | Yellow | Same as info | High threat detected, performance issue |
| **Critical** | Red | Urgent siren (1000-1200Hz) | Sensor offline, Rogue AP detected |

### Sound Alerts Configuration

1. **Enable/Disable Sounds**:
   - Go to **Settings** → **Sound Alerts**
   - Toggle "Sound Alerts" switch to enable/disable all sounds
   - Mute state persists across sessions

2. **Test Sounds**:
   - **Test Ping**: Plays info/warning alert tone
   - **Test Siren**: Plays critical alert tone
   - Test buttons disabled when sounds are muted

3. **Browser Requirements**:
   - Requires user permission for browser notifications
   - Allow notifications when prompted
   - Some browsers may restrict audio to user interaction

### Webhook Integration (Slack/Discord)

1. **Configure Webhook**:
   - Go to **Settings** → **Webhook Integration**
   - Paste your Slack/Discord webhook URL
   - Click **Save Webhook**
   - Click **Test Connection** to verify

2. **Example Webhook URLs**:
   - **Slack**: `https://hooks.slack.com/services/YOUR/WEBHOOK/URL`
   - **Discord**: `https://discordapp.com/api/webhooks/YOUR/WEBHOOK`

3. **What Gets Sent**:
   - Notification title and message
   - Alert type and severity
   - Timestamp
   - Sensor/threat details (if applicable)

### Email Alerts Configuration

1. **Configure Email**:
   - Go to **Settings** → **Email Alerts**
   - Enter your email address
   - Click **Save Email**
   - Click **Send Test Email** to verify

2. **When Emails Are Sent**:
   - Critical sensor offline alerts
   - Rogue AP/deauth attack detections
   - System failure notifications
   - User-triggered test emails

3. **Email Settings** (localStorage):
   - Email address saved locally in browser
   - Persists across sessions
   - Not stored on server (for privacy)

### Managing Notifications

**In Notification Panel**:
- **Mark as Read**: Click notification to mark read
- **Mark All Read**: Button in dropdown footer
- **Delete Single**: Click X on any notification
- **Clear All**: Clear all notifications at once
- **Test Notification**: Verify UI + browser API working

### Automatic Triggers

Notifications are automatically triggered by:

- **Sensor Status Changes**
  - Sensor goes offline → Critical alert
  - Sensor comes online → Info alert

- **Threat Detection**
  - Rogue AP detected → Critical alert
  - De-authentication attack → Critical alert
  - High-severity threat → Warning alert

- **System Events**
  - Backend restart → Info alert
  - Update available → Info alert
  - Configuration changes → Info alert

### Best Practices

1. **Enable Sound Alerts**: Critical alerts deserve immediate attention
2. **Configure Webhooks**: Send alerts to your team's Slack/Discord
3. **Set Email Alerts**: Backup notification channel for critical events
4. **Review Notifications**: Check the notification panel regularly
5. **Test Regularly**: Use test buttons to ensure configuration works

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Sounds not playing | Check if muted, enable in Settings, browser may block audio |
| Webhook not working | Verify URL format, test connection, check logs |
| Notifications not appearing | Refresh page, check browser notification permission |
| Email not received | Verify email address, check spam folder |
| Badge count stuck | Click "Mark All Read" to reset |

### Mobile/Tablet Support

- Notification panel works on mobile devices
- Sounds play with appropriate permissions
- Webhooks/email work the same way
- Test connectivity before relying in production

---

## Production Deployment

Before production:

- [ ] Change all default passwords
- [ ] Set a strong `JWT_SECRET_KEY`
- [ ] Enable HTTPS/SSL
- [ ] Configure CORS properly
- [ ] Enable rate limiting
- [ ] Set up monitoring and backups
- [ ] Test sensor offline scenarios
- [ ] Configure sensor reconnection timeout thresholds
- [ ] Set up alerts for topology state changes

---

## Security Notes

Default credentials are for **development only**. Do not use them in production.

---

## License

Proprietary. All rights reserved.
