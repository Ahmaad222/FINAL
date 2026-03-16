# ZeinaGuard Pro - Docker Setup Guide

## Quick Start

### Prerequisites
- Docker Desktop installed and running
- Docker Compose (comes with Docker Desktop)
- 4GB RAM allocated to Docker (minimum)

### Step 1: Configure Environment Variables

Before starting the containers, update the `.env.docker` file with secure passwords:

```bash
# Edit these critical values in .env.docker:
POSTGRES_PASSWORD=your_secure_password_here
REDIS_PASSWORD=your_redis_password_here
JWT_SECRET_KEY=your_jwt_secret_min_32_chars_long
PGADMIN_DEFAULT_PASSWORD=your_pgadmin_password
```

### Step 2: Build and Start Services

```bash
# Build and start all services in the background
docker-compose up -d

# Or, start with logs visible for debugging
docker-compose up
```

### Step 3: Verify Services

Wait 30-60 seconds for all services to start, then verify:

```bash
# Check service status
docker-compose ps

# View logs for specific service
docker-compose logs flask-backend
docker-compose logs next-frontend
docker-compose logs postgres
docker-compose logs redis
```

## Access Points

Once running, access these services:

| Service | URL | Credentials |
|---------|-----|-------------|
| Next.js Dashboard | http://localhost:3000 | - |
| Flask API | http://localhost:5000 | - |
| Flask Health Check | http://localhost:5000/health | - |
| PgAdmin (Database GUI) | http://localhost:5050 | admin@zeinaguard.local / admin_password_change_me |
| PostgreSQL | localhost:5432 | zeinaguard_user / secure_password_change_me |
| Redis CLI | localhost:6379 | (requires redis_password_change_me) |

## Service Details

### PostgreSQL + TimescaleDB (Port 5432)
- **Database:** zeinaguard_db
- **User:** zeinaguard_user
- **Password:** secure_password_change_me (CHANGE THIS)
- **Features:**
  - TimescaleDB extension for time-series data
  - Automatic hypertables for threat_events and sensor_health
  - Continuous aggregates for fast analytics
  - Data compression for data > 7 days
  - Automatic retention policies (90 days)

### Redis (Port 6379)
- **Purpose:** Message queue for threat events, caching, session storage
- **Password:** redis_password_change_me (CHANGE THIS)
- **Data:** Persisted in `redis_data` volume

### Flask Backend (Port 5000)
- **Environment:** Development mode with auto-reload
- **Features:**
  - JWT authentication
  - WebSocket support (Socket.io)
  - Packet analysis (Scapy integration)
  - REST API endpoints
- **Volume:** Maps `./backend` to `/app` for hot-reload

### Next.js Frontend (Port 3000)
- **Environment:** Development mode with hot-reload
- **Features:**
  - React 19.2.4
  - Tailwind CSS 4
  - Recharts for analytics
  - Socket.io for real-time updates
- **Volume:** Maps entire project for hot-reload

### PgAdmin (Port 5050)
- **Purpose:** Web interface for PostgreSQL administration
- **Default Email:** admin@zeinaguard.local
- **Default Password:** admin_password_change_me (CHANGE THIS)
- **Note:** Development only, remove from docker-compose.yml in production

## Database Schema

The database is automatically initialized with:

1. **User Management Tables:**
   - users, roles, permissions, user_roles, role_permissions

2. **Sensor Management:**
   - sensors (physical/virtual WIPS sensors)
   - sensor_health (time-series hypertable for monitoring)

3. **Threat Detection (Time-Series):**
   - threats (threat records)
   - threat_events (time-series hypertable for detailed events)

4. **Alert & Incident Management:**
   - alert_rules, alerts
   - incidents, incident_events

5. **Additional:**
   - network_topology, reports, audit_logs, blocked_devices

## Common Commands

```bash
# Stop all services
docker-compose down

# Stop services but keep volumes (preserve data)
docker-compose down -v

# View logs for all services
docker-compose logs -f

# View logs for specific service
docker-compose logs -f flask-backend

# Execute command in running container
docker-compose exec postgres psql -U zeinaguard_user -d zeinaguard_db

# Rebuild services after code changes
docker-compose up -d --build

# Remove all data and start fresh
docker-compose down -v
docker-compose up -d
```

## Testing Services

### Test Flask API
```bash
curl http://localhost:5000/health
```

Response:
```json
{"status": "healthy", "service": "zeinaguard-backend"}
```

### Test PostgreSQL Connection
```bash
docker-compose exec postgres psql -U zeinaguard_user -d zeinaguard_db -c "SELECT version();"
```

### Test Redis Connection
```bash
docker-compose exec redis redis-cli -a redis_password_change_me ping
```

## Troubleshooting

### Services Won't Start
```bash
# Check logs
docker-compose logs

# Verify Docker resources
docker system df

# Restart Docker daemon and try again
docker-compose down
docker-compose up -d
```

### Database Connection Failed
```bash
# Wait longer for PostgreSQL to start (it can take 30-60s)
docker-compose logs postgres

# Check if postgres service is healthy
docker-compose ps
# Status should show "healthy" for postgres
```

### Redis Connection Issues
```bash
# Test Redis directly
docker-compose exec redis redis-cli -a redis_password_change_me ping
```

### Port Already in Use
If ports 3000, 5000, 5432, 6379, or 5050 are already in use:
```bash
# Edit docker-compose.yml and change the port mappings
# For example: "3001:3000" instead of "3000:3000"
```

## Production Deployment

For production deployment:

1. Update all passwords in `.env.docker`
2. Set `FLASK_ENV=production`
3. Set `FLASK_DEBUG=0`
4. Remove PgAdmin service
5. Use external managed database (AWS RDS, Google Cloud SQL, etc.)
6. Use external Redis (Redis Cloud, AWS ElastiCache, etc.)
7. Deploy to Vercel (frontend), Railway/Render (backend)

## Next Steps

1. **Phase 1:** Implement JWT authentication between Flask and Next.js
2. **Phase 2:** Set up WebSocket real-time threat feed
3. **Phase 3:** Build the Dashboard UI in Next.js
4. **Phase 4:** Implement threat detection engine in Flask
5. **Phase 5:** Add reporting and analytics

See the main project plan for detailed implementation roadmap.
