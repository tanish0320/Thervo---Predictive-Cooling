"""
DEBUG: CPU MEASUREMENT DISCREPANCY
Trace exactly what happens to CPU value in collect_telemetry()
"""

import os
import sys
import time
import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.inference import InferenceEngine

print("[DEBUG] CPU Measurement Tracing")
print("="*70)

engine = InferenceEngine(run_parity_check=False)

# Initialize disk/net counters
dk_init = psutil.disk_io_counters()
nk_init = psutil.net_io_counters()
dk_prev = {"val": (dk_init.read_bytes + dk_init.write_bytes) if dk_init else 0, "time": time.monotonic()}
nk_prev = {"val": (nk_init.bytes_sent + nk_init.bytes_recv) if nk_init else 0, "time": time.monotonic()}

print("\n[TEST 1] Direct psutil measurements")
print("-"*70)

psutil_none = psutil.cpu_percent(interval=None)
print(f"psutil.cpu_percent(interval=None):         {psutil_none:.2f}%")

time.sleep(0.15)

psutil_01 = psutil.cpu_percent(interval=0.1)
print(f"psutil.cpu_percent(interval=0.1):          {psutil_01:.2f}%")

print("\n[TEST 2] Backend telemetry")
print("-"*70)

for i in range(5):
    raw_data, dk_prev, nk_prev = engine.collect_telemetry(dk_prev, nk_prev)
    backend_cpu = raw_data.get('cpu', -1)

    # Also measure what psutil returns right now
    psutil_now = psutil.cpu_percent(interval=None)

    print(f"Cycle {i+1}:")
    print(f"  Backend CPU:     {backend_cpu:6.2f}%")
    print(f"  psutil(None):    {psutil_now:6.2f}%")
    print(f"  Difference:      {abs(backend_cpu - psutil_now):6.2f}%")

    time.sleep(1.0)

print("\n[ANALYSIS]")
print("-"*70)
print("If backend CPU consistently does NOT match psutil(None),")
print("then there's filtering, normalization, or multiplication happening")
print("that we need to find and fix.")
