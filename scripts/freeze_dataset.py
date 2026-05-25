import os
import shutil
import hashlib
import json
import pickle
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

import sys

# Configure path to import src/constants
_SCRIPTS_DIR = os.path.abspath(os.path.dirname(__file__))
_SRC_PATH = os.path.abspath(os.path.join(_SCRIPTS_DIR, '..', 'src'))
if _SRC_PATH not in sys.path:
    sys.path.insert(0, _SRC_PATH)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
ARTIFACTS_ROOT = Path("artifacts")
REGISTRY_DIR = ARTIFACTS_ROOT / "registry"
DATASETS_DIR = ARTIFACTS_ROOT / "datasets"
LATEST_DIR = ARTIFACTS_ROOT / "latest"

REQUIRED_FILES = {
    "master_telemetry_dataset.csv": Path("data/raw/master_telemetry_dataset.csv"),
    "X.csv": Path("data/processed/X.csv"),
    "y.csv": Path("data/processed/y.csv"),
    "processed_dataset.csv": Path("data/processed/processed_dataset.csv"),
    "preprocessor_state.pkl": Path("models/preprocessor_state.pkl"),
    "dataset_summary.txt": Path("data/raw/dataset_summary.txt")
}

def get_sha256(file_path: Path) -> str:
    """Generate SHA256 hash for a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def validate_artifacts() -> Dict[str, Any]:
    """Perform rigorous validation before freezing."""
    logger.info("Starting artifact validation...")
    
    # 1. Check existence
    for name, path in REQUIRED_FILES.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing required artifact: {path}")

    # 2. Load and validate data integrity
    X = pd.read_csv(REQUIRED_FILES["X.csv"])
    y = pd.read_csv(REQUIRED_FILES["y.csv"])
    master = pd.read_csv(REQUIRED_FILES["master_telemetry_dataset.csv"])
    
    # Feature count check
    if X.shape[1] != 15:
        raise ValueError(f"X.csv has {X.shape[1]} features, expected 15.")
    
    # Row count consistency
    # Due to prediction horizon shift, X and y are truncated by PREDICTION_HORIZON_STEPS
    from constants import PREDICTION_HORIZON_STEPS
    expected_rows = len(master) - PREDICTION_HORIZON_STEPS
    if not (len(X) == len(y) == expected_rows):
        raise ValueError(f"Row count mismatch: X({len(X)}), y({len(y)}), expected_rows({expected_rows})")
    
    # NaN check
    if X.isna().any().any():
        raise ValueError("X.csv contains NaN values.")
    
    # Preprocessor state check
    try:
        with open(REQUIRED_FILES["preprocessor_state.pkl"], "rb") as f:
            state = pickle.load(f)
            if not all(k in state for k in ["max_disk_log", "max_net_log"]):
                raise ValueError("preprocessor_state.pkl is missing required keys.")
    except Exception as e:
        raise ValueError(f"Failed to load preprocessor_state.pkl: {e}")

    logger.info("Validation successful.")
    return {
        "row_count": len(X),
        "feature_names": X.columns.tolist(),
        "workload_distribution": master["workload_label"].value_counts().to_dict()
    }

def get_next_version() -> str:
    """Determine the next dataset version (v1, v2, ...)."""
    if not DATASETS_DIR.exists():
        return "dataset_v1"
    
    versions = [d.name for d in DATASETS_DIR.iterdir() if d.is_dir() and d.name.startswith("dataset_v")]
    if not versions:
        return "dataset_v1"
    
    version_nums = [int(v.replace("dataset_v", "")) for v in versions]
    return f"dataset_v{max(version_nums) + 1}"

def create_readme(version_dir: Path, version: str, validation_data: Dict):
    """Generate a README.txt for the frozen dataset."""
    readme_content = f"""AI PREDICTIVE COOLING SYSTEM - DATASET SNAPSHOT
================================================

Dataset Version: {version}
Created At: {datetime.now().isoformat()}

PURPOSE:
This dataset is a canonical training asset for the sensor-free predictive cooling model.
It represents a production-aligned snapshot of telemetry and engineered features.

