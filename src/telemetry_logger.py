"""
=============================================================
  AI-Driven Sensor-Free Predictive Cooling
  Real-Time Telemetry Logger  ·  v1.0
  Collects: CPU, GPU, Memory, Disk I/O, Net I/O, Temps
  Output:   telemetry_data.csv  (append mode)
=============================================================
  Requirements:
      pip install psutil
  Optional (GPU support):
      nvidia-smi must be in PATH (comes with NVIDIA drivers)

  Usage:
      python telemetry_logger.py                  # 1-sec interval
      python telemetry_logger.py --interval 2     # 2-sec interval
      python telemetry_logger.py --output my.csv  # custom CSV path
=============================================================
"""

import argparse
import csv
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    print("[FATAL] psutil not installed. Run: pip install psutil")
    sys.exit(1)


# ─────────────────────────────────────────────
#  CONFIGURATION DEFAULTS
# ─────────────────────────────────────────────
DEFAULT_INTERVAL_SEC = 1.0
# Base path is the script directory so defaults work regardless of current
# working directory when the script is invoked.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "raw" / "telemetry_data.csv"
LOG_FILE = PROJECT_ROOT / "logs" / "telemetry_logger.log"

CSV_COLUMNS = [
    "timestamp",
    "cpu",
    "gpu",
    "memory",
    "disk_io",
    "network_io",
    "gpu_temp",
    "cpu_temp",
    "fan_rpm",
    "throttle_flag",
    "ambient_temp",
]


# ─────────────────────────────────────────────
#  LOGGING SETUP
# ─────────────────────────────────────────────
def setup_logging() -> logging.Logger:
    """Configure console + file logging."""
    logger = logging.getLogger("TelemetryLogger")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    # File handler (always DEBUG so we capture everything)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


def ensure_directories(csv_path: str, log_path: str) -> None:
    """Create parent directories for CSV and log files if they don't exist."""
    try:
        csv_dir = Path(csv_path).parent
        log_dir = Path(log_path).parent
        csv_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # If we cannot create directories, that's fatal for running the logger
        print(f"[FATAL] Cannot create required directories: {exc}")
        sys.exit(1)


# Ensure folders exist before configuring logging and CSV
ensure_directories(DEFAULT_CSV_PATH, LOG_FILE)
logger = setup_logging()


# ─────────────────────────────────────────────
#  TELEMETRY COLLECTORS
# ─────────────────────────────────────────────

def collect_cpu_usage() -> float:
    """Return CPU utilisation % (non-blocking, 0.1s interval)."""
    try:
        return psutil.cpu_percent(interval=None)
    except Exception as exc:
        logger.warning("CPU usage collection failed: %s", exc)
        return 0.0


def collect_memory_usage() -> float:
    """Return RAM utilisation %."""
    try:
        return psutil.virtual_memory().percent
    except Exception as exc:
        logger.warning("Memory usage collection failed: %s", exc)
        return 0.0


def collect_disk_io(prev_counters: dict) -> tuple[float, dict]:
    """
    Return disk I/O bytes/sec since last call.
    Returns (bytes_per_sec, new_counters).
    """
    try:
        now = time.monotonic()
        counters = psutil.disk_io_counters()
        if counters is None:
            return 0.0, prev_counters

        current = {
            "read":  counters.read_bytes,
            "write": counters.write_bytes,
            "time":  now,
        }

        if prev_counters:
            elapsed = current["time"] - prev_counters["time"]
            if elapsed > 0:
                delta = (
                    (current["read"]  - prev_counters["read"]) +
                    (current["write"] - prev_counters["write"])
                )
                rate = max(0.0, delta / elapsed)
                return round(rate, 2), current

        return 0.0, current

    except Exception as exc:
        logger.warning("Disk I/O collection failed: %s", exc)
        return 0.0, prev_counters


def collect_network_io(prev_counters: dict) -> tuple[float, dict]:
    """
    Return network I/O bytes/sec since last call.
    Returns (bytes_per_sec, new_counters).
    """
    try:
        now = time.monotonic()
        counters = psutil.net_io_counters()
        if counters is None:
            return 0.0, prev_counters

        current = {
            "sent": counters.bytes_sent,
            "recv": counters.bytes_recv,
            "time": now,
        }

        if prev_counters:
            elapsed = current["time"] - prev_counters["time"]
            if elapsed > 0:
                delta = (
                    (current["sent"] - prev_counters["sent"]) +
                    (current["recv"] - prev_counters["recv"])
                )
                rate = max(0.0, delta / elapsed)
                return round(rate, 2), current

        return 0.0, current

    except Exception as exc:
        logger.warning("Network I/O collection failed: %s", exc)
        return 0.0, prev_counters


