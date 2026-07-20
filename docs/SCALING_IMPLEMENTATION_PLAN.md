# Scaling Implementation Plan: Single Laptop → 50-Machine Lab

**Current State**: Single Lenovo Legion laptop with 1-second local telemetry loop, XGBoost + AnalyticGNN inference, in-memory dashboard.

**Target**: 50 heterogeneous lab computers (Windows/Linux/macOS, mixed hardware, no admin access) with centralized telemetry, distributed inference, per-machine policy execution, lab-wide monitoring.

---

## Executive Summary

The scaling strategy uses a **hybrid push-pull telemetry + central inference + edge actuation** architecture with time-series database persistence and graceful degradation. This preserves sub-second per-machine responsiveness while enabling lab-wide observability.

**Key trade-offs**:
- **Telemetry**: Agent-push (low latency, agent responsibility) over pull (simpler but adds polling overhead)
- **Inference**: Central server (model consistency, simplicity) over edge (lower latency but deployment burden)
- **Actuation**: JSON polling on edge (no admin, flexible) over RPC (more complex, faster)
- **Storage**: InfluxDB (time-series optimized, retention policies) + optional Parquet (bulk retraining)
- **Hardware abstraction**: OS-level APIs (systemd on Linux, launchd on macOS, Task Scheduler on Windows) + fallback telemetry collection

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Lab Network                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  50 Client Machines (Windows/Linux/macOS)                        │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │  Machine 1       │  │  Machine 2       │  │  Machine N     │ │
│  ├──────────────────┤  ├──────────────────┤  ├────────────────┤ │
│  │ telemetry_agent  │  │ telemetry_agent  │  │ telemetry_agent│ │
│  │ (1 sec collect)  │  │ (1 sec collect)  │  │ (1 sec collect)│ │
│  │ ↓                │  │ ↓                │  │ ↓              │ │
│  │ policy_executor  │  │ policy_executor  │  │ policy_executor│ │
│  │ (polls decision) │  │ (polls decision) │  │ (polls decision)│ │
│  │ ↓                │  │ ↓                │  │ ↓              │ │
│  │ fan_control      │  │ fan_control      │  │ fan_control    │ │
│  │ (HW specific)    │  │ (HW specific)    │  │ (HW specific)  │ │
│  └──────┬───────────┘  └──────┬───────────┘  └────────┬────────┘ │
│         │                     │                       │           │
│         └─────────────────────┼───────────────────────┘           │
│                               ↓ (HTTPS push via agent)            │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Central Server (Linux VM or Kubernetes)                  │   │
│  ├────────────────────────────────────────────────────────────┤   │
│  │ ┌──────────────────────┐  ┌───────────────────────────┐  │   │
│  │ │ Telemetry Ingestion  │  │ Inference Service (GPU)   │  │   │
│  │ │ (FastAPI on port     │  │ (XGBoost + AnalyticGNN)   │  │   │
│  │ │  8000)               │  │ (batched every 100ms or   │  │   │
│  │ │ POST /ingest         │  │  on demand)               │  │   │
│  │ └──────────┬───────────┘  └───────────┬───────────────┘  │   │
│  │            │                          │                   │   │
│  │            └──────────────┬───────────┘                   │   │
│  │                           ↓                               │   │
│  │         ┌─────────────────────────────────┐              │   │
│  │         │ Orchestration Logic             │              │   │
│  │         │ (CoolingPolicyEngine per node)  │              │   │
│  │         │ → generates target fan %        │              │   │
│  │         └─────────────┬───────────────────┘              │   │
│  │                       ↓                                   │   │
│  │ ┌──────────────────────────────────────────────────────┐ │   │
│  │ │ InfluxDB (time-series storage + retention)           │ │   │
│  │ │ - 7 days raw data (1s interval)                       │ │   │
│  │ │ - 30 days hourly aggregates                           │ │   │
│  │ │ - decisions + telemetry + risk scores                 │ │   │
│  │ └──────────────────────────────────────────────────────┘ │   │
│  │                                                            │   │
│  │ ┌──────────────────────────────────────────────────────┐ │   │
│  │ │ HTTP Decision Service (port 8001)                    │ │   │
│  │ │ GET /decision/{machine_id}                           │ │   │
│  │ │ → returns: {target_fan_pct, mode, confidence}        │ │   │
│  │ └──────────────────────────────────────────────────────┘ │   │
│  │                                                            │   │
│  └────────────────────────────────────────────────────────────┘   │
│                           ↑                                        │
│                           │ (agents poll every 200ms)             │
│                           │                                        │
└──────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    Lab-Wide Dashboard (port 8002)               │
│  - Real-time thermal map (50 machines)                          │
│  - Historical trends (Grafana + InfluxDB)                       │
│  - Anomaly alerts (Prometheus AlertManager)                     │
│  - Model retraining data export                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Detailed Decision Matrix

### 1. Telemetry Collection Strategy

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Push vs Pull** | **Push (agent-initiated)** | Agents on each machine push telemetry every 1 sec to central server. Eliminates polling overhead at center; agents own their network backoff/retry logic. Aligns with existing 1s interval. |
| **Protocol** | **HTTPS + batching** | Each agent buffers 5-10 telemetry points and pushes JSON every 5-10 seconds (configurable). Reduces overhead from 50 * 1/sec = 50 Hz to ~5-10 Hz at server. |
| **Agent framework** | **Systemd (Linux), launchd (macOS), Task Scheduler (Windows)** + fallback Python process manager | Ensure agents survive reboots and crashes. Python process manager (supervisor) as secondary layer for non-systemd systems. |
| **Telemetry schema** | **Identical to current but per-machine** | `{machine_id, timestamp, cpu, gpu, memory, disk_io, network_io, local_temps, local_fan_info}` + machine metadata (OS, hardware hash, capabilities). |

