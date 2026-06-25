# Scaling Quick Start: Week-by-Week Checklist

This document is a condensed, actionable version of the full implementation plan. Use it as your weekly sprint guide.

---

## Pre-Phase 0: Week -1 (Preparation)

- [ ] **Infrastructure**
  - [ ] Provision central server VM (Linux, 4 CPU, 16GB RAM, 500GB SSD)
  - [ ] Set up Docker + Docker Compose on central server
  - [ ] Reserve static IP: 10.0.1.254 (or use hostname: cooling-lab-server)
  - [ ] Test HTTPS connectivity: generate self-signed cert or use internal CA
  - [ ] Create `.env.local` for secrets (InfluxDB token, API keys)

- [ ] **Lab Setup**
  - [ ] Identify 5 pilot machines (Windows, Linux, macOS mix)
  - [ ] Verify network connectivity (DNS, firewall rules)
  - [ ] Create shared folder for logs (optional: /var/log/cooling-lab or NAS)
  - [ ] Document hardware specs for each machine (CPU, GPU, OS, RAM)

- [ ] **Code Preparation**
  - [ ] Create `agents/` directory structure
  - [ ] Create `server/` directory structure
  - [ ] Create `drivers/` directory structure
  - [ ] Create `tests/` directory for resilience tests
  - [ ] Refactor `src/telemetry_logger.py` → `agents/telemetry_collector.py`

---

## Phase 1: Centralize Telemetry (Weeks 1-2)

### Week 1

**Monday-Wednesday**:
- [ ] **`agents/telemetry_collector.py`** (refactored from `src/telemetry_logger.py`)
  - [ ] Extract telemetry collection into `TelemetryCollector` class
  - [ ] Add batching: buffer 5 points, send every 5 seconds
  - [ ] Add HTTPS client (requests library, cert pinning optional)
  - [ ] Add retry logic (exponential backoff, max 30s wait)
  - [ ] Test on single machine (local mode, to disk only)

- [ ] **`agents/hardware_detector.py`**
  - [ ] Machine ID generation: `hash(hostname + MAC + disk serial)`
  - [ ] OS detection: `platform.system()` (Windows, Linux, Darwin)
  - [ ] CPU/GPU/RAM detection: `psutil` + `subprocess` calls
  - [ ] Include in every telemetry batch
  - [ ] Test on 3 machines (Windows, Linux, macOS)

- [ ] **`agents/agent_config.json`** (template)
  - [ ] Server URL: `https://central-server:8000`
  - [ ] API key: placeholder (fill per deployment)
  - [ ] Telemetry interval: 1.0 sec
  - [ ] Batch size: 5, batch interval: 5 sec
  - [ ] Fallback cache TTL: 1 sec

**Thursday-Friday**:
- [ ] **`server/telemetry_ingest.py`** (FastAPI endpoint)
  - [ ] POST `/ingest/{machine_id}` — validate + store in ring buffer
  - [ ] GET `/telemetry/{machine_id}` — return latest 10 points
  - [ ] In-memory ring buffer (size=100 per machine)
  - [ ] Test with curl on localhost

- [ ] **`docker-compose.yml`** (minimal, InfluxDB only)
  - [ ] InfluxDB 2.x service
  - [ ] Expose port 8086
  - [ ] Volume mount for persistence (/var/lib/influxdb2)
  - [ ] Test `docker-compose up -d && sleep 5 && curl http://localhost:8086/ping`

- [ ] **Deploy to 2 pilot machines**
  - [ ] Manual deployment (no automation yet)
  - [ ] Verify telemetry arrives at server within 1 second
  - [ ] Check error logs for schema/network issues

### Week 2

**Monday-Wednesday**:
- [ ] **Deployment scripts**
  - [ ] `agents/install_systemd.sh` (Linux)
    - [ ] Create systemd unit file: `/etc/systemd/system/cooling-agent.service`
    - [ ] Enable + start: `systemctl enable cooling-agent && systemctl start cooling-agent`
    - [ ] Verify: `systemctl status cooling-agent` shows running
    - [ ] Test restart: `systemctl restart cooling-agent` → verify telemetry resumes

  - [ ] `agents/install_launchd.sh` (macOS)
    - [ ] Create plist: `~/Library/LaunchAgents/com.cooling.agent.plist`
    - [ ] Load: `launchctl load ~/Library/LaunchAgents/com.cooling.agent.plist`
    - [ ] Verify: `launchctl list | grep cooling`

  - [ ] `agents/install_windows_task.ps1` (Windows)
    - [ ] Create Task Scheduler task: "CoolingAgent"
    - [ ] Run as user (no admin), trigger on logon
    - [ ] Verify: `Get-ScheduledTask -TaskName CoolingAgent | Select-Object State`

