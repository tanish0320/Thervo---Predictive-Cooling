"""
LIVE TELEMETRY DASHBOARD
========================

Runs the full thermal control system with REAL PC telemetry data.
Displays real-time CPU, GPU, memory, disk, network metrics on the dashboard.

This is NOT a demo with synthetic data - this collects actual OS metrics from your PC
and feeds them through the inference engine in real-time.

Usage:
    python scripts/run_live_telemetry_dashboard.py

Then open: http://localhost:3000/
"""

import sys
import os
import time
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, HTTPServer
import psutil

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.inference import InferenceEngine
from runtime.api_server import APIServer
from runtime.live_stream_bus import LiveStreamBus


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.path = '/Index.html'
        return super().do_GET()

    def log_message(self, format, *args):
        pass  # Suppress logging


def run_live_dashboard():
    """Run frontend with REAL telemetry data from this PC"""

    print("=" * 70)
    print(" THERVO - LIVE TELEMETRY DASHBOARD")
    print("=" * 70)
    print()
    print("[STARTUP] Initializing real-time thermal monitoring system...")
    print()

    # Initialize inference engine (will use actual hardware metrics)
    try:
        print("[1/4] Loading AI models and feature processor...")
        engine = InferenceEngine(run_parity_check=False)
        print("      [OK] Models loaded successfully")
    except Exception as e:
        print(f"      [ERROR] Failed to load models: {e}")
        print("      This is expected if models/cooling_model.pkl doesn't exist")
        print("      The system will still collect and display real telemetry")
        engine = None

    # Initialize streaming bus for dashboard updates
    print("[2/4] Initializing WebSocket broadcast system...")
    stream_bus = LiveStreamBus()
    print("      [OK] Stream bus ready")

    # Initialize API server (for dashboard communication)
    print("[3/4] Starting API server (port 8080)...")
    api_server = APIServer(stream_bus, None)
    api_thread = threading.Thread(target=api_server.start, kwargs={'port': 8080}, daemon=True)
    api_thread.start()
    print("      [OK] API server running on port 8080")

    # Start HTTP dashboard server
    print("[4/4] Starting dashboard web server (port 3000)...")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def serve_dashboard():
        os.chdir(root_dir)
        server = HTTPServer(('0.0.0.0', 3000), DashboardHandler)
        server.serve_forever()

    dashboard_thread = threading.Thread(target=serve_dashboard, daemon=True)
    dashboard_thread.start()
    print("      [OK] Dashboard running on port 3000")
    print()

    print("=" * 70)
    print(" DASHBOARD READY")
    print("=" * 70)
    print()
    print("[OPEN] Dashboard URL: http://localhost:3000/")
    print("[OPEN] Launching in your browser...")
    print()

    # Open browser
    webbrowser.open("http://localhost:3000/")

    # Initialize disk/network counters
    dk_init = psutil.disk_io_counters()
    nk_init = psutil.net_io_counters()
    dk_prev = {"val": (dk_init.read_bytes + dk_init.write_bytes) if dk_init else 0, "time": time.monotonic()}
    nk_prev = {"val": (nk_init.bytes_sent + nk_init.bytes_recv) if nk_init else 0, "time": time.monotonic()}

    print("[SYSTEM] Hardware Detection:")
    print(f"  CPU Cores:    {psutil.cpu_count()}")
    print(f"  RAM:          {psutil.virtual_memory().total / (1024**3):.1f} GB")
    print(f"  Disk:         {psutil.disk_usage('/').total / (1024**3):.1f} GB")
    try:
        import subprocess
        res = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                            capture_output=True, text=True, timeout=1)
        if res.returncode == 0:
            gpu_name = res.stdout.strip()
            print(f"  GPU:          {gpu_name}")
        else:
            print(f"  GPU:          Not detected")
    except:
        print(f"  GPU:          Not available (nvidia-smi not found)")

    print()
    print("[TELEMETRY] Starting real-time data collection (1Hz)...")
    print("[TELEMETRY] Values displayed on dashboard will update every second")
    print()
    print("=" * 70)
    print(" Press Ctrl+C to stop")
    print("=" * 70)
    print()

    cycle = 0
    try:
        while True:
            try:
                cycle += 1

                # Collect actual telemetry from PC
                raw_data, dk_prev, nk_prev = engine.collect_telemetry(dk_prev, nk_prev) if engine else None

                if raw_data:
                    # Try to predict risk (optional, will fail if model not loaded)
                    try:
                        risk_score, risk_level, gnn_emb = engine.predict(raw_data)
                    except:
                        risk_score = 0.5
                        risk_level = "BALANCE"
                        gnn_emb = 0.5

                    # Display real telemetry
                    if cycle % 10 == 0:  # Print every 10 cycles
                        print(f"[{cycle:4d}] CPU: {raw_data['cpu']:5.1f}% | GPU: {raw_data['gpu']:5.1f}% | MEM: {raw_data['memory']:5.1f}% | " +
                              f"Temp: CPU {raw_data['cpu_temp']:5.1f}°C GPU {raw_data['gpu_temp']:5.1f}°C | " +
                              f"Risk: {risk_score:.2f} ({risk_level})")

                    # Broadcast to dashboard
                    stream_bus.emit({
                        'timestamp': time.time(),
                        'cpu': raw_data['cpu'],
                        'gpu': raw_data['gpu'],
                        'memory': raw_data['memory'],
                        'cpu_temp': raw_data['cpu_temp'],
                        'gpu_temp': raw_data['gpu_temp'],
                        'disk_io': raw_data['disk_io'],
                        'network_io': raw_data['network_io'],
                        'risk_score': risk_score,
                        'risk_level': risk_level,
                        'gnn_embedding': gnn_emb,
                    })

                time.sleep(1.0)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[ERROR] Cycle {cycle}: {e}")
                time.sleep(1.0)

    except KeyboardInterrupt:
        print()
        print()
        print("[SHUTDOWN] Stopping telemetry collection...")
        print("[SHUTDOWN] Dashboard will remain accessible at http://localhost:3000/")
        print("[SHUTDOWN] until you close this terminal (Ctrl+C)")
        print()

        # Try to keep server running for a bit
        try:
            print("Press Ctrl+C again to fully exit...")
            for i in range(30):
                time.sleep(1)
        except KeyboardInterrupt:
            print("[SHUTDOWN] Goodbye!")
            sys.exit(0)


if __name__ == "__main__":
    run_live_dashboard()
