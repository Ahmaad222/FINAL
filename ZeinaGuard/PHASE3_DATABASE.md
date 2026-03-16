# Phase 3: PostgreSQL + TimescaleDB Migration - Implementation Guide

## Overview

Phase 3 migrates from in-memory mock data to a production-grade PostgreSQL database with TimescaleDB for time-series optimization. This enables data persistence, historical analysis, and scales to millions of threat events.

## What Was Implemented

### SQLAlchemy Models (`backend/models.py`)

Complete ORM models for all database entities:

**User Management:**
- `User` - System users
- `Role` - User roles (Admin, Analyst, Monitor)
- `Permission` - Fine-grained permissions
- `UserRole`, `RolePermission` - Relationships

**Monitoring:**
- `Sensor` - WIPS sensor devices
- `SensorHealth` - Time-series sensor metrics
- `NetworkTopology` - Discovered networks and devices

**Threats & Events:**
- `Threat` - Detected threats with metadata
- `ThreatEvent` - Time-series threat events (optimized for queries)

**Alerts & Incidents:**
- `AlertRule` - Rules for threat alerting
- `Alert` - Triggered alerts
- `Incident` - Security incidents
- `IncidentEvent` - Incident timeline events

**Administration:**
- `Report` - Generated reports
- `AuditLog` - System audit trail
- `BlockedDevice` - Blocked MAC addresses

### Database Initialization (`backend/init_db.py`)

**Automatic Setup:**
- Creates all tables and indexes
- Seeds default roles (Admin, Analyst, Monitor)
- Seeds default permissions (10 permissions)
- Creates demo users with different roles
- Creates sample sensors with health data
- Creates demo threat and alert rule

**Demo Users:**
```
Admin:    username: admin, password: admin123
Analyst:  username: analyst, password: analyst123
Monitor:  monitor / monitor123 (view-only)
```

### Flask Integration

**Database Configuration:**
- SQLAlchemy initialization
- Connection pooling (10 connections)
- Auto-reconnect on pool recycle
- Health check on each connection

**Automatic Initialization:**
- Tables created on Flask startup
- Graceful handling of existing tables
- No manual migrations needed (for development)

## Architecture

```
PostgreSQL 16
    ↓
TimescaleDB Extension
    ↓
SQLAlchemy ORM
    ↓
Flask Models
    ↓
API Routes (database queries)
    ↓
Next.js Frontend
```

## Running Phase 3

### Prerequisites

Docker containers running with PostgreSQL:
```bash
docker-compose up -d postgres redis flask-backend next-frontend
```

### Initialize Database

```bash
# Terminal 1: Enter backend directory
cd backend

# Install dependencies (if not already done)
pip install -r requirements.txt

# Initialize database
python init_db.py

# Output should show:
# [DB] Creating tables...
# [DB] Tables created successfully!
# [DB] Seeding default roles...
# [DB] Demo users created!
# ... etc ...
```

### Start Flask with Database

```bash
# Terminal 2: Start Flask with real database
python -m flask run

# Output should show:
# [DB] Database tables created/verified
# * Running on http://localhost:5000
```

### Verify Database

**Option 1: Using PgAdmin (Web Interface)**
```
URL: http://localhost:5050
Email: admin@zeinaguard.local
Password: admin_password_change_me
```

1. Login to PgAdmin
2. Add server connection:
   - Host: postgres
   - Port: 5432
   - User: zeinaguard_user
   - Password: secure_password_change_me
3. Browse tables in zeinaguard_db database

**Option 2: Using psql (Command Line)**
```bash
docker-compose exec postgres psql -U zeinaguard_user -d zeinaguard_db

# Then in psql:
\dt                    # List all tables
SELECT * FROM users;   # View users
SELECT * FROM threats; # View threats
\q                     # Quit
```

## Database Schema

### User Management
```sql
users         -- System users (id, username, email, password_hash, is_admin)
roles         -- Roles: Admin, Analyst, Monitor
permissions   -- Permissions: view_dashboard, manage_alerts, etc.
user_roles    -- Many-to-many: users ↔ roles
role_permissions -- Many-to-many: roles ↔ permissions
```

### Monitoring
```sql
sensors       -- Physical/virtual WIPS sensors
sensor_health -- Time-series: status, CPU, memory, uptime
```

### Threat Detection
```sql
threats       -- Threat records with type, severity, MAC addresses
threat_events -- Time-series hypertable: detailed threat events
```

### Alerts & Incidents
```sql
alert_rules   -- Rules for automatic alerting
alerts        -- Triggered alerts (readable, acknowledged)
incidents     -- Security incidents
incident_events -- Timeline: status changes, comments, actions
```

### Administration
```sql
reports       -- Generated reports (daily, weekly, monthly)
audit_logs    -- Audit trail: user actions, changes
blocked_devices -- Blocked MAC addresses with expiration
```

## Performance Optimizations

### Indexes Created
```
sensor_health:
  - idx_sensor_health_sensor_created (sensor_id, created_at)

threats:
  - idx_threats_created_at (created_at)
  - idx_threats_severity (severity)
  - idx_threats_sensor (detected_by)

threat_events:
  - idx_threat_events_threat_time (threat_id, time)
  - idx_threat_events_sensor_time (sensor_id, time)

alert_rules:
  - idx_alert_rules_enabled (is_enabled)

incidents:
  - idx_incidents_status (status)

audit_logs:
  - idx_audit_logs_user (user_id)
  - idx_audit_logs_created (created_at)
```

