"""
WebSocket Server for ZeinaGuard Pro
Handles real-time communication between Sensors and Dashboard

Features:
- Proper Socket.IO initialization with eventlet/gevent support
- Robust event handling with validation
- Database deduplication using WiFiNetwork model
- Comprehensive logging for observability
- Background cleanup for old scan events
"""

import os
import time
import threading
import logging
from datetime import datetime, timedelta
from flask_socketio import SocketIO, emit
from flask import request, current_app
from sqlalchemy.orm.attributes import flag_modified
from models import db, Threat, Sensor, NetworkTopology, WiFiNetwork, NetworkScanEvent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('websocket_server')

# Socket.IO instance (initialized in init_socketio)
socketio = None

# =========================================================
# 1. Background Cleanup Thread for Old Scan Events
# =========================================================

CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes
RETENTION_HOURS = 24  # Keep scan events for 24 hours


def cleanup_old_scan_events():
    """
    Background thread that periodically removes old network scan events.
    Keeps the database size under control while preserving recent history.
    """
    logger.info(f"[Cleanup] Started background cleanup thread (retention: {RETENTION_HOURS}h)")

    while True:
        try:
            time.sleep(CLEANUP_INTERVAL_SECONDS)

            with current_app.app_context():
                cutoff_time = datetime.utcnow() - timedelta(hours=RETENTION_HOURS)

                # Count records to be deleted
                count_to_delete = NetworkScanEvent.query.filter(
                    NetworkScanEvent.scanned_at < cutoff_time,
                    ~NetworkScanEvent.is_purged
                ).count()

                if count_to_delete > 0:
                    logger.info(f"[Cleanup] Removing {count_to_delete} old scan events...")

                    # Delete in batches to avoid locking
                    batch_size = 1000
                    deleted = 0

                    while True:
                        batch = NetworkScanEvent.query.filter(
                            NetworkScanEvent.scanned_at < cutoff_time,
                            ~NetworkScanEvent.is_purged
                        ).limit(batch_size).all()

                        if not batch:
                            break

                        for event in batch:
                            db.session.delete(event)
                            deleted += 1

                        db.session.commit()
                        logger.info(f"[Cleanup] Deleted {deleted}/{count_to_delete} events")

                    logger.info(f"[Cleanup] Completed: {deleted} events removed")

                else:
                    logger.debug("[Cleanup] No old events to clean up")

        except Exception as e:
            logger.error(f"[Cleanup] Error during cleanup: {e}", exc_info=True)
            db.session.rollback()


# =========================================================
# 2. Socket.IO Initialization
# =========================================================

