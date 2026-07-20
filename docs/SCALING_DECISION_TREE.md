# Scaling Decision Tree: Quick Reference

## Architecture Decision Flowchart

```
QUESTION: How do we collect telemetry from 50 machines?
┌─────────────────────────────────────────────────────────────┐
│ Push (agents report) vs Pull (central scrapes)             │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ↓                                       ↓
   PUSH (✓)                            PULL
   - Agents own                        - Central scrapes
     retry/backoff                       periodically
   - Low central load                 - Simpler agents
   - Better agent offline             - Central bottleneck
     handling                          - Polling overhead
   - Resilient to network
     jitter
   
   DECISION: PUSH
   └─→ Each agent batches 5 telemetry points, sends every 5s
       with exponential backoff (max 30s wait)
```

```
QUESTION: Where do we run inference (XGBoost + GNN)?
┌─────────────────────────────────────────────────────────────┐
│ Central (one model) vs Edge (50 copies) vs Hybrid          │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ↓                   ↓                   ↓
   CENTRAL (✓)         EDGE                 HYBRID
   - Single model      - 50 agents run       - Future option
   - Easy to update      locally             - Trade latency
   - Model consistency - ~100ms latency       for consistency
   - Requires central  - Deployment
     server              complex
   - Latency: 200ms    - Hard to update
   - Bottleneck risk     models
   
   DECISION: CENTRAL (now), plan EDGE (later)
   └─→ Central inference service, 4-8 Gunicorn workers
       Batch every 100ms (50 machines × 15 features)
       Plan ONNX deployment to edges for Phase 7+
```

```
QUESTION: How do we communicate decisions from central to agents?
┌─────────────────────────────────────────────────────────────┐
│ JSON polling vs RPC vs Message Queue vs gRPC               │
└─────────────────────────────────────────────────────────────┘
                            │
   ┌────────┬────────┬──────┴──────┬─────────┐
   ↓        ↓        ↓             ↓         ↓
JSON       RPC      MQ          gRPC      MQTT
Polling    (X)      (X)          (X)       (X)
(✓)
- Simple    Complex  Complex     Complex  Complex
- No admin  Binary   Requires     Binary    Pub/sub
  needed    protocol  broker      protocol  overhead
- Cacheable Tight    Reliable     Tight    Language
  locally   coupling delivery     coupling  agnostic
- Resilient Fast     Heavy        Fast     Good for
  (cache)   (ms)     overhead     (ms)     IoT
- HTTP GET Overkill  Overkill    Overkill Light
  stateless for       for this     weight?
          this        use case
  
   DECISION: JSON POLLING
   └─→ GET /decision/{machine_id} every 200ms
       Simple HTTP, easy to debug, cache-friendly
       Latency: 200ms agent poll + 1ms server lookup = 201ms
```

```
QUESTION: Where do we store historical data?
┌─────────────────────────────────────────────────────────────┐
│ InfluxDB vs Prometheus vs PostgreSQL vs Parquet CSV        │
└─────────────────────────────────────────────────────────────┘
                            │
   ┌──────────┬───────┬────┴───┬────────┐
   ↓          ↓       ↓        ↓        ↓
InfluxDB     Prom    PG    Parquet   CSV
(✓)          (X)     (X)    (✓ aux)  (X)
- Time-     Counter Series SQL     Simple
  series    only    store  export   but
  optimized               only      slow
- Native    No fine Full                No
  downsamp  granule ACID             time-
  -ling     storage            series
- Retention Built-in Tag  MVCC   Columnar,
  policies  scrape  support compressed
- Fast     interval Powerful
  queries   based   queries
- 50 mach  Good for Good for
  × 1s = metrics relational
  acceptable only data
  
   DECISION: InfluxDB (primary) + Parquet (exports)
   └─→ InfluxDB: real-time telemetry + decisions
       Retention: 7d raw (1s), 90d hourly, 1y daily
       Parquet: monthly exports for model retraining
```

