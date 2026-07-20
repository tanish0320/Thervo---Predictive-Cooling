# Scaling Architecture: Detailed Diagrams

## 1. High-Level System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           LAB NETWORK (50 Machines)                          │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐  │
│  │   Machine 1         │  │   Machine 2         │  │   Machine N         │  │
│  │  (Windows/Linux)    │  │  (macOS)            │  │  (non-Lenovo)       │  │
│  │                     │  │                     │  │                     │  │
│  │ ┌─────────────────┐ │  │ ┌─────────────────┐ │  │ ┌─────────────────┐ │  │
│  │ │Telemetry Agent  │ │  │ │Telemetry Agent  │ │  │ │Telemetry Agent  │ │  │
│  │ │ (collects 1/s)  │ │  │ │ (collects 1/s)  │ │  │ │ (collects 1/s)  │ │  │
│  │ │ psutil+WMI      │ │  │ │ psutil+Sysctl   │ │  │ │ psutil+sysfs    │ │  │
│  │ └────────┬────────┘ │  │ └────────┬────────┘ │  │ └────────┬────────┘ │  │
│  │          │          │  │          │          │  │          │          │  │
│  │    [Buffer 5pts]    │  │    [Buffer 5pts]    │  │    [Buffer 5pts]    │  │
│  │          │          │  │          │          │  │          │          │  │
│  │ ┌────────▼────────┐ │  │ ┌────────▼────────┐ │  │ ┌────────▼────────┐ │  │
│  │ │Policy Executor  │ │  │ │Policy Executor  │ │  │ │Policy Executor  │ │  │
│  │ │ (polls /decision)│ │  │ │ (polls /decision)│ │  │ │ (polls /decision)│ │  │
│  │ │ every 200ms     │ │  │ │ every 200ms     │ │  │ │ every 200ms     │ │  │
│  │ └────────┬────────┘ │  │ └────────┬────────┘ │  │ └────────┬────────┘ │  │
│  │          │          │  │          │          │  │          │          │  │
│  │ ┌────────▼────────┐ │  │ ┌────────▼────────┐ │  │ ┌────────▼────────┐ │  │
│  │ │ Fan Controller  │ │  │ │ Fan Controller  │ │  │ │ Fan Controller  │ │  │
│  │ │ (WMI/sysfs/IOK)│ │  │ │ (WMI/sysfs/IOK)│ │  │ │ (Fallback curve)│ │  │
│  │ │ or Fallback     │ │  │ │ or Fallback     │ │  │ │ or Fallback     │ │  │
│  │ └────────────────┘ │  │ └────────────────┘ │  │ └────────────────┘ │  │
│  │                     │  │                     │  │                     │  │
│  └────────┬────────────┘  └────────┬────────────┘  └────────┬────────────┘  │
│           │                         │                         │               │
│           │  HTTPS POST /ingest     │  (every 5 sec)         │               │
│           │  {machine_id, telemetry}│                         │               │
│           │                         │                         │               │
│           └─────────────────────────┼─────────────────────────┘               │
│                                     ↓                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                  CENTRAL SERVER (Linux VM or K8s)                      │  │
│  │                  [High-Availability Configuration]                    │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │ Telemetry Ingestion Service (FastAPI, port 8000)                │ │  │
│  │  │                                                                  │ │  │
│  │  │  POST /ingest/{machine_id}                                      │ │  │
│  │  │    → validate schema                                            │ │  │
│  │  │    → append to live_telemetry_buffer[machine_id]               │ │  │
│  │  │    → check if batch window (100ms) ready                       │ │  │
│  │  │                                                                  │ │  │
│  │  │  GET /telemetry/{machine_id}                                    │ │  │
│  │  │    → returns latest 10 points (for debugging)                   │ │  │
│  │  └────────────┬─────────────────────────────────────────────────────┘ │  │
│  │               │                                                        │  │
│  │  ┌────────────▼─────────────────────────────────────────────────────┐ │  │
│  │  │ Batch Orchestrator                                              │ │  │
│  │  │  (accumulates 100ms window)                                      │ │  │
│  │  │                                                                  │ │  │
│  │  │  Every 100ms:                                                   │ │  │
│  │  │    → collect latest point from each of 50 machines             │ │  │
│  │  │    → invoke inference_service.predict(batch_50)                │ │  │
│  │  │    → return [risk_0, risk_1, ..., risk_49]                    │ │  │
│  │  │                                                                  │ │  │
│  │  │  If queue > 100 items: load shedding (drop oldest)            │ │  │
│  │  │  If inference slow: increase window to 200ms                   │ │  │
│  │  └────────────┬─────────────────────────────────────────────────────┘ │  │
│  │               │                                                        │  │
│  │  ┌────────────▼─────────────────────────────────────────────────────┐ │  │
│  │  │ Inference Service (FastAPI, port 8050, GPU-optimized)           │ │  │
│  │  │                                                                  │ │  │
│  │  │  Loads:                                                          │ │  │
│  │  │    - XGBoost model (models/cooling_model.pkl)                   │ │  │
│  │  │    - AnalyticGNN adjacency matrix                               │ │  │
│  │  │    - Feature preprocessor state (models/preprocessor_state.pkl)│ │  │
│  │  │                                                                  │ │  │
│  │  │  POST /predict                                                   │ │  │
│  │  │    accepts: [{"cpu":50, "gpu":40, ...}, ...]                   │ │  │
│  │  │    computes: feature vectors → XGBoost → risk_scores           │ │  │
│  │  │    applies: AnalyticGNN fusion (0.75*XGB + 0.25*GNN)           │ │  │
│  │  │    returns: [0.34, 0.56, 0.22, ...]                            │ │  │
│  │  │    latency: < 50ms for 50 samples                              │ │  │
│  │  │                                                                  │ │  │
│  │  │  Fallback: if model fails, use intensity heuristic             │ │  │
│  │  └────────────┬─────────────────────────────────────────────────────┘ │  │
│  │               │                                                        │  │
│  │  ┌────────────▼─────────────────────────────────────────────────────┐ │  │
│  │  │ Central Policy Engine                                            │ │  │
│  │  │  (wraps src/thermal_mode_controller.py × 50)                    │ │  │
│  │  │                                                                  │ │  │
│  │  │  For each of 50 machines:                                       │ │  │
│  │  │    state_i = CoolingPolicyEngine(machine_id=i)                 │ │  │
│  │  │    target_fan_i, mode_i = state_i.update(risk_i)              │ │  │
│  │  │    store decision_i                                             │ │  │
│  │  │                                                                  │ │  │
│  │  │  Maintains per-machine state:                                   │ │  │
│  │  │    - active_mode (QUIET, BALANCED, PERFORMANCE, FAILSAFE)      │ │  │
│  │  │    - hysteresis timers                                          │ │  │
│  │  │    - cooling_effectiveness tracking                             │ │  │
│  │  │    - thermal_soak accumulation                                  │ │  │
│  │  │    - prediction_stability_confidence                            │ │  │
│  │  └────────────┬─────────────────────────────────────────────────────┘ │  │
│  │               │                                                        │  │
│  │  ┌────────────▼─────────────────────────────────────────────────────┐ │  │
│  │  │ Decision Cache                                                   │ │  │
│  │  │  (in-memory or Redis for HA)                                    │ │  │
│  │  │                                                                  │ │  │
│  │  │  Stores: {machine_id → {risk, fan%, mode, timestamp, conf}}    │ │  │
│  │  │                                                                  │ │  │
│  │  │  GET /decision/{machine_id}                                     │ │  │
│  │  │    → agents poll this every 200ms                              │ │  │
│  │  │    → returns {target_fan_pct, mode, confidence, age_ms}        │ │  │
│  │  │                                                                  │ │  │
│  │  │  TTL: 2 seconds (decisions invalid after 2s of no update)      │ │  │
│  │  └────────────┬─────────────────────────────────────────────────────┘ │  │
│  │               │                                                        │  │
│  │  ┌────────────▼─────────────────────────────────────────────────────┐ │  │
│  │  │ InfluxDB Client (Async batch writer)                             │ │  │
│  │  │                                                                  │ │  │
│  │  │  Writes to InfluxDB (time-series database):                     │ │  │
│  │  │    - Measurement: telemetry                                     │ │  │
│  │  │      Tags: machine_id, os, hardware_hash                        │ │  │
│  │  │      Fields: cpu, gpu, memory, disk_io, network_io              │ │  │
│  │  │                                                                  │ │  │
│  │  │    - Measurement: decisions                                     │ │  │
│  │  │      Tags: machine_id, policy_reason                            │ │  │
│  │  │      Fields: risk_score, xgb_pred, gnn_pred, fan_pct           │ │  │
│  │  │                                                                  │ │  │
│  │  │  Batching: 500 points per write (5 machines × 100 decisions)    │ │  │
│  │  │  Flush: every 1 second or when buffer full                      │ │  │
│  │  └────────────┬─────────────────────────────────────────────────────┘ │  │
│  │               │                                                        │  │
│  │  ┌────────────▼─────────────────────────────────────────────────────┐ │  │
│  │  │ InfluxDB (Time-Series Database, port 8086)                      │ │  │
│  │  │  [Persistent Storage]                                           │ │  │
│  │  │                                                                  │ │  │
│  │  │  Retention Policies:                                            │ │  │
│  │  │    - Raw data (1s interval): 7 days = ~30GB                    │ │  │
│  │  │    - Hourly aggregates: 90 days = ~1GB                         │ │  │
│  │  │    - Daily aggregates: 1 year = ~200MB                         │ │  │
│  │  │                                                                  │ │  │
│  │  │  Downsampling: automated via InfluxDB tasks                     │ │  │
│  │  │  Backup: daily snapshots to S3/NAS                              │ │  │
│  │  └──────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                   ↑                                           │
│                                   │                                           │
│                    (agents poll /decision every 200ms)                        │
│                                   │                                           │
│  ┌────────────────────────────────┴────────────────────────────────────────┐ │
│  │                   Monitoring & Observability Stack                    │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │ Prometheus (port 9090)                                           │ │  │
│  │  │  - Scrapes InfluxDB remote-read endpoint                         │ │  │
│  │  │  - Evaluates alert rules (temp > 90C, latency > 500ms)          │ │  │
│  │  │  - Triggers alerts every 30 seconds                              │ │  │
│  │  │  - Stores 15 days of metrics (downsampled)                       │ │  │
│  │  └──────────────────────────────────────────────────────────────────┘ │  │
│  │                                   ↓                                      │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │ AlertManager (port 9093)                                         │ │  │
│  │  │  - Receives alerts from Prometheus                               │ │  │
│  │  │  - Groups/deduplicates alerts                                    │ │  │
│  │  │  - Routes to Slack/email webhook                                 │ │  │
│  │  │  - Enriches with incident history                                │ │  │
│  │  └──────────────────────────────────────────────────────────────────┘ │  │
│  │                                   ↓                                      │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │ Grafana (port 3000)                                              │ │  │
│  │  │  - Dashboard: 50 thermal curves (real-time update 5s interval)  │ │  │
│  │  │  - Dashboard: lab-wide stats (avg/max temp, failsafe count)     │ │  │
│  │  │  - Dashboard: per-machine decision timeline                      │ │  │
│  │  │  - Dashboard: inference latency heatmap                          │ │  │
│  │  │  - Alerts dashboard (active, resolved, silenced)                 │ │  │
│  │  │  - Export capability (Parquet download)                          │ │  │
│  │  └──────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Telemetry Push Flow (Per Second)