**Thursday-Friday**:
- [ ] **Test with 5 machines**
  - [ ] Deploy on all 5 pilot machines
  - [ ] Monitor for 2 hours: zero telemetry loss
  - [ ] Kill agent process → verify systemd/launchd/Task Scheduler restart works
  - [ ] Pull network cable → verify graceful shutdown, log error
  - [ ] Restore network → verify auto-reconnect (backoff working)

- [ ] **Metrics dashboard (minimal)**
  - [ ] Check InfluxDB: `SELECT * FROM telemetry LIMIT 100`
  - [ ] Verify schema: tags (machine_id, os, hardware_hash), fields (cpu, gpu, memory, disk_io, network_io)
  - [ ] Count points: should be ~50 per machine (1/sec × 50 sec = 50 points)

- [ ] **Success criteria (Phase 1)**
  - [ ] 5 machines → central server in < 1s
  - [ ] 0% data loss over 2-hour test
  - [ ] Graceful fallback on network issue
  - [ ] Agent survives restart

---

## Phase 2: Centralize Inference (Weeks 3-4)

### Week 3

**Monday-Wednesday**:
- [ ] **`server/inference_service.py`** (FastAPI + Gunicorn)
  - [ ] Load XGBoost model: `models/cooling_model.pkl`
  - [ ] Load AnalyticGNN: `models/preprocessor_state.pkl`
  - [ ] POST `/predict` — batch inference
    - [ ] Input: `{features: [[...], [...], ...]}`  (50 × 15 dim)
    - [ ] Output: `{xgb_scores: [...], gnn_scores: [...], fused_scores: [...]}`
  - [ ] Measure latency: should be < 50ms for 50 samples
  - [ ] Test on local machine with synthetic data

- [ ] **`server/batch_orchestrator.py`**
  - [ ] Accumulate telemetry every 100ms
  - [ ] Collect latest point from each machine
  - [ ] Invoke inference_service.predict()
  - [ ] Return batch results to policy engine
  - [ ] Handle edge cases: missing machines, slow inference

- [ ] **`server/central_policy_engine.py`**
  - [ ] Instantiate `CoolingPolicyEngine` for each of 50 machines
  - [ ] Invoke `update(risk_score)` after each batch inference
  - [ ] Return `{risk, fan%, mode, timestamp}`
  - [ ] Store in decision cache

**Thursday-Friday**:
- [ ] **`server/decision_cache.py`**
  - [ ] In-memory dictionary: `{machine_id → {risk, fan%, mode, ts}}`
  - [ ] GET `/decision/{machine_id}` endpoint
  - [ ] TTL: 2 seconds (decisions > 2s old marked stale)
  - [ ] Test with concurrent access (thread-safe)

- [ ] **InfluxDB integration**
  - [ ] `server/influxdb_client.py` — async batch writer
  - [ ] Write telemetry points (500 per batch)
  - [ ] Write decision points (50 per batch)
  - [ ] Batching: flush every 1 second or buffer full
  - [ ] Test: verify points appear in InfluxDB

- [ ] **Test on 5 machines**
  - [ ] Run inference service + orchestrator + policy engine
  - [ ] Monitor latency: P95 < 200ms (collection → decision)
  - [ ] Verify InfluxDB receives data
  - [ ] Check decision cache: update every 100ms

### Week 4

**Monday-Wednesday**:
- [ ] **Tune batch inference**
  - [ ] Load test: 50 machines × 10Hz = 500 decisions/sec
  - [ ] Measure: P50/P95/P99 latency
  - [ ] If P95 > 200ms: optimize (profile CPU, check GPU usage)
  - [ ] Consider: onnx format (future optimization)

- [ ] **InfluxDB retention policies**
  - [ ] Raw (1s): 7 days
  - [ ] Hourly: 90 days (auto-downsampled)
  - [ ] Daily: 1 year (auto-downsampled)
  - [ ] Create tasks in InfluxDB UI or CLI