```
QUESTION: How do we handle missing sensors / non-Lenovo hardware?
┌─────────────────────────────────────────────────────────────┐
│ Graceful fallback vs Admin requirement vs Ignore            │
└─────────────────────────────────────────────────────────────┘
                            │
   ┌──────────────────┬─────┴────────┬──────────────────┐
   ↓                  ↓              ↓                  ↓
Graceful         Require       Ignore    Hardcoded
Fallback (✓)     Admin (X)     (X)       Curve (✓ aux)
- Telemetry      Complex       Loss of   Simple fan curve
  still works    to maintain   visibility based on CPU+GPU
- Fan control    Operator      High risk intensity
  degrades to    training      of Fails
  fallback       Silent mode
  curve (CPU+GPU
  intensity)
- No admin
  needed
- Conservative
  (fan higher
  than optimal)
- Acceptable
  trade-off
  
   DECISION: Graceful Fallback + Fallback Fan Curve
   └─→ Telemetry: always works (psutil, WMI, sysfs read-only)
       Fan control: tries HW-specific → falls back to intensity curve
       No admin required, system stays online
```

```
QUESTION: What happens if central server is down for 10+ minutes?
┌─────────────────────────────────────────────────────────────┐
│ Escalate to max fan vs Cache decisions vs Both (✓)         │
└─────────────────────────────────────────────────────────────┘
                            │
   ┌────────────┬──────────┬─────────────────┐
   ↓            ↓          ↓                 ↓
Escalate    Cache Only  Both (✓)       Aggressive
to Max      (1s TTL)    - Cache 1s       heuristic
(X)                     - Then escalate
- High      - Uses      - Balance:       - CPU usage
  acoustic    stale     ├─ first 1s:     escalates
- Wastes      decision    normal          too quickly
  energy      ├─ 1-2s:
- Dangerous    escalate
  if wrong      ├─ 2-5s:
- Not          escalate
  responsive   ├─ 5+ min:
  to changes     escalate
- Acceptable  - Fallback
  safe        heuristic
  default     kicks in
  
   DECISION: Cache (1s) + Escalate (> 2s)
   └─→ Agents cache last decision (TTL 1s)
       If central unavailable > 2s: escalate to PERFORMANCE (85% fan)
       Conservative but safe, preserves thermal control
```

```
QUESTION: What if the model crashes or returns NaN?
┌─────────────────────────────────────────────────────────────┐
│ Fallback heuristic vs Freeze decision vs Manual             │
└─────────────────────────────────────────────────────────────┘
                            │
   ┌──────────────────┬─────┴────────┬──────────────┐
   ↓                  ↓              ↓              ↓
Heuristic (✓)    Freeze (X)    Manual (X)    Alarm Only
- CPU + GPU      - Uses last   - Operator   - Hope
  intensity      good decision  controls    someone
  → fan %        - Stale,      fans          notices
- Always works   not optimal   - Slow
- Conservative   for changing  response
  (fan higher)   workload     - Not
- Detectable     - May miss    scalable
  failure        spike
  (log error)
- Automatic
  recovery
  (when model
  fixed)
  
   DECISION: Fallback Heuristic + Logging
   └─→ Try/catch XGBoost errors
       On failure: use (CPU + GPU) / 2 → fan %
       Log error + alert (low confidence decision)
       Auto-recovery when model fixed
```

```
QUESTION: How do we know if agents are still online?
┌─────────────────────────────────────────────────────────────┐
│ Heartbeat vs Last decision age vs Telemetry lag             │
└─────────────────────────────────────────────────────────────┘
                            │
   ┌──────────────┬────────┬─────────────────┐
   ↓              ↓        ↓                 ↓
Heartbeat   Last Decision Telemetry Lag  Dashboard
(X)         (✓)           (✓)             Manual
- Extra     - If agent    - If telemetry  - Operator
  message    polling      hasn't          monitoring
  per agent  but can't    arrived in      - High MTTR
- Complex   reconnect,    1 minute, agent
  fallback  we know       is offline
- Adds      it's alive    - Simple to
  traffic   - Uses        implement
            existing      - Reliable
            polling       signal
            - No extra
            overhead
  
   DECISION: Last decision age + Telemetry lag
   └─→ Monitor: age of last decision + age of last telemetry
       If both > 1 min: mark machine offline in dashboard
       Alert: "machine_X offline for 5+ min"
       No heartbeat messages needed
```

