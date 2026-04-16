import threading
import time
from collections import deque

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich import box
from rich.layout import Layout
from rich.panel import Panel
import readchar

console = Console()

aps_view = {}
signal_history = {}
recent_sent = deque(maxlen=12)

lock = threading.Lock()

current_filter = "ALL"
hunt_mode = False

# -------------------------
# Status
# -------------------------
status_state = {
    "sensor_status": "starting",
    "backend_status": "offline",
    "sent_count": 0,
}

# -------------------------
# Attack log
# -------------------------
attack_log = []
MAX_LOG = 15

attack_stats = {
    "deauth_count": 0,
    "clients_kicked": 0,
    "target_bssid": None,
    "start_time": time.time()
}

# -------------------------
# AP Update
# -------------------------
def update_ap(event_summary):
    with lock:
        bssid = event_summary["bssid"]
        signal = event_summary.get("signal")

        if bssid not in signal_history:
            signal_history[bssid] = []

        if signal is not None:
            signal_history[bssid].append(signal)
            if len(signal_history[bssid]) > 6:
                signal_history[bssid].pop(0)

        event_summary["last_seen"] = time.time()
        aps_view[bssid] = event_summary


def remove_ap(bssid):
    with lock:
        aps_view.pop(bssid, None)
        signal_history.pop(bssid, None)


# -------------------------
# Status update
# -------------------------
def update_status(sensor_status=None, backend_status=None):
    with lock:
        if sensor_status:
            status_state["sensor_status"] = sensor_status
        if backend_status:
            status_state["backend_status"] = backend_status


def mark_sent(event_summary):
    ssid = event_summary.get("ssid") or "Hidden"
    bssid = event_summary.get("bssid") or "unknown"
    line = f"📡 Sent: {ssid} ({bssid})"

    with lock:
        status_state["sent_count"] += 1
        recent_sent.appendleft(line)


# -------------------------
# Attack logging
# -------------------------
def log_attack(message, bssid=None):
    with lock:
        ts = time.strftime("%H:%M:%S")
        attack_log.append(f"[{ts}] {message}")

        if len(attack_log) > MAX_LOG:
            attack_log.pop(0)

        if bssid:
            attack_stats["target_bssid"] = bssid

        attack_stats["deauth_count"] += 1


def client_kicked():
    with lock:
        attack_stats["clients_kicked"] += 1


# -------------------------
# Helpers
# -------------------------
def get_signal_bars(signal):
    if signal is None:
        return "N/A"
    if signal > -50:
        return "▂▄▆█"
    elif signal > -60:
        return "▂▄▆"
    elif signal > -70:
        return "▂▄"
    else:
        return "▂"


def estimate_distance(signal):
    if signal is None:
        return "Unknown"
    if signal > -45:
        return "🔥 ~1m"
    elif signal > -55:
        return "~3m"
    elif signal > -65:
        return "~7m"
    elif signal > -75:
        return "~15m"
    else:
        return "20m+"


def get_trend(bssid):
    history = signal_history.get(bssid, [])
    if len(history) < 2:
        return "..."
    if history[-1] > history[0]:
        return "Closer"
    elif history[-1] < history[0]:
        return "Away"
    return "Stable"


def radar_meter(signal):
    if signal is None:
        return "[----------]"
    level = int((signal + 90) / 4)
    level = max(0, min(level, 10))
    return "[" + "█"*level + "░"*(10-level) + "]"


def get_last_seen(ts):
    diff = int(time.time() - ts)
    if diff < 5:
        return "now"
    return f"{diff}s"


def apply_filter(aps):
    if current_filter == "ALL":
        return aps
    return [ap for ap in aps if ap.get("classification") == current_filter]


# -------------------------
# Table
# -------------------------
def generate_table():
    table = Table(
        title=f"📡 ZeinaGuard Monitor | Filter: {current_filter}",
        box=box.ROUNDED,
        expand=True
    )

    table.add_column("SSID", style="cyan")
    table.add_column("BSSID", style="magenta")
    table.add_column("CH", justify="center")
    table.add_column("SIGNAL", justify="center")
    table.add_column("LAST", justify="center")
    table.add_column("STATUS", justify="center")
    table.add_column("SCORE", justify="center")

    with lock:
        aps = sorted(aps_view.values(), key=lambda x: x.get("score", 0), reverse=True)
        aps = apply_filter(aps)

        for ap in aps[:20]:
            status = ap.get("classification", "UNKNOWN")
            signal = ap.get("signal")

            color = "green"
            if status == "SUSPICIOUS":
                color = "yellow"
            elif status == "ROGUE":
                color = "bold white on red"

            table.add_row(
                str(ap.get("ssid")),
                str(ap.get("bssid")),
                str(ap.get("channel")),
                get_signal_bars(signal),
                get_last_seen(ap.get("last_seen", time.time())),
                f"[{color}]{status}[/{color}]",
                str(ap.get("score"))
            )

    return table


# -------------------------
# Panels
# -------------------------
def generate_summary():
    with lock:
        aps = list(aps_view.values())

        total = len(aps)
        rogue = sum(1 for ap in aps if ap.get("classification") == "ROGUE")
        suspicious = sum(1 for ap in aps if ap.get("classification") == "SUSPICIOUS")
        legit = sum(1 for ap in aps if ap.get("classification") == "LEGIT")

        sensor_status = status_state["sensor_status"]
        backend_status = status_state["backend_status"]
        sent_count = status_state["sent_count"]

    return Panel(
        f"[bold]A[/]ll | [red]R[/]ogue | [yellow]S[/]uspicious | [green]L[/]egit | [cyan]H[/]unt | [bold]Q[/]uit\n"
        f"📊 Total: {total} | 🔴 Rogue: {rogue} | 🟡 Suspicious: {suspicious} | 🟢 Legit: {legit}\n"
        f"Sensor: {sensor_status} | Backend: {backend_status} | Sent: {sent_count}",
        title="Controls",
        border_style="bright_blue"
    )


def generate_recent_panel():
    with lock:
        content = "\n".join(recent_sent) or "No transmissions yet"
    return Panel(content, title="Recent Sent", border_style="green")


def generate_attack_panel():
    with lock:
        logs = "\n".join(attack_log[-MAX_LOG:])
    return Panel(logs or "No attacks", title="⚡ Attack Activity", border_style="red")


# -------------------------
# Layout
# -------------------------
def generate_layout():
    layout = Layout()

    layout.split_column(
        Layout(generate_summary(), size=6),
        Layout(generate_table(), ratio=3),
        Layout(generate_recent_panel(), size=10),
        Layout(generate_attack_panel(), size=8)
    )

    return layout


# -------------------------
# Keyboard
# -------------------------
def keyboard_listener():
    global current_filter, hunt_mode

    while True:
        key = readchar.readkey()

        if key.lower() == "a":
            current_filter = "ALL"
        elif key.lower() == "r":
            current_filter = "ROGUE"
        elif key.lower() == "s":
            current_filter = "SUSPICIOUS"
        elif key.lower() == "l":
            current_filter = "LEGIT"
        elif key.lower() == "q":
            console.print("\n👋 Exiting...")
            exit(0)


# -------------------------
# Run
# -------------------------
def run_terminal_ui():
    t = threading.Thread(target=keyboard_listener, daemon=True)
    t.start()

    with Live(generate_layout(), refresh_per_second=3, console=console) as live:
        while True:
            live.update(generate_layout())
            time.sleep(0.5)