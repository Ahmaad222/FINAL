"""
WebSocket server setup for ZeinaGuard.
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta

from flask import request
from flask_socketio import SocketIO, emit
from sqlalchemy.orm.attributes import flag_modified

from models import NetworkScanEvent, NetworkTopology, Sensor, Threat, WiFiNetwork, db


logger = logging.getLogger('websocket_server')

socketio = None

CLEANUP_INTERVAL_SECONDS = 300
RETENTION_HOURS = 24


def cleanup_old_scan_events(flask_app):
    logger.info('[Cleanup] Started background cleanup thread (retention=%sh)', RETENTION_HOURS)

    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            with flask_app.app_context():
                cutoff_time = datetime.utcnow() - timedelta(hours=RETENTION_HOURS)
                count_to_delete = NetworkScanEvent.query.filter(
                    NetworkScanEvent.scanned_at < cutoff_time,
                    ~NetworkScanEvent.is_purged,
                ).count()

                if count_to_delete <= 0:
                    continue

                logger.info('[Cleanup] Removing %s old scan events', count_to_delete)
                batch_size = 1000
                deleted = 0

                while True:
                    batch = NetworkScanEvent.query.filter(
                        NetworkScanEvent.scanned_at < cutoff_time,
                        ~NetworkScanEvent.is_purged,
                    ).limit(batch_size).all()

                    if not batch:
                        break

                    for event in batch:
                        db.session.delete(event)
                        deleted += 1

                    db.session.commit()

                logger.info('[Cleanup] Completed deletion of %s scan events', deleted)
        except Exception:
            with flask_app.app_context():
                db.session.rollback()
            logger.exception('[Cleanup] Cleanup job failed')


def init_socketio(app):
    global socketio

    async_mode = os.getenv('SOCKETIO_ASYNC_MODE', 'eventlet')
    cors_allowed = os.getenv('SOCKETIO_CORS_ORIGINS', '*')

    logger.info('[SocketIO] Initializing with async_mode=%s cors=%s', async_mode, cors_allowed)

    socketio = SocketIO(
        app,
        cors_allowed_origins=cors_allowed,
        async_mode=async_mode,
        ping_timeout=60,
        ping_interval=25,
        max_http_buffer_size=10 * 1024 * 1024,
        logger=True,
        engineio_logger=True,
    )

    cleanup_thread = threading.Thread(target=cleanup_old_scan_events, args=(app,), daemon=True)
    cleanup_thread.start()
    logger.info('[SocketIO] Background cleanup thread started')

    @socketio.on('connect')
    def handle_connect():
        logger.info('[WebSocket] Client connected sid=%s ip=%s', request.sid, request.remote_addr)

    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info('[WebSocket] Client disconnected sid=%s', request.sid)

    @socketio.on('connect_error')
    def handle_connect_error(error):
        logger.error('[WebSocket] Connection error: %s', error)

    @socketio.on('sensor_register')
    def handle_sensor_register(data):
        sensor_id = data.get('sensor_id', 'unknown_sensor')
        logger.info('[WebSocket] Sensor registration request for %s', sensor_id)

        try:
            sensor = Sensor.query.filter_by(name=sensor_id).first()
            if not sensor:
                sensor = Sensor(
                    name=sensor_id,
                    hostname=sensor_id,
                    is_active=True,
                    firmware_version='1.0.0',
                )
                db.session.add(sensor)
            else:
                sensor.is_active = True
                sensor.updated_at = datetime.utcnow()

            db.session.commit()
            emit(
                'registration_success',
                {
                    'status': 'registered',
                    'sensor_id': sensor_id,
                    'sensor_db_id': sensor.id,
                },
            )
            logger.info('[WebSocket] Sensor registration completed for %s', sensor_id)
        except Exception:
            db.session.rollback()
            logger.exception('[WebSocket] Sensor registration failed for %s', sensor_id)
            emit('registration_error', {'status': 'error', 'message': 'registration failed'})

    @socketio.on('new_threat')
    def handle_new_threat(payload):
        logger.info(
            '[WebSocket] Threat received type=%s ssid=%s severity=%s',
            payload.get('threat_type'),
            payload.get('ssid'),
            payload.get('severity'),
        )

        try:
            if not payload.get('threat_type'):
                logger.warning('[WebSocket] Invalid threat payload: missing threat_type')
                return

            threat = Threat(
                threat_type=payload.get('threat_type', 'UNKNOWN'),
                severity=payload.get('severity', 'MEDIUM'),
                source_mac=payload.get('source_mac'),
                target_mac=payload.get('target_mac'),
                ssid=payload.get('ssid'),
                description=f"Threat detected: Signal={payload.get('signal')}dBm",
            )
            db.session.add(threat)
            db.session.commit()

            emit(
                'threat_event',
                {
                    'id': threat.id,
                    'threat_type': payload.get('threat_type'),
                    'severity': payload.get('severity'),
                    'ssid': payload.get('ssid'),
                    'source_mac': payload.get('source_mac'),
                    'signal': payload.get('signal'),
                    'timestamp': datetime.utcnow().isoformat(),
                },
            )
            logger.info('[WebSocket] Threat stored and broadcast successfully')
        except Exception:
            db.session.rollback()
            logger.exception('[WebSocket] Threat handling failed')

    @socketio.on('network_scan')
    def handle_network_scan(payload):
        sensor_name = payload.get('sensor_id', 'unknown')
        bssid = payload.get('bssid')
        ssid = payload.get('ssid', '<hidden>')

        try:
            sensor = Sensor.query.filter_by(name=sensor_name).first()
            if not sensor:
                sensor = Sensor(name=sensor_name, hostname=sensor_name, is_active=True)
                db.session.add(sensor)
                db.session.commit()

            if not bssid:
                logger.warning('[WebSocket] Scan ignored because BSSID is missing')
                return

            now = datetime.utcnow()
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
                raw_beacon=payload.get('raw_beacon'),
            )
            db.session.commit()

            scan_event = NetworkScanEvent(
                sensor_id=sensor.id,
                network_id=network.id,
                event_type=payload.get('status', 'SCAN'),
                severity=_classify_severity(payload.get('status')),
                risk_score=payload.get('score'),
                signal_strength=payload.get('signal'),
                channel=payload.get('channel'),
                reasons=payload.get('reasons'),
                scan_metadata={
                    'distance': payload.get('distance'),
                    'wps': payload.get('wps'),
                    'elapsed_time': payload.get('elapsed_time'),
                },
            )
            db.session.add(scan_event)
            _update_network_topology(sensor, payload)
            db.session.commit()

            emit(
                'new_scan_data',
                {
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
                    'timestamp': now.isoformat(),
                },
            )
        except Exception:
            db.session.rollback()
            logger.exception('[WebSocket] Network scan handling failed')
            if os.getenv('FLASK_ENV') == 'development':
                raise

    logger.info('[SocketIO] Socket.IO event handlers registered successfully')
    return socketio


def _calculate_frequency(channel):
    if channel is None:
        return None

    channel = int(channel)

    if 1 <= channel <= 14:
        return 2407 + (5 * channel)
    if 36 <= channel <= 165:
        return 5000 + (5 * channel)
    if channel >= 170:
        return 5000 + (5 * channel)

    return None


def _classify_severity(status):
    severity_map = {
        'ROGUE': 'HIGH',
        'EVIL_TWIN': 'CRITICAL',
        'SUSPICIOUS': 'MEDIUM',
        'SCAN': 'INFO',
        'NORMAL': 'INFO',
    }
    return severity_map.get(status, 'INFO')


def _update_network_topology(sensor, payload):
    topology = NetworkTopology.query.filter_by(sensor_id=sensor.id).first()
    if not topology:
        topology = NetworkTopology(sensor_id=sensor.id, discovered_networks=[], discovered_devices=[])
        db.session.add(topology)

    bssid = payload.get('bssid')
    networks = topology.discovered_networks or []
    network_info = {
        'ssid': payload.get('ssid'),
        'bssid': bssid,
        'channel': payload.get('channel'),
        'signal': payload.get('signal'),
        'status': payload.get('status'),
        'last_seen': datetime.utcnow().isoformat(),
    }

    updated = False
    for index, network in enumerate(networks):
        if isinstance(network, dict) and network.get('bssid') == bssid:
            networks[index] = network_info
            updated = True
            break

    if not updated:
        networks.append(network_info)

    topology.discovered_networks = networks
    flag_modified(topology, 'discovered_networks')


def broadcast_threat_event(threat_data):
    if socketio is None:
        logger.warning('[broadcast_threat_event] SocketIO not initialized')
        return

    socketio.emit('threat_event', threat_data)
    logger.info('[broadcast_threat_event] Threat broadcast sent')


def broadcast_sensor_status(sensor_data):
    if socketio is None:
        logger.warning('[broadcast_sensor_status] SocketIO not initialized')
        return

    socketio.emit('sensor_status', sensor_data)
    logger.info('[broadcast_sensor_status] Sensor status broadcast sent')


def broadcast_scan_data(scan_data):
    if socketio is None:
        logger.warning('[broadcast_scan_data] SocketIO not initialized')
        return

    socketio.emit('new_scan_data', scan_data)
    logger.info('[broadcast_scan_data] Scan data broadcast sent')
