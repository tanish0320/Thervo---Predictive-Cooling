"""
training/xgboost_model.py
--------------------------
XGBoost thermal risk regressor -- training logic only.

Input contract (FRD §3.1):
  X : np.ndarray (n_samples, 6)
      [cpu_norm, gpu_norm, memory_norm, disk_io_norm, network_io_norm, gnn_embedding]
      All values in [0, 1].

  y : np.ndarray (n_samples,)
      Risk score in [0, 1].

Output contract:
  predict() returns float in [0, 1].
  Saved model: models/cooling_model.pkl  (joblib tuple: (model, feature_names))

Risk fusion (PRD §4.2) -- performed in src/inference.py, NOT here:
  risk = 0.75 * xgb_prediction + 0.25 * gnn_embedding

Why XGBoost for Phase 1:
  - Best accuracy/latency for 6-dim tabular data at small-medium scale.
  - Interpretable feature importances (patent documentation requirement).
  - Inference < 1ms per row on CPU.
  - Handles non-linear cpu/gpu/gnn interactions without manual feature crosses.
  - No CUDA, no runtime deps beyond xgboost + numpy.

Dependencies: xgboost, scikit-learn, numpy, pandas, joblib
"""

import sys
import os
import numpy as np
import pandas as pd
import xgboost as xgb
import joblib
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from typing import Dict, List, Optional

# -- Resolve paths ------------------------------------------------------------
_TRAIN_DIR = os.path.abspath(os.path.dirname(__file__))
_SRC_PATH  = os.path.abspath(os.path.join(_TRAIN_DIR, '..', 'src'))
if _SRC_PATH not in sys.path:
    sys.path.insert(0, _SRC_PATH)

from features import FEATURE_NAMES, FEATURE_DIM  # single source of truth


# =============================================================================
# HYPERPARAMETERS
# =============================================================================

DEFAULT_XGB_PARAMS: Dict = {
    "n_estimators":     300,
    "max_depth":        6,
    "min_child_weight": 3,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "reg_alpha":        0.1,
    "reg_lambda":       1.0,
    "objective":        "reg:squarederror",
    "eval_metric":      "rmse",
    "random_state":     42,
    "n_jobs":           -1,
    "tree_method":      "hist",
}


# =============================================================================
# MODEL CLASS
# =============================================================================

class ThermalRiskXGB:
    """
    XGBoost regressor for thermal risk prediction.

    Input:  6-dim FRD feature vector, all values in [0, 1].
    Output: risk score in [0, 1].
    """

    def __init__(self, params: Optional[Dict] = None):
        self.params         = params or DEFAULT_XGB_PARAMS
        self.model          = xgb.XGBRegressor(**self.params)
        self.feature_names: List[str] = list(FEATURE_NAMES)  # from src/features.py
        self._is_trained    = False

    # -------------------------------------------------------------------------
    # TRAINING
    # -------------------------------------------------------------------------

    def train(
        self,
        X:              np.ndarray,
        y:              np.ndarray,
        val_fraction:   float = 0.15,
        early_stopping: Optional[int] = None,
        verbose:        bool  = True,
    ) -> Dict:
        """
        Train with auto train/val split and early stopping.

        Parameters
        ----------
        X              : (n_samples, 6), all values in [0,1].
        y              : (n_samples,), risk scores in [0,1].
        val_fraction   : fraction for early-stopping validation set.
        early_stopping : patience in rounds.
        verbose        : print training log.

        Returns
        -------
        dict with val RMSE, MAE, R2.

        Raises
        ------
        ValueError : if X has wrong number of features or values outside [0,1].
        """
        # Validate input dimensions (FRD §3.1)
        if X.shape[1] != FEATURE_DIM:
            raise ValueError(
                f"[ThermalRiskXGB] X has {X.shape[1]} features but FRD requires "
                f"{FEATURE_DIM}. Feature names: {FEATURE_NAMES}."
            )

        # Validate input ranges (catch scale bugs early)
        if X.max() > 1.0 + 1e-6 or X.min() < -1e-6:
            raise ValueError(
                f"[ThermalRiskXGB] X values outside [0,1]: "
                f"range=[{X.min():.4f}, {X.max():.4f}]. "
                f"Ensure data_processing.build_training_dataset() was used."
            )

        # Sequential train/val split to prevent autocorrelation leakage (Task 7)
        n_samples = len(X)
        split_idx = int(n_samples * (1.0 - val_fraction))
        X_tr, y_tr = X[:split_idx], y[:split_idx]
        X_val, y_val = X[split_idx:], y[split_idx:]

        if early_stopping and early_stopping > 0:
            self.model.set_params(
                early_stopping_rounds=early_stopping,
                verbosity=1 if verbose else 0,
            )
        else:
            self.model.set_params(
                early_stopping_rounds=None,
                verbosity=1 if verbose else 0,
            )
        self.model.fit(
            X_tr, y_tr,
            eval_set=[(X_val, y_val)],
            verbose=verbose,
        )

        self._is_trained = True
        metrics = self.evaluate(X_val, y_val, prefix="val")
        if verbose:
            self._print_metrics(metrics)
        return metrics

    # -------------------------------------------------------------------------
    # PREDICTION
    # -------------------------------------------------------------------------

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Predict risk scores, clipped to [0,1].

        Parameters
        ----------
        X : np.ndarray (n_samples, 6) or (1, 6).

        Returns
        -------
        scores : np.ndarray (n_samples,), in [0,1].
        """
        self._check_trained()
        return np.clip(self.model.predict(X), 0.0, 1.0)

    # -------------------------------------------------------------------------
    # EVALUATION
    # -------------------------------------------------------------------------

    def evaluate(self, X: np.ndarray, y: np.ndarray, prefix: str = "test") -> Dict:
        """Return RMSE, MAE, R2 on [0,1] scale."""
        self._check_trained()
        y_pred = self.predict(X)
        return {
            f"{prefix}_rmse": float(np.sqrt(mean_squared_error(y, y_pred))),
            f"{prefix}_mae":  float(mean_absolute_error(y, y_pred)),
            f"{prefix}_r2":   float(r2_score(y, y_pred)),
        }

    # -------------------------------------------------------------------------
    # FEATURE IMPORTANCE
    # -------------------------------------------------------------------------

    def feature_importance_df(self, top_n: int = 10) -> pd.DataFrame:
        """
        Sorted DataFrame of XGBoost feature importances.
        gnn_embedding ranking high validates the analytic GNN adds predictive signal.
        """
        self._check_trained()
        importances = self.model.feature_importances_
        names = self.feature_names or [f"f{i}" for i in range(len(importances))]
        return (
            pd.DataFrame({"feature": names, "importance": importances})
            .sort_values("importance", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )

    # -------------------------------------------------------------------------
    # PERSISTENCE
    # -------------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save (model, feature_names) tuple to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        joblib.dump((self.model, self.feature_names), path)
        print(f"[ThermalRiskXGB] Model saved -> {path}")

    def load(self, path: str) -> None:
        """Load model from disk."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"[ThermalRiskXGB] Model not found at '{path}'.")
        self.model, self.feature_names = joblib.load(path)
        self._is_trained = True
        print(f"[ThermalRiskXGB] Model loaded <- {path}")

    # -------------------------------------------------------------------------
    # INTERNALS
    # -------------------------------------------------------------------------

    def _check_trained(self) -> None:
        if not self._is_trained:
            raise RuntimeError("[ThermalRiskXGB] Not trained. Call .train() first.")

    @staticmethod
    def _print_metrics(metrics: Dict) -> None:
        print("\n-- XGBoost Evaluation -----------------------")
        for k, v in metrics.items():
            print(f"  {k:<22s}: {v:.6f}")
        print("---------------------------------------------\n")


