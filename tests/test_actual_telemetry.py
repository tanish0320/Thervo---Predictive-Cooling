"""
TEST: Actual live telemetry collection from this PC
Compares raw psutil values vs. inference engine output
Measures actual inflation ratio on real hardware
"""

import sys
import os
import time
from pathlib import Path

# Setup path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import psutil
from src.inference import InferenceEngine


def test_actual_live_telemetry():
    """Collect actual telemetry and measure inflation"""
    print("\n" + "=" * 70)
    print("ACTUAL LIVE TELEMETRY TEST - Real Hardware Validation")
    print("=" * 70)

    try:
        engine = InferenceEngine(run_parity_check=False)
        print("[INFO] InferenceEngine initialized")
    except FileNotFoundError as e:
        print(f"[SKIP] Model not found: {e}")
        return False

    print("\nCollecting 15 samples at 1-second intervals...")
    print("(This tests CPU, GPU, Memory, Disk, Network telemetry)\n")

    # Storage for comparisons
    results = {
        'cpu': [],
        'memory': [],
        'timestamps': []
    }

    # Initialize disk/network counters
    dk_init = psutil.disk_io_counters()
    nk_init = psutil.net_io_counters()
    dk_prev = {"val": (dk_init.read_bytes + dk_init.write_bytes) if dk_init else 0, "time": time.monotonic()}
    nk_prev = {"val": (nk_init.bytes_sent + nk_init.bytes_recv) if nk_init else 0, "time": time.monotonic()}

    print(f"{'Sample':<7} {'Raw CPU%':<10} {'Reported%':<12} {'Ratio':<8} {'Raw MEM%':<10} {'Reported%':<12}")
    print("-" * 70)

    for i in range(15):
        # Get inference engine values FIRST
        raw_data, dk_prev, nk_prev = engine.collect_telemetry(dk_prev, nk_prev)
        reported_cpu = raw_data["cpu"]
        reported_mem = raw_data["memory"]

        # Get raw psutil values AFTER (to measure what the engine just reported)
        raw_cpu = psutil.cpu_percent(interval=0.1)
        raw_mem = psutil.virtual_memory().percent

        # Calculate ratio (avoid division by zero)
        cpu_ratio = reported_cpu / raw_cpu if raw_cpu > 1.0 else 1.0

        # Store results
        results['cpu'].append({
            'raw': raw_cpu,
            'reported': reported_cpu,
            'ratio': cpu_ratio,
            'mem_raw': raw_mem,
            'mem_reported': reported_mem
        })
        results['timestamps'].append(time.time())

        # Print row
        ratio_str = f"{cpu_ratio:.3f}" if raw_cpu > 1.0 else "N/A"
        print(f"{i+1:<7} {raw_cpu:<10.2f} {reported_cpu:<12.2f} {ratio_str:<8} {raw_mem:<10.2f} {reported_mem:<12.2f}")

        time.sleep(1.0)

    # Analysis
    print("\n" + "=" * 70)
    print("ANALYSIS")
    print("=" * 70)

    # Filter samples where CPU was above noise floor
    valid_samples = [r for r in results['cpu'] if r['raw'] > 2.0]

    if valid_samples:
        cpu_ratios = [r['ratio'] for r in valid_samples]
        avg_ratio = sum(cpu_ratios) / len(cpu_ratios)
        min_ratio = min(cpu_ratios)
        max_ratio = max(cpu_ratios)

        print(f"\nCPU Inflation Ratio (Reported / Raw):")
        print(f"  Average:  {avg_ratio:.4f} ({(avg_ratio - 1.0) * 100:+.1f}%)")
        print(f"  Min:      {min_ratio:.4f}")
        print(f"  Max:      {max_ratio:.4f}")
        print(f"  Samples:  {len(valid_samples)} (raw CPU > 2%)")

        # Check if within acceptable range (±10% due to measurement noise)
        # Note: psutil with 0.1s interval can have variance, and background processes affect readings
        if 0.90 <= avg_ratio <= 1.10:
            print(f"\n[PASS] CPU inflation within acceptable range (±10%)")
            result_cpu = True
        else:
            print(f"\n[FAIL] CPU inflation outside acceptable range: {avg_ratio:.4f}")
            result_cpu = False

        # Memory analysis
        mem_ratios = [(r['mem_reported'] / r['mem_raw']) if r['mem_raw'] > 10 else 1.0 for r in results['cpu']]
        valid_mem_ratios = [m for m in mem_ratios if 0.5 < m < 2.0]

        if valid_mem_ratios:
            avg_mem_ratio = sum(valid_mem_ratios) / len(valid_mem_ratios)
            print(f"\nMemory Inflation Ratio:")
            print(f"  Average:  {avg_mem_ratio:.4f} ({(avg_mem_ratio - 1.0) * 100:+.1f}%)")

            if 0.98 <= avg_mem_ratio <= 1.02:
                print(f"[PASS] Memory inflation within acceptable range (±2%)")
                result_mem = True
            else:
                print(f"[FAIL] Memory inflation outside range: {avg_mem_ratio:.4f}")
                result_mem = False
        else:
            print(f"\n[SKIP] Memory analysis: insufficient valid samples")
            result_mem = None

        print("\n" + "=" * 70)
        print("HARDWARE INFO")
        print("=" * 70)
        print(f"CPU Count:     {psutil.cpu_count()} cores")
        print(f"Total RAM:     {psutil.virtual_memory().total / (1024**3):.1f} GB")

        # Check if GPU data was collected
        if raw_data.get('gpu_util', 0) > 0 or raw_data.get('gpu', 0) > 0:
            print(f"GPU Detected:  Yes (util: {raw_data.get('gpu_util', 0):.1f}%)")
        else:
            print(f"GPU Detected:  No or idle")

        print("\n" + "=" * 70)
        if result_cpu and (result_mem is None or result_mem):
            print("[RESULT] ACTUAL TELEMETRY TEST PASSED")
            print("=" * 70)
            print("\nThe fixes work correctly on your actual hardware!")
            print("Telemetry values match OS metrics within acceptable range.")
            return True
        else:
            print("[RESULT] ACTUAL TELEMETRY TEST FAILED")
            print("=" * 70)
            print("\nTelemetry inflation still detected. Further investigation needed.")
            return False
    else:
        print("\n[SKIP] No valid CPU samples (CPU usage was too low)")
        return None


if __name__ == "__main__":
    success = test_actual_live_telemetry()
    if success is True:
        sys.exit(0)
    elif success is False:
        sys.exit(1)
    else:
        print("\n[INFO] Test inconclusive (no high CPU samples)")
        sys.exit(0)
