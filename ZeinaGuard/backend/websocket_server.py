"""
WebSocket server and background maintenance for ZeinaGuard.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Any

from flask import current_app, request
from flask_socketio import SocketIO, emit
from redis import Redis
from sqlalchemy import func, literal_column, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models import NetworkScanEvent, Sensor, Threat, WiFiNetwork, db
from security import sanitize_input, validate_mac_address


LOGGER = logging.getLogger("zeinaguard.websocket")
CLEANUP_LOGGER = logging.getLogger("zeinaguard.cleanup")

UPTIME_PART_PATTERN = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
connected_clients: dict[str, dict[str, Any]] = {}

WRITE_THROTTLE_SECONDS = int(os.getenv("NETWORK_WRITE_THROTTLE_SECONDS", "5"))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "600"))
SCAN_RETENTION_HOURS = int(os.getenv("NETWORK_SCAN_RETENTION_HOURS", "24"))
NETWORK_RETENTION_HOURS = int(os.getenv("WIFI_NETWORK_RETENTION_HOURS", "48"))
ADVISORY_LOCK_ID = int(os.getenv("ZEINAGUARD_CLEANUP_LOCK_ID", "240416"))

_network_write_cache: dict[tuple[int, str], float] = {}
_network_write_cache_lock = threading.Lock()
_sensor_id_cache: dict[str, int] = {}
_sensor_id_cache_lock = threading.Lock()
_cleanup_thread_started = False
_cleanup_thread_lock = threading.Lock()


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
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


def parse_uptime_to_seconds(uptime_str: str) -> int:
    if uptime_str is None:
        return 0

    if isinstance(uptime_str, (int, float)):
        return max(int(uptime_str), 0)

    if not isinstance(uptime_str, str):
        return 0

    value = uptime_str.strip()
    if not value:
        return 0

    if value.isdigit():
        return max(int(value), 0)

    total_seconds = 0
    found_any = False

    for amount_str, unit in UPTIME_PART_PATTERN.findall(value):
        found_any = True
        amount = int(amount_str)
        unit = unit.lower()

        if unit == "d":
            total_seconds += amount * 86400
        elif unit == "h":
            total_seconds += amount * 3600
        elif unit == "m":
            total_seconds += amount * 60
        elif unit == "s":
            total_seconds += amount

    return total_seconds if found_any else 0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_bssid(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper().replace("-", ":")


def _normalize_ssid(value: Any) -> str:
    if not value:
        return "Hidden"
    return sanitize_input(str(value), max_length=255) or "Hidden"


def _calculate_frequency(channel: Any) -> int | None:
    channel_value = _safe_int(channel, default=0)
    if channel_value <= 0:
        return None
    if 1 <= channel_value <= 14:
        return 2407 + (channel_value * 5)
    return 5000 + (channel_value * 5)


def _cache_sensor_id(sensor_id: int, *keys: str) -> None:
    with _sensor_id_cache_lock:
        for key in keys:
            if key:
                _sensor_id_cache[key] = sensor_id


def _resolve_sensor(sensor_identifier: Any, hostname: Any = None) -> Sensor:
    sensor_key = sanitize_input(str(sensor_identifier or hostname or "sensor"), max_length=255)
    host_key = sanitize_input(str(hostname or sensor_key), max_length=255)

    with _sensor_id_cache_lock:
        cached_id = _sensor_id_cache.get(sensor_key) or _sensor_id_cache.get(host_key)

    if cached_id:
        sensor = db.session.get(Sensor, cached_id)
        if sensor is not None:
            return sensor

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

    _cache_sensor_id(sensor.id, sensor_key, host_key, str(sensor.id))
    return sensor


def _normalize_network_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        networks = payload.get("networks")
        if isinstance(networks, list):
            shared = {key: value for key, value in payload.items() if key != "networks"}
            merged_networks = []
            for item in networks:
                if not isinstance(item, dict):
                    continue
                merged = shared.copy()
                merged.update(item)
                merged_networks.append(merged)
            return merged_networks
        return [payload]

    return []


def _should_write_network(sensor_id: int, bssid: str) -> bool:
    cache_key = (sensor_id, bssid)
    now = time.monotonic()

    with _network_write_cache_lock:
        last_seen = _network_write_cache.get(cache_key)
        if last_seen is not None and (now - last_seen) < WRITE_THROTTLE_SECONDS:
            return False
        _network_write_cache[cache_key] = now
        return True


def _mark_write_failed(sensor_id: int, bssid: str) -> None:
    with _network_write_cache_lock:
        _network_write_cache.pop((sensor_id, bssid), None)


def _prune_write_cache(max_age_seconds: int = 3600) -> None:
    cutoff = time.monotonic() - max_age_seconds
    with _network_write_cache_lock:
        expired_keys = [key for key, seen_at in _network_write_cache.items() if seen_at < cutoff]
        for key in expired_keys:
            _network_write_cache.pop(key, None)


def _upsert_wifi_network(network_data: dict[str, Any], sensor_id: int, ssid: str, bssid: str) -> tuple[int, bool, int]:
    now = datetime.utcnow()
    uptime_seconds = parse_uptime_to_seconds(network_data.get("uptime"))
    channel = _safe_int(network_data.get("channel"), default=0) or None
    signal_strength = _safe_int(network_data.get("signal"), default=0) or None
    clients_count = _safe_int(network_data.get("clients"), default=0)
    risk_score = _safe_int(network_data.get("score"), default=0)

    payload = {
        "sensor_id": sensor_id,
        "ssid": ssid,
        "bssid": bssid,
        "channel": channel,
        "frequency": _calculate_frequency(channel),
        "signal_strength": signal_strength,
        "encryption": sanitize_input(str(network_data.get("encryption") or "UNKNOWN"), max_length=50),
        "clients_count": clients_count,
        "classification": sanitize_input(
            str(network_data.get("classification") or "UNKNOWN"),
            max_length=50,
        ),
        "risk_score": risk_score,
        "auth_type": sanitize_input(str(network_data.get("auth_type") or network_data.get("auth") or ""), max_length=50)
        or None,
        "wps_info": network_data.get("wps_info") or network_data.get("wps"),
        "manufacturer": sanitize_input(str(network_data.get("manufacturer") or ""), max_length=255) or None,
        "device_type": sanitize_input(str(network_data.get("device_type") or "AP"), max_length=50) or "AP",
        "uptime_seconds": uptime_seconds,
        "first_seen": now,
        "last_seen": now,
        "raw_beacon": network_data.get("raw_beacon"),
        "raw_data": network_data,
        "created_at": now,
        "updated_at": now,
    }

    table = WiFiNetwork.__table__
    insert_stmt = pg_insert(table).values(**payload)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["sensor_id", "bssid"],
        set_={
            "ssid": insert_stmt.excluded.ssid,
            "channel": insert_stmt.excluded.channel,
            "frequency": insert_stmt.excluded.frequency,
            "signal_strength": insert_stmt.excluded.signal_strength,
            "encryption": insert_stmt.excluded.encryption,
            "clients_count": insert_stmt.excluded.clients_count,
            "classification": insert_stmt.excluded.classification,
            "risk_score": insert_stmt.excluded.risk_score,
            "auth_type": insert_stmt.excluded.auth_type,
            "wps_info": insert_stmt.excluded.wps_info,
            "manufacturer": insert_stmt.excluded.manufacturer,
            "device_type": insert_stmt.excluded.device_type,
            "uptime_seconds": insert_stmt.excluded.uptime_seconds,
            "raw_beacon": insert_stmt.excluded.raw_beacon,
            "raw_data": insert_stmt.excluded.raw_data,
            "last_seen": func.now(),
            "updated_at": func.now(),
            "seen_count": table.c.seen_count + 1,
        },
    ).returning(
        table.c.id,
        table.c.seen_count,
        literal_column("xmax = 0").label("inserted"),
    )

    row = db.session.execute(upsert_stmt).one()
    return row.id, bool(row.inserted), int(row.seen_count or 1)


def _insert_scan_event(network_data: dict[str, Any], sensor_id: int, network_id: int) -> None:
    now = datetime.utcnow()
    scan_insert = NetworkScanEvent.__table__.insert().values(
        sensor_id=sensor_id,
        network_id=network_id,
        event_type=sanitize_input(str(network_data.get("classification") or "SCAN"), max_length=50) or "SCAN",
        severity=sanitize_input(str(network_data.get("severity") or "INFO"), max_length=50) or "INFO",
        risk_score=_safe_int(network_data.get("score"), default=0),
        signal_strength=_safe_int(network_data.get("signal"), default=0) or None,
        channel=_safe_int(network_data.get("channel"), default=0) or None,
        reasons=network_data.get("reasons"),
        metadata={
            "ssid": _normalize_ssid(network_data.get("ssid")),
            "bssid": _normalize_bssid(network_data.get("bssid")),
            "uptime_seconds": parse_uptime_to_seconds(network_data.get("uptime")),
            "raw_data": network_data,
        },
        scanned_at=now,
    )
    db.session.execute(scan_insert)


def _store_network_scan(network_data: dict[str, Any]) -> str:
    sensor = _resolve_sensor(
        sensor_identifier=network_data.get("sensor_id"),
        hostname=network_data.get("hostname"),
    )

    bssid = _normalize_bssid(network_data.get("bssid"))
    ssid = _normalize_ssid(network_data.get("ssid"))
    if not bssid or not validate_mac_address(bssid):
        raise ValueError(f"Invalid BSSID: {network_data.get('bssid')}")

    if not _should_write_network(sensor.id, bssid):
        return "skipped"

    LOGGER.info("[WebSocket] Received: %s (%s)", ssid, bssid)

    try:
        network_id, inserted, seen_count = _upsert_wifi_network(network_data, sensor.id, ssid, bssid)
        _insert_scan_event(network_data, sensor.id, network_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        _mark_write_failed(sensor.id, bssid)
        raise

    if inserted:
        LOGGER.info("[DB] New network stored")
        return "stored"

    LOGGER.info("[DB] Network updated (seen_count=%s)", seen_count)
    return "updated"


def _try_acquire_cleanup_lock() -> bool:
    try:
        return bool(
            db.session.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": ADVISORY_LOCK_ID},
            ).scalar()
        )
    except Exception:
        db.session.rollback()
        return False


def run_cleanup_cycle() -> tuple[int, int]:
    deleted_scan_events = 0
    deleted_networks = 0

    if not _try_acquire_cleanup_lock():
        return deleted_scan_events, deleted_networks

    try:
        deleted_scan_events = (
            db.session.query(NetworkScanEvent)
            .filter(
                NetworkScanEvent.scanned_at
                < func.now() - text(f"INTERVAL '{SCAN_RETENTION_HOURS} hours'")
            )
            .delete(synchronize_session=False)
        )
        deleted_networks = (
            db.session.query(WiFiNetwork)
            .filter(
                WiFiNetwork.last_seen
                < func.now() - text(f"INTERVAL '{NETWORK_RETENTION_HOURS} hours'")
            )
            .delete(synchronize_session=False)
        )
        db.session.commit()
        _prune_write_cache()
    except Exception:
        db.session.rollback()
        raise

    if deleted_scan_events:
        CLEANUP_LOGGER.info("[Cleanup] Deleted %s old scan records", deleted_scan_events)
    if deleted_networks:
        CLEANUP_LOGGER.info("[Cleanup] Deleted %s stale wifi networks", deleted_networks)
    return deleted_scan_events, deleted_networks


def _cleanup_loop(app) -> None:
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        with app.app_context():
            try:
                run_cleanup_cycle()
            except Exception as exc:
                db.session.rollback()
                CLEANUP_LOGGER.warning("[Cleanup] Failed: %s", exc)


def start_cleanup_thread(app) -> None:
    global _cleanup_thread_started

    with _cleanup_thread_lock:
        if _cleanup_thread_started:
            return

        cleanup_thread = threading.Thread(
            target=_cleanup_loop,
            args=(app,),
            daemon=True,
            name="zeinaguard-cleanup",
        )
        cleanup_thread.start()
        _cleanup_thread_started = True


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

    start_cleanup_thread(app)

    @socketio.on("connect")
    def handle_connect():
        client_id = request.sid
        connected_clients[client_id] = {
            "connected_at": datetime.utcnow().isoformat(),
        }

    @socketio.on("disconnect")
    def handle_disconnect():
        client_id = request.sid
        connected_clients.pop(client_id, None)

    @socketio.on("sensor_register")
    def handle_sensor_register(data):
        try:
            sensor = _resolve_sensor(
                sensor_identifier=(data or {}).get("sensor_id"),
                hostname=(data or {}).get("hostname"),
            )
            db.session.commit()
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
            emit("registration_error", {"status": "error", "message": "registration_failed"})
            LOGGER.warning("[WebSocket] Sensor registration failed: %s", exc)

    @socketio.on("network_scan")
    def handle_network_scan(payload):
        network_events = _normalize_network_events(payload)
        if not network_events:
            emit("network_scan_ack", {"status": "ignored", "processed": 0})
            return

        processed = 0
        for network_data in network_events:
            try:
                result = _store_network_scan(network_data)
                if result != "skipped":
                    processed += 1
            except Exception as exc:
                db.session.rollback()
                LOGGER.warning("[WebSocket] Failed to persist network scan: %s", exc)

        emit(
            "network_scan_ack",
            {
                "status": "ok",
                "processed": processed,
            },
        )

    @socketio.on("new_threat")
    def handle_new_threat(payload):
        ssid = _normalize_ssid((payload or {}).get("ssid"))
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
        except Exception as exc:
            db.session.rollback()
            LOGGER.warning("[WebSocket] Failed to store threat for %s: %s", ssid, exc)

    return socketio


def broadcast_threat_event(threat_data):
    socketio = current_app.socketio
    socketio.emit("threat_event", threat_data)


def broadcast_sensor_status(sensor_data):
    socketio = current_app.socketio
    socketio.emit("sensor_status", sensor_data)