---

## Decision Impact Matrix

| Decision | Latency | Complexity | Robustness | Scalability |
|----------|---------|-----------|-----------|------------|
| Push (agents) | Low (batched) | Medium | High (offline handling) | Excellent (50→500) |
| Central inference | Medium (100ms) | Low | Medium (single point of failure) | Good (batching) |
| JSON polling | Medium (200ms) | Low | High (cacheable) | Excellent (HTTP) |
| InfluxDB | Fast (< 1s queries) | Medium (retention) | High (persistent) | Good (retention policy) |
| Graceful fallback | N/A | Medium | High (always operational) | Excellent (no admin) |
| Fallback heuristic | Very fast (< 1ms) | Low | Medium (less optimal) | Excellent (no ML) |

---

## File Architecture Summary

```
src/ (existing, core logic — KEEP)
├─ telemetry_logger.py           (single-machine collection)
├─ inference.py                  (single-machine inference loop)
├─ features.py                   (feature engineering SSoT)
├─ thermal_mode_controller.py    (policy engine)
├─ fan_controller.py             (hardware abstraction)
└─ constants.py                  (shared constants)

agents/ (NEW, per-machine agents)
├─ telemetry_agent.py            (main entry point per machine)
├─ telemetry_collector.py        (refactored from src/)
├─ hardware_detector.py          (machine ID + HW info)
├─ policy_executor.py            (fetch decisions, apply control)
├─ fallback_decision.py          (offline cache + TTL)
├─ network_retry_policy.py       (backoff + jitter)
├─ agent_config.json             (config template)
├─ install_systemd.sh            (Linux deploy)
├─ install_launchd.sh            (macOS deploy)
└─ install_windows_task.ps1      (Windows deploy)

drivers/ (NEW, hardware-specific)
├─ fan_controller_base.py        (abstract interface)
├─ fan_controller_linux.py       (sysfs PWM)
├─ fan_controller_windows.py     (WMI + PowerShell)
├─ fan_controller_macos.py       (IOKit / system_profiler)
├─ fallback_fan_curve.py         (intensity-based)
├─ telemetry_reader_linux.py     (sysfs temp reading)
├─ telemetry_reader_windows.py   (WMI temp reading)
└─ telemetry_reader_macos.py     (IOKit temp reading)

server/ (NEW, central server)
├─ telemetry_ingest.py           (FastAPI POST /ingest)
├─ batch_orchestrator.py         (accumulate + batch)
├─ inference_service.py          (FastAPI model serving)
├─ central_policy_engine.py      (50× CoolingPolicyEngine)
├─ decision_cache.py             (in-memory cache)
├─ decision_buffer.py            (ring buffer for InfluxDB outages)
├─ influxdb_client.py            (async batch writer)
├─ inference_fallback.py         (heuristic fallback)
├─ alert_webhook.py              (Prometheus → Slack)
├─ export_pipeline.py            (InfluxDB → Parquet)
├─ grafana_dashboard.json        (50-machine dashboard)
├─ prometheus_rules.yaml         (alert rules)
├─ docker-compose.yml            (stack definition)
└─ .env.local                    (secrets, not committed)

scripts/ (NEW, utilities)
├─ export_training_data.py       (manual InfluxDB → Parquet)
├─ replay_offline.py             (validate offline parity)
├─ decision_audit_log.py         (find anomalies)
├─ lead_time_analysis.py         (warning time tracking)
├─ monitor_inference.py          (latency monitoring)
└─ deploy_grafana.sh             (bootstrap)

training/ (NEW, monthly retraining)
├─ retrain_monthly.py            (consume Parquet, retrain)
├─ validate_parity.py            (offline vs live)
└─ failure_case_analysis.py      (cluster root causes)

tests/ (NEW, resilience)
├─ test_agent_fallback.py        (offline 10+ min)
├─ test_central_buffer.py        (InfluxDB outage)
├─ test_inference_fallback.py    (model error)
└─ test_network_jitter.py        (latency spike)

docs/ (NEW, scaling documentation)
├─ SCALING_IMPLEMENTATION_PLAN.md        (70 pages)
├─ SCALING_ARCHITECTURE_DIAGRAM.md       (50 pages)
├─ SCALING_QUICK_START.md                (15 pages)
├─ SCALING_EXECUTIVE_SUMMARY.md          (20 pages)
└─ SCALING_DECISION_TREE.md              (this file)
```

