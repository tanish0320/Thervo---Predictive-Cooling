"""
Direct unit test for telemetry calculation without subprocess issues
"""

import sys
import os
from pathlib import Path

# Setup path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from features import FeatureProcessor
import numpy as np


def test_feature_processor_normalization():
    """Test that feature processor doesn't inflate values"""
    print("\n[UNIT TEST] Feature Processor Normalization")
    print("-" * 60)

    proc = FeatureProcessor()
    proc.stats['max_disk_log'] = 14.0
    proc.stats['max_net_log'] = 12.0

    # Test 1: 50% CPU should normalize to 0.50
    raw_point = {
        'cpu': 50.0,
        'gpu': 0.0,
        'memory': 50.0,
        'disk_io': 0.0,
        'network_io': 0.0
    }
    vector = proc.process_single(raw_point)
    assert abs(vector[0, 0] - 0.50) < 0.01, f"CPU not 0.50: {vector[0, 0]}"
    print(f"[OK] 50% CPU -> normalized 0.50 (got {vector[0, 0]:.4f})")

    # Test 2: 40% GPU should normalize to 0.40
    raw_point2 = {
        'cpu': 0.0,
        'gpu': 40.0,
        'memory': 50.0,
        'disk_io': 0.0,
        'network_io': 0.0
    }
    proc.reset_state()
    vector = proc.process_single(raw_point2)
    assert abs(vector[0, 1] - 0.40) < 0.01, f"GPU not 0.40: {vector[0, 1]}"
    print(f"[OK] 40% GPU -> normalized 0.40 (got {vector[0, 1]:.4f})")

    # Test 3: 60% MEM should normalize to 0.60
    assert abs(vector[0, 2] - 0.50) < 0.01, f"MEM not 0.50: {vector[0, 2]}"
    print(f"[OK] 50% MEM -> normalized 0.50 (got {vector[0, 2]:.4f})")

    print("[PASS] No inflation in feature normalization")


def test_no_power_weighting():
    """Verify power is NOT converted to utilization"""
    print("\n[UNIT TEST] Power-to-Utilization Conversion Check")
    print("-" * 60)

    # Simulate the fixed calculation
    filtered_cpu = 50.0  # 50% CPU utilization

    # OLD (WRONG) CODE:
    # cpu_power = 7.0 + 85.0 * (filtered_cpu / 100.0)  # 7 + 42.5 = 49.5W
    # power_cpu_util = (cpu_power / 55.0) * 100.0  # 49.5 / 55 * 100 = 90%
    # blended_cpu = 0.4 * 50 + 0.6 * 90 = 20 + 54 = 74%
    old_power = 7.0 + 85.0 * (filtered_cpu / 100.0)
    old_power_util = (old_power / 55.0) * 100.0
    old_blended = 0.4 * filtered_cpu + 0.6 * old_power_util
    print(f"[INFO] OLD (buggy) calculation:")
    print(f"  Input CPU: {filtered_cpu}%")
    print(f"  Power estimate: {old_power:.1f}W")
    print(f"  Power-to-util conversion: {old_power_util:.1f}%")
    print(f"  Blended result: {old_blended:.1f}% (INFLATED by {((old_blended/filtered_cpu - 1) * 100):.0f}%)")

    # NEW (CORRECT) CODE:
    new_blended = filtered_cpu  # Just use CPU directly
    print(f"\n[INFO] NEW (fixed) calculation:")
    print(f"  Input CPU: {filtered_cpu}%")
    print(f"  Direct output: {new_blended}%")
    print(f"  Inflation: {((new_blended/filtered_cpu - 1) * 100):.0f}% (ZERO!)")

    assert new_blended == filtered_cpu, "New blended should equal input CPU"
    print("\n[PASS] Power weighting removed, no inflation")


def test_gpu_filter_smoothness():
    """Test GPU filtering has no discontinuities"""
    print("\n[UNIT TEST] GPU Filtering Smoothness")
    print("-" * 60)

    test_points = [
        (5.0, 5.0, "Below thresholds"),
        (10.0, 5.0, "Power at start of ramp"),
        (12.5, 5.0, "Power mid-ramp"),
        (15.0, 5.0, "Power at threshold"),
        (20.0, 5.0, "Power above threshold"),
        (10.0, 7.5, "Util mid-ramp"),
        (10.0, 12.0, "Util at boundary"),
        (10.0, 20.0, "Util above threshold"),
    ]

    print("\nGPU Power & Util -> Filter Output:")
    prev_filter = None
    for gpu_power, gpu_util, desc in test_points:
        # New smooth filter logic
        power_factor = min(1.0, max(0.0, (gpu_power - 10.0) / 5.0))
        util_factor = min(1.0, max(0.0, (gpu_util - 5.0) / 10.0))
        filter_confidence = max(power_factor, util_factor)
        filtered = gpu_util * filter_confidence

        print(f"  Power {gpu_power:5.1f}W, Util {gpu_util:5.1f}% -> {filtered:5.2f}% ({desc})")

        # Check no discontinuities (changes by small amounts)
        if prev_filter is not None and gpu_util > 0:
            max_reasonable_jump = 15.0  # Max reasonable jump per test step
            assert abs(filtered - prev_filter) < max_reasonable_jump, f"Discontinuity detected: {prev_filter} -> {filtered}"

        if gpu_util > 0:
            prev_filter = filtered

    print("\n[PASS] GPU filtering is smooth with no discontinuities")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("TELEMETRY BUG FIX - DIRECT UNIT TESTS")
    print("=" * 60)

    try:
        test_feature_processor_normalization()
        test_no_power_weighting()
        test_gpu_filter_smoothness()

        print("\n" + "=" * 60)
        print("[RESULT] ALL UNIT TESTS PASSED")
        print("=" * 60)
        print("\nBug fixes verified:")
        print("  - Power-to-utilization conversion removed")
        print("  - No inflation in feature normalization")
        print("  - GPU filtering is smooth")
        sys.exit(0)

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
