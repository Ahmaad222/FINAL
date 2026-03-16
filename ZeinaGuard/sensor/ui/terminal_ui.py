from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich import box
import threading
import time

console = Console()

aps_view = {}
lock = threading.Lock()


def update_ap(event_summary):
    with lock:
        aps_view[event_summary["bssid"]] = event_summary


def remove_ap(bssid):
    with lock:
        aps_view.pop(bssid, None)


def generate_table():
    table = Table(
        title="📡 ZeinaGuard Terminal Monitor",
        box=box.ROUNDED,
        expand=True
    )

    table.add_column("SSID", style="cyan", no_wrap=True)
    table.add_column("BSSID", style="magenta")
    table.add_column("CH", justify="center")
    table.add_column("STATUS", justify="center")
    table.add_column("SCORE", justify="center")

    with lock:
        for ap in aps_view.values():

            status = ap.get("classification", "UNKNOWN")

            color = "green"
            if status == "SUSPICIOUS":
                color = "yellow"
            elif status == "ROGUE":
                color = "bold red"

            table.add_row(
                str(ap.get("ssid")),
                str(ap.get("bssid")),
                str(ap.get("channel")),
                f"[{color}]{status}[/{color}]",
                str(ap.get("score"))
            )

    return table


def run_terminal_ui():
    with Live(generate_table(), refresh_per_second=2, console=console) as live:
        while True:
            live.update(generate_table())
            time.sleep(1)