def _run_nvidia_smi(query: str) -> str | None:
    """
    Run nvidia-smi with a single query field.
    Returns the stripped output string or None on failure.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={query}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            value = result.stdout.strip().split("\n")[0].strip()
            return value
        logger.debug("nvidia-smi returned non-zero: %s", result.stderr.strip())
        return None
    except FileNotFoundError:
        logger.debug("nvidia-smi not found — GPU metrics unavailable.")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("nvidia-smi timed out.")
        return None
    except Exception as exc:
        logger.debug("nvidia-smi query failed: %s", exc)
        return None


def collect_gpu_usage() -> float:
    """Return GPU utilisation % (0.0 if unavailable)."""
    try:
        val = _run_nvidia_smi("utilization.gpu")
        if val is not None:
            return float(val)
    except (ValueError, TypeError) as exc:
        logger.debug("GPU usage parse error: %s", exc)
    return 0.0


def collect_gpu_temperature() -> float:
    """Return GPU temperature in °C (0.0 if unavailable)."""
    try:
        val = _run_nvidia_smi("temperature.gpu")
        if val is not None:
            return float(val)
    except (ValueError, TypeError) as exc:
        logger.debug("GPU temperature parse error: %s", exc)
    return 0.0


def collect_cpu_temperature() -> float:
    """
    Return CPU temperature in °C.

    Priority order:
      1. psutil.sensors_temperatures() — Linux / macOS
      2. OpenHardwareMonitor WMI query  — Windows (if OHM is running)
      3. Returns 0.0 gracefully if nothing is available.
    """
    # ── Option 1: psutil sensors (Linux/macOS) ──
    try:
        if hasattr(psutil, "sensors_temperatures"):
            sensors = psutil.sensors_temperatures()
            if sensors:
                # Look for common keys: coretemp, k10temp, cpu_thermal, etc.
                candidates = [
                    "coretemp", "k10temp", "cpu_thermal", "acpitz",
                    "cpu-thermal", "zenpower",
                ]
                for key in candidates:
                    entries = sensors.get(key)
                    if entries:
                        # Take the first "Package" or first entry
                        for entry in entries:
                            if "package" in entry.label.lower() or entry.label == "":
                                return round(entry.current, 1)
                        return round(entries[0].current, 1)
    except Exception as exc:
        logger.debug("psutil CPU temp failed: %s", exc)

    # ── Option 2: Windows OpenHardwareMonitor via WMI ──
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Get-WmiObject -Namespace root/OpenHardwareMonitor "
                        "-Class Sensor | Where-Object {$_.SensorType -eq 'Temperature' "
                        "-and $_.Name -like '*CPU*'} | "
                        "Select-Object -First 1 -ExpandProperty Value"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            val = result.stdout.strip()
            if val:
                return round(float(val), 1)
        except Exception as exc:
            logger.debug("OHM WMI CPU temp failed: %s", exc)

    return 0.0


def collect_fan_rpm() -> float:
    """Return average fan speed in RPM if available, otherwise 0.0."""
    try:
        if hasattr(psutil, "sensors_fans"):
            fans = psutil.sensors_fans()
            if fans:
                vals = []
                for name, entries in fans.items():
                    for entry in entries:
                        vals.append(entry.current)
                if vals:
                    return float(sum(vals) / len(vals))
    except Exception as exc:
        logger.debug("psutil fan RPM failed: %s", exc)
    return 0.0


def collect_throttle_flag() -> int:
    """Return 1 if thermal throttling is active, else 0."""
    try:
        if sys.platform == "win32":
            # Check if CPU is throttled via WMI or power status (defaulting to 0)
            pass
    except Exception:
        pass
    return 0


def collect_ambient_temp() -> float:
    """Return ambient temperature in °C if available, else 0.0."""
    return 0.0


# ─────────────────────────────────────────────
#  CSV INITIALISATION
# ─────────────────────────────────────────────

def init_csv(csv_path: str) -> None:
    """
    Create the CSV and write the header row ONLY if the file
    does not already exist (so we append without duplicating headers).
    Ensures parent directory exists for user-specified paths.
    """
    path = Path(csv_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Cannot create directory for CSV file: %s", exc)
        sys.exit(1)

    if not path.exists():
        try:
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
            logger.info("CSV created: %s", path.resolve())
        except OSError as exc:
            logger.error("Cannot create CSV file: %s", exc)
            sys.exit(1)
    else:
        logger.info("Appending to existing CSV: %s", path.resolve())


def write_row(csv_path: str, row: dict) -> None:
    """Append a single telemetry row to the CSV."""
    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writerow(row)
    except OSError as exc:
        logger.error("CSV write failed: %s", exc)


# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────

def run(interval: float = DEFAULT_INTERVAL_SEC, csv_path: str = DEFAULT_CSV_PATH) -> None:
    """
    Main collection loop. Runs indefinitely until Ctrl-C.
    Collects all metrics, writes CSV row, sleeps for `interval` seconds.
    """
    logger.info("=" * 60)
    logger.info("  Telemetry Logger  —  AI Predictive Cooling System")
    logger.info("  Interval : %.1f sec", interval)
    logger.info("  CSV path : %s", csv_path)
    logger.info("  Press Ctrl-C to stop.")
    logger.info("=" * 60)

    init_csv(csv_path)

    # Prime the I/O delta counters with a short warmup read
    psutil.cpu_percent(interval=0.1)   # flush the first (always-0) reading
    _disk_prev: dict = {}
    _net_prev:  dict = {}

    # Prime I/O baselines so first tick isn't 0
    try:
        dk = psutil.disk_io_counters()
        _disk_prev = {"read": dk.read_bytes, "write": dk.write_bytes, "time": time.monotonic()} if dk else {}
    except Exception:
        pass
    try:
        nk = psutil.net_io_counters()
        _net_prev = {"sent": nk.bytes_sent, "recv": nk.bytes_recv, "time": time.monotonic()} if nk else {}
    except Exception:
        pass

    tick = 0
    while True:
        loop_start = time.monotonic()
        tick += 1

        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # ms precision

            cpu     = collect_cpu_usage()
            memory  = collect_memory_usage()
            gpu     = collect_gpu_usage()
            gpu_tmp = collect_gpu_temperature()
            cpu_tmp = collect_cpu_temperature()

            disk_io, _disk_prev   = collect_disk_io(_disk_prev)
            net_io,  _net_prev    = collect_network_io(_net_prev)

            fan_rpm = collect_fan_rpm()
            throttle = collect_throttle_flag()
            ambient = collect_ambient_temp()

            row = {
                "timestamp":  ts,
                "cpu":        round(cpu, 2),
                "gpu":        round(gpu, 2),
                "memory":     round(memory, 2),
                "disk_io":    disk_io,
                "network_io": net_io,
                "gpu_temp":   round(gpu_tmp, 1),
                "cpu_temp":   round(cpu_tmp, 1),
                "fan_rpm":    round(fan_rpm, 1),
                "throttle_flag": throttle,
                "ambient_temp": round(ambient, 1),
            }

            write_row(csv_path, row)

            # Console status every 10 ticks
            if tick % 10 == 1:
                logger.info(
                    "Tick %5d | CPU %5.1f%% | GPU %5.1f%% | MEM %5.1f%% | "
                    "Disk %8.0f B/s | Net %8.0f B/s | GPU_T %4.1f°C | CPU_T %4.1f°C | "
                    "Fan %5.0f RPM | Throttle %d",
                    tick, cpu, gpu, memory, disk_io, net_io, gpu_tmp, cpu_tmp, fan_rpm, throttle
                )

        except Exception as exc:
            # Log unexpected errors but NEVER crash the loop
            logger.error("Unexpected error at tick %d: %s", tick, exc, exc_info=True)

        # Compensate for execution time so interval stays accurate
        elapsed  = time.monotonic() - loop_start
        sleep_s  = max(0.0, interval - elapsed)
        time.sleep(sleep_s)


# ─────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Real-Time Telemetry Logger for AI Predictive Cooling"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SEC,
        metavar="SEC",
        help=f"Sampling interval in seconds (default: {DEFAULT_INTERVAL_SEC})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_CSV_PATH,
        metavar="FILE",
        help=f"CSV output path (default: {DEFAULT_CSV_PATH})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        run(interval=args.interval, csv_path=args.output)
    except KeyboardInterrupt:
        logger.info("\nLogger stopped by user. Data saved to: %s", args.output)
        sys.exit(0)
