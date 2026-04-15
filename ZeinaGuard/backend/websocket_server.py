"""
WebSocket Server for ZeinaGuard Pro.
Handles communication between sensors and the dashboard.
"""

import logging
import os
import re
from datetime import datetime
from typing import Any

from flask import current_app, request
from flask_socketio import SocketIO, emit
from redis import Redis

from models import Sensor, Threat, WiFiNetwork, db
from security import sanitize_input, validate_mac_address


LOGGER = logging.getLogger("zeinaguard.websocket")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False

UPTIME_PART_PATTERN = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
connected_clients: dict[str, dict[str, Any]] = {}


try:
    redis_client = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
except Exception:
    redis_client = None


def configure_socket_logging() -> None:
    logging.getLogger("engineio").setLevel(logging.WARNING)
    logging.getLogger("socketio").setLevel(logging.WARNING)


def parse_uptime_to_seconds(uptime_str: str) -> int:
    if uptime_str is None:
        return 0

    if isinstance(uptime_str, (int, float)):
        return max(int(uptime_str), 0)

    if not isinstance(uptime_str, str):
        return 0

    uptime_str = uptime_str.strip()
    if not uptime_str:
        return 0

    if uptime_str.isdigit():
        return int(uptime_str)

    total_seconds = 0
    found_any = False

    for value, unit in UPTIME_PART_PATTERN.findall(uptime_str):
        found_any = True
        amount = int(value)
        unit = unit.lower()

        if unit == "d":
            total_seconds += amount * 86400
        elif unit == "h":
            total_seconds += amount * 3600
        elif unit == "m":
            total_seconds += amount * 60
        elif unit == "s":
            total_seconds += amount

    if not found_any:
        return 0

    return total_seconds


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_bssid(value: Any) -> str:
    if value is None:
        return ""

    bssid = str(value).strip().upper().replace("-", ":")
    return bssid


def _normalize_ssid(value: Any) -> str:
    if not value:
        return "Hidden"
    return sanitize_input(str(value), max_length=255) or "Hidden"


def _resolve_sensor(sensor_identifier: Any, hostname: Any = None) -> Sensor:
    sensor_key = sanitize_input(str(sensor_identifier or hostname or "sensor"), max_length=255)
    host_key = sanitize_input(str(hostname or sensor_key), max_length=255)

    sensor = None
    if sensor_key.isdigit():
        sensor = db.session.get(Sensor, int(sensor_key))

    if sensor is None:
        sensor = Sensor.query.filter_by(hostname=host_key).first()

    if sensor is None:
        sensor = Sensor.query.filter_by(name=sensor_key).first()

    if sensor is None:
        sensor = Sensor(
            name=sensor_key,
            hostname=host_key,
            is_active=True,
            firmware_version="sensor-ws",
        )
        db.session.add(sensor)
        db.session.flush()

    return sensor


def _normalize_network_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        networks = payload.get("networks")
        if isinstance(networks, list):
            metadata = {key: value for key, value in payload.items() if key != "networks"}
            normalized = []
            for item in networks:
                if not isinstance(item, dict):
                    continue
                merged = metadata.copy()
                merged.update(item)
                normalized.append(merged)
            return normalized
        return [payload]

    return []


def _store_network_scan(network_data: dict[str, Any]) -> None:
    sensor = _resolve_sensor(
        sensor_identifier=network_data.get("sensor_id"),
        hostname=network_data.get("hostname"),
    )

    bssid = _normalize_bssid(network_data.get("bssid"))
    ssid = _normalize_ssid(network_data.get("ssid"))

    if not bssid or not validate_mac_address(bssid):
        raise ValueError(f"Invalid BSSID: {network_data.get('bssid')}")

    uptime_seconds = parse_uptime_to_seconds(network_data.get("uptime"))
    now = datetime.utcnow()

    LOGGER.info("[WebSocket] 📡 Received: %s (%s)", ssid, bssid)

    network = WiFiNetwork.query.filter_by(sensor_id=sensor.id, bssid=bssid).first()

    if network is None:
        network = WiFiNetwork(
            sensor_id=sensor.id,
            ssid=ssid,
            bssid=bssid,
            first_seen=now,
            seen_count=1,
        )
        db.session.add(network)
        action = "stored"
    else:
        network.seen_count += 1
        action = "updated"

    network.ssid = ssid
    network.channel = _safe_int(network_data.get("channel"), default=0) or None
    network.signal_strength = _safe_int(network_data.get("signal"), default=0) or None
    network.encryption = sanitize_input(str(network_data.get("encryption") or "UNKNOWN"), max_length=50)
    network.clients_count = _safe_int(network_data.get("clients"), default=0)
    network.classification = sanitize_input(
        str(network_data.get("classification") or "UNKNOWN"),
        max_length=50,
    )
    network.risk_score = _safe_int(network_data.get("score"), default=0)
    network.uptime_seconds = uptime_seconds
    network.last_seen = now
    network.raw_data = network_data

    db.session.commit()

    if action == "stored":
        LOGGER.info("[WebSocket] ✅ Stored network: %s (%s)", ssid, bssid)
        LOGGER.info("[WebSocket] ✅ Stored: %s", ssid)
    else:
        LOGGER.info("[WebSocket] 🔄 Updated: %s (seen_count=%s)", ssid, network.seen_count)