**Implementation files to create**:
- `agents/telemetry_agent.py` — wraps `src/telemetry_logger.py` + batching + HTTPS push
- `agents/install_systemd.sh` — Linux install
- `agents/install_launchd.sh` — macOS install
- `agents/install_windows_task.ps1` — Windows install
- `agents/agent_config.json` — per-machine config (server URL, api_key, batch size, interval)

---

### 2. Inference Orchestration

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Central vs Edge** | **Central + optional edge caching** | Single server runs XGBoost + AnalyticGNN for all 50 machines. Ensures model consistency, simplifies retraining. Optional: edge agents cache last decision for up to 1 second if server unreachable. |
| **Batching** | **Time-windowed (100ms) or count-windowed (50 points)** | Accumulate telemetry from multiple machines, run XGBoost inference on batch. Saturates GPU better than per-machine inference. |
| **Inference engine** | **FastAPI + Gunicorn (4-8 workers)** | Lightweight, async-first, scales to 50 machines easily. Each worker runs model in-process. Optional: triton-inference-server if moving to ONNX later. |
| **Model deployment** | **Pickle (current) → ONNX (future)** | Start with existing `.pkl` serialization. Plan migration to ONNX for language-agnostic edge deployment. |
| **Latency SLA** | **< 200ms P95 per batch** | With 100ms window, worst-case latency = 100ms window + 50ms compute + network = ~200ms. Acceptable for 1s polling cycle on edge. |

**Implementation files to create**:
- `server/inference_service.py` — FastAPI inference endpoint
- `server/central_policy_engine.py` — wraps `src/thermal_mode_controller.py` for all machines
- `server/batch_orchestrator.py` — accumulates telemetry, triggers inference
- `server/decision_cache.py` — caches decisions per machine for edge fallback

---

### 3. Storage Architecture

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Primary store** | **InfluxDB 2.x (or managed cloud equivalent)** | Time-series optimized, native downsampling/retention policies, efficient disk usage, built-in Prometheus scrape. 1-second granularity for 7 days = ~1.2GB per 5 metrics per machine → 300GB for 50 machines. InfluxDB compresses to ~30GB. |
| **Retention** | **Raw (1s): 7 days, Hourly: 90 days, Daily: 1 year** | Enough raw data for incident replay, long-term trends. Automatic downsampling via InfluxDB tasks. |
| **Retraining data** | **Export to Parquet monthly** | InfluxDB → Parquet pipeline to preserve full training dataset. Parquet is columnar, compresses well, integrates with pandas/Polars. |
| **Query access** | **InfluxQL + Prometheus remote-read** | Grafana dashboards query InfluxQL. Prometheus can scrape InfluxDB as remote backend. |

**Implementation files to create**:
- `server/influxdb_client.py` — wrapper for inserting telemetry + decisions + risk scores
- `server/export_pipeline.py` — monthly export to Parquet (via pandas or DuckDB)
- `docker-compose.yml` — InfluxDB + Prometheus + Grafana stack
- `server/retention_policy.py` — manage InfluxDB retention/downsampling

**Storage math**:
```
50 machines × 1s interval × 7 days × (5 metrics) ≈ 30 million points
InfluxDB: ~30GB with compression
Parquet export (monthly): ~5-10GB per month (full retraining dataset)
```

---

### 4. Actuation & Hardware Abstraction

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Mechanism** | **JSON polling by edge agents (current approach, scales)** | Each agent reads decision JSON from central server every 200ms. No RPC coupling, resilient to network jitter. |
| **Hardware drivers** | **OS-native APIs + fallback** | Windows: WMI/PowerShell, Linux: sysfs/ACPI, macOS: system_profiler. Fallback: mock control if hardware not accessible (graceful degradation). |
| **Fan control abstraction** | **`HardwareFanController` → machine-type-specific implementations** | Current implementation writes to `runtime/fan_target.json`. Extend with per-OS drivers: `LinuxFanController`, `WindowsFanController`, `MacOSFanController`. |
| **Lenovo toolkit dependency** | **Remove critical path, make optional** | Current code assumes `llt.exe`. Make non-Lenovo machines work by defaulting to CPU/network intensity-based fallback fan curve (no hardware access needed). |

**Implementation files to create**:
- `agents/policy_executor.py` — agent-side decision polling + actuation
- `drivers/fan_controller_linux.py` — sysfs PWM + ACPI EC writes
- `drivers/fan_controller_windows.py` — WMI + PowerShell fan control
- `drivers/fan_controller_macos.py` — system_profiler + IOKit fallback
- `drivers/fan_controller_base.py` — abstract base class
- `drivers/fallback_fan_curve.py` — intensity-based fan control (no HW access)

---

### 5. Hardware Abstraction & Telemetry Portability

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **OS compatibility** | **Windows (WMI), Linux (sysfs/ACPI), macOS (system_profiler)** | Telemetry collection via `psutil` + OS-specific temp/fan readers. No admin required for telemetry; optional admin for fan control. |
| **Non-Lenovo support** | **Yes, via fallback intensity-based fan curves** | If hardware-specific control unavailable, use CPU/GPU/memory intensity to infer fan target. Conservative (fan stays higher) but safe. |
| **No-admin constraint** | **Telemetry collection: yes. Fan control: optional** | Users can read `/proc/` (Linux), WMI (Windows), `sysctl` (macOS) without admin. Fan control may degrade gracefully. |
| **Hardware identification** | **Collect at agent startup, tag all telemetry** | `machine_id` = hash(hostname + MAC + disk serial). Store hardware profile (CPU model, RAM, GPU, OS, kernel) in InfluxDB metadata. |