FEATURE DEFINITIONS:
0-5:   Base normalized telemetry (CPU, GPU, MEM, Disk, Net, Heat)
6-11:  Rolling means (Window 5 and 10) for CPU, GPU, Heat
12-14: Deltas (current - previous) for CPU, GPU, Heat

NORMALIZATION RULES:
- CPU/GPU/Memory: Linear scaling (/100), clipped [0,1]
- Disk/Network: Logarithmic scaling (log1p(x) / max_log_rate), clipped [0,1]
- Target Future Risk: Time-shifted (t + horizon) workload-based / physical thermal escalation risk, clipped [0,1]

LINEAGE:
- Source Data: 7 telemetry files (logs/ datasets/)
- Metadata: Cleaned and standardized via scripts/normalize_metadata.py
- Preprocessing: Stateful row-by-row via FeatureProcessor (src/features.py)

INTEGRITY:
Check checksums.txt for SHA256 hashes of all artifacts.
"""
    with open(version_dir / "README.txt", "w") as f:
        f.write(readme_content)

def main():
    try:
        # 1. Validate
        validation_data = validate_artifacts()
        
        # 2. Setup Directories
        version = get_next_version()
        version_dir = DATASETS_DIR / version
        version_dir.mkdir(parents=True, exist_ok=False) # Fail if exists
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        LATEST_DIR.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Freezing dataset as {version}...")
        
        # 3. Copy Artifacts and Generate Checksums
        checksums = []
        for name, src_path in REQUIRED_FILES.items():
            dst_path = version_dir / name
            shutil.copy2(src_path, dst_path)
            checksum = get_sha256(src_path)
            checksums.append(f"{name} -> {checksum}")
            
        with open(version_dir / "checksums.txt", "w") as f:
            f.write("\n".join(checksums))
            
        # 4. Generate Metadata (Task 11)
        from constants import PREDICTION_HORIZON_SEC, PREDICTION_HORIZON_STEPS, FEATURE_SCHEMA_VERSION
        metadata = {
            "dataset_version": version,
            "created_at": datetime.now().isoformat(),
            "row_count": validation_data["row_count"],
            "feature_count": 15,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "horizon_seconds": PREDICTION_HORIZON_SEC,
            "horizon_steps": PREDICTION_HORIZON_STEPS,
            "model_version": "xgboost_v2_predictive",
            "label_formula": "generate_future_thermal_risk with 30s prediction horizon",
            "normalization": {
                "cpu_gpu_memory": "linear /100",
                "disk_network": "log scaling"
            },
            "feature_order": validation_data["feature_names"],
            "workload_distribution": validation_data["workload_distribution"],
            "preprocessor_state_path": "models/preprocessor_state.pkl",
            "notes": "production-aligned predictive forecasting preprocessing snapshot"
        }
        
        with open(version_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=4)
            
        # 5. Create README
        create_readme(version_dir, version, validation_data)
        
        # 6. Update Registry
        registry_path = REGISTRY_DIR / "dataset_registry.csv"
        registry_entry = pd.DataFrame([{
            "dataset_version": version,
            "created_at": metadata["created_at"],
            "row_count": metadata["row_count"],
            "feature_count": 15,
            "label_count": metadata["row_count"], # 1-to-1 labels
            "notes": metadata["notes"]
        }])
        
        if registry_path.exists():
            registry_entry.to_csv(registry_path, mode='a', header=False, index=False)
        else:
            registry_entry.to_csv(registry_path, index=False)
            
        # 7. Update Latest Pointer
        latest_pointer = LATEST_DIR / "current_version.txt"
        with open(latest_pointer, "w") as f:
            f.write(version)
            
        logger.info(f"Successfully frozen artifacts in {version_dir}")
        print(f"\n[OK] DATASET FREEZE COMPLETE: {version}")
        print(f"Location: {version_dir}")
        print(f"Checksums and Metadata generated.")

    except Exception as e:
        logger.error(f"Freeze operation failed: {e}")
        # Cleanup if directory was created but failed mid-way
        if 'version_dir' in locals() and version_dir.exists():
            logger.warning(f"Cleaning up failed freeze directory: {version_dir}")
            shutil.rmtree(version_dir)
        exit(1)

if __name__ == "__main__":
    main()
