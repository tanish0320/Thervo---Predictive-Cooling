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

# Prevent OpenMP / MKL / XGBoost worker threads from busy-spinning at 100% CPU when idle
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
import time
import pickle
import subprocess
import numpy as np
import pandas as pd
import psutil
from datetime import datetime
from typing import Optional, Dict, List, Any, Union

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
from constants import FEATURE_DIM, FEATURE_IDX, GPU_NOISE_FLOOR_PCT

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

        from xai import DecisionExplainer, XAIHistory
        self.explainer = DecisionExplainer()
        self.xai_history = XAIHistory(max_capacity=100)
        self._prev_raw_data = None
        self._prev_risk_score = None
        self._prev_cooling_strength = None
        self._prev_gnn_emb = None
        self._last_xai_explanation = None

        # ponytail: CSV batching buffer - flush every 60 cycles (~60s)
        self._log_buffer = []
        self._log_buffer_count = 0

        if run_parity_check:
            self._startup_parity_check()

    def explain(
        self,
        raw_data: dict,
        risk_score: float,
        cooling_strength: float = 0.0,
        rack_id: str = "RACK-A07",
        epoch: Optional[int] = None,
        gnn_emb: Optional[float] = None,
        is_manual_override: bool = False
    ) -> dict:
        """
        Generate observational XAI decision explanation for the current inference step.
        Does not alter model predictions, risk scores, or cooling actions.
        """
        explanation = self.explainer.explain_decision(
            current_telemetry=raw_data,
            previous_telemetry=self._prev_raw_data,
            current_risk=risk_score,
            previous_risk=self._prev_risk_score,
            current_cooling_strength=cooling_strength,
            previous_cooling_strength=self._prev_cooling_strength,
            rack_id=rack_id,
            epoch=epoch,
            gnn_embedding=gnn_emb,
            previous_gnn_embedding=self._prev_gnn_emb,
            is_manual_override=is_manual_override,
            model=self._xgb_model
        )

        self._prev_raw_data = dict(raw_data)
        self._prev_risk_score = risk_score
        self._prev_cooling_strength = cooling_strength
        self._prev_gnn_emb = gnn_emb
        self._last_xai_explanation = explanation
        self.xai_history.add(explanation)
        return explanation

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
            psutil.cpu_percent(interval=None)  # Prime baseline
            self._cached_cpu = 15.0  # Initial placeholder until first query
            self._cached_gpu_util = 0.0
            self._cached_gpu_power = 0.0
            self._cached_gpu_temp = 0.0
            self._last_cpu_query = 0.0  # Force immediate query on tick 1
            self._last_gpu_query = 0.0
            
            if sys.platform == "win32":
                try:
                    import ctypes
                    class _FILETIME(ctypes.Structure):
                        _fields_ = [('dwLowDateTime', ctypes.c_uint32), ('dwHighDateTime', ctypes.c_uint32)]
                    idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
                    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
                    to_int = lambda ft: (ft.dwHighDateTime << 32) + ft.dwLowDateTime
                    self._prev_win_times = (to_int(idle), to_int(kernel), to_int(user))
                except Exception:
                    pass

        # 1. Update excluded process list (ONLY browsers/UI processes, not python workers)
        if now_mono - self._last_pid_update >= 30.0:
            self._browser_pids = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    name_lower = proc.info['name'].lower() if proc.info['name'] else ""
                    if name_lower in ("msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe"):
                        self._browser_pids.append(proc.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self._last_pid_update = now_mono

        # 2. Get system CPU percent using instance-tracked Win32 GetSystemTimes (sampled once per second)
        if now_mono - self._last_cpu_query >= 1.0:
            if sys.platform == "win32":
                try:
                    import ctypes
                    class _FILETIME(ctypes.Structure):
                        _fields_ = [('dwLowDateTime', ctypes.c_uint32), ('dwHighDateTime', ctypes.c_uint32)]
                    
                    idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
                    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
                    to_int = lambda ft: (ft.dwHighDateTime << 32) + ft.dwLowDateTime
                    i2, k2, u2 = to_int(idle), to_int(kernel), to_int(user)
                    
                    if hasattr(self, "_prev_win_times"):
                        i1, k1, u1 = self._prev_win_times
                        tot = (k2 - k1) + (u2 - u1)
                        busy = tot - (i2 - i1)
                        if tot > 1000:
                            self._cached_cpu = min(100.0, max(0.0, 100.0 * (busy / tot)))
                        else:
                            self._cached_cpu = psutil.cpu_percent(interval=None)
                    else:
                        self._cached_cpu = psutil.cpu_percent(interval=None)
                    self._prev_win_times = (i2, k2, u2)
                except Exception:
                    self._cached_cpu = psutil.cpu_percent(interval=None)
            else:
                self._cached_cpu = psutil.cpu_percent(interval=None)
            self._last_cpu_query = time.monotonic()

        sys_cpu = self._cached_cpu


        # 3. Use raw system CPU as the authoritative metric
        filtered_cpu = max(0.0, sys_cpu)

        # 4. CPU Package Power Query / Estimation
        cpu_power = getattr(self, "_cached_cpu_power", 0.0)
        # Try to query CPU Package Power from OpenHardwareMonitor WMI (rate limit to once every 5s to avoid spawning powershell process every tick)
        if getattr(self, "_check_wmi_power", True) and sys.platform == "win32" and (now_mono - getattr(self, "_last_power_query", 0.0) >= 5.0):
            self._last_power_query = now_mono
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
                    self._cached_cpu_power = cpu_power
                else:
                    # OpenHardwareMonitor WMI not present; stop spawning powershell subprocesses
                    self._wmi_fail_count = getattr(self, "_wmi_fail_count", 0) + 1
                    if self._wmi_fail_count >= 2:
                        self._check_wmi_power = False
            except Exception:
                self._check_wmi_power = False

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
        
        # 7. GPU Telemetry from NVML C-DLL (Microsecond direct hardware query) with nvidia-smi fallback
        if now_mono - self._last_gpu_query >= 0.5:
            self._last_gpu_query = now_mono
            gpu_queried = False
            
            # Try NVML C-DLL direct hardware query first
            if not hasattr(self, "_nvml_ok"):
                self._nvml_ok = False
                if sys.platform == "win32":
                    try:
                        import ctypes
                        self._ctypes = ctypes
                        self._nvml = ctypes.cdll.LoadLibrary("nvml.dll")
                        self._nvml.nvmlInit_v2()
                        self._nvml_device = ctypes.c_void_p()
                        self._nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self._nvml_device))
                        class _c_nvmlUtil(ctypes.Structure):
                            _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]
                        self._c_nvmlUtil = _c_nvmlUtil
                        self._nvml_ok = True
                    except Exception:
                        self._nvml_ok = False

            if self._nvml_ok:
                try:
                    utils = self._c_nvmlUtil()
                    if self._nvml.nvmlDeviceGetUtilizationRates(self._nvml_device, self._ctypes.byref(utils)) == 0:
                        self._cached_gpu_util = float(utils.gpu)
                        gpu_queried = True
                    
                    temp = self._ctypes.c_uint()
                    if self._nvml.nvmlDeviceGetTemperature(self._nvml_device, 0, self._ctypes.byref(temp)) == 0:
                        self._cached_gpu_temp = float(temp.value)
                        
                    pwr = self._ctypes.c_uint()
                    if self._nvml.nvmlDeviceGetPowerUsage(self._nvml_device, self._ctypes.byref(pwr)) == 0:
                        self._cached_gpu_power = float(pwr.value) / 1000.0
                except Exception:
                    self._nvml_ok = False

            if not gpu_queried:
                try:
                    res = subprocess.run(
                        ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw,temperature.gpu,memory.used", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=1,
                    )
                    if res.returncode == 0:
                        parts = res.stdout.strip().split(",")
                        if len(parts) >= 3:
                            self._cached_gpu_util = float(parts[0].strip())
                            self._cached_gpu_power = float(parts[1].strip())
                            self._cached_gpu_temp = float(parts[2].strip())
                except Exception:
                    pass

        gpu_util = self._cached_gpu_util
        gpu_power = self._cached_gpu_power
        gpu_temp_raw = self._cached_gpu_temp
            
        # 8. Apply WDDM Task Manager normalization calibration factor (0.72x) to align NVML duty cycle with Task Manager
        calibrated_gpu = gpu_util * 0.72
        filtered_gpu = calibrated_gpu if calibrated_gpu >= GPU_NOISE_FLOOR_PCT else 0.0
            
        # Use calibrated GPU directly without smoothing buffer
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
        # Read fresh every tick: the rate is a delta against dk_prev/nk_prev, which
        # advance every tick. Caching the counters made the numerator (cached - cached)
        # zero between refreshes, so disk_io/network_io collapsed to 0.0. These reads
        # are cheap; there is nothing to save here.
        dk = psutil.disk_io_counters()
        nk = psutil.net_io_counters()

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