- [ ] **Monitoring script**
  - [ ] `scripts/monitor_inference.py` — log latency metrics every minute
  - [ ] Alert if P95 > 300ms (degradation detected)

**Thursday-Friday**:
- [ ] **Success criteria (Phase 2)**
  - [ ] Inference service running, P95 latency < 200ms ✓
  - [ ] 50 machines' decisions computed every 100ms ✓
  - [ ] InfluxDB storing telemetry + decisions ✓
  - [ ] Zero inference crashes (fallback working) ✓

- [ ] **Prepare for Phase 3**
  - [ ] Review hardware abstraction requirements
  - [ ] Identify fan control methods per OS

---

## Phase 3: Edge Actuation (Weeks 5-6)

### Week 5

**Monday-Wednesday**:
- [ ] **Hardware abstraction layer**
  - [ ] `drivers/fan_controller_base.py` — abstract base class
    - [ ] `set_fan_percent(pct: float)`
    - [ ] `get_fan_rpm()`
    - [ ] `get_cpu_temp()`

  - [ ] `drivers/fan_controller_windows.py`
    - [ ] Use WMI: `Get-WmiObject Win32_Fan`
    - [ ] Use PowerShell to set fan (Lenovo API if available)
    - [ ] Fallback: hardcoded fan curve

  - [ ] `drivers/fan_controller_linux.py`
    - [ ] Read: `/sys/class/hwmon/hwmon*/pwm[1-8]_enable`
    - [ ] Write: `/sys/class/hwmon/hwmon*/pwm[1-8]` (0-255 scale)
    - [ ] Fallback: echo commands with sudo

  - [ ] `drivers/fan_controller_macos.py`
    - [ ] Use IOKit (if available)
    - [ ] Fallback: system_profiler

  - [ ] `drivers/fallback_fan_curve.py`
    - [ ] CPU + GPU intensity → fan %
    - [ ] Conservative: fan stays higher on unknown hardware

- [ ] **Test drivers on 3 machines** (Windows, Linux, macOS)
  - [ ] Windows: verify WMI queries work (no admin needed for telemetry)
  - [ ] Linux: test sysfs writes (may need sudo, optional)
  - [ ] macOS: test system_profiler (no admin)

**Thursday-Friday**:
- [ ] **`agents/policy_executor.py`**
  - [ ] Poll `/decision/{machine_id}` every 200ms
  - [ ] Parse JSON: `{risk, fan%, mode, confidence}`
  - [ ] Invoke OS-specific fan controller
  - [ ] Log decision locally (JSON file)
  - [ ] Cache decision for offline fallback

- [ ] **`agents/fallback_decision.py`**
  - [ ] Cache last decision in memory
  - [ ] TTL: 1000ms
  - [ ] If central server unreachable: use cached decision
  - [ ] If cache > 2s old: escalate to PERFORMANCE mode (safe default)

- [ ] **Test on 5 machines**
  - [ ] Agents fetch decisions every 200ms
  - [ ] Fan % changes within 500ms
  - [ ] Graceful fallback when central server offline
  - [ ] Log all decisions locally

### Week 6

**Monday-Wednesday**:
- [ ] **Non-Lenovo support**
  - [ ] Test on Dell, HP, Asus machines
  - [ ] Verify fallback fan curve works (no admin required)
  - [ ] Verify telemetry collection works (psutil + OS APIs)

- [ ] **Integration test: full loop**
  - [ ] Agent collects telemetry → sends to central
  - [ ] Central infers → policy → caches decision
  - [ ] Agent polls → applies fan control → logs
  - [ ] All within 300ms latency (telemetry age + inference + fetch + actuation)

**Thursday-Friday**:
- [ ] **Success criteria (Phase 3)**
  - [ ] Fan control working on Windows/Linux/macOS ✓
  - [ ] Fallback curve working on non-Lenovo hardware ✓
  - [ ] Agent-side decision polling + caching ✓
  - [ ] Zero admin access required for telemetry ✓

- [ ] **Prepare for Phase 4**
  - [ ] Set up Prometheus + Grafana containers

---

## Phase 4: Lab-Wide Dashboard (Weeks 7-8)

### Week 7

