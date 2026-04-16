import threading
import time
from collections import deque

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table


console = Console()
lock = threading.Lock()

aps_view = {}
recent_sent = deque(maxlen=12)
status_state = {
    "sensor_status": "starting",
    "backend_status": "offline",
    "message": "Booting sensor",
    "sent_count": 0,
}


def update_ap(event_summary):
    with lock:
        event_summary["last_seen"] = time.time()
        aps_view[event_summary["bssid"]] = event_summary


def remove_ap(bssid):
    with lock:
        aps_view.pop(bssid, None)


def update_status(sensor_status=None, backend_status=None, message=None):
    with lock:
        if sensor_status is not None:
            status_state["sensor_status"] = sensor_status
        if backend_status is not None:
            status_state["backend_status"] = backend_status
        if message is not None:
            status_state["message"] = message


def mark_sent(event_summary):
    batch_size = int(event_summary.get("batch_size") or 1)
    if batch_size > 1:
        ssid = event_summary.get("ssid") or "Hidden"
        line = f"Sent batch: {batch_size} networks (latest {ssid})"
    else:
        ssid = event_summary.get("ssid") or "Hidden"
        bssid = event_summary.get("bssid") or "unknown"
        line = f"Sent: {ssid} ({bssid})"

    with lock:
        status_state["sent_count"] += batch_size
        status_state["message"] = line
        recent_sent.appendleft(line)


def log_attack(message, bssid=None):
    del bssid
    with lock:
        status_state["message"] = message
        recent_sent.appendleft(message)


def client_kicked():
    with lock:
        status_state["message"] = "Containment action sent"


def _get_last_seen(last_seen):
    age = int(max(time.time() - last_seen, 0))
    if age < 2:
        return "now"
    return f"{age}s"


def _build_status_panel():
    with lock:
        total_networks = len(aps_view)
        sensor_status = status_state["sensor_status"]
        backend_status = status_state["backend_status"]
        message = status_state["message"]
        sent_count = status_state["sent_count"]

    content = (
        f"Sensor: {sensor_status}\n"
        f"Backend: {backend_status}\n"
        f"Live networks: {total_networks}\n"
        f"Sent count: {sent_count}\n"
        f"Status: {message}"
    )

    return Panel(content, title="ZeinaGuard Sensor", border_style="cyan")


def _build_networks_table():
    table = Table(title="Live Networks", box=box.ROUNDED, expand=True)
    table.add_column("SSID", style="cyan")
    table.add_column("BSSID", style="magenta")
    table.add_column("CH", justify="center")
    table.add_column("Signal", justify="center")
    table.add_column("Class", justify="center")
    table.add_column("Seen", justify="center")

    with lock:
        networks = sorted(
            aps_view.values(),
            key=lambda ap: (ap.get("signal") is not None, ap.get("signal") or -100),
            reverse=True,
        )

    if not networks:
        table.add_row("Waiting...", "-", "-", "-", "-", "-")
        return table

    for network in networks[:20]:
        table.add_row(
            str(network.get("ssid") or "Hidden"),
            str(network.get("bssid") or "-"),
            str(network.get("channel") or "-"),
            str(network.get("signal") if network.get("signal") is not None else "-"),
            str(network.get("classification") or "UNKNOWN"),
            _get_last_seen(network.get("last_seen", time.time())),
        )

    return table


def _build_recent_sent_panel():
    with lock:
        lines = list(recent_sent)

    content = "\n".join(lines) if lines else "No transmissions yet"
    return Panel(content, title="Recent Sent", border_style="green")


def _build_layout():
    layout = Layout()
    layout.split_column(
        Layout(_build_status_panel(), size=7),
        Layout(_build_networks_table(), ratio=3),
        Layout(_build_recent_sent_panel(), size=14),
    )
    return layout


def run_terminal_ui():
    with Live(_build_layout(), refresh_per_second=4, console=console, screen=False) as live:
        while True:
            live.update(_build_layout())
            time.sleep(0.25)