```
SECOND 1-5: Collection & Buffering
─────────────────────────────────

Agent (per machine):
  t=0.0s  collect()  → {cpu:45, gpu:30, mem:60, disk:1M, net:5M}
  t=1.0s  collect()  → {cpu:50, gpu:35, mem:62, disk:2M, net:6M}
  t=2.0s  collect()  → {cpu:52, gpu:36, mem:64, disk:1.5M, net:7M}
  t=3.0s  collect()  → {cpu:48, gpu:33, mem:63, disk:2.5M, net:5.5M}
  t=4.0s  collect()  → {cpu:55, gpu:40, mem:65, disk:1M, net:8M}
          ↓
          Buffer 5 points (local ring buffer, size=5)
          
SECOND 5: Push
─────────────

Agent:
  POST /ingest/machine_1 HTTPS
  ├─ headers: {"Authorization": "Bearer {api_key}"}
  └─ body: {
        "machine_id": "machine_1",
        "hardware_id": "4a2b3c4d5e6f7g8h",
        "os": "Windows 11",
        "timestamp": 1719345600,
        "telemetry": [
          {"t": 1719345600, "cpu": 45, "gpu": 30, "mem": 60, "disk_io": 1000000, "network_io": 5000000},
          {"t": 1719345601, "cpu": 50, "gpu": 35, "mem": 62, "disk_io": 2000000, "network_io": 6000000},
          {"t": 1719345602, "cpu": 52, "gpu": 36, "mem": 64, "disk_io": 1500000, "network_io": 7000000},
          {"t": 1719345603, "cpu": 48, "gpu": 33, "mem": 63, "disk_io": 2500000, "network_io": 5500000},
          {"t": 1719345604, "cpu": 55, "gpu": 40, "mem": 65, "disk_io": 1000000, "network_io": 8000000}
        ]
     }

Central Server (Telemetry Ingest):
  ├─ validate_schema()  ← checks for required keys
  ├─ append_to_buffer(machine_1, 5 points)
  ├─ metadata_store(machine_1, hw_id, os)
  └─ check_if_batch_ready()
        ↓
        If 100ms window elapsed and ≥ 1 point per machine:
          → trigger_inference()
          
SECOND 5-5.1: Concurrent Telemetry Push from 50 Machines
──────────────────────────────────────────────────────────

[Staggered to avoid thundering herd]
  Machine 1: POST /ingest (t=5.0s)
  Machine 2: POST /ingest (t=5.01s)
  Machine 3: POST /ingest (t=5.02s)
  ...
  Machine 50: POST /ingest (t=5.099s)

Central Server sees distributed load (500 ingest events over 100ms)
```