**Implementation files**:
- `agents/hardware_detector.py` — CPU/GPU/RAM/OS identification
- `agents/telemetry_reader_linux.py` — sysfs/ACPI/`hwmon` parsing
- `agents/telemetry_reader_windows.py` — WMI queries
- `agents/telemetry_reader_macos.py` — system_profiler + IOKit

---

### 6. Monitoring & Observability

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Dashboard** | **Grafana (InfluxDB backend)** | Replace `Index.html` with Grafana dashboard: 50 thermal curves, alerts, SLA tracking. HTML dashboard becomes read-only status page. |
| **Alerting** | **Prometheus AlertManager** | Define rules: temp > 90C, machine offline > 5min, prediction error > 0.2, repeated failsafe triggers. Route to Slack/email. |
| **Replay/simulation** | **Export-import pipeline via Parquet** | Agents log all decisions to InfluxDB. Batch export → replay script to re-run model inference offline for validation. |
| **Per-machine audit** | **Decision logs with confidence/reasoning** | Each decision JSON includes: `{risk_score, xgb_pred, gnn_pred, fused_score, policy_reason, alternative_decisions}`. Queryable in InfluxDB. |

**Implementation files**:
- `server/grafana_dashboard.json` — 50-machine thermal dashboard
- `server/prometheus_rules.yaml` — alerting rules (temp, latency, failures)
- `server/alert_webhook.py` — Slack/email formatter
- `scripts/replay_offline.py` — batch re-inference for validation

---

### 7. Graceful Degradation Strategy

| Failure Mode | Behavior | Implementation |
|--------------|----------|-----------------|
| **Central server down** | Agent falls back to cached last decision (up to 1s old); fan stays at last mode. No aggressive escalation. | `agents/policy_executor.py` with local decision cache + TTL |
| **Network latency spike** | Agent re-uses last decision with confidence discount. If latency > 5s, escalate to PERFORMANCE mode (safe default). | Timeout logic + backoff in agent |
| **Inference slow** | Batch pipeline falls back to single-machine inference if queue > 100 items. Inference SLA increases to 1s (acceptable). | `batch_orchestrator.py` with adaptive batching |
| **InfluxDB offline** | Central server buffers decisions in-memory (ring buffer, ~10k events). Replay when InfluxDB online. | `server/decision_buffer.py` |
| **Machine offline 5+ min** | Dashboard marks red, alerts triggered. Assume machine is down (no cascading retries). | InfluxDB scrape timeout detection |
| **Model inference NaN/error** | Fall back to intensity-based heuristic (CPU + GPU → fan %). Log error for investigation. | Try/catch in inference service |

**Implementation files**:
- `agents/fallback_decision.py` — cached decision + TTL
- `server/decision_buffer.py` — ring buffer for InfluxDB outages
- `agents/network_retry_policy.py` — exponential backoff with jitter
- `server/inference_fallback.py` — heuristic-based policy on model error

---

## Part 2: Step-by-Step Implementation Roadmap

### Phase 1: Centralize Telemetry (Weeks 1-2)

**Goal**: 50 agents → central telemetry collection, no inference yet.

1. **Refactor `src/telemetry_logger.py` → agent module**
   - Extract telemetry collection into `TelemetryCollector` class
   - Add batching (buffer 5 points, send every 5s)
   - Add HTTPS client with cert pinning
   - Test on Linux, Windows, macOS

2. **Create `server/telemetry_ingest.py`**
   - FastAPI endpoint `POST /ingest/{machine_id}` accepting JSON batch
   - Validate schema, store in-memory ring buffer
   - Serve stored telemetry on `GET /telemetry/{machine_id}`

3. **Create agent deployment scripts**
   - `agents/install_systemd.sh` — systemd service on Linux
   - `agents/install_launchd.sh` — launchd on macOS
   - `agents/install_windows_task.ps1` — Task Scheduler on Windows

4. **Write `agents/hardware_detector.py`**
   - Machine ID generation (hostname + MAC hash)
   - OS detection, CPU/GPU/RAM identification
   - Include in every telemetry batch

5. **Test with 5 machines in lab**
   - Deploy agents, verify telemetry arrives at central server
   - Monitor latency (target < 1s from collection to storage)
   - Check agent resilience (restart, network dropout, etc.)

**Success criteria**:
- All 5 test machines streaming telemetry to central server within 1 second
- No telemetry loss on agent restart
- Central server buffering working

---

### Phase 2: Centralize Inference (Weeks 3-4)

**Goal**: Central inference service predicts for all machines based on centralized telemetry.

1. **Create `server/inference_service.py`**
   - Load existing XGBoost + AnalyticGNN models
   - FastAPI endpoints:
     - `POST /predict` — accepts batch of telemetry, returns risk scores
     - `GET /decision/{machine_id}` — cached decisions per machine
   - Run under Gunicorn (4-8 workers)

2. **Create `server/batch_orchestrator.py`**
   - Accumulate telemetry from all machines into 100ms windows
   - Batch-invoke inference service
   - Store predictions in ring buffer

3. **Create `server/central_policy_engine.py`**
   - Instantiate `CoolingPolicyEngine` for each of 50 machines
   - Maintain per-machine state (mode, hysteresis, cooling effectiveness)
   - Invoke after each batch inference
   - Return decision JSON to decision cache

4. **Extend `HardwareFanController` → decision service**
   - Store decisions in memory/cache (Redis optional for HA)
   - Expose `GET /decision/{machine_id}` with `{target_fan_pct, mode, confidence, timestamp}`

