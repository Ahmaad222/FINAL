"""
WebSocket server, buffered persistence, and background maintenance for ZeinaGuard.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any

from flask import current_app, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from redis import Redis
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models import NetworkScanEvent, Sensor, SensorHealth, Threat, WiFiNetwork, db
from security import sanitize_input, sanitize_json_payload, validate_mac_address


LOGGER = logging.getLogger("zeinaguard.websocket")
CLEANUP_LOGGER = logging.getLogger("zeinaguard.cleanup")

UPTIME_PART_PATTERN = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
connected_clients: dict[str, dict[str, Any]] = {}

NETWORK_UPDATE_INTERVAL_SECONDS = float(os.getenv("NETWORK_UPDATE_INTERVAL_SECONDS", "7"))
BATCH_FLUSH_INTERVAL_SECONDS = float(os.getenv("NETWORK_BATCH_FLUSH_INTERVAL_SECONDS", "1"))
BATCH_SIZE_LIMIT = int(os.getenv("NETWORK_BATCH_SIZE_LIMIT", "200"))
NETWORK_LOG_INTERVAL_SECONDS = float(os.getenv("NETWORK_LOG_INTERVAL_SECONDS", "30"))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "600"))
SCAN_RETENTION_HOURS = int(os.getenv("NETWORK_SCAN_RETENTION_HOURS", "6"))
THREAT_RETENTION_HOURS = int(os.getenv("THREAT_RETENTION_HOURS", "24"))
NETWORK_RETENTION_HOURS = int(os.getenv("WIFI_NETWORK_RETENTION_HOURS", "48"))
THREAT_DEDUPE_WINDOW_SECONDS = int(os.getenv("THREAT_DEDUPE_WINDOW_SECONDS", "60"))
THREAT_MAX_ROWS = int(os.getenv("THREAT_MAX_ROWS", "50000"))
SCAN_EVENT_MAX_ROWS = int(os.getenv("NETWORK_SCAN_EVENT_MAX_ROWS", "250000"))
WIFI_NETWORK_MAX_ROWS = int(os.getenv("WIFI_NETWORK_MAX_ROWS", "50000"))
ADVISORY_LOCK_ID = int(os.getenv("ZEINAGUARD_CLEANUP_LOCK_ID", "240416"))
OUI_DB_PATH = Path(__file__).resolve().parent.parent / "sensor" / "oui_db.json"

NETWORK_SCAN_EVENT = "network_scan"
NETWORK_UPDATE_EVENT = "network_update"
THREAT_DETECTED_EVENT = "threat_detected"
ATTACK_COMMAND_EVENT = "attack_command"
ATTACK_ACK_EVENT = "attack_ack"
SENSOR_STATUS_EVENT = "sensor_status"
DASHBOARD_ROOM = "dashboards"

_sensor_id_cache: dict[str, int] = {}
_sensor_id_cache_lock = threading.Lock()
_cleanup_thread_started = False
_cleanup_thread_lock = threading.Lock()
_persistence_manager = None
_persistence_manager_lock = threading.Lock()
_recent_threat_event_cache: dict[tuple[int, str], float] = {}
_oui_db: dict[str, str] = {}


try:
    redis_client = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
except Exception:
    redis_client = None


@dataclass
class QueuedNetworkEvent:
    sensor_identifier: str
    hostname: str
    bssid: str
    ssid: str
    channel: int | None
    signal_strength: int | None
    encryption: str
    clients_count: int
    classification: str
    risk_score: int
    auth_type: str | None
    wps_info: Any
    manufacturer: str | None
    device_type: str
    uptime_seconds: int
    raw_beacon: str | None
    raw_data: dict[str, Any]
    reasons: Any
    severity: str
    observed_at: datetime
    fingerprint: tuple[Any, ...]


@dataclass
class BufferedNetworkUpdate:
    sensor_id: int
    bssid: str
    ssid: str
    channel: int | None
    frequency: int | None
    signal_strength: int | None
    encryption: str
    clients_count: int
    classification: str
    risk_score: int
    auth_type: str | None
    wps_info: Any
    manufacturer: str | None
    device_type: str
    uptime_seconds: int
    raw_beacon: str | None
    raw_data: dict[str, Any]
    reasons: Any
    severity: str
    seen_increment: int
    first_seen: datetime
    last_seen: datetime
    fingerprint: tuple[Any, ...]


@dataclass
class FlushResult:
    persisted_keys: set[tuple[int, str]]
    inserted_updates: list[BufferedNetworkUpdate]
    updated_updates: list[BufferedNetworkUpdate]
    inserted_count: int
    updated_count: int
    scan_event_count: int


class ScanPersistenceManager:
    def __init__(self, app):
        self.app = app
        self._ingest_queue: Queue[QueuedNetworkEvent] = Queue(maxsize=max(BATCH_SIZE_LIMIT * 20, 1000))
        self._pending_updates: dict[tuple[int, str], BufferedNetworkUpdate] = {}
        self._recent_cache: dict[tuple[int, str], float] = {}
        self._stats_lock = threading.Lock()
        self._stats = {
            "inserted": 0,
            "updated": 0,
            "scan_events": 0,
            "dropped": 0,
            "flushes": 0,
        }
        self._last_summary_log = time.monotonic()
        self._thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="zeinaguard-network-persistence",
        )
        self._thread.start()

    def ingest(self, network_data: dict[str, Any]) -> bool:
        queued_event = self._build_queued_event(sanitize_json_payload(network_data))
        try:
            self._ingest_queue.put_nowait(queued_event)
        except Full:
            with self._stats_lock:
                self._stats["dropped"] += 1
            LOGGER.warning("[WebSocket] Ingest queue is full, dropping: %s (%s)", queued_event.ssid, queued_event.bssid)
            return False

        return True

    def _build_queued_event(self, network_data: dict[str, Any]) -> QueuedNetworkEvent:
        bssid = _normalize_bssid(network_data.get("bssid"))
        ssid = _normalize_ssid(network_data.get("ssid"))
        if not bssid or not validate_mac_address(bssid):
            raise ValueError(f"Invalid BSSID: {network_data.get('bssid')}")

        channel = _safe_int(network_data.get("channel"), default=0) or None
        signal_strength = _safe_int(network_data.get("signal"), default=0) or None
        clients_count = _safe_int(network_data.get("clients"), default=0)
        risk_score = _safe_int(network_data.get("score"), default=0)
        uptime_seconds = _safe_int(
            network_data.get("uptime_seconds"),
            default=parse_uptime_to_seconds(network_data.get("uptime")),
        )
        encryption = sanitize_input(str(network_data.get("encryption") or "UNKNOWN"), max_length=50)
        classification = _normalize_classification(network_data.get("classification"))
        auth_type = sanitize_input(
            str(network_data.get("auth_type") or network_data.get("auth") or ""),
            max_length=50,
        ) or None
        manufacturer = _enrich_manufacturer(bssid, network_data.get("manufacturer"))
        device_type = sanitize_input(str(network_data.get("device_type") or "AP"), max_length=50) or "AP"
        severity = _normalize_severity(network_data.get("severity"), classification)

        return QueuedNetworkEvent(
            sensor_identifier=sanitize_input(str(network_data.get("sensor_id") or ""), max_length=255) or "sensor",
            hostname=sanitize_input(str(network_data.get("hostname") or ""), max_length=255) or "sensor",
            bssid=bssid,
            ssid=ssid,
            channel=channel,
            signal_strength=signal_strength,
            encryption=encryption,
            clients_count=clients_count,
            classification=classification,
            risk_score=risk_score,
            auth_type=auth_type,
            wps_info=network_data.get("wps_info") or network_data.get("wps"),
            manufacturer=manufacturer,
            device_type=device_type,
            uptime_seconds=uptime_seconds,
            raw_beacon=network_data.get("raw_beacon"),
            raw_data=network_data,
            reasons=network_data.get("reasons"),
            severity=severity,
            observed_at=datetime.utcnow(),
            fingerprint=(
                ssid,
                channel,
                signal_strength,
                encryption,
                clients_count,
                classification,
                risk_score,
                auth_type,
                manufacturer,
                device_type,
                uptime_seconds,
            ),
        )

    def _to_buffered_update(self, sensor_id: int, event: QueuedNetworkEvent) -> BufferedNetworkUpdate:
        return BufferedNetworkUpdate(
            sensor_id=sensor_id,
            bssid=event.bssid,
            ssid=event.ssid,
            channel=event.channel,
            frequency=_calculate_frequency(event.channel),
            signal_strength=event.signal_strength,
            encryption=event.encryption,
            clients_count=event.clients_count,
            classification=event.classification,
            risk_score=event.risk_score,
            auth_type=event.auth_type,
            wps_info=event.wps_info,
            manufacturer=event.manufacturer,
            device_type=event.device_type,
            uptime_seconds=event.uptime_seconds,
            raw_beacon=event.raw_beacon,
            raw_data=event.raw_data,
            reasons=event.reasons,
            severity=event.severity,
            seen_increment=1,
            first_seen=event.observed_at,
            last_seen=event.observed_at,
            fingerprint=event.fingerprint,
        )

    def _merge_update(self, pending: BufferedNetworkUpdate, incoming: BufferedNetworkUpdate) -> None:
        pending.ssid = incoming.ssid
        pending.channel = incoming.channel
        pending.frequency = incoming.frequency
        pending.signal_strength = incoming.signal_strength
        pending.encryption = incoming.encryption
        pending.clients_count = incoming.clients_count
        pending.classification = incoming.classification
        pending.risk_score = incoming.risk_score
        pending.auth_type = incoming.auth_type
        pending.wps_info = incoming.wps_info
        pending.manufacturer = incoming.manufacturer
        pending.device_type = incoming.device_type
        pending.uptime_seconds = incoming.uptime_seconds
        pending.raw_beacon = incoming.raw_beacon
        pending.raw_data = incoming.raw_data
        pending.reasons = incoming.reasons
        pending.severity = incoming.severity
        pending.last_seen = incoming.last_seen
        pending.fingerprint = incoming.fingerprint

    def _worker_loop(self) -> None:
        with self.app.app_context():
            next_flush_deadline = time.monotonic() + BATCH_FLUSH_INTERVAL_SECONDS
            while True:
                timeout = max(0.1, next_flush_deadline - time.monotonic())

                try:
                    queued_event = self._ingest_queue.get(timeout=timeout)
                    self._consume_event(queued_event)
                except Empty:
                    pass
                except Exception as exc:
                    db.session.rollback()
                    LOGGER.warning("[WebSocket] Worker ingest failed: %s", exc)

                if len(self._pending_updates) >= BATCH_SIZE_LIMIT or time.monotonic() >= next_flush_deadline:
                    self.flush()
                    next_flush_deadline = time.monotonic() + BATCH_FLUSH_INTERVAL_SECONDS

    def _consume_event(self, queued_event: QueuedNetworkEvent) -> None:
        sensor = _resolve_sensor(
            sensor_identifier=queued_event.sensor_identifier,
            hostname=queued_event.hostname,
        )
        cache_key = (sensor.id, queued_event.bssid)
        pending = self._pending_updates.get(cache_key)
        incoming = self._to_buffered_update(sensor.id, queued_event)

        if pending is None:
            self._pending_updates[cache_key] = incoming
        else:
            pending.seen_increment += 1
            self._merge_update(pending, incoming)

    def flush(self) -> None:
        ready_keys = self._collect_ready_keys()
        if not ready_keys:
            self._prune_recent_cache()
            self._log_periodic_summary()
            return

        batch = {key: self._pending_updates.pop(key) for key in ready_keys}
        self._prune_recent_cache()

        try:
            flushed_at = time.monotonic()
            flush_result = self._flush_batch(batch)
            for key in flush_result.persisted_keys:
                self._recent_cache[key] = flushed_at
            self._record_flush_result(flush_result)
            self._broadcast_flush_result(flush_result)
        except Exception as exc:
            db.session.rollback()
            for key, update in batch.items():
                existing = self._pending_updates.get(key)
                if existing is None:
                    self._pending_updates[key] = update
                else:
                    existing.seen_increment += update.seen_increment
                    self._merge_update(existing, update)
            LOGGER.warning("[DB] Batch flush failed: %s", exc)
        finally:
            self._log_periodic_summary()
            db.session.remove()

    def _collect_ready_keys(self) -> list[tuple[int, str]]:
        now = time.monotonic()
        ready_keys: list[tuple[int, str]] = []
        for key in self._pending_updates:
            last_persisted = self._recent_cache.get(key)
            if last_persisted is None:
                ready_keys.append(key)
                continue

            elapsed = now - last_persisted
            if elapsed >= NETWORK_UPDATE_INTERVAL_SECONDS:
                ready_keys.append(key)

        return ready_keys

    def _flush_batch(self, batch: dict[tuple[int, str], BufferedNetworkUpdate]) -> FlushResult:
        updates = list(batch.values())
        wifi_rows = [
            {
                "sensor_id": update.sensor_id,
                "ssid": update.ssid,
                "bssid": update.bssid,
                "channel": update.channel,
                "frequency": update.frequency,
                "signal_strength": update.signal_strength,
                "encryption": update.encryption,
                "clients_count": update.clients_count,
                "classification": update.classification,
                "risk_score": update.risk_score,
                "auth_type": update.auth_type,
                "wps_info": update.wps_info,
                "manufacturer": update.manufacturer,
                "device_type": update.device_type,
                "uptime_seconds": update.uptime_seconds,
                "seen_count": update.seen_increment,
                "first_seen": update.first_seen,
                "last_seen": update.last_seen,
                "raw_beacon": update.raw_beacon,
                "raw_data": update.raw_data,
                "created_at": update.first_seen,
                "updated_at": update.last_seen,
            }
            for update in updates
        ]

        wifi_table = WiFiNetwork.__table__
        insert_stmt = pg_insert(wifi_table).values(wifi_rows)
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
                "last_seen": insert_stmt.excluded.last_seen,
                "updated_at": func.now(),
                "seen_count": wifi_table.c.seen_count + insert_stmt.excluded.seen_count,
            },
        ).returning(
            wifi_table.c.id,
            wifi_table.c.sensor_id,
            wifi_table.c.bssid,
            wifi_table.c.seen_count,
            literal_column("xmax = 0").label("inserted"),
        )

        result_rows = db.session.execute(upsert_stmt).all()
        network_id_map = {
            (row.sensor_id, row.bssid): row.id
            for row in result_rows
        }
        persisted_keys = set(network_id_map.keys())
        inserted_count = sum(1 for row in result_rows if row.inserted)
        updated_count = len(result_rows) - inserted_count
        inserted_updates = [
            batch[(row.sensor_id, row.bssid)]
            for row in result_rows
            if row.inserted
        ]
        updated_updates = [
            batch[(row.sensor_id, row.bssid)]
            for row in result_rows
            if not row.inserted
        ]

        scan_rows = [
            {
                "sensor_id": update.sensor_id,
                "network_id": network_id_map[(update.sensor_id, update.bssid)],
                "event_type": update.classification or "SCAN",
                "severity": update.severity,
                "risk_score": update.risk_score,
                "signal_strength": update.signal_strength,
                "channel": update.channel,
                "metadata": {
                    "ssid": update.ssid,
                    "bssid": update.bssid,
                    "uptime_seconds": update.uptime_seconds,
                    "seen_increment": update.seen_increment,
                    "raw_data": update.raw_data,
                },
                "reasons": update.reasons,
                "scanned_at": update.last_seen,
            }
            for update in updates
        ]

        if scan_rows:
            db.session.execute(NetworkScanEvent.__table__.insert(), scan_rows)

        db.session.commit()

        return FlushResult(
            persisted_keys=persisted_keys,
            inserted_updates=inserted_updates,
            updated_updates=updated_updates,
            inserted_count=inserted_count,
            updated_count=updated_count,
            scan_event_count=len(scan_rows),
        )

    def _record_flush_result(self, flush_result: FlushResult) -> None:
        with self._stats_lock:
            self._stats["inserted"] += flush_result.inserted_count
            self._stats["updated"] += flush_result.updated_count
            self._stats["scan_events"] += flush_result.scan_event_count
            self._stats["flushes"] += 1

        for update in flush_result.inserted_updates:
            LOGGER.debug(
                "[DB] New Network: sensor=%s ssid=%s bssid=%s channel=%s signal=%s classification=%s risk=%s",
                update.sensor_id,
                update.ssid,
                update.bssid,
                update.channel if update.channel is not None else "-",
                update.signal_strength if update.signal_strength is not None else "-",
                update.classification,
                update.risk_score,
            )

    def _broadcast_flush_result(self, flush_result: FlushResult) -> None:
        socketio = getattr(self.app, "socketio", None)
        if socketio is None:
            return

        for update in flush_result.inserted_updates:
            _broadcast_network_event(socketio, NETWORK_SCAN_EVENT, update)

        for update in flush_result.updated_updates:
            _broadcast_network_event(socketio, NETWORK_UPDATE_EVENT, update)

    def _log_periodic_summary(self, force: bool = False) -> None:
        now = time.monotonic()
        elapsed = now - self._last_summary_log
        if not force and elapsed < NETWORK_LOG_INTERVAL_SECONDS:
            return

        with self._stats_lock:
            stats_snapshot = dict(self._stats)
            if not any(stats_snapshot.values()):
                self._last_summary_log = now
                return
            self._stats = {
                "inserted": 0,
                "updated": 0,
                "scan_events": 0,
                "dropped": 0,
                "flushes": 0,
            }

        LOGGER.info(
            "[DB] 30s summary: flushes=%s new=%s updated=%s scan_events=%s dropped=%s pending=%s queue=%s",
            stats_snapshot["flushes"],
            stats_snapshot["inserted"],
            stats_snapshot["updated"],
            stats_snapshot["scan_events"],
            stats_snapshot["dropped"],
            len(self._pending_updates),
            self._ingest_queue.qsize(),
        )
        self._last_summary_log = now

    def _prune_recent_cache(self) -> None:
        cutoff = time.monotonic() - max(NETWORK_UPDATE_INTERVAL_SECONDS * 4, 300)
        stale_keys = [key for key, value in self._recent_cache.items() if value < cutoff]
        for key in stale_keys:
            self._recent_cache.pop(key, None)


def configure_socket_logging() -> None:
    logging.getLogger("engineio").setLevel(logging.ERROR)
    logging.getLogger("socketio").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.ERROR)


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
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


def _normalize_classification(value: Any) -> str:
    normalized = sanitize_input(str(value or "LEGIT"), max_length=50).upper()
    if normalized not in {"ROGUE", "SUSPICIOUS", "LEGIT"}:
        return "LEGIT"
    return normalized


def _normalize_severity(value: Any, classification: str | None = None) -> str:
    normalized = sanitize_input(str(value or ""), max_length=50).lower()
    if normalized in {"critical", "high", "medium", "low", "info"}:
        return normalized

    if classification == "ROGUE":
        return "high"
    if classification == "SUSPICIOUS":
        return "medium"
    return "info"


def _normalize_threat_type(value: Any) -> str:
    return sanitize_input(str(value or "UNKNOWN"), max_length=100) or "UNKNOWN"


def _normalize_oui(bssid: str | None) -> str:
    normalized_bssid = _normalize_bssid(bssid)
    parts = normalized_bssid.split(":")
    if len(parts) < 3:
        return ""
    return ":".join(parts[:3])


def _load_oui_db() -> dict[str, str]:
    global _oui_db

    if _oui_db:
        return _oui_db

    try:
        with OUI_DB_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            _oui_db = {str(key).upper(): str(value) for key, value in data.items()}
    except Exception:
        _oui_db = {}

    return _oui_db


def _enrich_manufacturer(bssid: str | None, manufacturer: str | None) -> str | None:
    normalized = sanitize_input(str(manufacturer or ""), max_length=255) or None
    if normalized and normalized.lower() != "unknown":
        return normalized

    oui = _normalize_oui(bssid)
    if not oui:
        return None

    return _load_oui_db().get(oui)


def _find_recent_duplicate_threat(threat_type: str, source_mac: str | None) -> Threat | None:
    if not source_mac:
        return None

    cutoff = datetime.utcnow() - timedelta(seconds=THREAT_DEDUPE_WINDOW_SECONDS)
    return (
        Threat.query.filter(
            Threat.source_mac == source_mac,
            Threat.threat_type == threat_type,
            Threat.created_at >= cutoff,
        )
        .order_by(Threat.created_at.desc())
        .first()
    )


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


def _sensor_room(sensor_id: int) -> str:
    return f"sensor:{sensor_id}"


def _log_emit(event_name: str, payload: Any, room: str | None = None) -> None:
    if isinstance(payload, dict):
        preview = {
            key: payload.get(key)
            for key in (
                "sensor_id",
                "ssid",
                "bssid",
                "classification",
                "status",
                "action",
                "target_bssid",
                "channel",
                "timestamp",
            )
            if key in payload
        }
    else:
        preview = payload

    if room:
        if room == DASHBOARD_ROOM:
            LOGGER.info("[EMIT TO DASHBOARD] event=%s payload=%s", event_name, preview)
        elif room.startswith("sensor:"):
            LOGGER.info("[FORWARD COMMAND] event=%s room=%s payload=%s", event_name, room, preview)
        else:
            LOGGER.info("[WebSocket] emit %s room=%s payload=%s", event_name, room, preview)
    else:
        LOGGER.info("[WebSocket] emit %s payload=%s", event_name, preview)


def _emit_socket_event(socketio: SocketIO, event_name: str, payload: Any, room: str | None = None) -> None:
    _log_emit(event_name, payload, room=room)
    socketio.emit(event_name, payload, room=room)


def _emit_context_event(event_name: str, payload: Any) -> None:
    _log_emit(event_name, payload, room=request.sid)
    emit(event_name, payload)


def _log_received_from_sensor(event_name: str, payload: Any) -> None:
    if isinstance(payload, dict):
        preview = {
            key: payload.get(key)
            for key in (
                "event",
                "sensor_id",
                "ssid",
                "bssid",
                "status",
                "target_bssid",
                "action",
                "channel",
            )
            if key in payload
        }
    else:
        preview = payload
    LOGGER.info("[RECEIVED FROM SENSOR] event=%s payload=%s", event_name, preview)


def _format_network_contract(update: BufferedNetworkUpdate) -> dict[str, Any]:
    return {
        "sensor_id": update.sensor_id,
        "ssid": update.ssid,
        "bssid": update.bssid,
        "signal": update.signal_strength,
        "channel": update.channel,
        "classification": _normalize_classification(update.classification),
        "timestamp": update.last_seen.isoformat(),
        "manufacturer": _enrich_manufacturer(update.bssid, update.manufacturer),
    }


def _broadcast_network_event(socketio: SocketIO, event_name: str, update: BufferedNetworkUpdate) -> None:
    payload = _format_network_contract(update)
    _emit_socket_event(socketio, event_name, payload, room=DASHBOARD_ROOM)


def _should_emit_threat_event(sensor_id: int, bssid: str) -> bool:
    now = time.monotonic()
    key = (sensor_id, bssid)
    last_emitted = _recent_threat_event_cache.get(key)
    if last_emitted is not None and (now - last_emitted) < THREAT_DEDUPE_WINDOW_SECONDS:
        return False

    _recent_threat_event_cache[key] = now
    stale_cutoff = now - max(THREAT_DEDUPE_WINDOW_SECONDS * 4, 300)
    stale_keys = [cache_key for cache_key, value in _recent_threat_event_cache.items() if value < stale_cutoff]
    for stale_key in stale_keys:
        _recent_threat_event_cache.pop(stale_key, None)
    return True


def _persist_sensor_status(sensor_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    sensor = db.session.get(Sensor, sensor_id)
    if sensor is None:
        raise ValueError(f"Unknown sensor_id: {sensor_id}")

    status = sanitize_input(str(payload.get("status") or "online"), max_length=50) or "online"
    heartbeat = SensorHealth(
        sensor_id=sensor_id,
        status=status,
        signal_strength=_safe_int(payload.get("signal_strength"), default=0),
        cpu_usage=_safe_float(payload.get("cpu_usage", payload.get("cpu")), default=0.0),
        memory_usage=_safe_float(payload.get("memory_usage", payload.get("memory")), default=0.0),
        uptime=_safe_int(payload.get("uptime"), default=0),
        last_heartbeat=datetime.utcnow(),
    )
    db.session.add(heartbeat)
    sensor.is_active = status != "offline"
    sensor.updated_at = datetime.utcnow()
    db.session.commit()

    return {
        "event": "sensor_status",
        "sensor_id": sensor.id,
        "status": status,
        "signal_strength": heartbeat.signal_strength,
        "cpu": heartbeat.cpu_usage,
        "cpu_usage": heartbeat.cpu_usage,
        "memory": heartbeat.memory_usage,
        "memory_usage": heartbeat.memory_usage,
        "uptime": heartbeat.uptime,
        "last_heartbeat": heartbeat.last_heartbeat.isoformat(),
        "message": sanitize_input(str(payload.get("message") or ""), max_length=255) or None,
        "interface": sanitize_input(str(payload.get("interface") or ""), max_length=255) or None,
    }


def _normalize_network_events(payload: Any) -> list[dict[str, Any]]:
    payload = sanitize_json_payload(payload)

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


def _get_persistence_manager(app) -> ScanPersistenceManager:
    global _persistence_manager

    with _persistence_manager_lock:
        if _persistence_manager is None:
            _persistence_manager = ScanPersistenceManager(app)
        return _persistence_manager


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


def _apply_row_cap(model, time_column, max_rows: int) -> int:
    if max_rows <= 0:
        return 0

    total_rows = db.session.query(func.count(model.id)).scalar() or 0
    overflow = total_rows - max_rows
    if overflow <= 0:
        return 0

    oldest_rows = (
        select(model.id)
        .order_by(time_column.asc(), model.id.asc())
        .limit(overflow)
        .subquery()
    )

    return (
        db.session.query(model)
        .filter(model.id.in_(select(oldest_rows.c.id)))
        .delete(synchronize_session=False)
    )


def run_cleanup_cycle() -> tuple[int, int, int]:
    deleted_threats = 0
    deleted_scan_events = 0
    deleted_networks = 0

    if not _try_acquire_cleanup_lock():
        return deleted_threats, deleted_scan_events, deleted_networks

    try:
        deleted_threats = (
            db.session.query(Threat)
            .filter(
                Threat.created_at
                < func.now() - text(f"INTERVAL '{THREAT_RETENTION_HOURS} hours'")
            )
            .delete(synchronize_session=False)
        )
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
        deleted_threats += _apply_row_cap(Threat, Threat.created_at, THREAT_MAX_ROWS)
        deleted_scan_events += _apply_row_cap(
            NetworkScanEvent,
            NetworkScanEvent.scanned_at,
            SCAN_EVENT_MAX_ROWS,
        )
        deleted_networks += _apply_row_cap(WiFiNetwork, WiFiNetwork.last_seen, WIFI_NETWORK_MAX_ROWS)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    if deleted_threats:
        CLEANUP_LOGGER.info("[Cleanup] Deleted %s old threat records", deleted_threats)
    if deleted_scan_events:
        CLEANUP_LOGGER.info("[Cleanup] Deleted %s old scan records", deleted_scan_events)
    if deleted_networks:
        CLEANUP_LOGGER.info("[Cleanup] Deleted %s stale wifi networks", deleted_networks)
    return deleted_threats, deleted_scan_events, deleted_networks


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
    persistence_manager = _get_persistence_manager(app)

    @socketio.on("connect")
    def handle_connect():
        client_id = request.sid
        join_room(DASHBOARD_ROOM)
        connected_clients[client_id] = {
            "connected_at": datetime.utcnow().isoformat(),
            "client_type": "dashboard",
        }
        _emit_context_event(
            "connection_response",
            {
                "status": "connected",
                "sid": client_id,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    @socketio.on("disconnect")
    def handle_disconnect():
        client_id = request.sid
        client_info = connected_clients.pop(client_id, None) or {}
        sensor_id = client_info.get("sensor_id")
        if client_info.get("client_type") == "sensor" and sensor_id:
            try:
                status_payload = _persist_sensor_status(
                    int(sensor_id),
                    {
                        "status": "offline",
                        "message": "Sensor disconnected",
                    },
                )
                _emit_socket_event(socketio, SENSOR_STATUS_EVENT, status_payload, room=DASHBOARD_ROOM)
            except Exception as exc:
                db.session.rollback()
                LOGGER.warning("[WebSocket] Failed to persist offline status for sensor %s: %s", sensor_id, exc)

    @socketio.on("sensor_register")
    def handle_sensor_register(data):
        data = sanitize_json_payload(data or {})
        try:
            _log_received_from_sensor("sensor_register", data)
            sensor = _resolve_sensor(
                sensor_identifier=data.get("sensor_id"),
                hostname=data.get("hostname"),
            )
            db.session.commit()
            connected_clients[request.sid] = {
                "connected_at": datetime.utcnow().isoformat(),
                "client_type": "sensor",
                "sensor_id": sensor.id,
                "hostname": sensor.hostname,
            }
            leave_room(DASHBOARD_ROOM)
            join_room(_sensor_room(sensor.id))
            _emit_context_event(
                "registration_success",
                {
                    "status": "registered",
                    "sensor_id": sensor.id,
                    "sensor_name": sensor.name,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            status_payload = _persist_sensor_status(
                sensor.id,
                {
                    "status": "online",
                    "message": "Sensor registered",
                },
            )
            _emit_socket_event(socketio, SENSOR_STATUS_EVENT, status_payload, room=DASHBOARD_ROOM)
        except Exception as exc:
            db.session.rollback()
            _emit_context_event("registration_error", {"status": "error", "message": "registration_failed"})
            LOGGER.warning("[WebSocket] Sensor registration failed: %s", exc)

    @socketio.on(NETWORK_SCAN_EVENT)
    def handle_network_scan(payload):
        payload = sanitize_json_payload(payload)
        network_events = _normalize_network_events(payload)
        if not network_events:
            _emit_context_event("network_scan_ack", {"status": "ignored", "queued": 0})
            return

        queued = 0
        for network_data in network_events:
            try:
                _log_received_from_sensor(NETWORK_SCAN_EVENT, network_data)
                if persistence_manager.ingest(network_data):
                    queued += 1
            except Exception as exc:
                db.session.rollback()
                LOGGER.warning("[WebSocket] Failed to ingest network scan: %s", exc)

        _emit_context_event(
            "network_scan_ack",
            {
                "status": "ok",
                "queued": queued,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    @socketio.on("new_threat")
    def handle_new_threat(payload):
        payload = sanitize_json_payload(payload or {})
        ssid = _normalize_ssid(payload.get("ssid"))
        try:
            _log_received_from_sensor("new_threat", payload)
            classification = _normalize_classification(payload.get("classification"))
            threat_type = _normalize_threat_type(payload.get("threat_type") or classification)
            source_mac = _normalize_bssid(payload.get("source_mac") or payload.get("bssid"))
            duplicate_threat = _find_recent_duplicate_threat(threat_type, source_mac)
            if duplicate_threat is not None:
                LOGGER.info(
                    "[WebSocket] Suppressed duplicate threat: %s %s",
                    threat_type,
                    source_mac,
                )
                return

            new_threat = Threat(
                threat_type=threat_type,
                severity=_normalize_severity(payload.get("severity"), classification),
                source_mac=source_mac or None,
                ssid=ssid,
                description="Detected via Sensor WebSocket",
                detected_by=_safe_int(payload.get("sensor_id"), default=0) or None,
            )
            db.session.add(new_threat)
            db.session.commit()
            event_payload = {
                "sensor_id": _safe_int(payload.get("sensor_id"), default=new_threat.detected_by or 0),
                "ssid": ssid,
                "bssid": source_mac or None,
                "signal": _safe_int(payload.get("signal"), default=0) or None,
                "channel": _safe_int(payload.get("channel"), default=0) or None,
                "classification": classification,
                "timestamp": datetime.utcnow().isoformat(),
                "manufacturer": _enrich_manufacturer(source_mac, payload.get("manufacturer")),
                "threat_id": new_threat.id,
                "severity": new_threat.severity,
            }
            if event_payload["sensor_id"] and source_mac and _should_emit_threat_event(event_payload["sensor_id"], source_mac):
                _emit_socket_event(socketio, THREAT_DETECTED_EVENT, event_payload, room=DASHBOARD_ROOM)
            _emit_socket_event(
                socketio,
                "threat_event",
                {
                    "id": new_threat.id,
                    "type": THREAT_DETECTED_EVENT,
                    "timestamp": event_payload["timestamp"],
                    "severity": new_threat.severity,
                    "data": {
                        "id": new_threat.id,
                        "threat_type": new_threat.threat_type,
                        "severity": new_threat.severity,
                        "source_mac": new_threat.source_mac,
                        "ssid": new_threat.ssid,
                        "detected_by": new_threat.detected_by,
                        "description": new_threat.description,
                        "signal_strength": event_payload["signal"],
                        "packet_count": 0,
                        "is_resolved": new_threat.is_resolved,
                        "created_at": new_threat.created_at.isoformat(),
                    },
                },
                room=DASHBOARD_ROOM,
            )
        except Exception as exc:
            db.session.rollback()
            LOGGER.warning("[WebSocket] Failed to store threat for %s: %s", ssid, exc)

    @socketio.on(SENSOR_STATUS_EVENT)
    def handle_sensor_status(payload):
        payload = sanitize_json_payload(payload or {})
        try:
            _log_received_from_sensor(SENSOR_STATUS_EVENT, payload)
            sensor_id = _safe_int(payload.get("sensor_id"), default=0)
            if not sensor_id:
                sensor_info = connected_clients.get(request.sid) or {}
                sensor_id = _safe_int(sensor_info.get("sensor_id"), default=0)
            if not sensor_id:
                raise ValueError("sensor_status missing sensor_id")

            status_payload = _persist_sensor_status(sensor_id, payload)
            if request.sid in connected_clients:
                connected_clients[request.sid]["sensor_id"] = sensor_id
                connected_clients[request.sid]["client_type"] = "sensor"
            _emit_socket_event(socketio, SENSOR_STATUS_EVENT, status_payload, room=DASHBOARD_ROOM)
        except Exception as exc:
            db.session.rollback()
            LOGGER.warning("[WebSocket] Failed to persist sensor status: %s", exc)

    @socketio.on(ATTACK_COMMAND_EVENT)
    def handle_attack_command(payload):
        payload = sanitize_json_payload(payload or {})
        try:
            sensor_id = _safe_int(payload.get("sensor_id"), default=0)
            target_bssid = _normalize_bssid(payload.get("target_bssid") or payload.get("bssid"))
            action = sanitize_input(str(payload.get("action") or "deauth"), max_length=50) or "deauth"
            channel = _safe_int(payload.get("channel"), default=0) or None

            if not sensor_id:
                raise ValueError("attack_command missing sensor_id")
            if not target_bssid:
                raise ValueError("attack_command missing target_bssid")
            if channel is None:
                raise ValueError("attack_command missing channel")
            sensor = db.session.get(Sensor, sensor_id)
            if sensor is None:
                raise ValueError(f"Sensor {sensor_id} does not exist")

            room = _sensor_room(sensor_id)
            if not any(
                client.get("client_type") == "sensor" and _safe_int(client.get("sensor_id"), default=0) == sensor_id
                for client in connected_clients.values()
            ):
                raise ValueError(f"Sensor {sensor_id} is not connected")
            command_payload = {
                "sensor_id": sensor_id,
                "action": action,
                "target_bssid": target_bssid,
                "channel": channel,
            }
            _emit_socket_event(socketio, ATTACK_COMMAND_EVENT, {**command_payload, "sensor_id": sensor_id, "timestamp": datetime.utcnow().isoformat(), "status": "dispatched"}, room=DASHBOARD_ROOM)
            _emit_socket_event(socketio, ATTACK_COMMAND_EVENT, command_payload, room=room)
            _emit_context_event(
                "attack_command_ack",
                {
                    "status": "ok",
                    "sensor_id": sensor_id,
                    "target_bssid": target_bssid,
                    "channel": channel,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
        except Exception as exc:
            LOGGER.warning("[WebSocket] attack_command rejected: %s", exc)
            _emit_context_event(
                "attack_command_ack",
                {
                    "status": "error",
                    "message": str(exc),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

    @socketio.on(ATTACK_ACK_EVENT)
    def handle_attack_ack(payload):
        payload = sanitize_json_payload(payload or {})
        try:
            _log_received_from_sensor(ATTACK_ACK_EVENT, payload)
            sensor_id = _safe_int(payload.get("sensor_id"), default=0)
            if not sensor_id:
                sensor_info = connected_clients.get(request.sid) or {}
                sensor_id = _safe_int(sensor_info.get("sensor_id"), default=0)
            if not sensor_id:
                raise ValueError("attack_ack missing sensor_id")

            ack_payload = {
                "event": "attack_ack",
                "status": sanitize_input(str(payload.get("status") or "failed"), max_length=50) or "failed",
                "target_bssid": _normalize_bssid(payload.get("target_bssid")),
                "sensor_id": sensor_id,
                "message": sanitize_input(str(payload.get("message") or ""), max_length=255) or None,
                "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat(),
            }
            _emit_socket_event(socketio, ATTACK_ACK_EVENT, ack_payload, room=DASHBOARD_ROOM)
        except Exception as exc:
            LOGGER.warning("[WebSocket] Failed to handle attack_ack: %s", exc)

    return socketio


def broadcast_threat_event(threat_data):
    socketio = current_app.socketio
    _emit_socket_event(socketio, THREAT_DETECTED_EVENT, threat_data, room=DASHBOARD_ROOM)
    _emit_socket_event(socketio, "threat_event", threat_data, room=DASHBOARD_ROOM)


def broadcast_sensor_status(sensor_data):
    socketio = current_app.socketio
    _emit_socket_event(socketio, SENSOR_STATUS_EVENT, sensor_data, room=DASHBOARD_ROOM)
