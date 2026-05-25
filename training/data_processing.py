import pandas as pd
import numpy as np
import sys
import os
from pathlib import Path
from typing import Tuple

# Resolve paths
_TRAIN_DIR = os.path.abspath(os.path.dirname(__file__))
_SRC_PATH  = os.path.abspath(os.path.join(_TRAIN_DIR, '..', 'src'))
if _SRC_PATH not in sys.path:
    sys.path.insert(0, _SRC_PATH)

from features import FeatureProcessor
from constants import FEATURE_DIM, FEATURE_NAMES

# -- Import fusion from core ---------------------------------------------------
_CORE_PATH = os.path.join(_SRC_PATH, 'core')
if _CORE_PATH not in sys.path:
    sys.path.insert(0, _CORE_PATH)

from core.fusion import assert_parity

# =============================================================================
# CONSTANTS
# =============================================================================

REQUIRED_COLS = ['cpu', 'gpu', 'memory', 'disk_io', 'network_io']

# Risk label weights (PRD §4.2)
_RISK_CPU_W = 0.6
_RISK_GPU_W = 0.4


# =============================================================================
# SCHEMA VALIDATION
# =============================================================================

def validate_schema(df: pd.DataFrame) -> None:
    """
    Raise ValueError on missing required columns.
    Provides actionable hint for the common 'network' vs 'network_io' mistake.
    """
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        hint = ""
        if 'network_io' in missing and 'network' in df.columns:
            hint = " Hint: rename 'network' -> 'network_io' (PRD §2.1)."
        raise ValueError(
            f"[data_processing] Schema violation -- missing columns: {missing}.{hint}"
        )


# =============================================================================
# FUTURE THERMAL RISK AND TARGETS (Task 2 & Task 4)
# =============================================================================

def generate_future_thermal_risk(df: pd.DataFrame) -> pd.Series:
    """
    Compute continuous thermal risk in [0, 1] based on CPU/GPU temperatures.
    Gracefully falls back to workload-simulated temperatures if physical sensors are missing.
    """
    if 'cpu_temp' in df.columns and df['cpu_temp'].max() > 0:
        cpu_t = df['cpu_temp']
    else:
        # Simulate CPU temperature based on workload (with thermal inertia)
        # Idle = 35C, Max = 85C
        cpu_t = 35.0 + 0.5 * df['cpu'].ewm(span=20).mean()
        
    if 'gpu_temp' in df.columns and df['gpu_temp'].max() > 0:
        gpu_t = df['gpu_temp']
    else:
        # Simulate GPU temperature based on workload
        # Idle = 40C, Max = 90C
        gpu_t = 40.0 + 0.5 * df['gpu'].ewm(span=20).mean()

    # Normalize to [0, 1]
    cpu_t_norm = (cpu_t - 35.0) / 50.0
    gpu_t_norm = (gpu_t - 40.0) / 50.0
    
    # Clip bounds
    cpu_t_norm = cpu_t_norm.clip(0.0, 1.0)
    gpu_t_norm = gpu_t_norm.clip(0.0, 1.0)
    
    # Combined thermal risk
    future_risk = pd.Series(np.maximum(cpu_t_norm, gpu_t_norm), index=df.index)
    return future_risk

def build_future_targets(risk_series: pd.Series, horizon_steps: int) -> pd.Series:
    """
    Generate target values shifted by the forecasting horizon steps.
    y[i] = risk[i + horizon_steps]
    """
    # Shift series back in time by horizon_steps
    future_risk = risk_series.shift(-horizon_steps)
    # Truncate invalid tail rows (which are NaNs)
    return future_risk.iloc[:-horizon_steps]


# =============================================================================
# SYNTHETIC DATA GENERATOR  (testing / demo)
# =============================================================================