**Monday-Wednesday**:
- [ ] **Deploy Prometheus + Grafana**
  - [ ] Add to `docker-compose.yml`: prometheus service
  - [ ] Add to `docker-compose.yml`: grafana service
  - [ ] Prometheus config: scrape InfluxDB remote-read
  - [ ] `docker-compose up -d`
  - [ ] Verify: http://localhost:9090 (Prometheus), http://localhost:3000 (Grafana)

- [ ] **Grafana dashboard**
  - [ ] `server/grafana_dashboard.json`
  - [ ] Create 50 thermal curve panels (one per machine)
  - [ ] Lab-wide stats: avg/max temp, failsafe count
  - [ ] Decision timeline: mode changes, confidence
  - [ ] Inference latency heatmap
  - [ ] Import into Grafana

- [ ] **Test dashboard**
  - [ ] View real-time curves for all 5 pilot machines
  - [ ] Verify update interval: 5 seconds
  - [ ] Zoom/drill-down into single machine
  - [ ] Export functionality (download data)

**Thursday-Friday**:
- [ ] **Alert rules**
  - [ ] `server/prometheus_rules.yaml`
  - [ ] Rule: `temp > 90C for > 30s` → warning
  - [ ] Rule: `temp > 95C` → critical
  - [ ] Rule: `machine offline > 5 min` → alert
  - [ ] Rule: `inference latency > 500ms` → warning
  - [ ] Rule: `failsafe triggered > 3 in 5 min` → anomaly

- [ ] **AlertManager + webhooks**
  - [ ] Deploy AlertManager (docker-compose)
  - [ ] `server/alert_webhook.py` — Slack formatter
  - [ ] Route alerts to lab ops Slack channel
  - [ ] Test alert: manually trigger high temp (synthetic data)

- [ ] **Monthly export pipeline**
  - [ ] `scripts/export_training_data.py`
  - [ ] InfluxDB → Parquet conversion
  - [ ] Store in shared folder (NAS or S3)
  - [ ] Schedule: cron job on first day of month

### Week 8

**Monday-Wednesday**:
- [ ] **Dashboard refinement**
  - [ ] Add machine metadata (hardware, OS, IP)
  - [ ] Add decision history: last 10 decisions per machine
  - [ ] Add SLA tracking: uptime %, temp exceedances, lead time
  - [ ] Test performance: dashboard queries < 1s

- [ ] **Local HTML dashboard**
  - [ ] Update `Index.html` to link to central Grafana
  - [ ] Show fallback status (central server reachable? decision cache age?)
  - [ ] Keep as local read-only view

**Thursday-Friday**:
- [ ] **Success criteria (Phase 4)**
  - [ ] Grafana shows all 50 machines real-time ✓
  - [ ] Alerts working (tested with synthetic temp spike) ✓
  - [ ] Monthly Parquet export automated ✓
  - [ ] Dashboard latency < 1s ✓

- [ ] **Prepare for Phase 5**
  - [ ] Design resilience tests

---

## Phase 5: Graceful Degradation (Weeks 9-10)

### Week 9

**Monday-Wednesday**:
- [ ] **Agent-side fallback**
  - [ ] Extend `agents/policy_executor.py`
  - [ ] Implement decision cache (TTL 1s)
  - [ ] Escalate to PERFORMANCE if decision stale (> 2s)
  - [ ] Log fallback events → dashboard alerts

- [ ] **Central buffer for InfluxDB**
  - [ ] `server/decision_buffer.py`
  - [ ] Ring buffer: 10k decisions (100 seconds of decisions)
  - [ ] On InfluxDB unavailable: buffer in-memory
  - [ ] On InfluxDB back online: replay buffered decisions
  - [ ] Preserve timestamp order + deduplication

- [ ] **Inference fallback**
  - [ ] `server/inference_fallback.py`
  - [ ] Try/catch XGBoost errors
  - [ ] Fallback: CPU + GPU intensity → fan % heuristic
  - [ ] Log error, include in decision (confidence=0.50)

- [ ] **Write resilience test suite**
  - [ ] `tests/test_agent_fallback.py` — agent offline for 10 min, uses cache
  - [ ] `tests/test_central_buffer.py` — InfluxDB offline, buffer works
  - [ ] `tests/test_inference_fallback.py` — XGBoost error, heuristic works
  - [ ] `tests/test_network_jitter.py` — latency spike (> 5s), agent escalates

