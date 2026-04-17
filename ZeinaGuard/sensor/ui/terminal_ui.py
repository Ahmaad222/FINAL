import _thread
import threading
import time
from collections import deque

import readchar
from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table


console = Console()
lock = threading.Lock()

aps_view = {}
signal_history = {}
recent_sent = deque(maxlen=12)
status_state = {
    "sensor_status": "starting",
    "backend_status": "offline",
    "message": "Booting sensor",
    "sent_count": 0,
}

current_filter = "ALL"
hunt_mode = False
ui_shutdown = threading.Event()


def update_ap(event_summary):
    with lock:
        bssid = event_summary["bssid"]
        signal = event_summary.get("signal")

        if signal is not None:
            history = signal_history.setdefault(bssid, deque(maxlen=6))
            history.append(signal)

        event_summary["last_seen"] = time.time()
        aps_view[bssid] = event_summary


def remove_ap(bssid):
    with lock:
        aps_view.pop(bssid, None)
        signal_history.pop(bssid, None)


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


def get_signal_bars(signal):
    if signal is None:
        return "...."
    if signal >= -45:
        return "||||"
    if signal >= -60:
        return "|||."
    if signal >= -75:
        return "||.."
    return "|..."


def estimate_distance(signal):
    if signal is None:
        return "Unknown"
    if signal >= -45:
        return "~1m"
    if signal >= -55:
        return "~3m"
    if signal >= -65:
        return "~7m"
    if signal >= -75:
        return "~15m"
    return "20m+"


def radar_meter(signal):
    if signal is None:
        return "[..........]"

    normalized = max(-90, min(signal, -30))
    level = int(round((normalized + 90) / 6))
    level = max(0, min(level, 10))
    return "[" + ("#" * level) + ("." * (10 - level)) + "]"


def _get_last_seen(last_seen):
    age = int(max(time.time() - last_seen, 0))
    if age < 2:
        return "now"
    return f"{age}s"


def _signal_sort_key(ap):
    signal = ap.get("signal")
    return (signal is not None, signal if signal is not None else -100)


def _filter_networks(networks):
    if current_filter == "ALL":
        return networks

    return [
        ap
        for ap in networks
        if str(ap.get("classification") or "").upper() == current_filter
    ]


def _style_classification(classification):
    classification = str(classification or "UNKNOWN").upper()
    if classification == "ROGUE":
        return "[bold white on red]ROGUE[/]"
    if classification == "SUSPICIOUS":
        return "[black on yellow]SUSPICIOUS[/]"
    if classification == "LEGIT":
        return "[green]LEGIT[/]"
    return classification


def _build_status_panel():
    with lock:
        networks = list(aps_view.values())
        sensor_status = status_state["sensor_status"]
        backend_status = status_state["backend_status"]
        message = status_state["message"]
        sent_count = status_state["sent_count"]
        active_filter = current_filter
        hunting = hunt_mode

    rogue_count = sum(1 for ap in networks if ap.get("classification") == "ROGUE")
    suspicious_count = sum(1 for ap in networks if ap.get("classification") == "SUSPICIOUS")
    legit_count = sum(1 for ap in networks if ap.get("classification") == "LEGIT")

    content = (
        f"Sensor: {sensor_status}\n"
        f"Backend: {backend_status}\n"
        f"Live networks: {len(networks)} | Rogue: {rogue_count} | Suspicious: {suspicious_count} | Legit: {legit_count}\n"
        f"Filter: {active_filter} | Hunt mode: {'ON' if hunting else 'OFF'}\n"
        f"Sent count: {sent_count}\n"
        f"Status: {message}"
    )

    return Panel(content, title="ZeinaGuard Sensor", border_style="cyan")


def _build_controls_panel():
    with lock:
        active_filter = current_filter
        hunting = hunt_mode

    content = (
        "A: All | R: Rogue | S: Suspicious | L: Legit | H: Hunt | Q: Quit\n"
        f"Active filter: {active_filter}\n"
        f"Hunt mode: {'Enabled' if hunting else 'Disabled'}"
    )
    return Panel(content, title="Controls", border_style="bright_blue")


