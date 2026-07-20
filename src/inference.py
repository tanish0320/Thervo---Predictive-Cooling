"""
src/inference.py
----------------
PRODUCTION INFERENCE ENGINE — runtime entry point.

Flow (FRD §6.2)
---------------
collect_telemetry()
  -> validate schema
  -> FeatureProcessor.process_single()
  -> XGBoost.predict(X)
  -> src.core.fusion.fuse(xgb, gnn)
  -> src.core.fusion.get_risk_level()
  -> CoolingPolicyEngine.update(risk)
  -> HardwareFanController.write_target()
  -> log to runtime/orchestration_logs.csv
"""

import os
import sys
import time
import pickle
import subprocess
import numpy as np
import pandas as pd
import psutil
from datetime import datetime

# -- Resolve src/ and project root for local imports ---------------------------
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from features import FeatureProcessor, validate_raw_input, REQUIRED_KEYS
from thermal_mode_controller import ThermalModeController
from fan_controller import HardwareFanController

# Import fusion from the SINGLE SOURCE OF TRUTH
_CORE_DIR = os.path.join(_SRC_DIR, 'core')
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from core.fusion import fuse, get_risk_level, assert_parity  # noqa: E402
from constants import FEATURE_DIM, FEATURE_IDX

# =============================================================================
# CONFIGURATION
# =============================================================================

MODEL_PATH         = os.path.join(_SRC_DIR, '..', 'models', 'cooling_model.pkl')
PREPROCESSOR_STATE = os.path.join(_SRC_DIR, '..', 'models', 'preprocessor_state.pkl')
OUTPUT_LOG         = os.path.join(_SRC_DIR, '..', 'data', 'inference_logs.csv')
ORCHESTRATION_LOG  = os.path.join(_SRC_DIR, '..', 'runtime', 'orchestration_logs.csv')
INTERVAL           = 1.0  # seconds between inference cycles


# =============================================================================
# INFERENCE ENGINE
# =============================================================================