**Thursday-Friday**:
- [ ] **Run resilience tests**
  - [ ] Kill central server → agents use cache
  - [ ] Stop InfluxDB → central server buffers decisions
  - [ ] Simulate model error → fallback to heuristic
  - [ ] Introduce network delay → agents escalate correctly

- [ ] **Verify recovery**
  - [ ] Restart central server → agents reconnect within 5s
  - [ ] Restart InfluxDB → decisions replayed + no data loss
  - [ ] Recover from network issue → sync within 2s

### Week 10

**Monday-Wednesday**:
- [ ] **Load shedding in batch orchestrator**
  - [ ] If queue > 100 items: drop oldest, shift to single-machine inference
  - [ ] Increase inference SLA to 1s (acceptable)
  - [ ] Alert: "Load shedding active"

- [ ] **Network resilience in agents**
  - [ ] Exponential backoff: 100ms × 2^attempt, max 30s
  - [ ] Jitter: ±20ms random delay (avoid thundering herd)
  - [ ] Circuit breaker: 5 consecutive failures → 30s wait

- [ ] **Advanced failure scenarios**
  - [ ] Scenario: 10 machines offline for 1 hour
    - [ ] Verify: central server tracks offline machines
    - [ ] Verify: agents operate independently (PERFORMANCE mode)
    - [ ] Verify: telemetry buffered locally
    - [ ] Recovery: replay telemetry when back online

  - [ ] Scenario: Cascading failure (central → InfluxDB → Grafana down)
    - [ ] Agents still control fans (cached decisions)
    - [ ] AlertManager still fires (Prometheus independent)
    - [ ] Slack alerts still work

**Thursday-Friday**:
- [ ] **Success criteria (Phase 5)**
  - [ ] Agent offline for 10 min: uses cache, escalates to PERFORMANCE ✓
  - [ ] Central offline: InfluxDB buffers decisions ✓
  - [ ] Model error: fallback heuristic works ✓
  - [ ] All tests passing ✓

- [ ] **Prepare for Phase 6**
  - [ ] Set up monthly retraining pipeline

---

## Phase 6: Monitoring & Validation (Weeks 11-12)

### Week 11

**Monday-Wednesday**:
- [ ] **Offline replay script**
  - [ ] `scripts/replay_offline.py`
  - [ ] Consume Parquet export (30 days of data)
  - [ ] Re-run XGBoost + AnalyticGNN inference
  - [ ] Compare to live decisions (should match within 0.01 risk points)
  - [ ] Generate parity report: `offline_vs_live_parity.json`

- [ ] **Decision audit log**
  - [ ] Query InfluxDB for decisions where reason = "FAILSAFE"
  - [ ] For each failsafe: log context (temp, risk score, velocity)
  - [ ] Identify root causes (workload spike, sensor error, etc.)
  - [ ] Generate audit report: `failsafe_analysis.json`

- [ ] **Lead-time analysis**
  - [ ] Fix bug in `live_leadtime_monitor.py` (currently inflates over time)
  - [ ] Calculate: for each high-temp event, how much warning did model provide?
  - [ ] Metric: P50/P95 lead time in seconds
  - [ ] Dashboard panel: lead-time distribution

**Thursday-Friday**:
- [ ] **Model retraining pipeline**
  - [ ] `training/retrain_monthly.py`
  - [ ] Load 30-day Parquet export (all 50 machines)
  - [ ] Retrain XGBoost on new data
  - [ ] Validate on 20% holdout (random machines)
  - [ ] Compare accuracy: current vs. new model
  - [ ] Alert if accuracy drops > 5% (version mismatch)

- [ ] **First month of operation**
  - [ ] Run full system on all 50 machines
  - [ ] Collect data for 30 days
  - [ ] Export to Parquet (end of month)
  - [ ] Re-train on collected data

### Week 12

**Monday-Wednesday**:
- [ ] **Failure case analysis**
  - [ ] Query: decisions with low confidence (< 0.70)
  - [ ] Cluster by workload type (gaming, rendering, idle, mixed)
  - [ ] Cluster by hardware type (Lenovo, Dell, HP, Asus)
  - [ ] Cluster by time of day (peak vs. off-peak)
  - [ ] Generate report: `failure_case_analysis.json`
  - [ ] Identify 3-5 actionable improvements

