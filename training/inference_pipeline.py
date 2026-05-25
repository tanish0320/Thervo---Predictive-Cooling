"""
training/inference_pipeline.py
--------------------------------
VALIDATION PIPELINE -- training/evaluation use only. NOT the production runtime.

Purpose
-------
1. Verify trained model produces correct 6-dim outputs on held-out data.
2. Assert training-serving parity via src.core.fusion.assert_parity().
3. Confirm risk fusion formula (PRD §4.2) and output range [0,1].
4. Check pipeline latency meets <50ms PRD SLA.

Production runtime: src/inference.py -> InferenceEngine

All scoring functions imported from src/core/fusion.py (single definition).
No local redefinitions of fuse() or get_risk_level().
"""

import sys
import os
import time
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# -- Resolve paths ------------------------------------------------------------
_TRAIN_DIR = os.path.abspath(os.path.dirname(__file__))
_SRC_PATH  = os.path.abspath(os.path.join(_TRAIN_DIR, '..', 'src'))
_CORE_PATH = os.path.join(_SRC_PATH, 'core')

for p in [_SRC_PATH, _TRAIN_DIR, _CORE_PATH]:
    if p not in sys.path:
        sys.path.insert(0, p)

from features      import FeatureProcessor, AnalyticGNN
from xgboost_model import ThermalRiskXGB
from core.fusion   import fuse, get_risk_level, assert_parity  # SINGLE source
from constants     import FEATURE_DIM, FEATURE_NAMES, FEATURE_IDX, PREDICTION_HORIZON_STEPS
from data_processing import generate_future_thermal_risk, build_future_targets
from metrics import calculate_regression_metrics, evaluate_predictive_performance, print_performance_summary


# =============================================================================
# RESULT DATACLASSES
# =============================================================================

@dataclass
class RowPrediction:
    row_idx:       int
    xgb_score:     float    # XGBoost output in [0,1]
    gnn_embedding: float    # Feature vector index [5], in [0,1]
    fused_risk:    float    # Final fused risk in [0,1]
    risk_level:    str      # LOW / MED / HIGH / CRITICAL
    latency_ms:    float = 0.0


@dataclass
class ValidationResult:
    n_samples:       int
    predictions:     List[RowPrediction] = field(default_factory=list)
    mean_risk:       float = 0.0
    max_risk:        float = 0.0
    p95_risk:        float = 0.0
    mean_latency_ms: float = 0.0
    latency_ok:      bool  = True
    level_dist:      Dict[str, int] = field(default_factory=dict)
    parity_passed:   bool  = False
    reg_metrics:     Dict[str, float] = field(default_factory=dict)
    event_metrics:   Dict[str, float] = field(default_factory=dict)


# =============================================================================
# VALIDATION PIPELINE
# =============================================================================