class InferenceEngine:
    def __init__(
        self,
        model_path:  str = MODEL_PATH,
        state_path:  str = PREPROCESSOR_STATE,
        adjacency         = None,
        run_parity_check: bool = False,
    ):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"[InferenceEngine] Model not found at '{model_path}'.")
        with open(model_path, 'rb') as f:
            loaded = pickle.load(f)

        if isinstance(loaded, tuple):
            self._xgb_model, self._feature_names = loaded
        else:
            self._xgb_model   = loaded
            self._feature_names = []

        self.processor = FeatureProcessor()
        self.processor.load(state_path)
        self.processor_state_path = state_path

        from features import AnalyticGNN
        self.gnn_engine = AnalyticGNN(adjacency=adjacency)

        # ponytail: CSV batching buffer - flush every 60 cycles (~60s)
        self._log_buffer = []
        self._log_buffer_count = 0

        # ponytail: I/O caching - query only every 10s instead of every cycle
        self._last_io_query = 0.0
        self._cached_dk = None
        self._cached_nk = None

        if run_parity_check:
            self._startup_parity_check()

    def _startup_parity_check(self) -> None:
        sample = {'cpu': 50.0, 'gpu': 40.0, 'memory': 60.0, 'disk_io': 1_000_000.0, 'network_io': 500_000.0}
        vec_a = self.processor.process_single(sample)
        proc2 = FeatureProcessor()
        proc2.stats = dict(self.processor.stats)
        vec_b = proc2.process_single(sample)
        assert_parity(vec_a, vec_b, label="startup parity check")

    @staticmethod
    def validate_telemetry(raw_data: dict) -> None:
        validate_raw_input(raw_data)

    def collect_telemetry(self, dk_prev: dict, nk_prev: dict) -> tuple:
        from collections import deque
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_mono = time.monotonic()
        
        # Initialize caching, filtering and history attributes if not present
        if not hasattr(self, "_own_pid"):
            self._own_pid = os.getpid()
            self._own_proc = psutil.Process(self._own_pid)
            self._browser_pids = []
            self._last_pid_update = 0.0
            
            # Deques for rolling filters to smooth utilization jitter
            self._cpu_history = deque(maxlen=5)
            self._gpu_history = deque(maxlen=5)
            
            # Thermal smoothing state (fallback thermal inertia)
            self._cpu_temp_smooth = 40.0
            self._gpu_temp_smooth = 38.0
            
            # Cached values for query rate limit
            self._cached_cpu = 0.0
            self._cached_gpu_util = 0.0
            self._cached_gpu_power = 0.0
            self._cached_gpu_temp = 0.0
            self._last_cpu_query = 0.0
            self._last_gpu_query = 0.0

        # 1. Update excluded process list (ONLY browsers/UI processes, not python workers)
        # NOTE: Excluding python.exe was causing artificial deflation when psutil subtracts the telemetry collector itself
        # ponytail: Rate-limit process scan to every 30 seconds (3x reduction in expensive iterations)
        if now_mono - self._last_pid_update >= 30.0:
            self._browser_pids = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    name_lower = proc.info['name'].lower() if proc.info['name'] else ""
                    # Only exclude BROWSER processes, not python.exe (that's legitimate work)
                    if name_lower in ("msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe"):
                        self._browser_pids.append(proc.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self._last_pid_update = now_mono

        # 2. Get system CPU percent (use blocking interval for fresh measurement)
        # NOTE: interval=None returns cached value from 1s ago, which breaks in 1-second polling
        # Use interval=0.0 to get fresh CPU% without blocking, or interval=0.1 for accuracy
        # psutil.cpu_percent() already measures actual CPU load fairly
        raw_psutil_cpu = psutil.cpu_percent(interval=0.1)  # 100ms blocking read for fresh value
        self._cached_cpu = raw_psutil_cpu
        self._last_cpu_query = now_mono

        sys_cpu = self._cached_cpu


        # 3. Calculate browser-only CPU consumption (optional smoothing, not subtraction)
        # We use this only for informational purposes, not for filtering the main CPU metric
        browser_cpu_sum = 0.0
        for pid in self._browser_pids:
            try:
                proc = psutil.Process(pid)
                browser_cpu_sum += proc.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Use raw system CPU as the authoritative metric
        filtered_cpu = max(0.0, sys_cpu)

        # 4. CPU Package Power Query / Estimation
        cpu_power = 0.0
        # Try to query CPU Package Power from OpenHardwareMonitor WMI
        if sys.platform == "win32":
            try:
                res = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        (
                            "Get-WmiObject -Namespace root/OpenHardwareMonitor "
                            "-Class Sensor | Where-Object {$_.SensorType -eq 'Power' "
                            "-and $_.Name -like '*CPU*'} | "
                            "Select-Object -First 1 -ExpandProperty Value"
                        ),
                    ],
                    capture_output=True, text=True, timeout=1,
                )
                if res.returncode == 0 and res.stdout.strip():
                    cpu_power = float(res.stdout.strip())
            except Exception:
                pass
                
        if cpu_power <= 0.0:
            # Fallback estimation for Intel i7-14700HX (Base TDP 55W)
            cpu_power = 7.0 + 85.0 * (filtered_cpu / 100.0)
            
        # 5. Use filtered_cpu directly without power weighting (power is for thermal estimation only)
        # Power is NOT equivalent to utilization and should not be converted 1:1
        # Keep filtered_cpu as the authoritative utilization metric
        blended_cpu = filtered_cpu
        
        # Use raw CPU directly without smoothing buffer
        # The 5-point rolling average causes lag and inflation during transients
        # Smoothing should be done at the policy layer, not the telemetry layer
        smooth_cpu = blended_cpu
        
        # 6. Memory query
        mem = psutil.virtual_memory().percent
        
        # 7. GPU Telemetry from nvidia-smi (All-in-one to reduce overhead)
        gpu_util = 0.0
        gpu_power = 0.0
        gpu_temp_raw = 0.0
        # ponytail: Rate-limit GPU query to every 2 seconds (50% reduction in subprocess spawns)
        if now_mono - self._last_gpu_query >= 2.0:
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw,temperature.gpu,memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=1,
                )
                if res.returncode == 0:
                    parts = res.stdout.strip().split(",")
                    if len(parts) >= 3:
                        gpu_util = float(parts[0].strip())
                        gpu_power = float(parts[1].strip())
                        gpu_temp_raw = float(parts[2].strip())
            except Exception:
                pass
            self._cached_gpu_util = gpu_util
            self._cached_gpu_power = gpu_power
            self._cached_gpu_temp = gpu_temp_raw
            self._last_gpu_query = now_mono
        else:
            gpu_util = self._cached_gpu_util
            gpu_power = self._cached_gpu_power
            gpu_temp_raw = self._cached_gpu_temp
            
        # 8. Workload-aware GPU filtering with smooth transition
        # FIXED: Lower thresholds to avoid zeroing out idle GPU readings
        # Power threshold: 3W, Utilization threshold: 1%
        power_factor = min(1.0, max(0.0, (gpu_power - 0.5) / 2.5))  # Smooth ramp 0.5-3W
        util_factor = min(1.0, max(0.0, (gpu_util - 0.5) / 2.0))    # Smooth ramp 0.5-2.5%
        filter_confidence = max(power_factor, util_factor)  # Either can enable GPU tracking
        filtered_gpu = gpu_util * filter_confidence  # Scale utilization by filter confidence
            
        # Use raw GPU directly without smoothing buffer (same reasoning as CPU)
        smooth_gpu = filtered_gpu
        
        # 9. Thermal Inertia Simulation for Fallback Temperatures
        # Smooth CPU temperature
        target_cpu_temp = 38.0 + 0.42 * smooth_cpu
        self._cpu_temp_smooth += 0.08 * (target_cpu_temp - self._cpu_temp_smooth)
        cpu_temp = self._cpu_temp_smooth
        
        # Smooth GPU temperature (use nvidia-smi reading if available, else fallback smooth)
        if gpu_temp_raw > 0.0:
            gpu_temp = gpu_temp_raw
        else:
            target_gpu_temp = 38.0 + 0.45 * smooth_gpu
            self._gpu_temp_smooth += 0.08 * (target_gpu_temp - self._gpu_temp_smooth)
            gpu_temp = self._gpu_temp_smooth
            
        # 10. Disk and Network rates
        now = time.monotonic()
        dk  = psutil.disk_io_counters()
        # ponytail: Cache I/O counters, query only every 10s (not every cycle)
        if now_mono - self._last_io_query >= 10.0:
            dk = psutil.disk_io_counters()
            nk = psutil.net_io_counters()
            self._last_io_query = now_mono
            self._cached_dk = dk
            self._cached_nk = nk
        else:
            dk = self._cached_dk
            nk = self._cached_nk

        disk_raw  = (dk.read_bytes + dk.write_bytes) if dk else 0
        disk_rate = ((disk_raw - dk_prev['val']) / max(now - dk_prev['time'], 1e-6)) if dk_prev else 0.0

        net_raw  = (nk.bytes_sent + nk.bytes_recv) if nk else 0
        net_rate = ((net_raw - nk_prev['val']) / max(now - nk_prev['time'], 1e-6)) if nk_prev else 0.0


        raw_data = {
            "timestamp":  ts,
            "cpu":        round(smooth_cpu, 2),
            "gpu":        round(smooth_gpu, 2),
            "memory":     round(mem, 2),
            "disk_io":    max(0.0, disk_rate),
            "network_io": max(0.0, net_rate),
            "cpu_temp":   round(cpu_temp, 1), 
            "gpu_temp":   round(gpu_temp, 1),
            "cpu_power":  round(cpu_power, 2),
            "gpu_power":  round(gpu_power, 2),
            # Support both format keys for backend consumers
            "cpu_util":   round(smooth_cpu, 2),
            "gpu_util":   round(smooth_gpu, 2),
            "mem_util":   round(mem, 2),
            "power_draw": round(cpu_power + gpu_power, 2),
        }
        
        return (
            raw_data,
            {"val": disk_raw, "time": now},
            {"val": net_raw,  "time": now},
        )

    def predict(self, raw_data: dict, rack_id: str = "rack_0") -> tuple:
        self.validate_telemetry(raw_data)
        X = self.processor.process_single(raw_data)

        assert X.shape == (1, 15)
        assert np.all(np.isfinite(X))
        assert np.all(X >= 0)
        assert np.all(X <= 1)

        heat_n = float(X[0, FEATURE_IDX["heat_norm"]])
        xgb_score = float(np.clip(self._xgb_model.predict(X)[0], 0.0, 1.0))
        gnn_emb = self.gnn_engine.compute_single(rack_id=rack_id, self_heat=heat_n)

        risk_score = fuse(xgb_score, gnn_emb)
        risk_level = get_risk_level(risk_score)
        return risk_score, risk_level, gnn_emb

    def log_result(self, raw_data: dict, risk_score: float, risk_level: str, gnn_emb: float) -> None:
        # ponytail: Batch CSV writes every 60 cycles (~60s) instead of every cycle (50x reduction in disk I/O)
        log_row = {
            **raw_data,
            "gnn_embedding": round(float(gnn_emb), 4),
            "risk_score":    round(float(risk_score), 4),
            "risk_level":    risk_level,
        }
        self._log_buffer.append(log_row)
        self._log_buffer_count += 1

        # Flush batch every 60 samples (~60 seconds at 1Hz)
        if self._log_buffer_count >= 60:
            os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_LOG)), exist_ok=True)
            file_exists = os.path.isfile(OUTPUT_LOG)
            pd.DataFrame(self._log_buffer).to_csv(OUTPUT_LOG, mode='a', index=False, header=not file_exists)
            self._log_buffer = []
            self._log_buffer_count = 0