5. **Deploy InfluxDB**
   - Docker image + docker-compose.yml
   - Configure retention policies (7d raw, 90d hourly, 1y daily)
   - Create database `cooling_lab`

6. **Create `server/influxdb_client.py`**
   - Write telemetry points to InfluxDB (batched)
   - Write decision points (risk_score, xgb_pred, gnn_pred, fused_score, mode, fan_pct)

7. **Test inference latency**
   - Inject 50 machines' worth of synthetic telemetry
   - Measure P50/P95 inference latency
   - Target: < 200ms per batch (100ms accumulation + 50ms inference)

**Success criteria**:
- Central inference service correctly predicts risk for all machines
- Decisions cached and updated every 200-500ms
- InfluxDB receives and stores decisions
- P95 latency < 200ms

---

### Phase 3: Edge Actuation & Hardware Abstraction (Weeks 5-6)

**Goal**: Agents fetch decisions and apply hardware-specific fan control.

1. **Create `agents/policy_executor.py`**
   - Poll `GET /decision/{machine_id}` every 200ms
   - Parse decision JSON
   - Invoke hardware-specific fan controller
   - Cache last decision for fallback (TTL 1s)
   - Log decisions locally (for offline audit)

2. **Create hardware abstraction layer**
   - `drivers/fan_controller_base.py` — abstract base
   - `drivers/fan_controller_linux.py` — `/sys/class/hwmon`, ACPI EC
   - `drivers/fan_controller_windows.py` — WMI, PowerShell
   - `drivers/fan_controller_macos.py` — IOKit, system settings
   - `drivers/fallback_fan_curve.py` — intensity-based curve (no HW access)

3. **Extend `agents/telemetry_reader_*.py`**
   - OS-specific temp/fan info collectors
   - Graceful degradation if sensors unavailable
   - Include in telemetry batch

4. **Test on heterogeneous hardware**
   - Windows + non-Lenovo: verify fallback fan curve works
   - Linux + AMD: verify sysfs PWM works
   - macOS: verify system settings access
   - No-admin scenarios: verify telemetry works, fan control degrades gracefully

**Success criteria**:
- Agents apply fan decisions within 300ms of decision fetch
- Fan RPM/speed changes observable on all OSes
- Graceful fallback on non-Lenovo or missing sensors
- No admin access required for telemetry (fan control optional)

---

### Phase 4: Lab-Wide Dashboard & Observability (Weeks 7-8)

**Goal**: Real-time and historical visibility into 50-machine thermal state.

1. **Deploy Prometheus + Grafana**
   - `docker-compose.yml` includes prometheus service
   - Prometheus scrapes InfluxDB remote-read (or uses InfluxDB plugin)
   - Configure 15s scrape interval

2. **Create Grafana dashboard**
   - Thermal curve for each machine (50 subpanels or dynamic row)
   - Lab-wide stats (avg temp, max temp, failsafe events)
   - Per-machine decision timeline (mode changes, confidence)
   - Heatmap of decision latency (agent → central → back to agent)

3. **Create alert rules**
   - Temp > 90C for > 30s → warning
   - Temp > 95C → critical
   - Machine offline > 5 min → alert
   - Inference latency > 500ms → warning
   - Repeated failsafe (> 3 in 5 min) → anomaly

4. **Create `server/alert_webhook.py`**
   - Prometheus AlertManager → Slack/email formatter
   - Route to lab ops channel
   - Include machine ID, current metrics, decision history

5. **Extend `Index.html` dashboard**
   - Keep minimal local view (current machine only)
   - Add link to central Grafana
   - Show fallback status (central server reachable? decision cache age?)

6. **Create export pipeline**
   - Monthly InfluxDB → Parquet export
   - Script: `scripts/export_training_data.py`
   - Parquet includes all telemetry + decisions for model retraining

**Success criteria**:
- Grafana dashboard shows all 50 machines in real-time
- Alerts working (test by simulating high temp)
- Monthly Parquet export contains full training dataset
- Dashboard latency < 1s (Grafana query to InfluxDB)

---

### Phase 5: Graceful Degradation & Resilience (Weeks 9-10)

**Goal**: System survives partial failures without cascading impact.

1. **Implement agent-side fallback**
   - `agents/fallback_decision.py` — cache + TTL for last decision
   - If central server unreachable for > 5s, use cached decision
   - Log cache miss events for dashboard alerting
   - Escalate fan to PERFORMANCE if decision is > 10s stale

2. **Implement central buffer for InfluxDB outages**
   - `server/decision_buffer.py` — ring buffer (10k decisions)
   - If InfluxDB unavailable, keep buffering in-memory
   - Replay to InfluxDB when back online (ordered by timestamp)

3. **Add inference fallback**
   - If XGBoost fails, fall back to intensity-based heuristic
   - CPU + GPU + memory intensity → percentile → fan %
   - Log fallback events for investigation

4. **Load shedding in batch orchestrator**
   - If queue > 100 items, drop oldest and shift to single-machine inference
   - Increase inference SLA to 1s (still acceptable)
   - Alert if load shedding active

5. **Network resilience in agents**
   - Exponential backoff for failed decision fetches
   - Jitter in poll interval (±20ms) to avoid thundering herd
   - Circuit breaker: if 5 consecutive failures, wait 30s before retrying

6. **Write resilience test suite**
   - `tests/test_agent_fallback.py` — agent works offline
   - `tests/test_central_buffer.py` — decisions buffered during InfluxDB outage
   - `tests/test_inference_fallback.py` — model failure → heuristic
   - `tests/test_network_jitter.py` — agents handle latency spikes

