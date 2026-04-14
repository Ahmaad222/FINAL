# ZeinaGuard WebSocket Data Flow Fix Summary

## Executive Summary

This document details the comprehensive fixes applied to resolve the WebSocket data ingestion issues in the ZeinaGuard system. The sensor was successfully sending data, but the backend was not receiving, processing, or storing it.

---

## 🔍 Root Cause Analysis

### Primary Issues Identified

#### 1. **Hardcoded Backend URL in Sensor** (CRITICAL)
**File:** `sensor/communication/ws_client.py` (line 8)

```python
# BEFORE (BROKEN):
self.backend_url = backend_url or "http://192.168.201.130:8000"
```

The sensor was trying to connect to a hardcoded IP address (`192.168.201.130:8000`) instead of the Docker service name or localhost.

**Fix:** Dynamic backend URL resolution based on `RUN_MODE` environment variable:

```python
# AFTER (FIXED):
RUN_MODE = os.getenv('RUN_MODE', 'LOCAL')

if RUN_MODE == 'DOCKER':
    DEFAULT_BACKEND_URL = 'http://flask-backend:5000'
else:
    DEFAULT_BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:5000')
```

---

#### 2. **Missing Database Schema for WiFi Networks**
**Problem:** No dedicated table existed for storing high-frequency WiFi scan data. Data was being stuffed into JSON columns in `network_topology`, causing:
- Database bloat from duplicate records
- Inefficient queries
- No automatic cleanup mechanism

**Fix:** Created two new optimized tables:

| Table | Purpose | Deduplication |
|-------|---------|---------------|
| `wifi_networks` | Unique networks (SSID+BSSID+sensor) | UPDATE existing records |
| `network_scan_events` | Time-series scan history | TTL-based auto-cleanup |

---

#### 3. **Insufficient Logging**
**Problem:** Backend had minimal logging, making debugging impossible.

**Fix:** Added comprehensive logging at all critical points:
- WebSocket connection/disconnection
- Sensor registration
- Data reception
- Database operations (insert/update)
- Deduplication events
- Error conditions

---

## 📋 Files Modified

### Backend Files

| File | Changes |
|------|---------|
| `backend/models.py` | Added `WiFiNetwork` and `NetworkScanEvent` models with upsert logic |
| `backend/websocket_server.py` | Complete rewrite with proper Socket.IO init, validation, logging |
| `backend/app.py` | Application factory pattern, health/ready endpoints, improved logging |
| `scripts/init-timescale.sql` | Added hypertables, compression, retention policies |
| `scripts/migrate-wifi-networks.sql` | NEW: Migration script for existing databases |

### Sensor Files

| File | Changes |
|------|---------|
| `sensor/communication/ws_client.py` | Fixed backend URL, added local logging (CSV+JSON) |
| `sensor/detection/threat_manager.py` | Fixed log path to `sensor/data-logs/`, added rotation |

---

## 🗄️ Database Deduplication Strategy (Option C - Hybrid)

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Sensor Data Flow                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐     ┌──────────────┐     ┌─────────────────┐ │
│  │  Sensor  │────▶│  WebSocket   │────▶│  WiFiNetwork    │ │
│  │  (data)  │     │   Server     │     │  (Unique Nets)  │ │
│  └──────────┘     └──────────────┘     └─────────────────┘ │
│                            │                    │           │
│                            │                    ▼           │
│                            │            ┌──────────────┐    │
│                            │            │ UPDATE if    │    │
│                            │            │ exists       │    │
│                            │            │ INSERT if    │    │
│                            │            │ new          │    │
│                            │            └──────────────┘    │
│                            │                                 │
│                            ▼                                 │
│                   ┌─────────────────┐                        │
│                   │ NetworkScanEvent│                        │
│                   │ (Time-Series)   │                        │
│                   │ TTL: 30 days    │                        │
│                   └─────────────────┘                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### WiFiNetwork Table (Deduplicated)

| Field | Type | Description |
|-------|------|-------------|
| `sensor_id` | FK | Reference to sensor |
| `ssid` | VARCHAR | Network name |
| `bssid` | VARCHAR | MAC address (unique key with sensor_id) |
| `channel` | INT | WiFi channel |
| `frequency` | INT | Frequency in MHz |
| `signal_strength` | INT | dBm value |
| `encryption` | VARCHAR | Security type |
| `seen_count` | INT | **Number of times seen** |
| `first_seen` | TIMESTAMP | **Initial detection** |
| `last_seen` | TIMESTAMP | **Last update** |

**Unique Constraint:** `(sensor_id, bssid)` - prevents duplicates

### NetworkScanEvent Table (Time-Series)

| Field | Type | Description |
|-------|------|-------------|
| `sensor_id` | FK | Reference to sensor |
| `network_id` | FK | Reference to wifi_networks |
| `event_type` | VARCHAR | SCAN, ROGUE, EVIL_TWIN, etc. |
| `severity` | VARCHAR | CRITICAL, HIGH, MEDIUM, LOW, INFO |
| `risk_score` | FLOAT | 0-100 score |
| `scanned_at` | TIMESTAMP | Event timestamp |

