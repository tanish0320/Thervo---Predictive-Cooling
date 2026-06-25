import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any

class TelemetryHandler(BaseHTTPRequestHandler):
    bus = None  # Will be injected
    manager = None  # Will be injected

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/telemetry':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            if self.bus:
                state = dict(self.bus.get_latest_state())
                state["live_mode"] = getattr(self.manager, "mode_live", False)
            else:
                state = {"live_mode": False}
                
            self.wfile.write(json.dumps(state).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/toggle-mode':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            if self.manager:
                self.manager.mode_live = not self.manager.mode_live
                res_val = self.manager.mode_live
            else:
                res_val = False
                
            self.wfile.write(json.dumps({"live_mode": res_val}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"[API HTTP] {format % args}")

class APIServer:
    def __init__(self, bus, manager=None):
        self.bus = bus
        self.manager = manager
        self.server = None
        self._thread = None

    def start(self, port=8080):
        TelemetryHandler.bus = self.bus
        TelemetryHandler.manager = self.manager
        self.server = HTTPServer(('0.0.0.0', port), TelemetryHandler)
        self._thread = threading.Thread(target=self.server.serve_forever)
        self._thread.daemon = True
        self._thread.start()
        print(f"API Server listening on port {port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self._thread:
            self._thread.join()
        print("API Server stopped")