---

## 3. Inference Pipeline (Batched, Every 100ms)

```
SECOND 5.1: Inference Trigger
──────────────────────────────

Batch Orchestrator:
  ├─ elapsed_since_last_batch = 105ms > 100ms ✓
  ├─ collect_latest_telemetry()
  │   ├─ machine_1: {cpu:55, gpu:40, mem:65, ...}
  │   ├─ machine_2: {cpu:48, gpu:33, mem:63, ...}
  │   └─ machine_50: {cpu:51, gpu:38, mem:66, ...}
  │
  ├─ features = FeatureProcessor.batch_process([telemetry_1..50])
  │   ├─ machine_1 features → [0.55, 0.40, 0.65, 0.12, 0.25, 0.52, ...]  (15-dim)
  │   └─ machine_50 features → [0.51, 0.38, 0.66, 0.18, 0.30, 0.49, ...]  (15-dim)
  │
  └─ invoke_inference_service()
  
Inference Service (on GPU, Gunicorn worker 1):
  ├─ load_models() [cached from startup]
  │   ├─ xgb_model: XGBoost Booster (loaded in 1ms)
  │   └─ gnn_adjacency: sparse matrix (50×50)
  │
  ├─ xgb_predict(features_batch)
  │   ├─ input: (50, 15) array
  │   ├─ forward: ~0.8ms on CPU
  │   └─ output: [0.34, 0.56, 0.22, 0.78, ..., 0.41]  (50 risk scores)
  │
  ├─ gnn_predict(features_batch)
  │   ├─ input: (50, 15) array
  │   ├─ forward: ~0.5ms (AnalyticGNN, no deep learning)
  │   └─ output: [0.32, 0.54, 0.20, 0.76, ..., 0.39]  (50 risk scores)
  │
  ├─ fuse(xgb_scores, gnn_scores)
  │   └─ fused = 0.75 * xgb + 0.25 * gnn
  │       ├─ machine_1: 0.75 * 0.34 + 0.25 * 0.32 = 0.335
  │       ├─ machine_2: 0.75 * 0.56 + 0.25 * 0.54 = 0.555
  │       └─ machine_50: 0.75 * 0.41 + 0.25 * 0.39 = 0.405
  │
  └─ return(fused_scores)  [Total latency: ~2ms]

SECOND 5.11: Policy Decision
──────────────────────────────

Central Policy Engine:
  for machine_i in [1..50]:
    state_i = CoolingPolicyEngine(machine_id=i)
    
    machine_1 (risk=0.335):
      ├─ risk < 0.35 → LOW risk
      ├─ policy.update(0.335) →
      │  ├─ velocity = (0.335 - 0.340) / 0.1 = -0.05 (cooling trend)
      │  ├─ alpha = 0.25 (adaptive EMA)
      │  ├─ smoothed_risk = 0.25 * 0.335 + 0.75 * 0.335 = 0.335
      │  ├─ mode_transition → QUIET (fan 30%)
      │  └─ check hysteresis: min_hold_time = 15s, last_switch = 5.0s, elapsed = 0.1s
      │      hysteresis blocks switch, keep BALANCED (fan 55%)
      │  └─ decision: {risk: 0.335, fan: 55, mode: BALANCED, confidence: 0.95}
      │
    machine_2 (risk=0.555):
      ├─ risk ∈ [0.35, 0.75] → MED risk
      ├─ policy.update(0.555) →
      │  ├─ velocity = (0.555 - 0.500) / 0.1 = 0.55 (heating trend)
      │  ├─ alpha = 0.40 (faster response to rising risk)
      │  ├─ smoothed_risk = 0.40 * 0.555 + 0.60 * 0.500 = 0.525
      │  ├─ mode_transition → PERFORMANCE (fan 85%)
      │  ├─ check hysteresis: can switch (hold time satisfied)
      │  └─ decision: {risk: 0.555, fan: 85, mode: PERFORMANCE, confidence: 0.88}
      │
    machine_3 (risk=0.22):
      ├─ decision: {risk: 0.22, fan: 30, mode: QUIET, confidence: 0.99}
      │
    ...
    
    machine_50 (risk=0.405):
      ├─ decision: {risk: 0.405, fan: 55, mode: BALANCED, confidence: 0.91}

Store decisions in cache:
  decision_cache = {
    "machine_1": {risk: 0.335, fan: 55, mode: "BALANCED", ts: 1719345605.11, conf: 0.95},
    "machine_2": {risk: 0.555, fan: 85, mode: "PERFORMANCE", ts: 1719345605.11, conf: 0.88},
    ...
    "machine_50": {risk: 0.405, fan: 55, mode: "BALANCED", ts: 1719345605.11, conf: 0.91}
  }

Write to InfluxDB (async batch, latency < 10ms):
  ├─ Insert telemetry points (50 machines × 5 points each = 250 points)
  ├─ Insert decision points (50 machines × 1 decision each = 50 points)
  └─ Flush: write_batch_to_influxdb()

Total latency (collection → decision → storage): ~150ms ✓ (target: < 200ms P95)
```

