import sys
import os
import time
import threading
import webbrowser

# Ensure import path is correct
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime.live_runtime_manager import LiveRuntimeManager
from http.server import SimpleHTTPRequestHandler, HTTPServer

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.path = '/Index.html'
        return super().do_GET()
        
    def log_message(self, format, *args):
        pass  # Disable logging to avoid console spam

def run_demo():
    print("======================================================")
    print(" THERMAL_AI - Hyperscale Orchestration Mission Control")
    print(" FINAL PROTOTYPE DEMONSTRATION")
    print("======================================================")
    print("[*] Initializing predictive runtime & orchestration layers...")
    
    # 1. Start backend runtime & API Server
    manager = LiveRuntimeManager()
    manager.start()
    
    # Start HTTP server on port 3000
    print("[*] Starting Dashboard Web Server on port 3000...")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    def serve_dashboard():
        os.chdir(root_dir)
        server = HTTPServer(('0.0.0.0', 3000), DashboardHandler)
        server.serve_forever()
        
    t = threading.Thread(target=serve_dashboard)
    t.daemon = True
    t.start()
    
    # 2. Open dashboard
    print("[*] Launching Mission Control Dashboard at: http://localhost:3000/")
    webbrowser.open("http://localhost:3000/")
    
    print("[*] Dashboard launched. Running 60-second deterministic orchestration timeline loop...")
    print("[*] The timeline will automatically cycle through:")
    print("    1. Idle State")
    print("    2. Heavy Workload Detection (Predictive Risk Spikes)")
    print("    3. Predictive Ramping (Leading Reactivity)")
    print("    4. Thermal Stabilization (Reactive Lags)")
    print("    5. Recovery & Idle")
    print("------------------------------------------------------")
    print("[*] Press Ctrl+C to stop the demonstration.")
    
    try:
        # Keep running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Stopping demonstration and exporting artifacts...")
        manager.stop()
        print("[*] Demonstration offline. Goodbye.")
        
if __name__ == "__main__":
    run_demo()
