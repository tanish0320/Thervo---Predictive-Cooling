# CLAUDE.md - Operations & Development Guide

This file provides instructions on how to build, run, test, and develop the **AI-Driven Sensor-Free Predictive Cooling System** in this repository.

---

## 🚀 Build & Run Commands

### 1. Environment Setup
Create a virtual environment and install the required production/training dependencies:
```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
# OR using uv for speed:
uv pip install -r requirements.txt
```

### 2. Demonstration & Mission Control Dashboard
To run the full end-to-end demo (runs the backend runtime manager, API server on port 8080, and dashboard server on port 3000):
```powershell
# Run the demo script (opens browser to http://localhost:3000/)
python scripts/run_demo.py

# Alternatively, run via bat file (handles admin elevation for Lenovo hardware checks)
.\start_demo.bat
```

To run the frontend dashboard only (static files with mock server interactions):
```powershell
python scripts/run_frontend_only.py
```

### 3. Training & Validation Pipelines
To build the training dataset from raw telemetry and train the XGBoost thermal risk model:
```powershell
# 1. Clean raw telemetry, normalize, and build features
python src/preprocess.py

# 2. Train the ThermalRiskXGB model
python training/xgboost_model.py
```

To run the validation pipeline (verifies training/serving parity and PRD compliance checklist):
```powershell
python training/inference_pipeline.py
```

### 4. Telemetry Collection & Workload Generation
To run the telemetry logger or inference loop standalone:
```powershell
# Run the real-time telemetry collector
python src/telemetry_logger.py

# Run the live inference loop (failsafe fallback mode if not running Lenovo CLI)
python src/inference.py
```

To generate workloads or synthetic telemetry:
```powershell
# Generate synthetic raw telemetry CSV
python scripts/generate_test_data.py

# Run live system workload generator (to stress-test telemetry)
python scripts/workload_generator.py
```

---

## 🧪 Testing Commands

To run the codebase validation and training-serving parity tests:
```powershell
python tests/test_training_serving_parity.py
```

---

## 🛠️ Code Style & Architecture Guidelines

### Core Principles
1. **Single Source of Truth**: All feature preprocessing logic MUST reside in `src/features.py` (`FeatureProcessor`). Do not duplicate scale/bounds calculations or normalization formulas elsewhere.
2. **Training-Serving Parity**: Ensure that `FeatureProcessor.process_single()` is used identically during offline dataset building and online live inference. Use `core.fusion.assert_parity` to enforce vector equivalence.
3. **No PyTorch in Runtime**: Keep the production serving path dependency-free. Keep PyTorch Geometric and GNN model training confined to `training/research/` (e.g. `training/research/gnn_model.py`). Use the mathematical distillation `AnalyticGNN` in `src/features.py` for live deployments.
4. **Input Constraints**: All model input features and outputs must be strictly validated to be in the range `[0.0, 1.0]`. Validate shape (15-dim feature vector) and type safety, raising actionable exceptions on mismatch.

### Python Style Guide
- **Formatting**: Adhere to standard PEP 8 spacing, variable names, and naming conventions.
- **Imports**: Group imports into Standard Library, Third-Party libraries, and Local modules. Resolve paths relative to the project root or use `sys.path.insert` inside script entrypoints to avoid import collision.
- **Error Handling**: Use fail-safe fallbacks in loops. Wrap system commands (e.g. `nvidia-smi`, WMI power commands) in try-except blocks to gracefully degrade to simulated telemetry when physical hardware or privileges are absent.
- **State Management**: Use `collections.deque(maxlen=N)` for all sliding windows or rolling feature metrics to avoid memory accumulation over long running sessions.