---

## 4. Decision Polling by Agents (Every 200ms)

```
Agent thread (runs in background, every 200ms):
  
SECOND 5.2:
  ├─ GET /decision/machine_1?format=json
  │  ├─ network: ~5ms (local network)
  │  ├─ server processing: ~1ms (in-memory cache lookup)
  │  └─ response: 200 OK
  │     {
  │       "risk": 0.335,
  │       "target_fan_pct": 55,
  │       "mode": "BALANCED",
  │       "confidence": 0.95,
  │       "timestamp": 1719345605.11,
  │       "age_ms": 90
  │     }
  │
  ├─ validate_decision()  ← check age_ms < 2000ms (TTL)
  │
  ├─ apply_fan_control(target_fan_pct=55)
  │  │
  │  └─ On Windows:
  │     ├─ Check if Lenovo Legion Toolkit available
  │     ├─ If yes: invoke llt.exe with mode BALANCED (legacy path)
  │     └─ If no: use WMI to set fan to 55% via PowerShell
  │
  │  Or on Linux:
  │     ├─ Check if hardware supports sysfs PWM
  │     ├─ If yes: write to /sys/class/hwmon/hwmon*/pwm[1-8]
  │     │   ├─ map 55% → PWM value (0-255)
  │     │   └─ write atomic: echo 140 > /sys/class/hwmon/hwmon0/pwm1
  │     └─ If no: use fallback intensity curve
  │
  │  Or on macOS:
  │     ├─ Check if IOKit available
  │     ├─ If yes: invoke system settings (may require Rosetta on M1/M2)
  │     └─ If no: use fallback intensity curve
  │
  ├─ log_local_decision()  ← store to local file for audit
  │  └─ {timestamp, risk, fan_pct, mode, status: "applied"}
  │
  └─ store_cache(decision, ttl=1000ms)  ← for offline fallback
  
SECOND 5.4:
  [repeat every 200ms]
  
If central server unreachable:
  ├─ check_fallback_cache()
  │  └─ if cache_age < 1000ms: use cached decision
  │  └─ if cache_age >= 1000ms: escalate to PERFORMANCE (safe default)
  │
  └─ log_fallback_event("CACHE_MISS", age_ms)  ← triggers dashboard alert

If decision age > 2000ms:
  ├─ network_backoff(attempt=1)
  │  ├─ wait: 100ms * 2^attempt + random(0, 100ms)
  │  ├─ max_wait: 30s
  │  └─ retry: attempt++
```