**Success criteria**:
- Agent continues controlling fan if central server offline for 10+ minutes
- Decisions buffered in central server if InfluxDB offline
- Inference falls back to heuristic on model error (no crashes)
- All tests passing with synthetic failure injection

---

### Phase 6: Monitoring & Model Validation (Weeks 11-12)

**Goal**: Understand model performance and system behavior at scale.

1. **Create offline replay script**
   - `scripts/replay_offline.py` — consume Parquet export
   - Re-run XGBoost + AnalyticGNN inference offline
   - Compare to live decisions (should match within 0.01 risk points)
   - Generate parity report monthly

2. **Create decision audit log**
   - Every decision written to InfluxDB includes: `xgb_pred`, `gnn_pred`, `fused_score`, `policy_reason`
   - Query: find all decisions where reason = "FAILSAFE" → investigate root cause
   - Query: find decisions with low confidence (fused_score unstable)

3. **Create model retraining pipeline**
   - Monthly: export 30 days of Parquet data
   - Script: `training/retrain_monthly.py`
   - Retrain XGBoost on 50 machines' data (distribution shift from single laptop)
   - Validate on 20% holdout (random machines)
   - Generate performance report, alert if accuracy drops > 5%

4. **Create lead-time analysis**
   - Fix bug in `live_leadtime_monitor.py` (currently inflates over time)
   - Calculate: for each high-temp event, how much warning did model provide?
   - Metric: P50/P95 lead time in seconds
   - Dashboard panel: lead-time distribution

5. **Create failure case analysis**
   - Query: decisions that led to throttling or shutdown
   - Cluster by workload type, hardware, time of day
   - Feed insights into feature engineering (for retraining)

**Success criteria**:
- Monthly Parquet exports contain clean training data (50 machines)
- Offline replay parity > 99.5%
- Retraining pipeline automated (manual trigger only)
- Lead-time analysis shows median lead time ≥ 10 seconds
- Failure case analysis identifies 3-5 actionable improvements

---

## Part 3: Critical Files & Code Artifacts

### New Files to Create (by phase)

**Phase 1: Telemetry**
```
agents/
├── telemetry_agent.py           (main entry point)
├── telemetry_collector.py       (refactored from src/telemetry_logger.py)
├── telemetry_reader_linux.py    (sysfs/ACPI parsing)
├── telemetry_reader_windows.py  (WMI queries)
├── telemetry_reader_macos.py    (system_profiler)
├── hardware_detector.py         (machine ID, CPU/GPU/RAM info)
├── agent_config.json            (server URL, batch size, interval)
├── install_systemd.sh           (systemd service install)
├── install_launchd.sh           (launchd install)
└── install_windows_task.ps1     (Task Scheduler install)

server/
├── telemetry_ingest.py          (FastAPI POST /ingest endpoint)
├── live_telemetry_buffer.py     (ring buffer for recent data)
└── docker-compose.yml           (InfluxDB stack)
```

**Phase 2: Inference**
```
server/
├── inference_service.py         (FastAPI POST /predict)
├── batch_orchestrator.py        (accumulate telemetry, batch inference)
├── central_policy_engine.py     (per-machine CoolingPolicyEngine)
├── decision_cache.py            (in-memory decision store)
├── influxdb_client.py           (write telemetry + decisions)
└── decision_service.py          (GET /decision/{machine_id})
```

**Phase 3: Actuation**
```
agents/
├── policy_executor.py           (fetch decisions, apply control)
├── fallback_decision.py         (cache + TTL)
└── network_retry_policy.py      (exponential backoff)

drivers/
├── fan_controller_base.py       (abstract base)
├── fan_controller_linux.py      (sysfs PWM, ACPI EC)
├── fan_controller_windows.py    (WMI, PowerShell)
├── fan_controller_macos.py      (IOKit, system settings)
└── fallback_fan_curve.py        (intensity-based curve)
```

**Phase 4: Dashboard**
```
server/
├── alert_webhook.py             (Prometheus → Slack/email)
├── grafana_dashboard.json       (50-machine thermal dashboard)
├── prometheus_rules.yaml        (alerting rules)
└── export_pipeline.py           (InfluxDB → Parquet monthly)

scripts/
├── export_training_data.py      (manual export trigger)
└── deploy_grafana.sh            (docker-compose up)
```

**Phase 5: Resilience**
```
server/
├── decision_buffer.py           (ring buffer for InfluxDB outages)
└── inference_fallback.py        (heuristic-based policy)

tests/
├── test_agent_fallback.py       (agent offline behavior)
├── test_central_buffer.py       (decision buffering)
├── test_inference_fallback.py   (model failure)
└── test_network_jitter.py       (latency spikes)
```

**Phase 6: Monitoring**
```
scripts/
├── replay_offline.py            (consume Parquet, re-run inference)
├── decision_audit_log.py        (query InfluxDB for anomalies)
└── lead_time_analysis.py        (P50/P95 warning time)

training/
├── retrain_monthly.py           (consume Parquet, retrain XGBoost)
├── validate_parity.py           (offline vs live predictions)
└── failure_case_analysis.py     (cluster + investigate)
```

### Files to Modify

1. **`src/telemetry_logger.py`**
   - Keep as-is for backward compatibility (single-machine use)
   - Create wrapper in `agents/telemetry_collector.py`

2. **`src/inference.py`**
   - Keep as-is for single-machine fallback
   - Central server uses refactored version

3. **`src/thermal_mode_controller.py`**
   - Refactor into `CoolingPolicyEngine` (already exists in `src/cooling_policy.py`)
   - Make stateless for parallel invocation (50 machines)