---

## Latency Budget (200ms Agent Poll Cycle)

```
Timeline:
t=0ms:     Agent starts polling /decision/{machine_id}
t=1ms:     Network: DNS + TCP connection (local LAN: ~1ms)
t=5ms:     HTTP request arrives at central server
t=5-100ms: Central server processing
           ├─ Batch accumulated telemetry (50 points): ~10ms
           ├─ Inference (XGBoost + GNN): ~2-50ms (varies)
           ├─ Policy engine (50 machines): ~20ms
           ├─ Decision cache update: ~1ms
           └─ InfluxDB write (async, non-blocking): ~0ms
t=100ms:   HTTP response sent from server
t=101ms:   Network: response travels back to agent (~1ms)
t=102ms:   Agent receives decision JSON
t=102-110ms: Agent processing
           ├─ Parse JSON: ~1ms
           ├─ Validate decision: ~1ms
           ├─ Apply fan control (OS call): ~5-10ms
           └─ Log locally: ~1ms
t=110-115ms: Total latency from telemetry age to control

Actual: ~115ms (well under 200ms poll interval)
Buffer: 200ms - 115ms = 85ms cushion for network jitter

Worst case (inference slow):
  t=0-50ms: inference latency spike (GPU busy)
  t=50-100ms: policy + cache
  t=100-105ms: network + client
  TOTAL: ~155ms (still < 200ms)
```

---

## Weekly Rhythm

```
WEEKS 1-2 (PHASE 1: TELEMETRY)
Monday:    Code telemetry_collector.py + hardware_detector.py
Tuesday:   Code agent_config.json + install scripts
Wednesday: Deploy to 2 machines, test collection latency
Thursday:  Debug schema + network issues
Friday:    Deploy to 5 machines, verify zero data loss

WEEKS 3-4 (PHASE 2: INFERENCE)
Monday:    Code inference_service.py + batch_orchestrator.py
Tuesday:   Code central_policy_engine.py + decision_cache.py
Wednesday: Integrate InfluxDB, test inference latency
Thursday:  Tune batch window (100ms), monitor P95
Friday:    Full integration test (telemetry → inference → decisions)

WEEKS 5-6 (PHASE 3: ACTUATION)
Monday:    Code fan_controller_base.py + OS-specific drivers
Tuesday:   Code policy_executor.py + fallback_decision.py
Wednesday: Test on Windows, Linux, macOS
Thursday:  Test non-Lenovo fallback curve, zero-admin mode
Friday:    Integration test (decision → fan control)

WEEKS 7-8 (PHASE 4: DASHBOARD)
Monday:    Code alert_webhook.py + prometheus_rules.yaml
Tuesday:   Code grafana_dashboard.json (50 subpanels)
Wednesday: Deploy Prometheus + Grafana stack
Thursday:  Test dashboard queries (< 1s), verify alerts
Friday:    Test monthly export pipeline (InfluxDB → Parquet)

WEEKS 9-10 (PHASE 5: RESILIENCE)
Monday:    Code decision_buffer.py + inference_fallback.py
Tuesday:   Code resilience tests (4 scenarios)
Wednesday: Run tests: central down, InfluxDB down, model error, network jitter
Thursday:  Debug failures, improve fallback logic
Friday:    All tests passing, document recovery SLAs

WEEKS 11-12 (PHASE 6: VALIDATION)
Monday:    Code replay_offline.py + retrain_monthly.py
Tuesday:   Run monthly retraining on collected 30-day data
Wednesday: Validate offline parity (> 99.5%)
Thursday:  Code decision_audit_log.py + failure_case_analysis.py
Friday:    Final sign-off, prepare for production monitoring
```

---

## One-Page Checklist: Go/No-Go Decision Points