def init_socketio(app):
    """
    Initialize Flask-SocketIO with proper configuration for production.

    Note: async_mode='threading' is used for simplicity.
    For high-throughput, consider eventlet or gevent:
    - async_mode='eventlet' (recommended for Windows)
    - async_mode='gevent' (recommended for Linux)
    """
    global socketio

    # Determine async mode based on environment
    async_mode = os.getenv('SOCKETIO_ASYNC_MODE', 'threading')

    # CORS configuration
    cors_allowed = os.getenv('SOCKETIO_CORS_ORIGINS', '*')

    logger.info(f"[SocketIO] Initializing with async_mode={async_mode}, cors={cors_allowed}")

    socketio = SocketIO(
        app,
        cors_allowed_origins=cors_allowed,
        async_mode=async_mode,
        ping_timeout=60,
        ping_interval=25,
        max_http_buffer_size=10 * 1024 * 1024,  # 10MB max payload
        logger=True,
        engineio_logger=True
    )

    # Start background cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_scan_events, daemon=True)
    cleanup_thread.start()
    logger.info("[SocketIO] Background cleanup thread started")

    # =========================================================
    # 3. Event Handlers
    # =========================================================

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        client_sid = request.sid
        client_ip = request.remote_addr
        logger.info(f"[WebSocket] 🟢 Client Connected: SID={client_sid}, IP={client_ip}")

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        client_sid = request.sid
        logger.info(f"[WebSocket] 🔴 Client Disconnected: SID={client_sid}")

    @socketio.on('connect_error')
    def handle_connect_error(error):
        """Handle connection errors."""
        logger.error(f"[WebSocket] ❌ Connection Error: {error}")

    @socketio.on('sensor_register')
    def handle_sensor_register(data):
        """
        Handle sensor registration when it first connects.
        Creates or updates sensor record in database.
        """
        sensor_id = data.get('sensor_id', 'unknown_sensor')
        client_sid = request.sid

        logger.info(f"[WebSocket] 🛰️ Sensor Registration Request: {sensor_id} (SID={client_sid})")

        try:
            with current_app.app_context():
                # Check if sensor exists
                sensor = Sensor.query.filter_by(name=sensor_id).first()

                if not sensor:
                    logger.info(f"[WebSocket] 🆕 Auto-creating sensor in DB: {sensor_id}")
                    sensor = Sensor(
                        name=sensor_id,
                        hostname=sensor_id,
                        is_active=True,
                        firmware_version='1.0.0'
                    )
                    db.session.add(sensor)
                    db.session.commit()
                    logger.info(f"[WebSocket] ✅ Sensor created with ID={sensor.id}")
                else:
                    # Update existing sensor
                    sensor.is_active = True
                    sensor.updated_at = datetime.utcnow()
                    db.session.commit()
                    logger.info(f"[WebSocket] 🔄 Sensor updated: ID={sensor.id}")

            # Send confirmation to sensor
            emit('registration_success', {
                'status': 'registered',
                'sensor_id': sensor_id,
                'sensor_db_id': sensor.id if sensor else None
            })

            logger.info(f"[WebSocket] ✅ Registration confirmed for {sensor_id}")

        except Exception as e:
            logger.error(f"[WebSocket] ❌ Registration failed: {e}", exc_info=True)
            db.session.rollback()
            emit('registration_error', {
                'status': 'error',
                'message': str(e)
            })

    @socketio.on('new_threat')
    def handle_new_threat(payload):
        """
        Handle threat alerts from sensors.
        Broadcasts to all connected dashboard clients.
        """
        logger.info(f"[WebSocket] 🚨 Threat Received: type={payload.get('threat_type')}, "
                    f"ssid={payload.get('ssid')}, severity={payload.get('severity')}")

        try:
            # Validate payload
            if not payload.get('threat_type'):
                logger.warning("[WebSocket] ⚠️ Invalid threat payload: missing threat_type")
                return

            # Store threat in database
            with current_app.app_context():
                threat = Threat(
                    threat_type=payload.get('threat_type', 'UNKNOWN'),
                    severity=payload.get('severity', 'MEDIUM'),
                    source_mac=payload.get('source_mac'),
                    target_mac=payload.get('target_mac'),
                    ssid=payload.get('ssid'),
                    description=f"Threat detected: Signal={payload.get('signal')}dBm"
                )
                db.session.add(threat)
                db.session.commit()
                logger.info(f"[WebSocket] ✅ Threat stored in DB: ID={threat.id}")

            # Broadcast to dashboard
            emit('threat_event', {
                'id': threat.id if 'threat' in locals() else None,
                'threat_type': payload.get('threat_type'),
                'severity': payload.get('severity'),
                'ssid': payload.get('ssid'),
                'source_mac': payload.get('source_mac'),
                'signal': payload.get('signal'),
                'timestamp': datetime.utcnow().isoformat()
            })

            logger.info(f"[WebSocket] 📡 Threat broadcasted to dashboard")

        except Exception as e:
            logger.error(f"[WebSocket] ❌ Threat handling failed: {e}", exc_info=True)
            db.session.rollback()

    @socketio.on('network_scan')
    def handle_network_scan(payload):
        """
        Handle network scan data from sensors.

        This is the MAIN data ingestion endpoint. It:
        1. Validates incoming payload
        2. Ensures sensor exists in DB
        3. Upserts WiFi network (deduplication)
        4. Records scan event for history
        5. Broadcasts to dashboard

        Deduplication Strategy (Option C - Hybrid):
        - WiFiNetwork table: Unique networks (SSID+BSSID), updated in-place
        - NetworkScanEvent table: Time-series events with TTL cleanup
        """
        sensor_name = payload.get('sensor_id', 'unknown')
        bssid = payload.get('bssid')
        ssid = payload.get('ssid', '<hidden>')

        logger.debug(f"[WebSocket] 📶 Network Scan Received: "
                     f"sensor={sensor_name}, bssid={bssid}, ssid={ssid}")

        try:
            with current_app.app_context():
                # ----- Step 1: Ensure sensor exists -----
                sensor = Sensor.query.filter_by(name=sensor_name).first()

                if not sensor:
                    logger.info(f"[WebSocket] 🆕 Auto-creating sensor: {sensor_name}")
                    sensor = Sensor(
                        name=sensor_name,
                        hostname=sensor_name,
                        is_active=True
                    )
                    db.session.add(sensor)
                    db.session.commit()
                    logger.info(f"[WebSocket] ✅ Sensor created: ID={sensor.id}")

                # ----- Step 2: Validate BSSID -----
                if not bssid:
                    logger.warning("[WebSocket] ⚠️ Scan received without BSSID, ignoring")
                    return

                # ----- Step 3: Upsert WiFi Network (DEDUPLICATION) -----
                now = datetime.utcnow()
                is_new_network = False

                network, is_new_network = WiFiNetwork.upsert_network(
                    session=db.session,
                    sensor_id=sensor.id,
                    bssid=bssid,
                    ssid=ssid,
                    signal_strength=payload.get('signal'),
                    channel=payload.get('channel'),
                    frequency=_calculate_frequency(payload.get('channel')),
                    encryption=payload.get('auth', 'UNKNOWN'),
                    auth_type=payload.get('auth'),
                    wps_info=payload.get('wps'),
                    manufacturer=payload.get('manufacturer'),
                    uptime_seconds=payload.get('uptime'),
                    raw_beacon=payload.get('raw_beacon')
                )

                db.session.commit()

                if is_new_network:
                    logger.info(f"[WebSocket] ✅ NEW network stored: {ssid} ({bssid})")
                else:
                    logger.debug(f"[WebSocket] 🔄 Network updated: {ssid} ({bssid}), "
                                 f"seen_count={network.seen_count}")

                # ----- Step 4: Record Scan Event (for history) -----
                scan_event = NetworkScanEvent(
                    sensor_id=sensor.id,
                    network_id=network.id,
                    event_type=payload.get('status', 'SCAN'),
                    severity=_classify_severity(payload.get('status')),
                    risk_score=payload.get('score'),
                    signal_strength=payload.get('signal'),
                    channel=payload.get('channel'),
                    reasons=payload.get('reasons'),
                    metadata={
                        'distance': payload.get('distance'),
                        'wps': payload.get('wps'),
                        'elapsed_time': payload.get('elapsed_time')
                    }
                )
                db.session.add(scan_event)
                db.session.commit()

                logger.debug(f"[WebSocket] ✅ Scan event recorded: ID={scan_event.id}")

                # ----- Step 5: Update Network Topology (legacy support) -----
                _update_network_topology(sensor, payload)

                # ----- Step 6: Broadcast to Dashboard -----
                emit('new_scan_data', {
                    'sensor_id': sensor_name,
                    'sensor_db_id': sensor.id,
                    'network_id': network.id,
                    'ssid': ssid,
                    'bssid': bssid,
                    'channel': payload.get('channel'),
                    'signal': payload.get('signal'),
                    'distance': payload.get('distance'),
                    'auth': payload.get('auth'),
                    'wps': payload.get('wps'),
                    'manufacturer': payload.get('manufacturer'),
                    'uptime': payload.get('uptime'),
                    'status': payload.get('status', 'SCAN'),
                    'score': payload.get('score'),
                    'is_new': is_new_network,
                    'seen_count': network.seen_count,
                    'timestamp': now.isoformat()
                })

                logger.debug(f"[WebSocket] 📡 Scan data broadcasted to dashboard")

        except Exception as e:
            logger.error(f"[WebSocket] ❌ Network scan handling failed: {e}", exc_info=True)
            db.session.rollback()
            # Re-raise for debugging during development
            if os.getenv('FLASK_ENV') == 'development':
                raise

    return socketio