---

## 5. InfluxDB Data Model

```
Database: cooling_lab

Measurement: telemetry
  ├─ Tags (indexed, low cardinality):
  │  ├─ machine_id         (e.g., "machine_1", cardinality=50)
  │  ├─ os                 (e.g., "Windows 11", cardinality=3)
  │  └─ hardware_hash      (e.g., "4a2b3c4d", cardinality=50)
  │
  └─ Fields (not indexed, time-series data):
     ├─ cpu             (float) %
     ├─ gpu             (float) %
     ├─ memory          (float) %
     ├─ disk_io         (integer) bytes/sec
     ├─ network_io      (integer) bytes/sec
     ├─ gpu_temp        (float) °C (optional)
     ├─ cpu_temp        (float) °C (optional)
     └─ fan_rpm         (integer) RPM (optional)
  
  Retention Policy:
    ├─ raw             (1s interval) → 7 days
    ├─ hourly_avg      (1h interval) → 90 days [auto-downsampled]
    └─ daily_avg       (1d interval) → 1 year  [auto-downsampled]
  
  Total points for 50 machines:
    ├─ 1s granule:     50 machines × 1 point/sec × 86400 sec/day × 7 days = 30.24M points
    ├─ 1h granule:     50 machines × 1 point/hour × 24 hours/day × 90 days = 108k points
    └─ 1d granule:     50 machines × 1 point/day × 365 days = 18.25k points
  
  Disk usage:
    ├─ raw (1s):    ~30GB (with compression, ~3GB practical)
    ├─ hourly:      ~100MB
    └─ daily:       ~10MB
    └─ TOTAL:       ~3.1GB per week


Measurement: decisions
  ├─ Tags:
  │  ├─ machine_id      (e.g., "machine_1", cardinality=50)
  │  ├─ policy_reason   (e.g., "BALANCED", "PERFORMANCE", cardinality=5)
  │  └─ inference_status (e.g., "OK", "FALLBACK", cardinality=2)
  │
  └─ Fields:
     ├─ risk_score          (float) [0.0, 1.0]
     ├─ xgb_pred            (float) [0.0, 1.0]
     ├─ gnn_pred            (float) [0.0, 1.0]
     ├─ fused_score         (float) [0.0, 1.0]
     ├─ target_fan_pct      (float) [0, 100]
     ├─ policy_reason_code  (integer) [0=QUIET, 1=BALANCED, 2=PERFORMANCE, 3=FAILSAFE]
     ├─ elapsed_ms          (integer) inference latency
     ├─ confidence          (float) [0.0, 1.0]
     └─ actual_fan_pct      (float) [0, 100] (feedback from agent)
  
  Retention Policy:
    ├─ raw             (200ms interval) → 7 days
    ├─ hourly_avg      (1h interval) → 90 days
    └─ daily_avg       (1d interval) → 1 year
  
  Total points for 50 machines:
    └─ 1 decision per machine × 100ms window = 10 decisions/sec/machine
    └─ 50 machines × 10 decisions/sec = 500 decisions/sec (lab-wide)
    └─ 500 decisions/sec × 86400 sec/day × 7 days = 302.4M points
  
  Disk usage:
    └─ ~300GB raw (compressed: ~30GB practical)
    └─ Actually acceptable due to aggressive downsampling


Measurement: alerts
  ├─ Tags:
  │  ├─ machine_id        (cardinality=50)
  │  ├─ alert_type        (e.g., "HIGH_TEMP", "INFERENCE_ERROR", cardinality=5)
  │  └─ severity          (e.g., "WARNING", "CRITICAL", cardinality=2)
  │
  └─ Fields:
     ├─ value           (float) (e.g., temperature 92°C, latency 450ms)
     ├─ threshold       (float)
     ├─ message         (string)
     └─ resolved_at     (timestamp, nullable)
  
  Retention Policy:
    └─ 90 days (for incident investigation)


Measurement: agent_health
  ├─ Tags:
  │  ├─ machine_id        (cardinality=50)
  │  └─ component         (e.g., "telemetry", "policy_executor", "fan_controller")
  │
  └─ Fields:
     ├─ status           (integer) [0=OK, 1=WARN, 2=ERROR]
     ├─ last_telemetry_age_ms  (integer)
     ├─ decision_cache_age_ms   (integer)
     ├─ fan_control_success     (boolean)
     └─ error_message    (string, nullable)
  
  Retention Policy:
    └─ 30 days
```

---

## 6. API Endpoints Summary