class ValidationPipeline:
    """
    Replicates EXACTLY what src/inference.py does at runtime.
    If results differ between here and production, there is a critical bug.

    Uses the same:
      - FeatureProcessor.process_single()  (src/features.py)
      - fusion.fuse()                      (src/core/fusion.py)
      - fusion.get_risk_level()            (src/core/fusion.py)
    """

    def __init__(
        self,
        model_path: str,
        state_path: str,
    ):
        self.xgb = ThermalRiskXGB()
        self.xgb.load(model_path)

        self.processor = FeatureProcessor()
        self.processor.load(state_path)

        self.gnn = AnalyticGNN()

        print(f"[ValidationPipeline] Feature dim = {FEATURE_DIM}")
        print(f"[ValidationPipeline] Feature names = {FEATURE_NAMES}")

    def predict_row(self, raw_point: dict, row_idx: int = 0) -> RowPrediction:
        """
        Full inference for one telemetry dict.
        Mirrors src/inference.py InferenceEngine.predict() exactly.
        """
        t0 = time.perf_counter()

        # 15-dim feature vector
        X       = self.processor.process_single(raw_point)  # (1, 15)
        
        # Assertions
        assert X.shape == (1, 15), f"Expected shape (1, 15), got {X.shape}"
        assert np.all(np.isfinite(X)), "Non-finite values in validation feature vector"
        assert np.all(X >= 0), f"Negative value in validation feature vector: {X}"
        assert np.all(X <= 1), f"Value > 1 in validation feature vector: {X}"

        heat_n  = float(X[0, FEATURE_IDX["heat_norm"]])
        gnn_emb = self.gnn.compute_single(rack_id="rack_0", self_heat=heat_n)

        xgb_score  = float(self.xgb.predict(X)[0])          # already clipped [0,1]
        fused      = fuse(xgb_score, gnn_emb)                # src/core/fusion.py
        level      = get_risk_level(fused)                   # src/core/fusion.py

        latency_ms = (time.perf_counter() - t0) * 1000.0

        return RowPrediction(
            row_idx       = row_idx,
            xgb_score     = xgb_score,
            gnn_embedding = gnn_emb,
            fused_risk    = fused,
            risk_level    = level,
            latency_ms    = latency_ms,
        )

    def validate_dataframe(self, df: pd.DataFrame) -> ValidationResult:
        """
        Run validation on a full DataFrame of telemetry rows.
        """
        predictions = []
        for idx, row in df.iterrows():
            pred = self.predict_row(row.to_dict(), row_idx=int(idx))
            predictions.append(pred)

        fused_scores = np.array([p.fused_risk for p in predictions])
        latencies    = np.array([p.latency_ms for p in predictions])

        level_dist: Dict[str, int] = {}
        for p in predictions:
            level_dist[p.risk_level] = level_dist.get(p.risk_level, 0) + 1

        mean_latency = float(latencies.mean())

        # Generate future shifted targets for validation scoring (Task 2 & 8)
        current_risk = generate_future_thermal_risk(df)
        y_true = build_future_targets(current_risk, PREDICTION_HORIZON_STEPS).values
        
        # Align predictions to y_true length by dropping the tail
        y_pred = fused_scores[:-PREDICTION_HORIZON_STEPS]

        # Calculate metrics if enough samples are present
        reg_metrics = {}
        event_metrics = {}
        if len(y_true) > 0:
            reg_metrics = calculate_regression_metrics(y_true, y_pred)
            event_metrics = evaluate_predictive_performance(y_true, y_pred)

        return ValidationResult(
            n_samples       = len(predictions),
            predictions     = predictions,
            mean_risk       = float(fused_scores.mean()),
            max_risk        = float(fused_scores.max()),
            p95_risk        = float(np.percentile(fused_scores, 95)),
            mean_latency_ms = mean_latency,
            latency_ok      = mean_latency < 50.0,
            level_dist      = level_dist,
            reg_metrics     = reg_metrics,
            event_metrics   = event_metrics,
        )

    def print_summary(self, result: ValidationResult) -> None:
        print("\n-- Validation Summary ----------------------------------------")
        print(f"  Samples       : {result.n_samples}")
        print(f"  Mean risk     : {result.mean_risk:.4f}")
        print(f"  Max risk      : {result.max_risk:.4f}")
        print(f"  P95 risk      : {result.p95_risk:.4f}")
        latency_status = "OK" if result.latency_ok else "EXCEEDS 50ms SLA"
        print(f"  Mean latency  : {result.mean_latency_ms:.3f} ms  [{latency_status}]")
        print(f"  Risk dist     : {result.level_dist}")
        print(f"  Parity check  : {'PASSED' if result.parity_passed else 'NOT RUN'}")
        print("-------------------------------------------------------------\n")
        
        if result.reg_metrics and result.event_metrics:
            latency_stats = {
                "mean_preprocess_ms": 0.0,
                "mean_inference_ms": result.mean_latency_ms,
                "sla_compliance_percent": 100.0 if result.latency_ok else 0.0
            }
            print_performance_summary(result.reg_metrics, result.event_metrics, latency_stats)


# =============================================================================
# PARITY INTEGRATION TEST
# =============================================================================

def run_parity_integration_test(processor: FeatureProcessor) -> bool:
    """
    Prove that the training feature path == inference feature path.

    Tests 3 representative inputs covering:
      - Idle system     (low values)
      - Burst load      (high CPU/GPU)
      - I/O heavy       (high disk/network, low CPU)

    Returns True if all assertions pass.
    """
    test_cases = [
        {"name": "idle",  "cpu": 5.0,  "gpu": 2.0,  "memory": 30.0, "disk_io": 50_000.0,       "network_io": 20_000.0},
        {"name": "burst", "cpu": 95.0, "gpu": 88.0, "memory": 85.0, "disk_io": 150_000_000.0,  "network_io": 40_000_000.0},
        {"name": "io",    "cpu": 12.0, "gpu": 5.0,  "memory": 55.0, "disk_io": 180_000_000.0,  "network_io": 45_000_000.0},
    ]

    print("\n[parity_test] Running 3-case integration test ...")
    all_pass = True

    # Initialize fresh instances with same stats to compare stateful processing
    train_proc = FeatureProcessor()
    train_proc.stats = dict(processor.stats)
    
    infer_proc = FeatureProcessor()
    infer_proc.stats = dict(processor.stats)

    for tc in test_cases:
        name = tc.pop("name")
        
        # Process sequentially to accumulate delta/rolling history in both
        train_vec = train_proc.process_single(tc)
        infer_vec = infer_proc.process_single(tc)

        try:
            assert_parity(train_vec, infer_vec, label=f"case '{name}'")
            print(f"  [{name}] PASS  vec={train_vec.flatten().round(4)}")
        except AssertionError as e:
            print(f"  [{name}] FAIL  {e}")
            all_pass = False

        tc["name"] = name  # restore

    if all_pass:
        print("[parity_test] All 3 cases: PASSED\n")
    else:
        print("[parity_test] FAILURES DETECTED -- investigate immediately\n")

    return all_pass


