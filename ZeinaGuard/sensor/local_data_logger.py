import csv
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class LocalDataLogger:
    def __init__(self, base_dir: Path | None = None, max_bytes: int = 50 * 1024 * 1024):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent / "data-logs")
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._csv_path: Path | None = None
        self._json_path: Path | None = None
        self._csv_file = None
        self._json_file = None
        self._csv_writer = None
        self._csv_fields = [
            "timestamp",
            "sensor_id",
            "hostname",
            "ssid",
            "bssid",
            "channel",
            "signal",
            "encryption",
            "clients",
            "classification",
            "score",
            "uptime",
            "uptime_seconds",
        ]

    def log_scan(self, payload: dict[str, Any]) -> None:
        row = self._build_row(payload)

        with self._lock:
            self._ensure_handles()
            self._csv_writer.writerow(row)
            self._json_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._csv_file.flush()
            self._json_file.flush()

    def _build_row(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat(),
            "sensor_id": payload.get("sensor_id", ""),
            "hostname": payload.get("hostname", ""),
            "ssid": payload.get("ssid", "Hidden"),
            "bssid": payload.get("bssid", ""),
            "channel": payload.get("channel"),
            "signal": payload.get("signal"),
            "encryption": payload.get("encryption", "UNKNOWN"),
            "clients": payload.get("clients", 0),
            "classification": payload.get("classification", "UNKNOWN"),
            "score": payload.get("score", 0),
            "uptime": payload.get("uptime", ""),
            "uptime_seconds": payload.get("uptime_seconds", 0),
        }

    def _ensure_handles(self) -> None:
        timestamp_key = datetime.utcnow().strftime("%Y%m%d-%H")
        csv_path = self._resolve_active_path(timestamp_key, "csv")
        json_path = self._resolve_active_path(timestamp_key, "ndjson")

        if self._csv_path != csv_path:
            if self._csv_file:
                self._csv_file.close()
            file_exists = csv_path.exists()
            self._csv_file = csv_path.open("a", newline="", encoding="utf-8")
            self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=self._csv_fields)
            if not file_exists or csv_path.stat().st_size == 0:
                self._csv_writer.writeheader()
            self._csv_path = csv_path

        if self._json_path != json_path:
            if self._json_file:
                self._json_file.close()
            self._json_file = json_path.open("a", encoding="utf-8")
            self._json_path = json_path

    def _resolve_active_path(self, timestamp_key: str, extension: str) -> Path:
        index = 0
        while True:
            filename = f"wifi-scan-{timestamp_key}-{index:03d}.{extension}"
            candidate = self.base_dir / filename
            if not candidate.exists():
                return candidate
            if candidate.stat().st_size < self.max_bytes:
                return candidate
            index += 1