4. **`src/fan_controller.py`**
   - Refactor `HardwareFanController` → abstract factory with OS-specific implementations
   - Keep JSON polling for central server → agent communication

5. **`runtime/live_runtime_manager.py`**
   - Remove local-machine telemetry loop
   - Add central server mode (orchestration only)
   - Keep as optional local UI

6. **`Index.html`**
   - Add link to central Grafana dashboard
   - Show fallback status (central server reachable? decision cache age?)
   - Keep as read-only status view

7. **`docker-compose.yml`** (new)
   - InfluxDB, Prometheus, Grafana, central server (FastAPI)

---

## Part 4: Deployment & Testing Strategy

### Deployment Order

1. **Week 1-2**: Deploy central telemetry server, install agents on 5 test machines
2. **Week 3-4**: Deploy inference service, InfluxDB, verify predictions
3. **Week 5-6**: Deploy agents' policy executors, test on all hardware types
4. **Week 7-8**: Deploy Grafana, test dashboard + alerts on 10 machines
5. **Week 9-10**: Test resilience (kill central server, InfluxDB, simulate network issues)
6. **Week 11-12**: Validate model performance, run monthly retraining

### Testing Checklist

**Phase 1: Telemetry**
- [ ] Agent sends telemetry to central server within 1s
- [ ] Agent handles network dropout (backoff, retry)
- [ ] Agent survives restart (systemd/launchd/Task Scheduler)
- [ ] Telemetry schema matches contract (machine_id, timestamp, metrics)
- [ ] 5 machines × 1s interval = no telemetry loss

**Phase 2: Inference**
- [ ] Central inference service loads XGBoost + GNN models
- [ ] Batch inference P95 latency < 200ms
- [ ] 50 machines' risk scores computed in < 500ms
- [ ] Decision cache updated every 200-500ms
- [ ] InfluxDB writes succeed (no data loss)

**Phase 3: Actuation**
- [ ] Agent fetches decision every 200ms
- [ ] Fan speed changes on Windows (WMI + PowerShell)
- [ ] Fan speed changes on Linux (sysfs PWM)
- [ ] Fan speed changes on macOS (IOKit or system settings)
- [ ] Fallback fan curve works on non-Lenovo hardware
- [ ] No admin access required for telemetry

**Phase 4: Dashboard**
- [ ] Grafana shows all 50 machines in real-time
- [ ] Thermal curves update every 5s
- [ ] Alerts trigger on high temp (test with synthetic spike)
- [ ] Monthly Parquet export contains complete training data

**Phase 5: Resilience**
- [ ] Central server down → agents use cached decisions for > 5 min
- [ ] InfluxDB down → central server buffers decisions in-memory
- [ ] Model inference fails → heuristic fallback works
- [ ] Network latency spike (> 5s) → agent escalates to PERFORMANCE
- [ ] Inference queue > 100 items → load shedding triggers

**Phase 6: Model Validation**
- [ ] Offline replay parity > 99.5% with live predictions
- [ ] Monthly retraining on 50 machines' data completes
- [ ] Lead-time analysis shows median ≥ 10s warning
- [ ] Failure case clustering identifies root causes

### Synthetic Test Scenarios

**Scenario A: High CPU Load + Heat Ramp**
- Inject synthetic workload increasing CPU from 20% → 100% over 30s
- Verify agent fetches decisions every 200ms
- Verify fan % increases monotonically with risk
- Verify no oscillation (hysteresis working)

**Scenario B: Network Dropout**
- Kill central server for 10 minutes
- Agents should use cached decisions (fan control unchanged)
- Restore central server
- Verify agents re-sync within 2s

**Scenario C: InfluxDB Unavailable**
- Stop InfluxDB container
- Verify central server continues computing decisions
- Decisions buffered in-memory
- Restore InfluxDB, verify replay succeeds (no data loss)

**Scenario D: Heterogeneous Hardware**
- Windows non-Lenovo: fallback fan curve works
- Linux AMD: sysfs PWM works
- macOS: system settings or IOKit fallback works
- Verify telemetry collected on all platforms

**Scenario E: 50-Machine Scale**
- Deploy on full 50-machine lab
- Verify central server doesn't bottleneck (P95 latency < 200ms)
- Verify InfluxDB ingestion rate (50 machines × 10Hz = 500 points/sec)
- Verify Grafana dashboard responsive (query latency < 1s)

---

## Part 5: Data Flow Diagram