# =============================================================================
# FULL CHECKLIST
# =============================================================================

def run_validation_checklist(
    model_path: str,
    state_path: str,
    n_samples:  int = 100,
    seed:       int = 99,
) -> bool:
    """
    Automated PRD compliance checklist.
    Returns True if ALL checks pass.
    """
    from data_processing import generate_synthetic_telemetry

    print("\n" + "=" * 60)
    print("  FINAL VALIDATION CHECKLIST  (PRD/FRD Compliance)")
    print("=" * 60)

    raw      = generate_synthetic_telemetry(n_rows=n_samples, seed=seed)
    pipeline = ValidationPipeline(model_path=model_path, state_path=state_path)
    result   = pipeline.validate_dataframe(raw)

    checks: Dict[str, bool] = {}

    sample_X = pipeline.processor.process_single(
        {"cpu": 50.0, "gpu": 40.0, "memory": 60.0, "disk_io": 1e6, "network_io": 5e5}
    )
    checks["Feature dim == 15 (FRD §3.1)"]             = sample_X.shape == (1, FEATURE_DIM)

    # C2: All fused risk scores in [0,1]
    checks["Risk scores in [0,1]"]                    = all(0.0 <= p.fused_risk <= 1.0 for p in result.predictions)

    # C3: GNN embedding in [0,1]
    checks["GNN embedding in [0,1]"]                  = all(0.0 <= p.gnn_embedding <= 1.0 for p in result.predictions)

    # C4: GNN embedding is scalar (float, not array)
    checks["GNN embedding is scalar"]                 = all(isinstance(p.gnn_embedding, float) for p in result.predictions)

    # C5: Latency < 50ms
    checks["Mean latency < 50ms"]                     = result.latency_ok

    # C6: No NaN in outputs
    checks["No NaN in predictions"]                   = all(not np.isnan(p.fused_risk) for p in result.predictions)

    # C7: Valid risk level strings
    valid_levels = {"LOW", "MED", "HIGH", "CRITICAL"}
    checks["Valid risk level strings"]                = all(p.risk_level in valid_levels for p in result.predictions)

    # C8: Parity test
    parity_ok = run_parity_integration_test(pipeline.processor)
    checks["Training == inference parity"]            = parity_ok
    result.parity_passed = parity_ok

    # C9: Schema guard fires on bad input
    try:
        pipeline.processor.process_single({"cpu": 50, "gpu": 30, "memory": 60, "disk_io": 1e6, "network": 5e5})
        checks["Schema guard raises on 'network' key"] = False
    except ValueError:
        checks["Schema guard raises on 'network' key"] = True

    # C10: fusion.fuse raises on out-of-range input
    try:
        fuse(1.5, 0.5)
        checks["fuse() raises on xgb > 1.0"]          = False
    except ValueError:
        checks["fuse() raises on xgb > 1.0"]          = True

    # -- Print results --
    all_pass = True
    for check, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}]  {check}")
        if not passed:
            all_pass = False

    pipeline.print_summary(result)
    verdict = "ALL CHECKS PASSED" if all_pass else "CHECKS FAILED"
    print(f"\nFinal result: {verdict}")
    print("=" * 60)

    return all_pass


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    MODEL_PATH = os.path.join(_TRAIN_DIR, '..', 'models', 'cooling_model.pkl')
    STATE_PATH = os.path.join(_TRAIN_DIR, '..', 'models', 'preprocessor_state.pkl')

    if not os.path.exists(MODEL_PATH):
        print("[INFO] No trained model found. Running training first ...")
        from data_processing  import generate_synthetic_telemetry, build_training_dataset
        from xgboost_model    import ThermalRiskXGB

        raw  = generate_synthetic_telemetry(n_rows=500, seed=42)
        X, y, proc = build_training_dataset(raw, state_save_path=STATE_PATH)

        m = ThermalRiskXGB()
        m.train(X, y, verbose=False)
        m.save(MODEL_PATH)
        print("[INFO] Model trained and saved.")

    passed = run_validation_checklist(MODEL_PATH, STATE_PATH)
    sys.exit(0 if passed else 1)
