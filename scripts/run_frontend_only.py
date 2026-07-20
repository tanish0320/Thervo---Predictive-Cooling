import sys
import os
import webbrowser
from http.server import SimpleHTTPRequestHandler, HTTPServer

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.path = '/Index.html'
        return super().do_GET()
        
    def log_message(self, format, *args):
        pass  # Disable logging to avoid console spam

def run_frontend():
    print("======================================================")
    print(" THERVO - Dashboard Web Server (Frontend Only)")
    print("======================================================")
    
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root_dir)
    
    port = 3000
    server = HTTPServer(('127.0.0.1', port), DashboardHandler)
    
    print(f"[*] Starting Dashboard Web Server on port {port}...")
    print(f"[*] Launching Mission Control Dashboard at: http://localhost:{port}/")
    
    # Open the browser to show the page
    webbrowser.open(f"http://localhost:{port}/")
    
    print("[*] Web server is running. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping Web Server...")
        server.server_close()
        print("[*] Web Server offline. Goodbye.")

if __name__ == "__main__":
    run_frontend()
