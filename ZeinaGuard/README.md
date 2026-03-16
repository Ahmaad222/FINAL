```
 _   _           _           ____                 _                                  _   
| | | |_ __   __| | ___ _ __|  _ \  _____   _____| | ___  _ __  _ __ ___   ___ _ __ | |_ 
| | | | '_ \ / _` |/ _ \ '__| | | |/ _ \ \ / / _ \ |/ _ \| '_ \| '_ ` _ \ / _ \ '_ \| __|
| |_| | | | | (_| |  __/ |  | |_| |  __/\ V /  __/ | (_) | |_) | | | | | |  __/ | | | |_ 
 \___/|_| |_|\__,_|\___|_|  |____/ \___| \_/ \___|_|\___/| .__/|_| |_| |_|\___|_| |_|\__|
                                                         |_|                               
```
# ZeinaGuard Pro - Enterprise Wireless Intrusion Prevention System (WIPS)

A modern, production-ready Wireless Intrusion Prevention System (WIPS) built with cutting-edge technology for detecting, analyzing, and mitigating wireless network threats in real-time.

## Features

### Real-Time Threat Detection
- Live threat feed with < 500ms latency
- Multiple threat types: Rogue APs, Evil Twins, Deauth Attacks, Signal Jamming
- Automatic severity classification (Critical, High, Medium, Low, Info)
- Real-time WebSocket updates to dashboard

### Advanced Sensor Management
- Deploy and manage multiple wireless sensors
- Heartbeat monitoring with signal strength visualization
- Automatic sensor health tracking and alerts
- Network topology discovery and mapping

### Enterprise Analytics
- Historical threat trend analysis with TimescaleDB
- Time-series data compression and retention policies
- Continuous aggregates for fast dashboard queries
- Custom report generation (Daily, Weekly, Monthly)

### Security & Compliance
- JWT-based authentication with role-based access control (RBAC)
- Audit logging for all system actions
- Incident response workflow management
- Compliance reporting features

### Modern User Interface
- Real-time dashboard with metric cards and charts
- Dark mode cybersecurity command center aesthetic
- Command Palette (CTRL+K) for quick actions
- Responsive design with Tailwind CSS

## Tech Stack

### Frontend
- **Next.js 16.1.6** - React framework with server-side rendering
- **React 19.2.4** - UI library
- **Tailwind CSS 4.2** - Utility-first CSS framework
- **Recharts 2.15** - React charting library
- **Socket.io Client** - Real-time WebSocket communication
- **shadcn/ui** - Accessible component library

### Backend
- **Flask 3.0** - Lightweight Python web framework
- **PostgreSQL + TimescaleDB** - Time-series optimized database
- **Redis 7** - Message queue and caching
- **Scapy** - Packet analysis library
- **PyShark** - Network packet analysis
- **Flask-JWT-Extended** - JWT authentication

### Infrastructure
- **Docker & Docker Compose** - Containerization
- **Vercel** - Frontend deployment (production)
- **Railway/Render** - Backend deployment (production)
- **Neon PostgreSQL** - Managed database (production)

## Quick Start

### Prerequisites
- Docker Desktop (recommended for local development)
- Or: Python 3.11+, Node.js 20+, PostgreSQL 16+, Redis 7+

### Option 1: Docker (Recommended)
```bash
git clone https://github.com/Ln0rag/ZeinaGuard.git
cd ZeinaGuard/
chmod +x ./scripts/start-docker.sh
./scripts/start-docker.sh

# Services will be available at:
# - Dashboard: http://localhost:3000
# - API: http://localhost:5000
# - PgAdmin: http://localhost:5050

# For exiting docker:
docker-compose down
docker-compose stop
```

### Option 2: Local Development
```bash
# Backend setup
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
export FLASK_APP=app.py
flask run