- [ ] **Feature importance analysis**
  - [ ] Extract XGBoost feature importances
  - [ ] Identify which features most predictive (CPU, GPU, memory, I/O)
  - [ ] Consider: drop low-importance features in retraining
  - [ ] Report: `feature_importance.json`

- [ ] **Thermal model validation**
  - [ ] Compare predicted risk to actual temperature
  - [ ] Calculate: correlation between risk score and peak temp
  - [ ] For each machine: generate thermal model curve
  - [ ] Identify outliers (model mismatch)

**Thursday-Friday**:
- [ ] **Success criteria (Phase 6)**
  - [ ] Monthly Parquet exports contain clean data ✓
  - [ ] Offline replay parity > 99.5% ✓
  - [ ] Retraining pipeline automated ✓
  - [ ] Lead-time analysis shows median ≥ 10 seconds ✓
  - [ ] Failure case analysis identifies 3-5 improvements ✓

- [ ] **Final sign-off**
  - [ ] All 50 machines running for > 1 week
  - [ ] Zero unplanned escalations to PERFORMANCE
  - [ ] Dashboard showing real-time thermal state
  - [ ] Monthly retraining cycle established

---

## Beyond Phase 6: Future Enhancements (Optional)

- [ ] **Edge inference** (weeks 13-16)
  - [ ] Deploy ONNX model to agents
  - [ ] Agent-side inference for offline operation
  - [ ] Reduce latency to < 100ms

- [ ] **Hardware-specific models** (weeks 17-20)
  - [ ] Train separate models per hardware type (Lenovo vs. Dell)
  - [ ] Route telemetry to appropriate model
  - [ ] Improve accuracy on heterogeneous hardware

- [ ] **Predictive scaling** (weeks 21-24)
  - [ ] Forecast lab workload 5 minutes ahead
  - [ ] Pre-cool machines before spike
  - [ ] Reduce peak fan RPM

- [ ] **HA setup** (weeks 25-28)
  - [ ] Deploy 2+ central servers (load balanced)
  - [ ] Redis for distributed decision cache
  - [ ] Kubernetes for orchestration (optional)

---

## Key Success Metrics (Continuous)

- [ ] **Telemetry**
  - [ ] Collection latency: P95 < 1s ✓
  - [ ] Data loss: < 0.1% ✓
  - [ ] Agent uptime: > 99.5% ✓

- [ ] **Inference**
  - [ ] Batch latency: P95 < 200ms ✓
  - [ ] Model parity: offline vs live > 99.5% ✓
  - [ ] Inference failures: < 1 per 100k ✓

- [ ] **Thermal Control**
  - [ ] Peak temperature: < 85°C ✓
  - [ ] Avg temperature: < 55°C ✓
  - [ ] Throttling events: < 1/day ✓
  - [ ] Lead time: P50 ≥ 10 seconds ✓

- [ ] **Observability**
  - [ ] Dashboard latency: < 1s ✓
  - [ ] Alert accuracy: > 95% ✓
  - [ ] MTTR (mean time to recovery): < 5 min ✓

---

## Command Reference

**Deploy central server**:
```bash
cd /path/to/cooling-lab
docker-compose up -d
```

**Check central server health**:
```bash
curl http://localhost:8000/health
```

**View decision cache**:
```bash
curl http://localhost:8001/decision/all?format=compact
```

**View InfluxDB data**:
```bash
influx query 'from(bucket:"cooling_lab") |> range(start:-7d) |> filter(fn:(r) => r._measurement == "telemetry")'
```

**View Prometheus metrics**:
```bash
curl http://localhost:9090/api/v1/query?query=up
```

**View Grafana dashboard**:
```bash
Open browser: http://localhost:3000
Login: admin / admin
Go to Dashboards → Cooling Lab Dashboard
```

**Check agent status (Linux)**:
```bash
systemctl status cooling-agent
systemctl logs -n 100 cooling-agent
```

**Check agent status (macOS)**:
```bash
launchctl list | grep cooling
log stream --predicate 'process == "cooling-agent"'
```

**Check agent status (Windows)**:
```powershell
Get-ScheduledTask -TaskName CoolingAgent | Select-Object State
Get-ScheduledTaskInfo -TaskName CoolingAgent
```

---

**Document Version**: 1.0  
**Last Updated**: 2026-06-25  
**Next Review**: End of Week 2  
**Owner**: System Architecture Team
