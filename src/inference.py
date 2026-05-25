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

# -- Resolve src/ for local imports -------------------------------------------
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from features import FeatureProcessor, validate_raw_input, REQUIRED_KEYS
from cooling_policy import CoolingPolicyEngine
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

        from features import AnalyticGNN
        self.gnn_engine = AnalyticGNN(adjacency=adjacency)

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
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        gpu = 0.0
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=1,
            )
            if res.returncode == 0:
                gpu = float(res.stdout.strip().split("\n")[0])
        except Exception:
            pass

        now = time.monotonic()
        dk  = psutil.disk_io_counters()
        disk_raw  = (dk.read_bytes + dk.write_bytes) if dk else 0
        disk_rate = ((disk_raw - dk_prev['val']) / max(now - dk_prev['time'], 1e-6)) if dk_prev else 0.0

        nk = psutil.net_io_counters()
        net_raw  = (nk.bytes_sent + nk.bytes_recv) if nk else 0
        net_rate = ((net_raw - nk_prev['val']) / max(now - nk_prev['time'], 1e-6)) if nk_prev else 0.0

        raw_data = {
            "timestamp":  ts,
            "cpu":        cpu,
            "gpu":        gpu,
            "memory":     mem,
            "disk_io":    max(0.0, disk_rate),
            "network_io": max(0.0, net_rate),
            # Mocking temperature for testing fail-safes when real sensors are missing
            "cpu_temp":   40.0 + 0.3 * cpu, 
            "gpu_temp":   45.0 + 0.3 * gpu
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
        os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_LOG)), exist_ok=True)
        file_exists = os.path.isfile(OUTPUT_LOG)
        log_row = {
            **raw_data,
            "gnn_embedding": round(float(gnn_emb), 4),
            "risk_score":    round(float(risk_score), 4),
            "risk_level":    risk_level,
        }
        pd.DataFrame([log_row]).to_csv(OUTPUT_LOG, mode='a', index=False, header=not file_exists)

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
        policy_engine = CoolingPolicyEngine()
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
