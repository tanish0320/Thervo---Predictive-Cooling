"""
DEBUG: Trace telemetry values through the pipeline
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import psutil
import time
import numpy as np


def debug_collect_telemetry_inline():
    """Manually trace through the collection logic step by step"""
    print("\n" + "=" * 70)
    print("DEBUG: Telemetry Collection Pipeline Trace")
    print("=" * 70)

    # Simulate InferenceEngine.collect_telemetry() step by step

    print("\n[STEP 1] Get raw psutil CPU")
    raw_cpu = psutil.cpu_percent(interval=None)
    print(f"  psutil.cpu_percent(interval=None) = {raw_cpu:.2f}%")

    print("\n[STEP 2] Get memory")
    raw_mem = psutil.virtual_memory().percent
    print(f"  psutil.virtual_memory().percent = {raw_mem:.2f}%")

    print("\n[STEP 3] Simulate process filtering (FIXED - no exclusion now)")
    sys_cpu = raw_cpu  # No process exclusion in fixed code
    print(f"  sys_cpu = {sys_cpu:.2f}%")

    print("\n[STEP 4] Calculate filtered CPU (no exclusion)")
    filtered_cpu = max(0.0, sys_cpu)
    print(f"  filtered_cpu = {filtered_cpu:.2f}%")

    print("\n[STEP 5] Get GPU data")
    import subprocess
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw,temperature.gpu"],
            capture_output=True, text=True, timeout=1,
        )
        if res.returncode == 0:
            parts = res.stdout.strip().split(",")
            gpu_util = float(parts[0].strip()) if len(parts) > 0 else 0.0
            gpu_power = float(parts[1].strip()) if len(parts) > 1 else 0.0
            print(f"  nvidia-smi returned: util={gpu_util:.1f}%, power={gpu_power:.1f}W")
        else:
            print(f"  nvidia-smi failed with code {res.returncode}")
            gpu_util = 0.0
            gpu_power = 0.0
    except Exception as e:
        print(f"  nvidia-smi exception: {e}")
        gpu_util = 0.0
        gpu_power = 0.0

    print("\n[STEP 6] Apply GPU filtering")
    power_factor = min(1.0, max(0.0, (gpu_power - 10.0) / 5.0))
    util_factor = min(1.0, max(0.0, (gpu_util - 5.0) / 10.0))
    filter_confidence = max(power_factor, util_factor)
    filtered_gpu = gpu_util * filter_confidence
    print(f"  GPU filtering: util={gpu_util:.1f}% -> filtered={filtered_gpu:.2f}% (confidence={filter_confidence:.2f})")

    print("\n[STEP 7] Final values (NO smoothing buffer)")
    smooth_cpu = filtered_cpu
    smooth_gpu = filtered_gpu
    print(f"  smooth_cpu = {smooth_cpu:.2f}%")
    print(f"  smooth_gpu = {smooth_gpu:.2f}%")

    print("\n[FINAL] Values that would be returned")
    print(f"  CPU:    {round(smooth_cpu, 2)}%")
    print(f"  GPU:    {round(smooth_gpu, 2)}%")
    print(f"  Memory: {round(raw_mem, 2)}%")

    print("\n" + "=" * 70)
    print("VALIDATION")
    print("=" * 70)

    # Check for expected behavior
    assert 0 <= smooth_cpu <= 100, f"CPU out of range: {smooth_cpu}"
    assert 0 <= smooth_gpu <= 100, f"GPU out of range: {smooth_gpu}"
    assert 0 <= raw_mem <= 100, f"Memory out of range: {raw_mem}"

    print("[PASS] All values in valid ranges")

    # Check no inflation
    if raw_cpu > 5:
        inflation_ratio = smooth_cpu / raw_cpu
        print(f"\nCPU Inflation: {raw_cpu:.2f}% -> {smooth_cpu:.2f}% (ratio: {inflation_ratio:.4f})")
        if 0.95 <= inflation_ratio <= 1.05:
            print("[PASS] CPU inflation within acceptable range")
        else:
            print(f"[WARN] CPU inflation outside range: {inflation_ratio:.4f}")


def test_actual_inference_engine():
    """Now test the actual InferenceEngine"""
    print("\n\n" + "=" * 70)
    print("TEST: Actual InferenceEngine.collect_telemetry()")
    print("=" * 70)

    try:
        from src.inference import InferenceEngine
        engine = InferenceEngine(run_parity_check=False)
    except Exception as e:
        print(f"[ERROR] Failed to initialize InferenceEngine: {e}")
        return

    # Initialize disk/net counters
    dk_init = psutil.disk_io_counters()
    nk_init = psutil.net_io_counters()
    dk_prev = {"val": (dk_init.read_bytes + dk_init.write_bytes) if dk_init else 0, "time": time.monotonic()}
    nk_prev = {"val": (nk_init.bytes_sent + nk_init.bytes_recv) if nk_init else 0, "time": time.monotonic()}

    print("\nCollecting 5 samples with 1 second delay between each...")

    for sample_num in range(5):
        print(f"\n[Sample {sample_num + 1}]")

        # Get raw psutil
        raw_cpu = psutil.cpu_percent(interval=None)
        raw_mem = psutil.virtual_memory().percent
        print(f"  Raw psutil: CPU={raw_cpu:.2f}%, MEM={raw_mem:.2f}%")

        # Get from engine
        raw_data, dk_prev, nk_prev = engine.collect_telemetry(dk_prev, nk_prev)
        reported_cpu = raw_data["cpu"]
        reported_mem = raw_data["memory"]
        reported_gpu = raw_data["gpu"]

        print(f"  Engine output: CPU={reported_cpu:.2f}%, MEM={reported_mem:.2f}%, GPU={reported_gpu:.2f}%")

        if raw_cpu > 2:
            ratio = reported_cpu / raw_cpu
            print(f"  Inflation ratio: {ratio:.4f}")

        time.sleep(1.0)


if __name__ == "__main__":
    debug_collect_telemetry_inline()
    test_actual_inference_engine()
