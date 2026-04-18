import logging
import os
import subprocess
import sys
import threading
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / ".venv"
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
BOOTSTRAP_FLAG = "ZEINAGUARD_VENV_ACTIVE"


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        force=True,
    )


def _venv_python_path():
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_virtualenv():
    if os.environ.get(BOOTSTRAP_FLAG) == "1":
        return

    venv_python = _venv_python_path()
    if not venv_python.exists():
        print(f"[Bootstrap] Creating virtual environment at {VENV_DIR}")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])

    marker = VENV_DIR / ".requirements-installed"
    if not marker.exists() or REQUIREMENTS_FILE.stat().st_mtime > marker.stat().st_mtime:
        print("[Bootstrap] Installing sensor requirements")
        subprocess.check_call([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([str(venv_python), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])
        marker.write_text("ok\n", encoding="utf-8")

    current_python = Path(sys.executable).resolve()
    if current_python != venv_python.resolve():
        env = dict(os.environ)
        env[BOOTSTRAP_FLAG] = "1"
        os.execve(str(venv_python), [str(venv_python), __file__, *sys.argv[1:]], env)


def main():
    ensure_virtualenv()
    configure_logging()

    import config
    from communication.api_client import APIClient
    from communication.ws_client import WSClient
    from detection.threat_manager import ThreatManager
    from monitoring.sniffer import start_monitoring
    from runtime_state import update_status

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Warning: not running as root. Packet capture may fail.")

    selected_interface = config.select_wireless_interface()
    update_status(
        sensor_status="starting",
        backend_status="connecting",
        message=f"Booting sensor on {selected_interface}",
    )

    token = None
    try:
        api = APIClient(backend_url=config.BACKEND_URL)
        token = api.authenticate_sensor()
        update_status(
            backend_status="authenticated" if token else "offline",
            message="Backend authenticated" if token else "Offline mode: local logging only",
        )
    except Exception:
        update_status(backend_status="offline", message="Backend unavailable: local logging only")

    ws_client = WSClient(backend_url=config.BACKEND_URL, token=token)
    threading.Thread(target=ws_client.start, daemon=True, name="WSClient").start()

    threat_manager = ThreatManager()
    threading.Thread(target=threat_manager.start, daemon=True, name="ThreatManager").start()

    update_status(sensor_status="monitoring", message="Wireless monitoring active")
    start_monitoring()


if __name__ == "__main__":
    main()