# =============================================================================
# TRAINING ENTRY POINT
# =============================================================================

def train_from_csv(
    csv_path:        str,
    model_save_path: str = os.path.join('..', 'models', 'cooling_model.pkl'),
    state_save_path: str = os.path.join('..', 'models', 'preprocessor_state.pkl'),
    verbose:         bool = True,
) -> "ThermalRiskXGB":
    """
    Full training pipeline from raw CSV to saved model.

    Parameters
    ----------
    csv_path        : path to raw telemetry CSV (must have 'network_io' column).
    model_save_path : where to save the trained XGBoost model.
    state_save_path : where to save the preprocessor state.
    """
    from data_processing import build_training_dataset
    from metrics import calculate_regression_metrics, evaluate_predictive_performance, print_performance_summary
    
    raw_df = pd.read_csv(csv_path)
    X, y, _ = build_training_dataset(raw_df, state_save_path=state_save_path)

    model = ThermalRiskXGB()
    model.train(X, y, verbose=verbose)
    model.save(model_save_path)
    
    # Run evaluation on validation slice and print summary
    n_samples = len(X)
    split_idx = int(n_samples * 0.85)  # 85% train, 15% validation
    X_val, y_val = X[split_idx:], y[split_idx:]
    y_pred = model.predict(X_val)
    
    reg_m = calculate_regression_metrics(y_val, y_pred)
    event_m = evaluate_predictive_performance(y_val, y_pred)
    
    print_performance_summary(reg_m, event_m)
    return model


# =============================================================================
# SMOKE TEST
# =============================================================================

if __name__ == "__main__":
    from data_processing import generate_synthetic_telemetry, build_training_dataset

    print("\n[SMOKE TEST] xgboost_model.py")
    raw = generate_synthetic_telemetry(n_rows=300, seed=1)
    X, y, proc = build_training_dataset(raw, state_save_path="preprocessor_state_xgb_smoke.pkl")

    print(f"\n  X shape      : {X.shape}   (expected: (300, {FEATURE_DIM}))")
    assert X.shape[1] == FEATURE_DIM, f"Feature dim mismatch: {X.shape[1]} != {FEATURE_DIM}"

    model = ThermalRiskXGB()
    metrics = model.train(X, y, verbose=False)
    preds = model.predict(X[:4])

    print(f"  Metrics      : {metrics}")
    print(f"  Sample preds : {preds.round(4)}  (expected: in [0,1])")
    assert all(0.0 <= p <= 1.0 for p in preds), "Predictions outside [0,1]!"

    fi = model.feature_importance_df(top_n=6)
    print(f"\n  Feature importances:\n{fi.to_string(index=False)}")

    print("\ntraining/xgboost_model.py OK")