```
SECOND 0:
  Machine 1..50: collect telemetry (1-second interval via psutil, WMI, etc.)
  
SECOND 0.5 (batching window):
  Machine 1..50: buffer 5 raw points
  
SECOND 5 (batch window):
  Agent 1: POST /ingest/machine_1 with 5 telemetry points (HTTPS)
  Agent 2: POST /ingest/machine_2 with 5 telemetry points
  ...
  Agent 50: POST /ingest/machine_50 with 5 telemetry points
  
  Central Server: receive_ingest()
    → validate schema per machine
    → append to live_telemetry_buffer[machine_id]
    → check if 100ms window elapsed
  
  IF 100ms window elapsed:
    Central Server: batch_orchestrator()
      → collect latest point from each machine (50 points)
      → invoke inference_service.predict(batch_50)
      
      Inference Service: predict(batch_50)
        → load XGBoost + AnalyticGNN models
        → forward batch through model
        → return [risk_0, risk_1, ..., risk_49]
      
      Central Server: central_policy_engine()
        → for machine_i in 1..50:
          → invoke CoolingPolicyEngine(risk_i, state_i)
          → compute target_fan_pct_i
          → store decision_i = {risk_i, fan_pct_i, mode_i, timestamp}
      
      Central Server: influxdb_client.write_batch()
        → write decisions to InfluxDB
        → write telemetry to InfluxDB (aggregated per machine)
      
      Central Server: decision_cache.update()
        → store latest decision per machine in-memory
  
SECOND 5.2 (agent poll):
  Agent 1..50: GET /decision/{machine_id}
    → receive {target_fan_pct, mode, confidence, timestamp}
    
  Agent 1..50: apply_fan_control(target_fan_pct)
    → invoke OS-specific fan controller
    → on Windows: WMI/PowerShell
    → on Linux: sysfs PWM
    → on macOS: IOKit/system settings
    → on non-Lenovo: fallback curve
    
  Agent 1..50: log_local_decision()
    → store decision JSON locally (for audit)
  
SECOND 5.5:
  Agent 1..50: POST /ingest/machine_i with next 5 telemetry points
  
[LOOP] every 200ms: agent polls /decision
[LOOP] every 100ms: central server batches + infers
[LOOP] every 5s: agent pushes telemetry batch

DAILY:
  Prometheus AlertManager: scrape InfluxDB
    → check rules (temp > 90C, latency > 500ms, etc.)
    → trigger alerts → webhook → Slack/email
  
MONTHLY (day 1):
  export_pipeline.py:
    → query InfluxDB for all telemetry + decisions (30 days)
    → convert to Parquet (columnar, compressed)
    → save to shared storage
  
  training/retrain_monthly.py:
    → load Parquet (50 machines × 30 days)
    → train XGBoost on features + target (future_risk)
    → validate on 20% holdout
    → if accuracy OK: upload new model to central server
```

---

## Part 6: Phased Rollout Strategy

### Pilot Phase (Week 1-4)
- **Machines**: 5 test machines (Windows non-Lenovo, Linux desktop, macOS laptop)
- **Goal**: Validate architecture without scale overhead
- **Success**: Telemetry + inference working, decisions applied, no crashes
- **Go/No-Go**: If all 5 machines stable for 48 hours, proceed

### Ramp Phase (Week 5-8)
- **Machines**: 15 machines (add 10 more, diverse hardware)
- **Goal**: Validate scalability (inference latency, InfluxDB ingestion)
- **Success**: P95 latency < 200ms, InfluxDB handles 150 pts/sec
- **Go/No-Go**: If performance acceptable and no unexpected crashes, proceed

### Full Rollout (Week 9-12)
- **Machines**: All 50 lab machines
- **Goal**: Full-scale operation, resilience testing
- **Success**: 50 machines online, Grafana shows real-time thermal state, alerts working
- **Post-launch**: Monthly retraining, failure analysis, gradual model improvements

### Rollback Plan
- If central server fails: agents revert to locally cached decisions (graceful fallback)
- If inference accuracy drops: fall back to previous model version (versioned in server)
- If InfluxDB storage full: oldest data auto-deleted by retention policy
- If agent crashes on 5+ machines: pause rollout, debug, fix, resume

---

## Part 7: Configuration & Secrets

### Agent Configuration (`agents/agent_config.json`)
```json
{
  "central_server_url": "https://cooling-lab-server.local:8000",
  "api_key": "REDACTED",
  "machine_id_override": null,
  "telemetry_interval_sec": 1.0,
  "batch_size": 5,
  "batch_interval_sec": 5,
  "decision_poll_interval_ms": 200,
  "fallback_cache_ttl_sec": 1,
  "network_backoff_max_sec": 30,
  "enable_local_logging": true,
  "log_path": "/var/log/cooling_agent.log"
}
```

### Server Configuration (`server/.env`)
```
INFLUXDB_URL=http://influxdb:8086
INFLUXDB_ORG=cooling-lab
INFLUXDB_BUCKET=thermal
INFLUXDB_TOKEN=REDACTED
INFERENCE_BATCH_SIZE=50
INFERENCE_BATCH_WINDOW_MS=100
DECISION_CACHE_TTL_SEC=2
LOG_LEVEL=INFO
```

### Secrets Management
- Use environment variables for API keys, InfluxDB tokens
- Store in `.env.local` (never commit)
- Consider HashiCorp Vault for production HA
- Agent API key: rotated monthly, per-agent or global (TBD)

---

## Part 8: Success Metrics

### Telemetry Metrics
- **Collection latency**: P95 < 1s (from collection to central arrival)
- **Data loss**: < 0.1% (occasional network drops acceptable)
- **Agent uptime**: > 99.5% (systemd/launchd restart on failure)

### Inference Metrics
- **Batch latency**: P95 < 200ms (100ms window + 50ms compute)
- **Model parity**: offline replay > 99.5% agreement with live
- **Inference failures**: < 1 per 100k predictions (fallback to heuristic)

### Actuation Metrics
- **Decision-to-fan latency**: P95 < 500ms (decision → agent fetch → HW control)
- **Fan oscillation**: < 5 mode changes per hour in steady state
- **Graceful fallback**: 100% success rate when central server offline

### Thermal Metrics (lab-wide)
- **Peak temperature**: < 85°C (acceptable for 50-machine lab)
- **Avg temperature**: < 55°C (normal operation)
- **Throttling events**: < 1 per machine per day
- **Failsafe triggers**: < 10 per day across all 50 machines
- **Lead time**: P50 ≥ 10 seconds (warning before overheat)

### Observability Metrics
- **Dashboard query latency**: < 1s (Grafana → InfluxDB)
- **Alert accuracy**: > 95% (no false positives from jitter)
- **Historical retention**: 7 days raw, 90 days hourly, 1 year daily
- **Monthly retraining**: 100% success rate, no data loss