def log_orchestration(payload: dict):
    os.makedirs(os.path.dirname(os.path.abspath(ORCHESTRATION_LOG)), exist_ok=True)
    file_exists = os.path.isfile(ORCHESTRATION_LOG)
    pd.DataFrame([payload]).to_csv(ORCHESTRATION_LOG, mode='a', index=False, header=not file_exists)

# =============================================================================
# MAIN LOOP
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--reactive', action='store_true', help="Run in Reactive vs Predictive comparison mode")
    args = parser.parse_args()

    print("-" * 60)
    print("  AI-Driven Predictive Cooling -- Live Orchestration Engine")
    print("-" * 60)

    try:
        engine = InferenceEngine(run_parity_check=True)
        policy_engine = ThermalModeController()
        fan_controller = HardwareFanController()
    except Exception as exc:
        print(f"[FATAL] Initialization failed: {exc}")
        sys.exit(1)

    dk_init = psutil.disk_io_counters()
    nk_init = psutil.net_io_counters()
    dk_prev = {"val": (dk_init.read_bytes + dk_init.write_bytes) if dk_init else 0, "time": time.monotonic()}
    nk_prev = {"val": (nk_init.bytes_sent + nk_init.bytes_recv) if nk_init else 0, "time": time.monotonic()}

    print(f"\nRunning at {INTERVAL}s intervals. Press Ctrl-C to stop.\n")
    if args.reactive:
        print(">> COMPARISON MODE ACTIVE: Showing Predictive vs Reactive outputs.")

    try:
        while True:
            tick_start = time.monotonic()

            try:
                raw_data, dk_prev, nk_prev = engine.collect_telemetry(dk_prev, nk_prev)
                risk_score, risk_level, gnn_emb = engine.predict(raw_data)
                
                # Update Fan Policy Deterministically
                target_fan, policy_state, is_stabilizing, diagnostics = policy_engine.update(risk_score, raw_data)
                
                # Actuate Hardware Abstraction
                fan_controller.write_target(risk_score, target_fan, policy_state, is_stabilizing)
                
                # Generate Logs
                engine.log_result(raw_data, risk_score, risk_level, gnn_emb)
                
                orchestration_payload = {
                    "timestamp": raw_data["timestamp"],
                    "future_risk": round(risk_score, 4),
                    "target_fan_percent": round(target_fan, 2),
                    "actual_fan_percent": round(target_fan, 2), # Assuming hardware reaches target
                    "policy_state": policy_state,
                    "stabilization_active": is_stabilizing,
                    "orchestration_event": "UPDATED"
                }
                
                orchestration_payload.update(diagnostics)
                
                if args.reactive:
                    # Simulate reactive target based purely on temp
                    reactive_risk = max((raw_data['cpu_temp']-35)/50, (raw_data['gpu_temp']-40)/50)
                    reactive_risk = np.clip(reactive_risk, 0, 1)
                    # Simple reactive step
                    reactive_fan = 30
                    if reactive_risk > 0.7: reactive_fan = 100
                    elif reactive_risk > 0.5: reactive_fan = 60
                    orchestration_payload["reactive_fan_percent"] = reactive_fan
                    orchestration_payload["reactive_risk"] = round(reactive_risk, 4)
                
                log_orchestration(orchestration_payload)

                print(
                    f"[{raw_data['timestamp']}] "
                    f"Risk={risk_score:.3f} | "
                    f"Fan={target_fan:5.1f}% | "
                    f"State={policy_state:<10s} | "
                    f"Stab={is_stabilizing}"
                )

            except Exception as e:
                print(f"[ERROR] Inference loop failed: {e}. Executing FAIL-SAFE override.")
                target_fan, policy_state, is_stabilizing = 100.0, "CRITICAL", False
                fan_controller.write_target(1.0, target_fan, policy_state, is_stabilizing)

            elapsed = time.monotonic() - tick_start
            time.sleep(max(0.01, INTERVAL - elapsed))

    except KeyboardInterrupt:
        print("\n[InferenceEngine] Stopped by user.")


if __name__ == "__main__":
    main()
