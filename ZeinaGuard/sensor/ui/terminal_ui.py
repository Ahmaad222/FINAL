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

# 🎮 Filter state
current_filter = "ALL"


# 🔥 Update / Remove
def update_ap(event_summary):
    with lock:
        event_summary["last_seen"] = time.time()
        aps_view[event_summary["bssid"]] = event_summary


def remove_ap(bssid):
    with lock:
        aps_view.pop(bssid, None)


# 📶 Signal bars
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


# ⏱ Last seen
def get_last_seen(ts):
    diff = int(time.time() - ts)

    if diff < 5:
        return "now"
    return f"{diff}s ago"


# 🎯 Filter logic
def apply_filter(aps):
    global current_filter

    if current_filter == "ALL":
        return aps

    return [
        ap for ap in aps
        if ap.get("classification") == current_filter
    ]


# 📊 Table
def generate_table():
    table = Table(
        title=f"📡 ZeinaGuard Monitor | Filter: {current_filter}",
        box=box.ROUNDED,
        expand=True
    )

    table.add_column("SSID", style="cyan", no_wrap=True)
    table.add_column("BSSID", style="magenta")
    table.add_column("CH", justify="center")
    table.add_column("SIGNAL", justify="center")
    table.add_column("LAST SEEN", justify="center")
    table.add_column("STATUS", justify="center")
    table.add_column("SCORE", justify="center")

    with lock:
        aps = list(aps_view.values())

        # 🔥 ترتيب
        aps = sorted(aps, key=lambda ap: ap.get("score", 0), reverse=True)

        # 🎮 فلترة
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


# 📊 Summary
def generate_summary():
    with lock:
        aps = list(aps_view.values())

        total = len(aps)
        rogue = sum(1 for ap in aps if ap.get("classification") == "ROGUE")
        suspicious = sum(1 for ap in aps if ap.get("classification") == "SUSPICIOUS")
        legit = sum(1 for ap in aps if ap.get("classification") == "LEGIT")

    return Panel(
        f"[bold]A[/]ll | [red]R[/]ogue | [yellow]S[/]uspicious | [green]L[/]egit | [bold]Q[/]uit\n"
        f"📊 Total: {total} | 🔴 Rogue: {rogue} | 🟡 Suspicious: {suspicious} | 🟢 Legit: {legit}",
        title="🎮 Controls + Network Summary",
        border_style="bright_blue"
    )


# 🧠 Layout
def generate_layout():
    layout = Layout()

    layout.split_column(
        Layout(generate_summary(), size=4),
        Layout(generate_table())
    )

    return layout


# 🎮 Keyboard listener
def keyboard_listener():
    global current_filter

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


# 🚀 Run
def run_terminal_ui():
    # شغل keyboard في thread
    t = threading.Thread(target=keyboard_listener, daemon=True)
    t.start()

    with Live(generate_layout(), refresh_per_second=2, console=console) as live:
        while True:
            live.update(generate_layout())
            time.sleep(1)