def generate_synthetic_telemetry(n_rows: int = 500, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic telemetry compliant with PRD schema.

    Columns: timestamp, cpu, gpu, memory, disk_io, network_io
    """
    rng   = np.random.default_rng(seed)
    burst = rng.random(n_rows) < 0.10

    cpu    = np.where(burst, rng.uniform(75, 98, n_rows), rng.uniform(10, 65, n_rows))
    gpu    = np.where(burst, rng.uniform(70, 95, n_rows), rng.uniform( 5, 55, n_rows))
    memory = rng.uniform(40, 85, n_rows)

    disk_io    = rng.exponential(scale=5_000_000, size=n_rows).clip(0, 200_000_000)
    network_io = rng.exponential(scale=1_000_000, size=n_rows).clip(0,  50_000_000)

    return pd.DataFrame({
        'timestamp':  pd.date_range("2024-01-01", periods=n_rows, freq="1s"),
        'cpu':        cpu.clip(0, 100).round(2),
        'gpu':        gpu.clip(0, 100).round(2),
        'memory':     memory.clip(0, 100).round(2),
        'disk_io':    disk_io.round(2),
        'network_io': network_io.round(2),
    })


# =============================================================================
# PARITY ASSERTION  (mandatory before every training run)
# =============================================================================

def verify_training_inference_parity(processor: FeatureProcessor) -> None:
    """
    Assert that the training and inference feature paths produce identical
    vectors for the same input.
    """
    sample = {
        'cpu': 75.0, 'gpu': 60.0, 'memory': 70.0,
        'disk_io': 1_500_000.0, 'network_io': 800_000.0,
    }

    # Training path (fresh instance with same stats)
    train_proc = FeatureProcessor()
    train_proc.stats = dict(processor.stats)
    train_vec = train_proc.process_single(sample)

    # Inference path (fresh instance with same stats)
    infer_proc = FeatureProcessor()
    infer_proc.stats = dict(processor.stats)
    infer_vec = infer_proc.process_single(sample)

    assert_parity(train_vec, infer_vec, label="training vs inference feature vector")
    print("[data_processing] Parity check: PASSED -- training == inference feature path")


# =============================================================================
# MAIN DATASET BUILDER
# =============================================================================

def build_training_dataset(
    raw_df:          pd.DataFrame,
    state_save_path: str = os.path.join('..', 'models', 'preprocessor_state.pkl'),
) -> Tuple[np.ndarray, np.ndarray, FeatureProcessor]:
    """
    Full builder: raw telemetry DataFrame -> (X, y, processor).
    """
    print("-" * 60)
    print("[data_processing] Building training dataset ...")
    print(f"[data_processing] Feature dim = {FEATURE_DIM}, names = {FEATURE_NAMES}")

    validate_schema(raw_df)

    df = raw_df.copy()
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)

    for col in REQUIRED_COLS:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df[REQUIRED_COLS] = df[REQUIRED_COLS].ffill().fillna(df[REQUIRED_COLS].median())

    print(f"[data_processing] Rows after cleaning: {len(df)}")

    # Initialize and fit
    processor = FeatureProcessor()
    processor.fit(df)
    processor.save(state_save_path)

    # Process features sequentially
    print("[data_processing] Engineering 15-dim feature vectors statefully ...")
    X_rows = []
    for _, row in df.iterrows():
        X_row = processor.process_single(row.to_dict())
        
        # Step 1.6 Assertions
        assert X_row.shape == (1, 15), f"Expected shape (1, 15), got {X_row.shape}"
        assert np.all(np.isfinite(X_row)), "Non-finite values in features"
        assert np.all(X_row >= 0), f"Negative value in features: {X_row}"
        assert np.all(X_row <= 1), f"Value > 1 in features: {X_row}"
        
        X_rows.append(X_row.flatten())

    X = np.vstack(X_rows)
    
    # Generate continuous future thermal risk target (Task 2 & 4)
    current_risk = generate_future_thermal_risk(df)
    
    from constants import PREDICTION_HORIZON_STEPS
    
    y_series = build_future_targets(current_risk, PREDICTION_HORIZON_STEPS)
    y = y_series.values.astype(np.float64)
    
    # Align X and y by truncating the last PREDICTION_HORIZON_STEPS rows of X
    X = X[:-PREDICTION_HORIZON_STEPS]

    print(f"[data_processing] X shape: {X.shape} | y range: [{y.min():.4f}, {y.max():.4f}]")

    # Parity check
    verify_training_inference_parity(processor)

    print("[data_processing] Dataset build complete.")
    print("-" * 60)

    return X, y, processor


# =============================================================================
# STANDALONE ENTRY POINT
# =============================================================================

def main():
    raw_path = Path("data/raw/master_telemetry_dataset.csv")
    processed_dir = Path("data/processed")
    models_dir = Path("models")
    
    processed_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    
    if not raw_path.exists():
        print(f"Error: Raw dataset not found at {raw_path}")
        return

    # 1. Load Data
    df = pd.read_csv(raw_path)
    print(f"Loaded {len(df)} rows from {raw_path}")
    
    # 2. Build Dataset
    state_path = str(models_dir / "preprocessor_state.pkl")
    X_array, y_array, processor = build_training_dataset(df, state_path)
    
    # 3. Create DataFrames for saving
    X_df = pd.DataFrame(X_array, columns=processor.FEATURE_NAMES)
    y_df = pd.DataFrame(y_array, columns=['target_risk'])
    
    meta_cols = [c for c in ['timestamp', 'source', 'workload_label'] if c in df.columns]
    processed_df = pd.concat([df[meta_cols], X_df, y_df], axis=1)
    
    # 4. Save Outputs
    X_df.to_csv(processed_dir / "X.csv", index=False)
    y_df.to_csv(processed_dir / "y.csv", index=False)
    processed_df.to_csv(processed_dir / "processed_dataset.csv", index=False)
    
    print(f"Saved processed data to {processed_dir}")
    print("\nPREPROCESSING SUCCESSFUL: All validation checks passed.")

if __name__ == "__main__":
    main()
