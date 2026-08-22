# AI-Driven Sensor-Free Predictive Cooling System

[![Build Status](https://img.shields.io/badge/tests-34%20passed-success)](tests/)
[![Feature Schema](https://img.shields.io/badge/feature__schema-v2__15feature-cyan)](src/constants.py)
[![XAI Engine](https://img.shields.io/badge/XAI-Observational%20Causal%20Trace-purple)](docs/XAI.md)

An intelligent, AI-driven, **sensor-free predictive cooling platform** for data centers and high-performance computing infrastructure.

---

## 1. Problem Statement

Traditional data center cooling systems rely on reactive physical temperature sensors mounted on server racks or computer room air handlers (CRAHs). Physical sensors suffer from **inherent thermal inertia**—by the time physical heat radiates to an external sensor, compute silicon has already experienced severe thermal stress. This results in:
- **Delayed Cooling Response:** Thermal lag leads to temperature overshoot and emergency thermal throttling.
- **Energy Waste:** Fans and chillers over-compensate with aggressive, uncoordinated high-RPM bursts.
- **High Deployment Costs:** Physical sensor networks require hardware installation, calibration, cabling, and maintenance.

---

## 2. Solution

The AI-Driven Sensor-Free Predictive Cooling System replaces physical sensor dependence with **software-observable compute telemetry**. By analyzing real-time CPU, GPU, Memory, Disk I/O, and Network I/O workloads, the platform predicts thermal risk **up to 30 seconds before silicon heat accumulation occurs**, enabling proactive, smooth cooling orchestration.

---

## 3. Why Sensor-Free?

- **Zero Hardware Cost:** Eliminates physical thermal probes, thermocouples, and IoT sensor networks.
- **Microsecond Latency:** Direct software telemetry collection from OS kernels (`psutil`) and GPU drivers (`NVML`).
- **No Physical Failure Points:** Sensor drift, loose wiring, and hardware probe failures are completely bypassed.
- **Pre-Emptive Response:** Software compute spikes precede physical heat emission; predicting thermal risk at the workload level enables true proactive cooling.

---

## 4. Core Architecture

The canonical execution flow follows a strict 7-stage pipeline:

```text
Telemetry Collection (CPU, GPU, RAM, Disk, Net)
       │
       ▼
Deterministic Feature Processing (src/features.py — 15 canonical features)
       │
       ▼
Inferred Thermal Heat Proxy (0.6 * CPU + 0.4 * GPU)
       │
       ▼
Analytic GNN / Topology Context (0.7 * Self + 0.3 * Neighbor)
       │
       ▼
XGBoost Risk Model + Composite Fusion (0.75 * XGB + 0.25 * GNN)
       │
       ▼
Cooling Policy Orchestration (Threshold: 0.72)
       │
       ▼
Explainable AI (XAI) Causal Decision Explanation (src/xai.py)
```

---

## 5. System Features

- **Production-Grade Feature Engine:** 15 canonical normalized features with rolling windows (5s, 10s) and shifted deltas.
- **Analytic GNN Thermal Context:** Lightweight spatial heat propagation modeling across adjacent rack topologies without PyTorch overhead on the production path.
- **XGBoost Predictive Engine:** High-efficiency gradient boosted trees trained for zero training-serving skew.
- **Adaptive Cooling Orchestration:** State-machine hysteresis, acoustic smoothing, and emergency thermal mode control.
- **Production XAI Decision Layer:** Observational, audit-ready causal explanations detailing *why* cooling actions occurred.
- **Real-Time Live Dashboard:** High-fidelity web interface (`Index.html`) providing live telemetry, risk visualization, and interactive XAI decision traces.

---

## 6. Explainable AI (XAI) & Decision Explanation

The XAI layer explains **WHY** cooling increased, decreased, activated, or remained unchanged.

### XAI Processing Flow

```text
Telemetry -> Feature Engineering -> Thermal Context -> Risk Prediction -> Cooling Decision -> XAI Explanation
```

### Example Operator Explanation

> **COOLING INCREASED (20% → 40%)**
> - **GPU Workload:** 61.0% → 79.0% (`+18.0%` ↑)
> - **CPU Workload:** 52.0% → 61.7% (`+9.7%` ↑)
> - **Inferred Heat Proxy:** `+22.2%` ↑
> - **Neighbor Thermal Context:** `+7.0%` ↑
> - **Predicted Thermal Risk:** 68% → 77% (Level: `HIGH` → `CRITICAL`)
> - **Decision Cause:** Risk crossed automatic cooling threshold of `72%`

### Why This Matters

Infrastructure engineers and SREs cannot rely on black-box automated commands. The XAI layer provides transparent, audit-ready decision traces and natural-language summaries, giving operators full visibility into automated thermal management.

---

## 7. Machine Learning Architecture

The ML pipeline fuses two complementary models:
1. **XGBoost Regressor:** Evaluates local temporal workload patterns across 15 engineered features.
2. **Analytic GNN:** Computes spatial thermal influence from neighboring racks.

---

## 8. GNN Thermal Propagation

To maintain low-latency production execution, the system uses a deterministic analytic GNN formula on the inference path.

For each rack:

```text
neighbor_heat = mean(heat_norm of adjacent racks)

gnn_embedding =
    clip(
        0.7 * self_heat +
        0.3 * neighbor_heat,
        0.0,
        1.0
    )
```

**Characteristics:**
- **70% contribution** from the rack's own inferred thermal workload (`self_heat`)
- **30% contribution** from neighboring rack thermal context (`neighbor_heat`)
- **Output range:** Bounded strictly to `[0, 1]`
- **Deterministic & Low Latency:** Direct mathematical aggregation without PyTorch runtime overhead on the production inference path

Experimental PyTorch Geometric (PyG) GraphSAGE research models are isolated under `training/research/` and are not part of production inference.

---

## 9. XGBoost Standard Configuration

The XGBoost model produces a continuous thermal-risk prediction which is combined with topology-aware thermal context.

| Parameter | Value |
| :--- | ---: |
| `n_estimators` | 30 |
| `learning_rate` | 0.1 |
| `max_depth` | 4 |
| `base_score` | 0.18 |
| Output range | `[0, 1]` |

---

## 10. Risk Scoring & Composite Fusion

The canonical risk score combines local workload prediction with spatial thermal context:

```text
composite_risk =
    0.75 * xgb_prediction +
    0.25 * gnn_embedding
```

The final risk score is bounded to `[0, 1]`.

### Risk Classification Levels

| Risk Level | Score | Action Description |
| :--- | ---: | :--- |
| **LOW** | `< 0.35` | Baseline nominal operations |
| **MEDIUM** | `0.35 – < 0.55` | Elevated workload monitoring |
| **HIGH** | `0.55 – < 0.75` | Proactive cooling preparation |
| **CRITICAL** | `>= 0.75` | Maximum active cooling actuation |

**Automatic Cooling Action Threshold:**

```text
composite_risk >= 0.72
```

---

## 11. Cooling Orchestration

The cooling policy engine (`src/thermal_mode_controller.py`) manages fan speed actuation using:
- **Hysteresis Timers:** Prevents rapid fan RPM oscillation.
- **Progressive Escalation:** Smooth state transitions (`QUIET` → `BALANCED` → `PERFORMANCE` → `FAILSAFE`).
- **Acoustic Comfort Smoothing:** Enforces maximum RPM ramp-up and ramp-down rates per second.

---

## 12. Dataset & Features

The production feature vector (`v2_15feature`) consists of 15 normalized signals:

1. `cpu_norm` (`cpu / 100.0`)
2. `gpu_norm` (`gpu / 100.0`)
3. `mem_norm` (`memory / 100.0`)
4. `disk_io_norm` (`log(1 + rate) / max_log`)
5. `net_io_norm` (`log(1 + rate) / max_log`)
6. `heat_norm` (`0.6 * cpu_norm + 0.4 * gpu_norm`)
7. `cpu_roll_5` (5-sample rolling mean)
8. `gpu_roll_5` (5-sample rolling mean)
9. `heat_roll_5` (5-sample rolling mean)
10. `cpu_roll_10` (10-sample rolling mean)
11. `gpu_roll_10` (10-sample rolling mean)
12. `heat_roll_10` (10-sample rolling mean)
13. `cpu_delta` (Shifted delta in `[0, 1]`)
14. `gpu_delta` (Shifted delta in `[0, 1]`)
15. `heat_delta` (Shifted delta in `[0, 1]`)

---

## 13. Training-Serving Parity

Training code uses the exact same preprocessing entry point (`FeatureProcessor.process_single()`) in `src/features.py`. Automated unit tests (`tests/test_training_serving_parity.py`) enforce zero feature skew between offline model training and online inference.

---

## 14. Repository Structure

```text
Cooling-Project/
├── config/                     # Policy and demo profiles YAML
│   ├── cooling_policy.yaml
│   └── demo_profiles.yaml
├── data/                       # Telemetry logs and processed dataset
├── docs/                       # Architecture and XAI documentation
│   ├── ARCHITECTURE.md
│   └── XAI.md
├── models/                     # Trained XGBoost model & preprocessor state
│   ├── cooling_model.pkl
│   └── preprocessor_state.pkl
├── runtime/                    # Live runtime manager and web API server
│   ├── api_server.py
│   ├── live_runtime_manager.py
│   └── live_stream_bus.py
├── scripts/                    # Demo and workload generation tools
│   └── workload_generator.py
├── src/                        # PRODUCTION RUNTIME SOURCE OF TRUTH
│   ├── core/
│   │   └── fusion.py           # Single source of truth for risk fusion
│   ├── constants.py            # Feature schema and constants
│   ├── fan_controller.py       # Hardware fan actuation interface
│   ├── features.py             # FeatureProcessor single source of truth
│   ├── inference.py            # Production Inference Engine
│   ├── thermal_mode_controller.py # Cooling policy controller
│   └── xai.py                  # Production XAI & Decision Explanation Engine
├── tests/                      # Automated test suite (34 tests)
│   ├── test_actual_telemetry.py
│   ├── test_telemetry_accuracy.py
│   ├── test_training_serving_parity.py
│   └── test_xai.py
├── Index.html                  # Interactive Production Web Dashboard
├── requirements.txt            # Production runtime dependencies
├── requirements-training.txt   # Offline training dependencies
└── start_demo.bat              # One-click demo launcher
```

---

## 15. Installation & Setup

### Environment Setup

```bash
# Clone the repository
git clone https://github.com/AdithyaK3106/Cooling-Project.git
cd Cooling-Project

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install production dependencies
pip install -r requirements.txt
```

---

## 16. Running the System & Live Demo

### Option 1: One-Click Demo Launcher (Windows)
```cmd
start_demo.bat
```
Launches the Live Runtime Manager and opens the web dashboard (`Index.html`) in your browser.

### Option 2: Command Line Live Runtime
```bash
python runtime/live_runtime_manager.py
```

### Option 3: Production Inference Loop
```bash
python src/inference.py
```

---

## 17. Running Automated Tests

Run the full test suite (34 tests):
```bash
python -m pytest tests/
```

Run XAI decision explanation tests specifically:
```bash
python -m pytest tests/test_xai.py
```

---

## 18. Model Artifacts

- `models/cooling_model.pkl`: Serialized XGBoost regressor model.
- `models/preprocessor_state.pkl`: Normalization statistics (`max_disk_log`, `max_net_log`).

---

## 19. System Limitations

1. **Software Telemetry Dependency:** The platform infers thermal load from OS/driver workload metrics. Non-workload external heat sources (e.g. ambient HVAC failure) are not detected unless compute power/throttling changes.
2. **Observational Model Context:** XAI outputs explain model decision logic based on trained patterns; they do not represent physical computational fluid dynamics (CFD).

---

## 20. Intellectual Property & Patent Note

Feature attribution algorithms, stateful telemetry normalization, and deterministic decision tracing logic are structured for auditability and intellectual property documentation.