def _build_networks_table():
    with lock:
        active_filter = current_filter
        networks = sorted(aps_view.values(), key=_signal_sort_key, reverse=True)
        networks = _filter_networks(networks)

    table = Table(
        title=f"Live Networks [{active_filter}]",
        box=box.ROUNDED,
        expand=True,
    )
    table.add_column("SSID", style="cyan")
    table.add_column("BSSID", style="magenta")
    table.add_column("CH", justify="center")
    table.add_column("Signal", justify="center")
    table.add_column("Distance", justify="center")
    table.add_column("Class", justify="center")
    table.add_column("Seen", justify="center")

    if not networks:
        placeholder = "Waiting..." if active_filter == "ALL" else "No networks match filter"
        table.add_row(placeholder, "-", "-", "-", "-", "-", "-")
        return table

    for network in networks[:20]:
        signal = network.get("signal")
        signal_text = "-" if signal is None else f"{signal} {get_signal_bars(signal)}"
        table.add_row(
            str(network.get("ssid") or "Hidden"),
            str(network.get("bssid") or "-"),
            str(network.get("channel") or "-"),
            signal_text,
            estimate_distance(signal),
            _style_classification(network.get("classification")),
            _get_last_seen(network.get("last_seen", time.time())),
        )

    return table


def _build_hunt_panel():
    with lock:
        rogues = [
            ap for ap in aps_view.values() if str(ap.get("classification") or "").upper() == "ROGUE"
        ]

    if not rogues:
        return Panel("No Rogue detected", title="Hunt Mode", border_style="red")

    target = max(rogues, key=_signal_sort_key)
    signal = target.get("signal")
    content = (
        f"SSID: {target.get('ssid') or 'Hidden'}\n"
        f"BSSID: {target.get('bssid') or '-'}\n"
        f"Signal: {signal if signal is not None else '-'} dBm\n"
        f"Bars: {get_signal_bars(signal)}\n"
        f"Radar: {radar_meter(signal)}\n"
        f"Estimated distance: {estimate_distance(signal)}\n"
        f"Last seen: {_get_last_seen(target.get('last_seen', time.time()))}"
    )
    return Panel(content, title="Hunt Mode: Strongest Rogue", border_style="red")


def _build_recent_sent_panel():
    with lock:
        lines = list(recent_sent)

    content = "\n".join(lines) if lines else "No transmissions yet"
    return Panel(content, title="Recent Sent", border_style="green")


def _build_layout():
    with lock:
        hunting = hunt_mode

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=8),
        Layout(name="body", ratio=3),
        Layout(name="recent", size=14),
    )
    layout["header"].split_row(
        Layout(_build_status_panel(), ratio=2),
        Layout(_build_controls_panel(), ratio=1),
    )
    layout["body"].update(_build_hunt_panel() if hunting else _build_networks_table())
    layout["recent"].update(_build_recent_sent_panel())
    return layout


def keyboard_listener():
    global current_filter, hunt_mode

    while not ui_shutdown.is_set():
        try:
            key = readchar.readkey()
        except Exception:
            time.sleep(0.1)
            continue

        key = key.lower()

        with lock:
            if key == "a":
                current_filter = "ALL"
            elif key == "r":
                current_filter = "ROGUE"
            elif key == "s":
                current_filter = "SUSPICIOUS"
            elif key == "l":
                current_filter = "LEGIT"
            elif key == "h":
                hunt_mode = not hunt_mode
            elif key == "q":
                ui_shutdown.set()

        if key == "q":
            _thread.interrupt_main()
            return


def run_terminal_ui():
    ui_shutdown.clear()
    keyboard_thread = threading.Thread(
        target=keyboard_listener,
        daemon=True,
        name="UIKeyboard",
    )
    keyboard_thread.start()

    try:
        with Live(_build_layout(), refresh_per_second=4, console=console, screen=False) as live:
            while not ui_shutdown.is_set():
                live.update(_build_layout())
                time.sleep(0.25)
    finally:
        ui_shutdown.set()