```
✓ WEEK 2 Go-Gate: Telemetry Working
  ├─ [ ] 5 machines streaming to central < 1s ✓
  ├─ [ ] Zero data loss for 2-hour run ✓
  ├─ [ ] Agent restart works (systemd/launchd/Task Scheduler) ✓
  ├─ [ ] Network dropout recovery works ✓
  └─ Decision: [GO / NO-GO]

✓ WEEK 4 Go-Gate: Inference Working
  ├─ [ ] Central server running, loaded with models ✓
  ├─ [ ] POST /predict returns risk scores < 50ms ✓
  ├─ [ ] P95 latency < 200ms (100ms window + 50ms compute + network) ✓
  ├─ [ ] InfluxDB receiving telemetry + decisions ✓
  └─ Decision: [GO / NO-GO]

✓ WEEK 6 Go-Gate: Fan Control Working
  ├─ [ ] GET /decision/{machine_id} working ✓
  ├─ [ ] Fan % changes on Windows (WMI / PowerShell) ✓
  ├─ [ ] Fan % changes on Linux (sysfs) ✓
  ├─ [ ] Fan % changes on macOS (IOKit) ✓
  ├─ [ ] Fallback fan curve works on non-Lenovo ✓
  ├─ [ ] Zero admin access required for telemetry ✓
  └─ Decision: [GO / NO-GO]

✓ WEEK 8 Go-Gate: Dashboard Working
  ├─ [ ] Grafana showing all 50 machines real-time ✓
  ├─ [ ] Thermal curves updating every 5s ✓
  ├─ [ ] Alerts triggering correctly (high temp, offline, error) ✓
  ├─ [ ] Dashboard query latency < 1s ✓
  └─ Decision: [GO / NO-GO]

✓ WEEK 10 Go-Gate: Resilience Tested
  ├─ [ ] Agent uses cache when central offline ✓
  ├─ [ ] Central buffers decisions when InfluxDB offline ✓
  ├─ [ ] Inference falls back to heuristic on model error ✓
  ├─ [ ] Agent escalates to PERFORMANCE when decision stale > 2s ✓
  ├─ [ ] Recovery works (reconnect, replay, resume) ✓
  └─ Decision: [GO / NO-GO]

✓ WEEK 12 Go-Gate: Model Validated
  ├─ [ ] Offline replay parity > 99.5% ✓
  ├─ [ ] Monthly retraining automated ✓
  ├─ [ ] Lead-time analysis shows P50 ≥ 10s ✓
  ├─ [ ] Failure case clustering identifies improvements ✓
  └─ Decision: [GO / PRODUCTION / NO-GO]
```

---

## Deployment Checklist: Day 1 (Central Server)

```
Infrastructure:
  [ ] Central server VM provisioned (4 CPU, 16GB RAM, 500GB SSD, Linux)
  [ ] Static IP assigned: 10.0.1.254 (or hostname: cooling-lab-server)
  [ ] SSH access verified
  [ ] Docker + Docker Compose installed
  [ ] HTTPS certificate generated (self-signed or internal CA)

Code:
  [ ] Central server code cloned (all server/*.py files)
  [ ] docker-compose.yml with InfluxDB, Prometheus, Grafana services
  [ ] .env.local populated with InfluxDB token, API keys (never commit)
  [ ] models/cooling_model.pkl present (XGBoost)
  [ ] models/preprocessor_state.pkl present (feature state)

Deployment:
  [ ] docker-compose up -d (start stack)
  [ ] curl http://localhost:8086/ping → 200 OK (InfluxDB)
  [ ] curl http://localhost:9090 → Prometheus UI
  [ ] curl http://localhost:3000 → Grafana UI (admin/admin)
  [ ] curl http://localhost:8000/health → inference service up

Testing:
  [ ] POST http://localhost:8000/ingest/test_machine with sample telemetry
  [ ] GET http://localhost:8001/decision/test_machine → decision returned
  [ ] Verify InfluxDB: SELECT * FROM telemetry LIMIT 10
  [ ] Verify Grafana can query InfluxDB
  [ ] Generate test alert (temp > 90C) → verify Prometheus triggers rule

Ready for agents!
```

---

**Quick Reference Version**: 1.0  
**Last Updated**: 2026-06-25  
**For**: Architecture Decisions & Implementation  
**Status**: Ready for Daily Use
