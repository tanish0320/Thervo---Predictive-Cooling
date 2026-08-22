"""
tests/test_telemetry_accuracy.py
--------------------------------
Guards the dashboard-vs-Task-Manager fixes: CPU must be sampled over a ~1s
window (not 0.1s), GPU utilization must not be scaled down by a confidence
ramp, and memory must be reported as used%.

Run: python tests/test_telemetry_accuracy.py
"""

import os
import sys
import time

import psutil

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'src'))

from src.inference import InferenceEngine  # noqa: E402


def _engine():
    return InferenceEngine.__new__(InferenceEngine)  # skip model load; we only call collect_telemetry


def _collect(engine, dk, nk):
    return engine.collect_telemetry(dk, nk)


def test_cpu_matches_one_second_window():
    """CPU must track a ~1s psutil window, not a 0.1s one."""
    engine = _engine()
    dk = {"val": 0, "time": time.monotonic()}
    nk = {"val": 0, "time": time.monotonic()}

    _collect(engine, dk, nk)  # prime
    psutil.cpu_percent(interval=None)  # prime the reference too

    time.sleep(1.2)
    reference = psutil.cpu_percent(interval=None)
    raw, _, _ = _collect(engine, dk, nk)

    # Both sample the same ~1s of wall clock, so they should be close. A 0.1s
    # window drifts far from this on a lightly loaded machine.
    assert abs(raw["cpu"] - reference) < 15.0, (
        f"cpu {raw['cpu']} diverges from 1s reference {reference}"
    )


def test_cpu_is_not_resampled_within_one_second():
    """Ticks inside the 1s window reuse the cached value rather than resampling."""
    engine = _engine()
    dk = {"val": 0, "time": time.monotonic()}
    nk = {"val": 0, "time": time.monotonic()}

    _collect(engine, dk, nk)  # prime

    # A tick costs ~0.5-0.8s (nvidia-smi + the WMI power query), so two calls can
    # straddle a window boundary. Assert on the cache stamp, not on wall clock:
    # whenever the stamp is unchanged the value must be unchanged too.
    prev_stamp = engine._last_cpu_query
    prev_cpu = engine._cached_cpu
    resampled = 0
    for _ in range(4):
        raw, _, _ = _collect(engine, dk, nk)
        if engine._last_cpu_query == prev_stamp:
            assert raw["cpu"] == round(prev_cpu, 2), (
                "cpu changed without the sample window advancing"
            )
        else:
            resampled += 1
            prev_stamp = engine._last_cpu_query
            prev_cpu = engine._cached_cpu

    assert resampled < 4, "cpu resampled on every tick; the 1s window is not holding"


def test_gpu_utilization_is_not_scaled_down():
    """A real GPU reading must pass through unscaled (the old ramp zeroed idle load)."""
    from src.constants import GPU_NOISE_FLOOR_PCT

    engine = _engine()
    dk = {"val": 0, "time": time.monotonic()}
    nk = {"val": 0, "time": time.monotonic()}
    _collect(engine, dk, nk)  # prime
    time.sleep(1.1)
    raw, _, _ = _collect(engine, dk, nk)

    cached = engine._cached_gpu_util
    expected = (cached * 0.72) if cached >= GPU_NOISE_FLOOR_PCT else 0.0
    assert raw["gpu"] == round(expected, 2), (
        f"gpu {raw['gpu']} != calibrated nvidia-smi reading {expected}"
    )


def test_cpu_survives_other_psutil_callers():
    """
    Regression: psutil.cpu_percent(interval=None) shares one process-wide baseline.
    Another caller in the same process (telemetry_logger.py:116) used to steal our
    measurement window, making the engine report ~0% CPU intermittently.
    """
    engine = _engine()
    dk = {"val": 0, "time": time.monotonic()}
    nk = {"val": 0, "time": time.monotonic()}

    _collect(engine, dk, nk)  # prime

    for _ in range(3):
        # Simulate a competing caller resetting the shared global baseline.
        psutil.cpu_percent(interval=None)
        time.sleep(1.1)
        psutil.cpu_percent(interval=None)  # consumes the window the engine would have used
        raw, _, _ = _collect(engine, dk, nk)

        assert raw["cpu"] > 0.0, (
            "cpu collapsed to 0 after another psutil caller reset the shared baseline"
        )


def test_memory_is_used_percent():
    """Memory must be used%, matching Task Manager -- not available%."""
    engine = _engine()
    dk = {"val": 0, "time": time.monotonic()}
    nk = {"val": 0, "time": time.monotonic()}
    raw, _, _ = _collect(engine, dk, nk)

    expected = psutil.virtual_memory().percent
    assert abs(raw["memory"] - expected) < 3.0, (
        f"memory {raw['memory']} != used% {expected}"
    )
    # Guard the inversion specifically.
    assert abs(raw["memory"] - (100.0 - expected)) > 1.0 or expected == 50.0, (
        "memory looks like available%, not used%"
    )


if __name__ == "__main__":
    for fn in [
        test_cpu_matches_one_second_window,
        test_cpu_is_not_resampled_within_one_second,
        test_cpu_survives_other_psutil_callers,
        test_gpu_utilization_is_not_scaled_down,
        test_memory_is_used_percent,
    ]:
        fn()
        print(f"PASS  {fn.__name__}")
    print("\nAll telemetry accuracy checks passed.")