```
┌─────────────────────────────────────────────────────────────────┐
│              CENTRAL SERVER API ENDPOINTS                       │
└─────────────────────────────────────────────────────────────────┘

[Telemetry Ingest Service — port 8000]

POST /ingest/{machine_id}
  Headers:
    Authorization: Bearer {api_key}
    Content-Type: application/json
  
  Body:
    {
      "machine_id": "machine_1",
      "hardware_id": "4a2b3c4d5e6f7g8h",
      "os": "Windows 11",
      "timestamp": 1719345604,
      "telemetry": [
        {"t": 1719345600, "cpu": 45, "gpu": 30, "mem": 60, "disk_io": 1M, "network_io": 5M},
        ...
      ]
    }
  
  Response:
    200 OK
    {
      "status": "ingested",
      "machine_id": "machine_1",
      "points_accepted": 5,
      "buffer_size": 25
    }
  
  Latency: < 10ms (in-memory buffer append)


GET /telemetry/{machine_id}?limit=10
  Response:
    200 OK
    {
      "machine_id": "machine_1",
      "latest": [
        {"t": 1719345604, "cpu": 55, "gpu": 40, "mem": 65, ...},
        {"t": 1719345603, "cpu": 48, "gpu": 33, "mem": 63, ...},
        ...
      ]
    }
  
  Latency: < 5ms (ring buffer lookup)


[Decision Service — port 8001]

GET /decision/{machine_id}
  Response:
    200 OK
    {
      "machine_id": "machine_1",
      "risk": 0.335,
      "target_fan_pct": 55,
      "mode": "BALANCED",
      "confidence": 0.95,
      "timestamp": 1719345605.11,
      "age_ms": 90,
      "policy_reason": "MED_RISK_BALANCED_MODE"
    }
  
  Latency: < 1ms (in-memory cache)
  
  Note: agents poll this endpoint every 200ms
        if age_ms > 2000ms: agent escalates to PERFORMANCE (safety override)


GET /decision/all?format=compact
  Response:
    200 OK
    {
      "machines": [
        {"id": "machine_1", "risk": 0.335, "fan": 55, "mode": "BALANCED", "age_ms": 90},
        {"id": "machine_2", "risk": 0.555, "fan": 85, "mode": "PERFORMANCE", "age_ms": 95},
        ...
      ],
      "timestamp": 1719345605.11,
      "total_machines": 50,
      "failsafe_count": 0,
      "high_risk_count": 3
    }
  
  Latency: < 10ms (aggregate from cache)
  
  Note: used by dashboard to get full state snapshot


GET /health
  Response:
    200 OK
    {
      "status": "healthy",
      "inference_service": "online",
      "influxdb": "connected",
      "decision_cache": "synced",
      "avg_inference_latency_ms": 45.2,
      "p95_inference_latency_ms": 120.5,
      "uptime_sec": 864000,
      "total_decisions": 8640000
    }


[Inference Service — port 8050, for internal use]

POST /predict
  (Called internally by batch orchestrator, not exposed to agents)
  
  Body:
    {
      "features": [
        [0.45, 0.30, 0.60, 0.08, 0.25, ...],  // machine_1
        [0.50, 0.35, 0.62, 0.12, 0.28, ...],  // machine_2
        ...
      ]
    }
  
  Response:
    200 OK
    {
      "xgb_scores": [0.34, 0.56, ...],
      "gnn_scores": [0.32, 0.54, ...],
      "fused_scores": [0.335, 0.555, ...],
      "latency_ms": 2.1
    }
  
  Latency: < 50ms for 50 samples on GPU
```

---

## 7. Fallback Decision Flow (Central Server Unavailable)

```
Scenario: Central server offline for > 5 minutes
────────────────────────────────────────────────

Agent timeline:

t=0ms:    Last successful decision fetch
            decision_cache = {
              risk: 0.335,
              fan: 55,
              mode: "BALANCED",
              timestamp: 1719345605.11,
              age_ms: 0
            }

t=200ms:  Poll /decision/machine_1
          ├─ DNS lookup → timeout (no server)
          ├─ record_failure(attempt=1)
          └─ use cached decision
            decision_cache.age_ms = 200
            apply_fan_control(fan=55, confidence=0.95)

t=400ms:  Poll /decision/machine_1
          ├─ TCP connect → timeout
          ├─ record_failure(attempt=2)
          └─ use cached decision
            decision_cache.age_ms = 400
            apply_fan_control(fan=55, confidence=0.95)

t=600ms:  Poll /decision/machine_1
          ├─ timeout
          └─ backoff_attempt=1
            wait_time = 100ms * 2^1 + random(0, 100ms) = 200-300ms

t=900ms:  Poll /decision/machine_1
          ├─ timeout
          └─ backoff_attempt=2
            wait_time = 100ms * 2^2 + random(0, 100ms) = 400-500ms

t=5000ms: decision_cache.age_ms = 5000 (>2000ms)
          ├─ cache is stale
          └─ escalate to PERFORMANCE (safety default)
            apply_fan_control(fan=85, mode="PERFORMANCE_FALLBACK", confidence=0.50)

t=10000ms: decision_cache.age_ms = 10000
           ├─ still escalated
           └─ apply_fan_control(fan=85)

t=30000ms: Central server back online
           ├─ Poll /decision/machine_1 → 200 OK
           └─ resume normal polling (200ms interval)
             apply_fan_control(fan=55, mode="BALANCED", confidence=0.95)

Metrics logged (for dashboard alerting):
  ├─ fallback_cache_hit_count: 50  (50 polls served from cache)
  ├─ escalation_to_performance: 1  (single escalation after 5s)
  ├─ downtime_duration_sec: 25
  └─ recovery_time_sec: 3 (time until first successful poll)
```

---