### Connection Pooling
- Pool size: 10 connections
- Max overflow: 10 (total 20)
- Pool timeout: 30 seconds
- Recycle: 3600 seconds (reconnect hourly)
- Pre-ping: Verify connection before use

## Querying Examples

### Get All Threats with Recent Events

```python
from models import Threat, ThreatEvent

threats = Threat.query.filter_by(is_resolved=False)\
    .order_by(Threat.created_at.desc())\
    .limit(50).all()
```

### Get Sensor Health Metrics

```python
from models import Sensor, SensorHealth
from datetime import datetime, timedelta

sensor = Sensor.query.get(1)
recent_health = SensorHealth.query\
    .filter_by(sensor_id=1)\
    .filter(SensorHealth.created_at > datetime.utcnow() - timedelta(hours=24))\
    .order_by(SensorHealth.created_at.desc())\
    .all()
```

### Get Critical Threats in Last 24 Hours

```python
from datetime import datetime, timedelta

critical_threats = Threat.query\
    .filter_by(severity='critical', is_resolved=False)\
    .filter(Threat.created_at > datetime.utcnow() - timedelta(hours=24))\
    .order_by(Threat.created_at.desc())\
    .all()
```

### Get Incident Activity Log

```python
from models import Incident, IncidentEvent

incident = Incident.query.get(1)
events = IncidentEvent.query\
    .filter_by(incident_id=1)\
    .order_by(IncidentEvent.created_at.asc())\
    .all()
```

## TimescaleDB Features (Phase 3+)

Once fully integrated, these TimescaleDB features become available:

### Hypertables
```sql
-- Convert to hypertable (automatic compression)
SELECT create_hypertable('threat_events', 'time', if_not_exists => TRUE);
SELECT create_hypertable('sensor_health', 'created_at', if_not_exists => TRUE);
```

### Continuous Aggregates
```sql
-- Daily threat summary (auto-refreshed)
CREATE MATERIALIZED VIEW threat_daily_summary AS
SELECT
    time_bucket('1 day', time) as day,
    threat_id,
    COUNT(*) as event_count,
    AVG(packet_count) as avg_packets
FROM threat_events
GROUP BY day, threat_id;
```

### Automatic Compression
```sql
-- Compress data older than 7 days
SELECT add_compression_policy('threat_events', INTERVAL '7 days');

-- Results: 90% space reduction for 30-day-old data
```

## Data Migration from Mock

The system currently has:
1. **In-memory mock data** - Used during development
2. **Database tables** - Ready for real data

To migrate existing WebSocket threat events to database:

```python
# In routes.py or websocket_server.py
def broadcast_threat_event(threat_data):
    # Create database record
    threat = Threat(
        threat_type=threat_data['threat_type'],
        severity=threat_data['severity'],
        source_mac=threat_data['source_mac'],
        ssid=threat_data['ssid'],
        detected_by=threat_data['detected_by'],
        description=threat_data['description']
    )
    db.session.add(threat)
    
    # Create event record
    event = ThreatEvent(
        threat_id=threat.id,
        sensor_id=threat_data['detected_by'],
        packet_count=threat_data.get('packet_count'),
        signal_strength=threat_data.get('signal_strength'),
        event_data=threat_data
    )
    db.session.add(event)
    db.session.commit()
    
    # Broadcast to WebSocket clients
    socketio.emit('threat_event', {
        'id': threat.id,
        'data': threat_data
    })
```

## Troubleshooting

### "Cannot connect to postgres"
```bash
# Check if postgres is running
docker-compose ps postgres

# View postgres logs
docker-compose logs postgres

# Restart postgres
docker-compose restart postgres
```

### "Table already exists"
```bash
# This is normal! SQLAlchemy skips existing tables
# To start fresh:
docker-compose down -v
docker-compose up -d
python init_db.py
```

### "psycopg2.OperationalError: could not translate"
- Database URL format issue
- Check DATABASE_URL environment variable
- Should be: `postgresql://user:pass@host:port/db`

### "Permission denied for schema"
```bash
# Grant permissions in psql:
GRANT ALL ON SCHEMA public TO zeinaguard_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO zeinaguard_user;
```

## Next Steps (Phase 4)

Phase 4 will add:
1. **Database-backed API endpoints** - Replace mock data with real queries
2. **Historical analytics** - Threat trends, sensor uptime graphs
3. **Reporting** - Generate PDF/CSV reports from database
4. **Real-time aggregates** - Dashboard metrics from database

## Testing Checklist

- [ ] Docker PostgreSQL running
- [ ] init_db.py runs without errors
- [ ] Can access database via PgAdmin
- [ ] Can query users table: `SELECT * FROM users;`
- [ ] Demo users created with correct passwords
- [ ] Sensors created with health data
- [ ] Demo threat created
- [ ] Flask starts and connects to database
- [ ] API endpoints accessible
- [ ] WebSocket broadcast still works
- [ ] No database connection errors in logs

## References

- SQLAlchemy ORM: https://docs.sqlalchemy.org/
- Flask-SQLAlchemy: https://flask-sqlalchemy.palletsprojects.com/
- PostgreSQL Documentation: https://www.postgresql.org/docs/
- TimescaleDB Docs: https://docs.timescale.com/
- Database Design: https://en.wikipedia.org/wiki/Database_design