**Retention:** Auto-deleted after 30 days via TimescaleDB policy

---

## 🔧 How Deduplication Works

### Upsert Logic (in `models.py`)

```python
@classmethod
def upsert_network(cls, session, sensor_id, bssid, ssid, **kwargs):
    """
    Efficient upsert: update existing or create new.
    Returns: (network_instance, is_new)
    """
    existing = cls.query.filter_by(sensor_id=sensor_id, bssid=bssid).first()

    if existing:
        # UPDATE existing record
        existing.seen_count = (existing.seen_count or 0) + 1
        existing.last_seen = datetime.utcnow()
        existing.ssid = ssid
        existing.signal_strength = kwargs.get('signal_strength')
        # ... update other fields
        return existing, False
    else:
        # INSERT new record
        network = cls(sensor_id=sensor_id, bssid=bssid, ssid=ssid, ...)
        session.add(network)
        return network, True
```

### Result

| Scenario | Database Action | Log Output |
|----------|-----------------|------------|
| First sighting of AP | INSERT | `✅ NEW network stored: MyWiFi (AA:BB:CC:DD:EE:FF)` |
| Subsequent sightings | UPDATE (seen_count++, last_seen=NOW) | `🔄 Network updated: MyWiFi, seen_count=15` |

---

## 🧹 Automatic Cleanup System

### Background Thread (in `websocket_server.py`)

```python
def cleanup_old_scan_events():
    """
    Runs every 5 minutes.
    Removes scan events older than RETENTION_HOURS (default: 24h).
    """
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)  # 300 seconds

        cutoff_time = datetime.utcnow() - timedelta(hours=RETENTION_HOURS)

        # Delete old events in batches
        batch = NetworkScanEvent.query.filter(
            NetworkScanEvent.scanned_at < cutoff_time
        ).limit(1000).all()

        for event in batch:
            db.session.delete(event)

        db.session.commit()
```

### TimescaleDB Retention Policy

```sql
-- Automatic deletion after 30 days
SELECT add_retention_policy('network_scan_events', INTERVAL '30 days');
```

---

## 📊 Local Data Logging (Sensor)

### File Locations

```
sensor/
└── data-logs/
    ├── network_scan_20260415_143022.csv
    ├── network_scan_20260415_143022.json
    ├── network_scan_20260415_153022.csv  (rotated hourly)
    └── network_scan_20260415_153022.json
```

### CSV Format

```csv
timestamp,ssid,bssid,channel,signal,distance,auth,wps,manufacturer,uptime,raw_beacon,elapsed_time,encryption,clients
2026-04-15T14:30:22,MyWiFi,AA:BB:CC:DD:EE:FF,6,-45,12m,WPA2,disabled,Intel,3600,0x8008...,123.45,WPA2,2
```

### JSON Format (NDJSON)

```json
{"timestamp":"2026-04-15T14:30:22","session_id":"20260415_143022","event":{"ssid":"MyWiFi","bssid":"AA:BB:CC:DD:EE:FF",...}}
{"timestamp":"2026-04-15T14:30:23","session_id":"20260415_143022","event":{"ssid":"Neighbor","bssid":"11:22:33:44:55:66",...}}
```

### Log Rotation

- **Time-based:** Every hour (3600 seconds)
- **Size-based:** When file exceeds 50MB

---

## 🚀 Testing & Verification

### 1. Start Docker Services

```bash
cd ZeinaGuard
./scripts/start-docker.sh
```

### 2. Verify Backend Health

```bash
curl http://localhost:5000/health
# Expected: {"status":"healthy","service":"zeinaguard-backend","version":"1.0.0"}
```

### 3. Check Socket.IO Readiness

```bash
curl http://localhost:5000/ready
# Expected: {"ready":true,"database":"connected","socketio":"initialized"}
```

### 4. Start Sensor

```bash
# Local mode
cd ZeinaGuard/sensor
python3 main.py wlx002e2dc0346b

# Docker mode (if using Docker sensor)
docker-compose up sensor
```

### 5. Monitor Logs

**Backend logs:**
```
[WebSocket] 🟢 Client Connected: SID=abc123
[WebSocket] 🛰️ Sensor Registration Request: sensor1
[WebSocket] ✅ Sensor created with ID=1
[WebSocket] 📶 Network Scan Received: sensor=sensor1, bssid=AA:BB:CC:DD:EE:FF
[WebSocket] ✅ NEW network stored: MyWiFi (AA:BB:CC:DD:EE:FF)
[WebSocket] 📡 Scan data broadcasted to dashboard
```

**Sensor logs:**
```
[WebSocket] 🟢 Connected to Backend at http://localhost:5000
[WebSocket] ✅ Sensor registered: {'status': 'registered', 'sensor_id': 'sensor1'}
[DataTransmitter] 📡 Sent: MyWiFi (AA:BB:CC:DD:EE:FF)
```

### 6. Verify Database Storage

```bash
docker exec -it zeinaguard_postgres psql -U zeinaguard_user -d zeinaguard_db
```