def _resolve_async_mode() -> str:
    preferred_mode = os.getenv("SOCKETIO_ASYNC_MODE", "eventlet")
    if preferred_mode == "eventlet":
        try:
            import eventlet  # noqa: F401
        except ImportError:
            return "threading"
    return preferred_mode


def init_socketio(app):
    configure_socket_logging()

    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode=_resolve_async_mode(),
        logger=False,
        engineio_logger=False,
    )

    @socketio.on("connect")
    def handle_connect():
        client_id = request.sid
        connected_clients[client_id] = {
            "connected_at": datetime.utcnow().isoformat(),
        }
        LOGGER.info("[WebSocket] Connected client: %s", client_id)

    @socketio.on("disconnect")
    def handle_disconnect():
        client_id = request.sid
        connected_clients.pop(client_id, None)
        LOGGER.info("[WebSocket] Disconnected client: %s", client_id)

    @socketio.on("sensor_register")
    def handle_sensor_register(data):
        try:
            sensor = _resolve_sensor(
                sensor_identifier=(data or {}).get("sensor_id"),
                hostname=(data or {}).get("hostname"),
            )
            db.session.commit()
            LOGGER.info("[WebSocket] Sensor registered: %s", sensor.hostname or sensor.name)
            emit(
                "registration_success",
                {
                    "status": "registered",
                    "sensor_id": sensor.id,
                    "sensor_name": sensor.name,
                },
            )
        except Exception as exc:
            db.session.rollback()
            LOGGER.error("[WebSocket] ❌ Sensor registration failed: %s", exc)
            emit("registration_error", {"status": "error", "message": "registration_failed"})

    @socketio.on("network_scan")
    def handle_network_scan(payload):
        network_events = _normalize_network_events(payload)

        if not network_events:
            LOGGER.warning("[WebSocket] Ignored empty network_scan payload")
            emit("network_scan_ack", {"status": "ignored"})
            return

        stored_count = 0
        for network_data in network_events:
            try:
                _store_network_scan(network_data)
                stored_count += 1
            except Exception as exc:
                db.session.rollback()
                LOGGER.error("[WebSocket] ❌ Failed to store network scan: %s", exc)

        emit(
            "network_scan_ack",
            {
                "status": "ok" if stored_count else "failed",
                "stored_count": stored_count,
            },
        )

    @socketio.on("new_threat")
    def handle_new_threat(payload):
        ssid = _normalize_ssid((payload or {}).get("ssid"))
        LOGGER.info("[WebSocket] 🚨 Received Threat: %s", ssid)

        with app.app_context():
            try:
                new_threat = Threat(
                    threat_type=(payload or {}).get("threat_type", "UNKNOWN"),
                    severity=(payload or {}).get("severity", "HIGH"),
                    source_mac=(payload or {}).get("source_mac"),
                    ssid=(payload or {}).get("ssid"),
                    description="Detected via Sensor WebSocket",
                )

                db.session.add(new_threat)
                db.session.commit()

                socketio.emit(
                    "threat_event",
                    {
                        "id": new_threat.id,
                        "type": "threat_detected",
                        "timestamp": datetime.utcnow().isoformat(),
                        "data": payload,
                    },
                )

                LOGGER.info("[WebSocket] ✅ Stored threat: %s", ssid)
            except Exception as exc:
                db.session.rollback()
                LOGGER.error("[WebSocket] ❌ Error saving threat: %s", exc)

    return socketio


def broadcast_threat_event(threat_data):
    socketio = current_app.socketio
    socketio.emit("threat_event", threat_data)
    LOGGER.info("[WebSocket] 📡 Threat broadcasted to dashboard")


def broadcast_sensor_status(sensor_data):
    socketio = current_app.socketio
    socketio.emit("sensor_status", sensor_data)
    LOGGER.info("[WebSocket] 📡 Sensor status broadcasted")
