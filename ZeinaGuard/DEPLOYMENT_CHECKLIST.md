# ZeinaGuard Pro - Local Deployment Checklist

Complete this checklist before running `docker-compose up --build`

## Pre-Flight Checks

- [ ] **Docker & Docker Compose Installed**
  ```bash
  docker --version && docker-compose --version
  ```

- [ ] **Ports Available**
  - 3000 (Next.js Frontend)
  - 5000 (Flask Backend)
  - 5432 (PostgreSQL)
  - 6379 (Redis)
  - 5050 (PgAdmin)
  ```bash
  lsof -i :3000 && lsof -i :5000 && lsof -i :5432
  ```

- [ ] **Disk Space Available**
  - Minimum 5GB for images and volumes
  ```bash
  df -h
  ```

## Environment Setup

- [ ] **.env.example Reviewed**
  - All variables present: DATABASE_URL, JWT_SECRET_KEY, etc.
  - Update passwords for production

- [ ] **Database Initialization**
  - `scripts/init-db.sql` is present
  - `scripts/init-timescale.sql` is present (if required)

- [ ] **Docker Files Present**
  - `Dockerfile.flask` (backend)
  - `Dockerfile.nextjs` (frontend)
  - `docker-compose.yml` (orchestration)

## Dependencies Verified

- [ ] **Frontend Dependencies**
  - `package.json` has all required packages:
    - `next@16.1.6`
    - `react@19.2.4`
    - `reactflow@11.10.4`
    - `lucide-react@0.564.0`
    - `date-fns@4.1.0`
    - `sonner@1.7.1`

- [ ] **Backend Dependencies**
  - `backend/requirements.txt` present
  - All Flask extensions included

## Configuration Check

- [ ] **Port Mappings Correct**
  - Flask Backend: `5000:5000`
  - Next.js Frontend: `3000:5000` (note: container port 5000)
  - PostgreSQL: `5432:5432`
  - Redis: `6379:6379`

- [ ] **API URLs Correct**
  - `NEXT_PUBLIC_API_URL=http://localhost:5000`
  - `NEXT_PUBLIC_SOCKET_URL=http://localhost:5000`

- [ ] **Database Credentials**
  - PostgreSQL user: `zeinaguard_user`
  - Default password: `secure_password_change_me` (CHANGE IN PRODUCTION)
  - Database name: `zeinaguard_db`

## Feature Setup

- [ ] **Notification System Ready**
  - `public/AUDIO_README.md` explains sound asset setup
  - Web Audio API will work without audio files
  - Settings page accessible at `/settings`

- [ ] **Network Topology Ready**
  - `backend/topology_mock_data.py` generates mock data
  - `backend/routes_topology.py` provides API endpoints
  - Frontend components in `components/topology/`

- [ ] **Error Handling Implemented**
  - `components/topology/error-boundary.tsx` protects topology
  - Empty state UI for zero sensors
  - Graceful API responses

## Deployment Steps

### 1. Clone Repository
```bash
git clone <repository-url>
cd ZeinaGuard
```

### 2. Build and Start Containers
```bash
docker-compose up --build
```
*First run takes 3-5 minutes to download images and initialize DB*

### 3. Verify Services
```bash
# Check all services running
docker-compose ps

# Watch logs
docker-compose logs -f
```

### 4. Access Services

| Service | URL | Credentials |
|---------|-----|-------------|
| **Frontend** | http://localhost:3000 | N/A |
| **Backend API** | http://localhost:5000/health | N/A |
| **PgAdmin** | http://localhost:5050 | admin@zeinaguard.local / admin_password_change_me |

### 5. Initial Login

Default credentials (change immediately):
- **Username**: `admin`
- **Password**: `admin_password` (or as configured in backend)

## Post-Deployment Validation

- [ ] **Frontend Loads**
  - Navigate to http://localhost:3000
  - Dashboard should display without errors

- [ ] **Backend Connected**
  - Check Network tab in browser DevTools
  - API calls to `/api/dashboard/*` succeed

- [ ] **Notifications Working**
  - Click bell icon in top-right
  - Click "Test Notification"
  - Should see browser notification

- [ ] **Network Map Page**
  - Navigate to `/topology`
  - Loads mock sensor data (or shows "No Sensors Connected")
  - Zoom/pan controls functional

- [ ] **Settings Page**
  - Navigate to `/settings`
  - Sound Alerts section visible
  - Webhook/Email sections present

- [ ] **Database Initialized**
  - PgAdmin accessible at http://localhost:5050
  - zeinaguard_db exists with tables

## Stopping Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (⚠️ DELETES DATA)
docker-compose down -v

# View resource usage
docker stats
```

## Troubleshooting

### Issue: Port Already in Use
```bash
# Find process using port
lsof -i :5000
kill -9 <PID>
```

### Issue: Database Connection Failed
```bash
# Check PostgreSQL logs
docker-compose logs postgres

# Verify connection string in environment
docker-compose exec flask-backend env | grep DATABASE
```

### Issue: Frontend Not Loading
```bash
# Check Next.js build logs
docker-compose logs next-frontend

# Rebuild without cache
docker-compose build --no-cache next-frontend
docker-compose up
```

### Issue: Services Not Starting
```bash
# Full clean rebuild
docker-compose down -v
docker system prune -a
docker-compose up --build
```

## Performance Notes

- **First Build**: 3-5 minutes (downloading images, compiling)
- **Subsequent Starts**: 30-60 seconds
- **Memory Usage**: ~2GB for all services
- **Database Growth**: ~100MB initial, grows with events

## Security Reminders

⚠️ **PRODUCTION CHECKLIST**:
1. [ ] Change all default passwords
2. [ ] Set strong JWT_SECRET_KEY (use `openssl rand -hex 32`)
3. [ ] Enable HTTPS/SSL
4. [ ] Configure firewall rules
5. [ ] Set up backups for PostgreSQL volumes
6. [ ] Enable rate limiting on API
7. [ ] Review CORS configuration
8. [ ] Set up monitoring and logging

## Support

For issues:
1. Check `docker-compose logs <service-name>`
2. Verify `.env.example` values in `docker-compose.yml`
3. Ensure Docker daemon is running
4. Check available disk space
5. Verify firewall/antivirus not blocking ports