# =========================================================
# 4. Helper Functions
# =========================================================

def _calculate_frequency(channel):
    """
    Calculate frequency in MHz from channel number.
    2.4 GHz: channels 1-14 (2412-2484 MHz)
    5 GHz: channels 36-165 (5180-5825 MHz)
    """
    if channel is None:
        return None

    channel = int(channel)

    if 1 <= channel <= 14:
        return 2407 + (5 * channel)  # 2.4 GHz band
    elif 36 <= channel <= 165:
        return 5000 + (5 * channel)  # 5 GHz band
    elif channel >= 170:
        return 5000 + (5 * channel)  # 5 GHz extended

    return None


def _classify_severity(status):
    """Classify severity based on network status."""
    severity_map = {
        'ROGUE': 'HIGH',
        'EVIL_TWIN': 'CRITICAL',
        'SUSPICIOUS': 'MEDIUM',
        'SCAN': 'INFO',
        'NORMAL': 'INFO'
    }
    return severity_map.get(status, 'INFO')


def _update_network_topology(sensor, payload):
    """Update legacy network topology JSON (for backward compatibility)."""
    try:
        topology = NetworkTopology.query.filter_by(sensor_id=sensor.id).first()

        if not topology:
            topology = NetworkTopology(
                sensor_id=sensor.id,
                discovered_networks=[],
                discovered_devices=[]
            )
            db.session.add(topology)

        bssid = payload.get('bssid')
        networks = topology.discovered_networks or []

        network_info = {
            'ssid': payload.get('ssid'),
            'bssid': bssid,
            'channel': payload.get('channel'),
            'signal': payload.get('signal'),
            'status': payload.get('status'),
            'last_seen': datetime.utcnow().isoformat()
        }

        # Update or append
        updated = False
        for i, net in enumerate(networks):
            if isinstance(net, dict) and net.get('bssid') == bssid:
                networks[i] = network_info
                updated = True
                break

        if not updated:
            networks.append(network_info)

        topology.discovered_networks = networks
        flag_modified(topology, 'discovered_networks')

        logger.debug(f"[Topology] Updated for sensor {sensor.id}")

    except Exception as e:
        logger.error(f"[Topology] Update failed: {e}")