### Operational Metrics
- **Deployment time**: < 30 min per machine (agent install + config)
- **Mean time to recovery**: < 5 min (central server restart, agent re-sync)
- **Cost per machine**: < $5/month in cloud compute (InfluxDB + central server)

---

## Part 9: Known Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Central server becomes bottleneck | Inference latency > 500ms, decisions stale | Batch inference optimization, load shedding, optional edge caching (future) |
| InfluxDB cardinality explosion | Retention policy failure, slow queries | Time-based sharding, metric aggregation, cgroup labels (machine_id only) |
| Model inference NaN on unseen data | Silent failure, fan remains static | Try/catch in inference service, fall back to heuristic, alert on error |
| Network partitioning (50 agents unreachable) | All machines use stale decisions | Graceful timeout (1-5s), escalate to PERFORMANCE mode, dashboard alert |
| Agent OS-specific driver incompatibility | Fan control fails on some hardware | Fallback intensity curve, log error, prioritize debugging for Linux |
| Telemetry schema drift (new OS, new sensors) | Inference expects 5 inputs, gets 4 | Validate schema + fill missing with NaN/default, log schema errors |
| Monthly retraining fails (data corruption) | Model never updates | Verify Parquet integrity before retraining, keep previous model as fallback |
| No admin access for fan control (user constraint) | Can't modify sysfs/WMI | Graceful degradation: telemetry still works, fan control optional, alert in dashboard |

---

## Part 10: Future Enhancements (Beyond Phase 6)

1. **Edge inference (week 13-16)**
   - Deploy ONNX model to each agent
   - Agent-side inference for offline operation
   - Reduce decision latency to < 100ms

2. **Model ensemble (week 17-20)**
   - Train per-hardware-type models (Lenovo vs Dell vs Asus)
   - Route telemetry to appropriate model
   - Better accuracy on heterogeneous hardware

3. **Predictive scaling (week 21-24)**
   - Forecast lab workload 5 minutes ahead
   - Pre-cool machines before spike
   - Reduce peak fan RPM

4. **Reinforcement learning (week 25-28)**
   - Agent learns per-machine controller policy
   - Optimize for thermal + acoustic comfort trade-off
   - Personalized to each machine's cooling characteristics

5. **Multi-zone thermal model (week 29-32)**
   - AnalyticGNN: model spatial heat propagation across lab
   - Coordinate fan control between adjacent machines
   - Reduce overall lab temperature by 2-3°C

---

## Summary: Quick Checklist

**Before Phase 1 Start**:
- [ ] Set up central server (VM or Kubernetes)
- [ ] Create agent directory structure
- [ ] Draft agent_config.json template
- [ ] Identify 5 test machines (Windows, Linux, macOS)

**End of Phase 1**:
- [ ] Telemetry flowing from 5 machines to central server
- [ ] Agent survives restart, network dropout
- [ ] Central server buffering working

**End of Phase 2**:
- [ ] Inference service running and predicting
- [ ] InfluxDB storing telemetry + decisions
- [ ] P95 latency < 200ms

**End of Phase 3**:
- [ ] Fan control working on all OSes
- [ ] Fallback curve deployed
- [ ] No admin access required for telemetry

**End of Phase 4**:
- [ ] Grafana dashboard live
- [ ] Alerts working (tested with synthetic spike)
- [ ] Monthly export to Parquet

**End of Phase 5**:
- [ ] Resilience tests passing
- [ ] Agent fallback behavior verified
- [ ] Central buffer working

**End of Phase 6**:
- [ ] Offline replay parity > 99.5%
- [ ] Monthly retraining automated
- [ ] Lead-time analysis showing ≥ 10s warning

---

## Appendix: Architecture Diagrams

### Telemetry Push Flow (Agent → Central)
```
Agent (every 1s):         Central Server:
  collect() ──┐
  collect()   ├─ buffer 5 points
  collect()   │
  collect()   │
  collect() ──┘
                POST /ingest/{machine_id}
                ──────────────────────────→ validate_schema()
                                           append_to_buffer()
                                           check_batch_ready()
                                           
                (after 100ms window)
                           trigger_inference()
```

### Decision Flow (Central → Agent)
```
Central Server (computed):  Agent (polling every 200ms):
  decision_cache:
    machine_1 → {risk, fan%, mode}
    machine_2 → {risk, fan%, mode}
    ...
    machine_50 → {risk, fan%, mode}
    
                            GET /decision/{machine_id}
                ←─────────────────────────────
                {risk, fan%, mode, confidence}
                            │
                            ↓
                        apply_fan_control()
                            │
                            ↓
                        os_specific_driver()
```

### InfluxDB Schema
```
Measurement: telemetry
  Tags: machine_id, os, hardware_hash
  Fields: cpu (%), gpu (%), memory (%), disk_io (bytes/s), network_io (bytes/s)
  Timestamp: nanosecond precision

Measurement: decisions
  Tags: machine_id, policy_reason (QUIET, BALANCED, PERFORMANCE, FAILSAFE, RECOVERY)
  Fields: risk_score, xgb_pred, gnn_pred, fused_score, target_fan_pct, elapsed_ms
  Timestamp: nanosecond precision

Measurement: alerts
  Tags: machine_id, alert_type (HIGH_TEMP, INFERENCE_ERROR, OFFLINE)
  Fields: value (temp, latency, etc.)
  Timestamp: nanosecond precision
```

---

**Document Version**: 1.0  
**Last Updated**: 2026-06-25  
**Author**: System Architecture Team  
**Status**: Ready for Implementation
