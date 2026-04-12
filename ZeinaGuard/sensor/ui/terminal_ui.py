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
signal_history = {}

lock = threading.Lock()

current_filter = "ALL"
hunt_mode = False

# -------------------------
# Attack log system
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
    import config

    # 📝 Non-Interactive Logging Mode
    if not config.ENABLE_TUI:
        ssid = event_summary.get("ssid", "Hidden")
        bssid = event_summary.get("bssid")
        status = event_summary.get("classification", "LEGIT")
        signal = event_summary.get("signal", "??")
        print(f"[SCAN] SSID={str(ssid):<15} | BSSID={bssid} | SIG={signal:>3} | STATUS={status}")
        return

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
# Signal bars
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


# -------------------------
# Distance
# -------------------------

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


# -------------------------
# Trend
# -------------------------

def get_trend(bssid):

    history = signal_history.get(bssid, [])

    if len(history) < 2:
        return "..."

    if history[-1] > history[0]:
        return "Closer"
    elif history[-1] < history[0]:
        return "Away"
    else:
        return "Stable"


# -------------------------
# Radar Meter
# -------------------------

def radar_meter(signal):

    if signal is None:
        return "[----------]"

    level = int((signal + 90) / 4)

    level = max(0, min(level, 10))

    return "[" + "█"*level + "░"*(10-level) + "]"


# -------------------------
# Last seen
# -------------------------

def get_last_seen(ts):

    diff = int(time.time() - ts)

    if diff < 5:
        return "now"

    return f"{diff}s"


# -------------------------
# Filters
# -------------------------

def apply_filter(aps):

    if current_filter == "ALL":
        return aps

    return [
        ap for ap in aps
        if ap.get("classification") == current_filter
    ]


# -------------------------
# AP table
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


# -------------------------
# Rogue target
# -------------------------

def get_top_rogue():

    rogues = [
        ap for ap in aps_view.values()
        if ap.get("classification") == "ROGUE"
    ]

    if not rogues:
        return None

    return max(rogues, key=lambda ap: ap.get("signal", -100))


# -------------------------
# Rogue tracker
# -------------------------

def generate_hunt_panel():

    rogue = get_top_rogue()

    if not rogue:

        return Panel(
            "❌ No Rogue detected",
            title="Rogue Hunt",
            border_style="red"
        )

    signal = rogue.get("signal")
    bssid = rogue.get("bssid")

    content = (
        f"🎯 SSID : {rogue['ssid']}\n"
        f"📡 BSSID : {bssid}\n\n"
        f"Signal : {signal} dBm\n"
        f"Radar : {radar_meter(signal)}\n\n"
        f"Distance : {estimate_distance(signal)}\n"
        f"Trend : {get_trend(bssid)}"
    )

    return Panel(
        content,
        title="🔥 Rogue Tracker",
        border_style="bright_red"
    )


# -------------------------
# Summary
# -------------------------

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
        title="Controls",
        border_style="bright_blue"
    )


# -------------------------
# Attack feed
# -------------------------

def generate_attack_panel():

    with lock:
        logs = "\n".join(attack_log[-MAX_LOG:])

    return Panel(
        logs if logs else "No attack activity",
        title="⚡ Attack Activity",
        border_style="red"
    )


# -------------------------
# Attack stats
# -------------------------

def generate_attack_stats():

    with lock:

        elapsed = max(time.time() - attack_stats["start_time"], 1)
        rate = attack_stats["deauth_count"] / elapsed

        stats = (
            f"⚡ Deauth/sec : {rate:.2f}\n"
            f"🎯 Target : {attack_stats['target_bssid']}\n"
            f"📴 Clients kicked : {attack_stats['clients_kicked']}"
        )

    return Panel(
        stats,
        title="Attack Stats",
        border_style="bright_red"
    )


# -------------------------
# Layout
# -------------------------

def generate_layout():

    layout = Layout()

    if hunt_mode:

        layout.split_column(
            Layout(generate_summary(), size=4),
            Layout(generate_hunt_panel()),
            Layout(generate_attack_stats(), size=6),
            Layout(generate_attack_panel(), size=10)
        )

    else:

        layout.split_column(
            Layout(generate_summary(), size=4),
            Layout(generate_table()),
            Layout(generate_attack_stats(), size=6),
            Layout(generate_attack_panel(), size=10)
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

        elif key.lower() == "h":
            hunt_mode = not hunt_mode

        elif key.lower() == "q":
            console.print("\n👋 Exiting...")
            exit(0)


# -------------------------
# Run UI
# -------------------------

def run_terminal_ui():
    import config
    if not config.ENABLE_TUI:
        print("📝 Terminal UI disabled (Non-interactive mode). Streaming logs only.")
        return

    t = threading.Thread(
        target=keyboard_listener,
        daemon=True
    )
    t.start()

    # Use screen=True to prevent mixing with stdout logs
    # Use auto_refresh=False for manual control
    with Live(
        generate_layout(),
        refresh_per_second=4,
        console=console,
        screen=True,
        auto_refresh=False
    ) as live:

        while True:
            live.update(generate_layout(), refresh=True)
            time.sleep(0.5) # 2 FPS UI refresh for stability