# Frontend setup (new terminal)
npm install
npm run dev
```

## Project Structure

```
zeinaguard-pro/
├── app/                    # Next.js app directory
│   ├── layout.tsx         # Root layout
│   ├── page.tsx           # Home page
│   └── api/               # API routes
├── components/            # Reusable React components
│   ├── dashboard/         # Dashboard components
│   ├── threats/           # Threat management UI
│   └── ui/                # shadcn/ui components
├── backend/               # Flask backend
│   ├── app.py            # Flask application entry point
│   ├── requirements.txt   # Python dependencies
│   ├── api/              # API endpoints
│   ├── auth/             # Authentication logic
│   ├── detection/        # Threat detection engine
│   └── models/           # Database models
├── scripts/              # Utility scripts
│   ├── init-db.sql       # Database schema
│   ├── init-timescale.sql # TimescaleDB config
│   └── start-docker.sh   # Docker startup helper
├── docker-compose.yml    # Multi-container orchestration
├── Dockerfile.flask      # Flask container image
├── Dockerfile.nextjs     # Next.js container image
└── README.md            # This file
```

## Implementation Phases

### Phase 0: Docker Infrastructure ✓ (Complete)
- Docker Compose with all services
- PostgreSQL + TimescaleDB setup
- Redis message queue
- Database schema with hypertables

### Phase 1: JWT Auth Handshake (In Progress)
- JWT authentication between Flask and Next.js
- Login/logout flows
- Session management
- Token refresh logic

### Phase 2: Live WebSocket Threat Feed
- Real-time threat detection updates
- Redis event bus integration
- Socket.io WebSocket connections
- Red screen alerts for critical threats

### Phase 3: PostgreSQL Migration
- Database migration from Flask SQLite
- TimescaleDB optimization
- Query performance tuning

### Phase 4: Dashboard & Analytics UI
- Real-time metric dashboard
- Threat timeline visualization
- Sensor management interface
- Analytics charts with Recharts

### Phase 5: Command Palette & Advanced Features
- CTRL+K command palette
- Incident response workflow
- Report generation
- User management UI

### Phase 6: Production Deployment
- Security hardening
- Performance optimization
- Deployment to Vercel + Railway
- Production monitoring

## Database Schema

### Core Tables
- **users** - User accounts and authentication
- **roles & permissions** - RBAC system
- **sensors** - WIPS sensor devices
- **sensor_health** (hypertable) - Time-series sensor monitoring
- **threats** - Detected threats
- **threat_events** (hypertable) - Time-series threat events
- **alerts & alert_rules** - Alert management
- **incidents & incident_events** - Incident response workflow
- **audit_logs** - System audit trail
- **blocked_devices** - Blocked MAC addresses

### Time-Series Features (TimescaleDB)
- Automatic hypertables for threat_events and sensor_health
- Continuous aggregates for hourly/daily analytics
- Automatic data compression (7+ days)
- Retention policies (90 days)
- Optimized indexes for time range queries

## API Endpoints (In Development)

### Authentication
- `POST /api/auth/login` - User login
- `POST /api/auth/logout` - User logout
- `POST /api/auth/refresh` - Refresh JWT token

### Threats
- `GET /api/threats` - List threats
- `GET /api/threats/<id>` - Get threat details
- `POST /api/threats/<id>/resolve` - Resolve threat

### Sensors
- `GET /api/sensors` - List sensors
- `GET /api/sensors/<id>/health` - Sensor health metrics
- `POST /api/sensors` - Register new sensor

### Alerts
- `GET /api/alerts` - List alerts
- `POST /api/alerts/<id>/acknowledge` - Acknowledge alert

### Analytics
- `GET /api/analytics/threat-stats` - Threat statistics
- `GET /api/analytics/trends` - Historical trends
- `POST /api/reports/generate` - Generate report

## Configuration

### Environment Variables

See `.env.docker` for Docker development configuration. Key variables:

```bash
# PostgreSQL
DATABASE_URL=postgresql://user:password@postgres:5432/zeinaguard_db

# Redis
REDIS_URL=redis://:password@redis:6379/0

# JWT
JWT_SECRET_KEY=your_secret_key_here

# Flask
FLASK_ENV=development
FLASK_DEBUG=1

# Next.js
NEXT_PUBLIC_API_URL=http://localhost:5000
NEXT_PUBLIC_SOCKET_URL=http://localhost:5000
```

### Update Passwords
Before deploying, update these critical passwords in `.env.docker`:
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `JWT_SECRET_KEY`
- `PGADMIN_DEFAULT_PASSWORD`

## Performance & Scalability

### TimescaleDB Optimizations
- Time-series hypertables for threat_events and sensor_health
- Automatic data compression for historical data
- Continuous aggregates for fast analytics queries
- Retention policies to manage storage

### Redis Caching
- Session storage
- Real-time event queue
- Cache frequent queries
- Rate limiting

### Database Optimization
- Indexed queries on threat_id, sensor_id, timestamps
- Connection pooling for Flask
- Query result caching via Redis

## Security Considerations

### In Development
- Sample passwords in `.env.docker` (CHANGE BEFORE PRODUCTION)
- Flask debug mode enabled
- CORS enabled for localhost

### Production Requirements
- Enable HTTPS/TLS
- Rotate JWT secrets
- Use managed PostgreSQL (AWS RDS, Google Cloud SQL, etc.)
- Use managed Redis (Redis Cloud, AWS ElastiCache, etc.)
- Enable database encryption at rest
- Implement rate limiting and DDoS protection
- Regular security audits and penetration testing

## Troubleshooting

### Services won't start
```bash
# Check logs
docker-compose logs

# Verify Docker is running and has sufficient resources
docker system df
```

### Database connection issues
```bash
# Test PostgreSQL
docker-compose exec postgres psql -U zeinaguard_user -d zeinaguard_db

# Check Redis
docker-compose exec redis redis-cli ping
```

### Port conflicts
Update port mappings in `docker-compose.yml` if ports 3000, 5000, 5432, 6379, or 5050 are already in use.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is part of a graduation initiative for network security education.

## Support

For issues, questions, or contributions:
1. Check the [DOCKER_SETUP.md](DOCKER_SETUP.md) guide
2. Open an issue on GitHub

## Next Steps

1. Review the Docker setup: `DOCKER_SETUP.md`
2. Start services: `docker-compose up -d`
3. Access dashboard: http://localhost:3000
4. Begin Phase 1 implementation: JWT authentication

---

**ZeinaGuard Pro** - Protecting your wireless network infrastructure with enterprise-grade threat detection and response.