# =========================================================
# 5. Global Broadcast Functions (for use outside Socket context)
# =========================================================

def broadcast_threat_event(threat_data):
    """
    Broadcast threat event from anywhere in the application.
    Usage: from websocket_server import broadcast_threat_event
    """
    if socketio is None:
        logger.warning("[broadcast_threat_event] SocketIO not initialized")
        return

    socketio.emit('threat_event', threat_data)
    logger.info("[broadcast_threat_event] 📡 Global threat broadcast sent")


def broadcast_sensor_status(sensor_data):
    """
    Broadcast sensor status update.
    Usage: from websocket_server import broadcast_sensor_status
    """
    if socketio is None:
        logger.warning("[broadcast_sensor_status] SocketIO not initialized")
        return

    socketio.emit('sensor_status', sensor_data)
    logger.info("[broadcast_sensor_status] 📡 Sensor status broadcast sent")


def broadcast_scan_data(scan_data):
    """
    Broadcast network scan data from anywhere in the application.
    Usage: from websocket_server import broadcast_scan_data
    """
    if socketio is None:
        logger.warning("[broadcast_scan_data] SocketIO not initialized")
        return

    socketio.emit('new_scan_data', scan_data)
    logger.info("[broadcast_scan_data] 📡 Scan data broadcast sent")