## 8. Network Topology (Lab Infrastructure)

```
┌──────────────────────────────────────────────────────────┐
│                     Lab Network (10.0.0.0/24)            │
│                                                          │
│  ┌────────────────┐  ┌────────────────┐  ┌───────────┐  │
│  │  Gateway /     │  │  WiFi Router   │  │  Switch   │  │
│  │  Router        │  │  (802.11ax)    │  │  (managed)│  │
│  │  10.0.0.1      │  │  10.0.0.2      │  │  10.0.0.3 │  │
│  └────────────────┘  └────────────────┘  └───────────┘  │
│         │                    │                    │       │
│         │  1Gbps            │ 300Mbps            │ 1Gbps │
│         │                    │                    │       │
│   ┌─────┴───────────────┬────┴────────────────┬──┴──┐    │
│   │                     │                     │     │    │
│   ↓                     ↓                     ↓     ↓    │
│                                                          │
│  [Machine 1]  [Machine 2]  ...  [Machine 25] [Server]  │
│  Ethernet     WiFi                Ethernet   Ethernet   │
│  10.0.1.x     10.0.2.x            10.0.1.y  10.0.1.254 │
│                                                          │
│  ┌─────────────────────────────────────────────┬──────┐ │
│  │           (continue with                     │      │ │
│  │        machines 26-50)                       │      │ │
│  └─────────────────────────────────────────────┴──────┘ │
│                                                          │
└──────────────────────────────────────────────────────────┘
         │
         │ Internet (external)
         │ (optional: cloud backup, remote monitoring)
         ↓
    [Cloud Storage]
    [S3 / Azure Blob / NAS]
    (InfluxDB backups, Parquet exports)

Network assumptions:
  - Lab is on isolated subnet (10.0.0.0/24)
  - Central server has static IP: 10.0.1.254 (or 10.0.0.254)
  - Machines use DHCP or static IPs (10.0.1.1 - 10.0.1.253)
  - WiFi machines (10.0.2.x) have stable connection (signal > -70dBm)
  - No firewall blocking agents ↔ central server traffic
  - HTTPS with self-signed cert (or internal CA)
  - NTP sync (all machines within 100ms of each other) for log correlation

Latency assumptions:
  - Ethernet machine → server: ~1-5ms
  - WiFi machine → server: ~10-20ms
  - InfluxDB query: ~50-200ms (depends on query complexity)
  - Prometheus scrape: ~1-2s (60 machines × 30s scrape interval)
```

---

## 9. Graceful Degradation Scenarios