```sql
-- Check wifi_networks table
SELECT ssid, bssid, seen_count, last_seen FROM wifi_networks ORDER BY last_seen DESC LIMIT 10;

-- Check scan events
SELECT event_type, severity, scanned_at FROM network_scan_events ORDER BY scanned_at DESC LIMIT 10;

-- Check current networks view
SELECT * FROM v_current_networks;
```

---

## 🏗️ Scalable Architecture Recommendations

### For High-Throughput Production Deployment

```
┌────────────────────────────────────────────────────────────────────┐
│                     Production Architecture                         │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                     │
│  │ Sensor 1 │    │ Sensor 2 │    │ Sensor N │                     │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘                     │
│       │               │               │                            │
│       └───────────────┼───────────────┘                            │
│                       ▼                                            │
│              ┌─────────────────┐                                   │
│              │  Load Balancer  │                                   │
│              │   (nginx/HA)    │                                   │
│              └────────┬────────┘                                   │
│                       │                                            │
│       ┌───────────────┼───────────────┐                           │
│       ▼               ▼               ▼                            │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐                        │
│  │Backend 1│    │Backend 2│    │Backend N│                        │
│  │(Flask)  │    │(Flask)  │    │(Flask)  │                        │
│  └────┬────┘    └────┬────┘    └────┬────┘                        │
│       │             │              │                               │
│       └─────────────┼──────────────┘                               │
│                     ▼                                              │
│       ┌─────────────────────────┐                                  │
│       │     Redis (Pub/Sub)     │  ◄── For Socket.IO scaling       │
│       └─────────────────────────┘                                  │
│                     │                                              │
│       ┌─────────────┼─────────────┐                               │
│       ▼             ▼             ▼                                │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                            │
│  │Postgres │  │Timescale│  │  Redis  │                            │
│  │  (RW)   │  │  (RO)   │  │ (Cache) │                            │
│  └─────────┘  └─────────┘  └─────────┘                            │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

### Key Recommendations

1. **Socket.IO with Redis Adapter**
   - Enable horizontal scaling of Socket.IO servers
   - Required for multi-instance deployments

2. **Connection Pooling**
   - Use PgBouncer for PostgreSQL connection pooling
   - Configure SQLAlchemy pool_size and max_overflow

3. **Batch Inserts**
   - For extremely high-frequency data (>1000 scans/sec)
   - Buffer events and insert in batches of 100-1000

4. **Data Partitioning**
   - TimescaleDB hypertables already provide this
   - Consider additional partitioning by sensor_id for very large deployments

5. **Monitoring & Alerting**
   - Prometheus + Grafana for metrics
   - Alert on: queue depth, insert latency, disk usage

---

## 📁 Quick Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUN_MODE` | `LOCAL` | `LOCAL` or `DOCKER` |
| `BACKEND_URL` | `http://localhost:5000` | Backend URL |
| `SENSOR_INTERFACE` | `wlx002e2dc0346b` | WiFi interface |
| `SOCKETIO_ASYNC_MODE` | `threading` | `threading`, `eventlet`, or `gevent` |
| `SOCKETIO_CORS_ORIGINS` | `*` | CORS allowed origins |

### Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/ready` | GET | Readiness check |
| `/socket.io/` | WS | WebSocket connection |

### Socket.IO Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `connect` | Client→Server | - |
| `disconnect` | Client→Server | - |
| `sensor_register` | Client→Server | `{sensor_id: string}` |
| `network_scan` | Client→Server | `{sensor_id, ssid, bssid, channel, signal, ...}` |
| `new_threat` | Client→Server | `{threat_type, ssid, source_mac, severity}` |
| `registration_success` | Server→Client | `{status, sensor_id}` |
| `new_scan_data` | Server→Client | Full scan data for dashboard |
| `threat_event` | Server→Client | Threat alert for dashboard |

---

## 🎯 Summary

### What Was Fixed

1. ✅ **WebSocket connectivity** - Sensor now connects to correct backend URL
2. ✅ **Data reception** - Backend properly receives and logs incoming data
3. ✅ **Database storage** - New optimized tables prevent bloat
4. ✅ **Deduplication** - Same network updates counter instead of creating duplicates
5. ✅ **Auto-cleanup** - Old scan events automatically deleted
6. ✅ **Local logging** - Sensor stores CSV+JSON for redundancy
7. ✅ **Observability** - Comprehensive logging at all stages

### Expected Behavior After Fix

- Sensor connects to backend successfully
- Each unique WiFi network stored once in `wifi_networks`
- `seen_count` increments on subsequent detections
- `last_seen` timestamp updates continuously
- Scan events stored for 30 days then auto-deleted
- Local logs available in `sensor/data-logs/`
- Dashboard receives real-time updates via WebSocket

---

## 📞 Support

For issues or questions:
1. Check backend logs: `docker logs zeinaguard_flask`
2. Check sensor logs (in terminal where sensor runs)
3. Verify database: `SELECT * FROM v_current_networks;`
4. Test WebSocket connection manually using Socket.IO client
