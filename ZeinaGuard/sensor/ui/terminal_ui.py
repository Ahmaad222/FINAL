from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich import box
from rich.layout import Layout
from rich.panel import Panel
import threading
import time
import readchar

console = Console()

aps_view = {}
lock = threading.Lock()

current_filter = "ALL"
hunt_mode = False

signal_history = {}

attack_log = []
MAX_LOG = 15

attack_stats = {
    "deauth_count": 0,
    "clients_kicked": 0,
    "target_bssid": None,
    "start_time": time.time()
}


# --------------------------------------------------
# UPDATE AP
# --------------------------------------------------

def update_ap(event_summary):

    with lock:

        event_summary["last_seen"] = time.time()
        bssid = event_summary["bssid"]

        aps_view[bssid] = event_summary

        signal = event_summary.get("signal")

        if signal is not None:

            history = signal_history.setdefault(bssid, [])
            history.append(signal)

            if len(history) > 10:
                history.pop(0)


# --------------------------------------------------
# REMOVE AP  (حل المشكلة هنا)
# --------------------------------------------------

def remove_ap(bssid):

    with lock:

        if bssid in aps_view:
            del aps_view[bssid]

        if bssid in signal_history:
            del signal_history[bssid]


# --------------------------------------------------
# TREND
# --------------------------------------------------

def get_trend(bssid):

    history = signal_history.get(bssid, [])

    if len(history) < 3:
        return "..."

    mid = len(history) // 2

    old_avg = sum(history[:mid]) / max(mid, 1)
    new_avg = sum(history[mid:]) / max(len(history) - mid, 1)

    diff = new_avg - old_avg

    if diff > 2:
        return "📉"
    elif diff < -2:
        return "📈"
    else:
        return "➡️"


# --------------------------------------------------
# DISTANCE
# --------------------------------------------------

def estimate_distance(signal):

    if signal is None:
        return "?"

    if signal > -45:
        return "🔥 1m"
    elif signal > -55:
        return "🟡 3m"
    elif signal > -65:
        return "🟠 7m"
    elif signal > -75:
        return "🔴 15m"
    else:
        return "❌ 20m+"


# --------------------------------------------------
# SIGNAL BARS
# --------------------------------------------------

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


# --------------------------------------------------
# LAST SEEN
# --------------------------------------------------

def get_last_seen(ts):

    diff = int(time.time() - ts)

    if diff < 5:
        return "now"

    return f"{diff}s"


# --------------------------------------------------
# FILTER
# --------------------------------------------------

def apply_filter(aps):

    if current_filter == "ALL":
        return aps

    return [
        ap for ap in aps
        if ap.get("classification") == current_filter
    ]


# --------------------------------------------------
# TABLE
# --------------------------------------------------

def generate_table():

    table = Table(
        title=f"📡 ZeinaGuard Monitor | Filter: {current_filter}",
        box=box.ROUNDED,
        expand=True
    )

    table.add_column("SSID")
    table.add_column("BSSID")
    table.add_column("CH", justify="center")
    table.add_column("SIGNAL", justify="center")
    table.add_column("LAST SEEN", justify="center")
    table.add_column("STATUS", justify="center")
    table.add_column("SCORE", justify="center")

    with lock:

        aps = list(aps_view.values())

        aps = sorted(
            aps,
            key=lambda ap: ap.get("score", 0),
            reverse=True
        )

        aps = apply_filter(aps)

        for ap in aps:

            status = ap.get("classification", "UNKNOWN")
            signal = ap.get("signal")
            last_seen = ap.get("last_seen", time.time())

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
                get_last_seen(last_seen),
                f"[{color}]{status}[/{color}]",
                str(ap.get("score"))
            )

    return table


# --------------------------------------------------
# SUMMARY
# --------------------------------------------------

def generate_summary():

    with lock:

        aps = list(aps_view.values())

        total = len(aps)
        rogue = sum(1 for ap in aps if ap.get("classification") == "ROGUE")
        suspicious = sum(1 for ap in aps if ap.get("classification") == "SUSPICIOUS")
        legit = sum(1 for ap in aps if ap.get("classification") == "LEGIT")

    return Panel(
        f"[bold]A[/]ll | [red]R[/]ogue | [yellow]S[/]uspicious | [green]L[/]egit | [cyan]H[/]unt | [bold]Q[/]uit\n"
        f"📊 Total: {total} | 🔴 Rogue: {rogue} | 🟡 Suspicious: {suspicious} | 🟢 Legit: {legit}",
        title="🎮 Controls + Network Summary",
        border_style="bright_blue"
    )


# --------------------------------------------------
# HUNT MODE
# --------------------------------------------------

def get_top_rogue():

    rogues = [
        ap for ap in aps_view.values()
        if ap.get("classification") == "ROGUE"
    ]

    if not rogues:
        return None

    return max(rogues, key=lambda ap: ap.get("signal", -100))


def generate_hunt_panel():

    target = get_top_rogue()

    if not target:

        return Panel(
            "❌ No Rogue AP detected",
            title="🎯 Hunt Mode",
            border_style="red"
        )

    signal = target.get("signal")
    bssid = target.get("bssid")
    ssid = target.get("ssid")

    distance = estimate_distance(signal)
    trend = get_trend(bssid)

    content = (
        f"🎯 Target: {ssid}\n"
        f"📡 BSSID: {bssid}\n\n"
        f"📶 Signal: {signal}\n"
        f"📍 Distance: {distance}\n"
        f"📊 Trend: {trend}"
    )

    return Panel(
        content,
        title="🔥 Rogue Hunt Mode",
        border_style="bright_red"
    )


# --------------------------------------------------
# LAYOUT
# --------------------------------------------------

def generate_layout():

    layout = Layout()

    if hunt_mode:

        layout.split_column(
            Layout(generate_summary(), size=4),
            Layout(generate_hunt_panel())
        )

    else:

        layout.split_column(
            Layout(generate_summary(), size=4),
            Layout(generate_table())
        )

    return layout


# --------------------------------------------------
# KEYBOARD
# --------------------------------------------------

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

        elif key.lower() == "h":
            hunt_mode = not hunt_mode

        elif key.lower() == "q":

            console.print("\n👋 Exiting...")
            exit(0)


# --------------------------------------------------
# RUN UI
# --------------------------------------------------

def run_terminal_ui():

    t = threading.Thread(
        target=keyboard_listener,
        daemon=True
    )

    t.start()

    with Live(
        generate_layout(),
        refresh_per_second=2,
        console=console
    ) as live:

        while True:

            live.update(generate_layout())
            time.sleep(1)