```
┌─────────────────────────────────────────────────────────┐
│ Failure Mode Matrix: Impact & Recovery                 │
└─────────────────────────────────────────────────────────┘

Scenario A: Central Server Unavailable
──────────────────────────────────────

Timeline:
  t=0s:   Central server crashes
  t=0-5s: Agents poll, get timeout
  t=5s:   Agents escalate to PERFORMANCE mode (safe default)
          Dashboard shows "DEGRADED" (red alert)
  t=5-300s: Agents continue escalated mode
          ├─ Fan at 85%, high acoustic noise
          ├─ Temperature stable but not optimized
          ├─ No telemetry collection pauses (local only)
  t=300s: Operator restarts central server
  t=300-305s: Agents reconnect, resume normal polling
  t=305s+: Decisions return to normal

Impact:
  ├─ Temperature: slightly elevated (mitigated by PERFORMANCE escalation)
  ├─ Acoustic: loud (fans at 85%)
  ├─ Data loss: InfluxDB offline if server crashes, but buffering helps
  ├─ Recovery: < 5 minutes
  └─ User impact: HIGH (high fan noise)

Mitigation:
  ├─ Use load balancer with 2+ central server replicas (HA)
  ├─ Cache decisions locally (100ms old decisions still useful)
  └─ Alert operators immediately (high-priority Slack notification)


Scenario B: InfluxDB Unavailable
─────────────────────────────────

Timeline:
  t=0s:   InfluxDB container crashes
  t=0-1s: Central server tries to write decisions → InfluxDB timeout
  t=1s:   Central server catches exception, falls back to in-memory buffer
          ├─ ring_buffer = [decision_1, decision_2, ...]  (10k capacity)
          └─ continue_computing_decisions()  ✓
  t=1-60s: Central server buffers decisions in-memory
          ├─ agent polling works (decisions still served from cache)
          ├─ telemetry not stored (but agents still collect locally)
          ├─ dashboard shows "DEGRADED" (data loss risk)
  t=60s:  Operator restarts InfluxDB
  t=60-65s: Central server replays buffered decisions to InfluxDB
          ├─ ordered_by_timestamp()
          ├─ bulk_write(batch_size=1000)
          └─ verify_integrity()
  t=65s+: InfluxDB back online, dashboard shows "HEALTHY"

Impact:
  ├─ Decisions: NO impact (still served to agents)
  ├─ Telemetry history: 1 hour lost (30k data points)
  ├─ Monitoring: dashboard offline
  ├─ Data loss: mitigated by in-memory buffer
  └─ Recovery: ~5 minutes

Mitigation:
  ├─ InfluxDB persistent volume (data survives container restart)
  ├─ Ring buffer capacity: 10k decisions = ~100 seconds buffer
  ├─ Operator training: restart InfluxDB immediately
  └─ Alert on InfluxDB write failures (high-priority alert)


Scenario C: Network Latency Spike (central server→InfluxDB)
───────────────────────────────────────────────────────────

Timeline:
  t=0s:   Network congestion spike
          (e.g., lab file backup saturates network)
  t=0-500ms: InfluxDB write latency increases
          ├─ single write takes 100ms → 500ms
          └─ batch writes take 500ms → 2000ms
  t=0.5s: Central server notices slow writes
          ├─ adjust batch_size (50 → 25 points)
          ├─ async_write()  (don't block decision computation)
  t=0.5-10s: Decisions still computed quickly
          ├─ inference latency < 50ms (no InfluxDB dependency)
          └─ agents still polling, still get decisions
  t=10s:  Network recovers
  t=10s+: InfluxDB catches up, writes flush from queue

Impact:
  ├─ Decisions: NO impact (independent from InfluxDB)
  ├─ Telemetry history: queued, eventual consistency OK
  ├─ Agents: NO impact (polling works)
  └─ Recovery: automatic, < 1 minute

Mitigation:
  ├─ Async writes (non-blocking)
  ├─ Batch size adaptation (dynamic)
  └─ Alert if write queue > 1000 items (high-priority)


Scenario D: Model Inference Failure (NaN prediction)
────────────────────────────────────────────────────

Timeline:
  t=0s:   Bad feature values cause XGBoost to return NaN
          (e.g., division by zero, overflow)
  t=0.1s: Inference service catches exception
          └─ try/except blocks NaN, falls back to heuristic
  t=0.15s: Heuristic computes fan % from intensity
          ├─ cpu + gpu + memory intensity → percentile
          └─ return fan_pct ≈ (cpu + gpu) / 2
  t=0.2s: Central policy uses heuristic prediction
          ├─ compute decision as normal
          └─ add confidence=0.50  (lower than normal 0.90)
  t=0.3s: Agents poll, receive heuristic-based decision
          ├─ apply fan control (works, but less optimal)
  t=1-300s: Heuristic decisions work for ~5 min
          ├─ temperature stays reasonable (conservative fan curve)
          ├─ acoustic slightly higher than optimal
  t=300s: Model inference recovered (fixed upstream issue)
  t=300s+: Resume normal XGBoost predictions

Impact:
  ├─ Decisions: degraded (heuristic < ML model)
  ├─ Temperature: slightly elevated but safe
  ├─ Reliability: VERY HIGH (no crashes)
  └─ Recovery: automatic, < 1 minute

Mitigation:
  ├─ Input validation (check for NaN before model)
  ├─ Fallback heuristic (always-on backup logic)
  ├─ Alert on heuristic fallback (moderate-priority)
  └─ Log error for offline investigation


Scenario E: 10 Agents Offline (Network Unreachable)
───────────────────────────────────────────────────

Timeline:
  t=0s:   Network issue isolates 10 machines from central server
          (e.g., switch port down, WiFi dropped)
  t=0-5s: Agents poll, get timeout
  t=5s:   All 10 agents switch to cached decisions + PERFORMANCE escalation
  t=5-300s: 10 agents operate independently
          ├─ telemetry collected locally (not sent)
          ├─ fan controlled to PERFORMANCE (85%, safe but loud)
          ├─ central server sees 40 machines online (dashboard shows 40/50)
          ├─ alert: "10 machines offline for 5+ min"
  t=300s: Network issue resolved
  t=300-310s: Agents reconnect, resume normal operation
          ├─ send pending telemetry (queued locally)
          ├─ resume normal polling
  t=310s+: All 50 machines back online

Impact:
  ├─ Temperature: 10 machines at elevated temp (mitigated by escalation)
  ├─ Data loss: ~5 minutes telemetry for 10 machines (queued locally)
  ├─ Reliability: HIGH (agents operate independently)
  └─ User awareness: HIGH (dashboard shows offline machines)

Mitigation:
  ├─ Local telemetry buffering (agents queue if central unavailable)
  ├─ Operator awareness (dashboard alert immediately)
  ├─ Network monitoring (switch health checks)
  └─ Graceful escalation (PERFORMANCE mode is safe default)


Scenario F: Prometheus/Grafana Offline
──────────────────────────────────────

Timeline:
  t=0s:   Grafana container crashes
  t=0-5s: Dashboard unavailable (HTTP 503)
  t=5s:   Operator notices dashboard down
  t=5-60s: Central server continues operating
          ├─ inference works normally
          ├─ InfluxDB still stores data
          ├─ agents still controlled
          └─ no alerts visible to operators (Slack alerts still work)
  t=60s:  Operator restarts Grafana
  t=60-65s: Grafana reconnects to InfluxDB
  t=65s+: Dashboard comes online, shows historical data

Impact:
  ├─ Decisions: NO impact
  ├─ Alerts: Slack alerts still work (AlertManager independent)
  ├─ Visibility: LOST (no dashboard)
  ├─ Recovery: ~5 minutes
  └─ User impact: MODERATE (blind to GUI, but Slack alerts work)

Mitigation:
  ├─ Prometheus/AlertManager independent from Grafana
  ├─ Slack notifications continue even if dashboard down
  ├─ Grafana data persistent (local volume)
  └─ Low priority (dashboard is observability, not control)
```

---

**Diagram Version**: 1.0  
**Last Updated**: 2026-06-25  
**Status**: Ready for Architecture Review
