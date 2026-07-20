# Scaling Plan Executive Summary

## Problem Statement

Expand the predictive cooling system from a single Lenovo Legion laptop to 50 lab computers with heterogeneous hardware (Windows/Linux/macOS, Lenovo/Dell/HP/Asus, no admin access assumption). Maintain sub-second responsiveness per machine while enabling lab-wide observability.

## Solution Overview

**Architecture**: Hybrid push-pull telemetry + centralized inference + edge actuation

- **50 client agents** collect 1-second telemetry and push every 5 seconds
- **Central inference server** batches predictions (100ms windows, < 50ms latency)
- **Edge policy executors** fetch decisions every 200ms and apply hardware-specific fan control
- **Time-series database** (InfluxDB) stores all data for historical analysis and retraining
- **Lab-wide dashboard** (Grafana) provides real-time thermal visibility + alerts

## Key Design Decisions

| Decision | Rationale | Trade-Off |
|----------|-----------|-----------|
| **Agent push (not pull)** | Agents own telemetry responsibility; lower central server load | Agents must be more intelligent (retry logic, buffering) |
| **Central inference** | Single model ensures consistency; easier to manage and retrain | Adds latency (100ms window) and creates central bottleneck risk |
| **Edge actuation (JSON polling)** | No admin required for telemetry; flexible and resilient | Decision latency ~300ms (window + inference + fetch + control) |
| **InfluxDB time-series DB** | Optimized for 1-second granularity; native downsampling/retention | Storage overhead initially (~30GB raw, compresses to ~3GB per week) |
| **Graceful fallback on outages** | Agents cache decisions (offline for 1+ hour); heuristic fallback for model errors | System degrades gracefully but less optimally |
| **No admin assumption** | Broad hardware support (non-Lenovo, Linux, macOS) | Fallback fan curves less precise than hardware-specific control |

## Implementation Timeline

**Total**: 12 weeks (3 months)

| Phase | Duration | Scope | Success Metric |
|-------|----------|-------|----------------|
| **1: Telemetry** | Weeks 1-2 | Centralize collection (5 pilots) | 5 machines → server < 1s, zero data loss |
| **2: Inference** | Weeks 3-4 | Central inference service (5 pilots) | P95 latency < 200ms, 50 decisions/batch |
| **3: Actuation** | Weeks 5-6 | Edge fan control (all OSes) | Fan changes within 500ms on all platforms |
| **4: Dashboard** | Weeks 7-8 | Grafana + alerts + exports | Real-time 50-machine view, alerts working |
| **5: Resilience** | Weeks 9-10 | Graceful degradation testing | All failure scenarios handled |
| **6: Validation** | Weeks 11-12 | Model retraining + audit | 99.5% parity, monthly retraining automated |

## Architecture Highlights

### Data Flow (Per 200ms Agent Poll)

```
Agent (t=5200ms):
  Fetch /decision/{machine_id}
    ↓
  Central Server (t=5100ms):
    Batch accumulated telemetry (50 machines)
    ↓
    Inference Service (t=5050ms):
      XGBoost (2ms) + AnalyticGNN (0.5ms) → risk scores
    ↓
    Policy Engine (t=5030ms):
      Compute per-machine decisions → cache
    ↓
    InfluxDB Client:
      Write async (non-blocking)
    ↓
  Agent (t=5200ms):
    Apply fan control (50-100ms)
    Log decision (10ms)
    Cache for fallback (1ms)
```

**Total latency**: ~150-200ms (telemetry age + inference + fetch + control)

### Network Load

```
Worst case: 50 machines × 10 Hz = 500 decisions/sec
  ├─ Telemetry ingestion: ~50 requests/5sec = 10 Hz at server
  ├─ Decision polling: ~50 machines × 5 Hz = 250 Hz (very low bandwidth)
  ├─ InfluxDB writes: ~500 points/sec batched = acceptable
  └─ Network utilization: < 1% (LAN 1Gbps)

Best case: 50 machines × 1 Hz = 50 decisions/sec
  (steady state, no workload spikes)
```

## Critical Files to Create

### Phase 1: Telemetry (6 files)
```
agents/
  ├─ telemetry_agent.py           (main entry point)
  ├─ telemetry_collector.py       (refactored from src/telemetry_logger.py)
  ├─ hardware_detector.py         (machine ID, HW info)
  ├─ agent_config.json            (config template)
  ├─ install_systemd.sh           (Linux deploy)
  ├─ install_launchd.sh           (macOS deploy)
  └─ install_windows_task.ps1     (Windows deploy)

server/
  ├─ telemetry_ingest.py          (FastAPI POST /ingest endpoint)
  └─ docker-compose.yml           (InfluxDB stack)
```

### Phase 2: Inference (4 files)
```
server/
  ├─ inference_service.py         (FastAPI model serving)
  ├─ batch_orchestrator.py        (accumulate + batch)
  ├─ central_policy_engine.py     (50× CoolingPolicyEngine)
  ├─ decision_cache.py            (in-memory cache)
  └─ influxdb_client.py           (async batch writer)
```

### Phase 3: Actuation (7 files)
```
agents/
  ├─ policy_executor.py           (fetch + apply decisions)
  ├─ fallback_decision.py         (cache + TTL)
  └─ network_retry_policy.py      (backoff logic)

drivers/
  ├─ fan_controller_base.py       (abstract interface)
  ├─ fan_controller_linux.py      (sysfs PWM)
  ├─ fan_controller_windows.py    (WMI + PowerShell)
  ├─ fan_controller_macos.py      (IOKit)
  └─ fallback_fan_curve.py        (intensity-based)
```

### Phase 4: Dashboard (5 files)
```
server/
  ├─ alert_webhook.py             (Prometheus → Slack)
  ├─ grafana_dashboard.json       (50-machine dashboard)
  ├─ prometheus_rules.yaml        (alert rules)
  └─ export_pipeline.py           (InfluxDB → Parquet)

scripts/
  └─ export_training_data.py      (manual trigger)
```

### Phase 5-6: Resilience + Monitoring (8 files)
```
server/
  ├─ decision_buffer.py           (ring buffer for InfluxDB outages)
  └─ inference_fallback.py        (heuristic fallback)

tests/
  ├─ test_agent_fallback.py       (offline scenario)
  ├─ test_central_buffer.py       (InfluxDB outage)
  ├─ test_inference_fallback.py   (model error)
  └─ test_network_jitter.py       (latency spikes)

scripts/
  ├─ replay_offline.py            (offline inference validation)
  ├─ decision_audit_log.py        (anomaly investigation)
  └─ lead_time_analysis.py        (warning time tracking)

training/
  └─ retrain_monthly.py           (monthly retraining)
```

**Total: ~50 new files** (most are < 200 LOC, a few > 500 LOC)

## Graceful Degradation Guarantees

| Failure | Duration | Behavior | Recovery |
|---------|----------|----------|----------|
| Central server down | 1-10 min | Agents use cached decisions (PERFORMANCE escalation) | Auto-reconnect within 5s of server recovery |
| InfluxDB offline | 1-60 min | Decisions buffered in-memory (10k capacity = 100s) | Replay on recovery, zero data loss |
| Network latency spike | 5+ sec | Agent decision cache marked stale, escalate to PERFORMANCE | Auto-recover when latency normalizes |
| Model inference error | 1+ min | Fallback to intensity-based heuristic (CPU+GPU→fan%) | Auto-recover on upstream fix |
| 10 machines offline | 1+ hour | Machines operate independently with cached decisions | Auto-resync on network recovery |
| Prometheus/Grafana down | 1+ min | Dashboard offline, but Slack alerts still work | Auto-recover on restart |

**Key principle**: Agents always have a decision (cached or escalated). Never lose control of fans.

## Success Metrics (Target)

### Telemetry
- Collection latency: P95 < 1 second ✓
- Data loss: < 0.1% ✓
- Agent uptime: > 99.5% ✓

### Inference
- Batch latency: P95 < 200ms ✓
- Offline replay parity: > 99.5% ✓
- Inference failures: < 1 per 100,000 predictions ✓

### Thermal Control
- Peak temperature: < 85°C (50-machine lab) ✓
- Average temperature: < 55°C ✓
- Throttling events: < 1 per machine per day ✓
- Failsafe triggers: < 10 per day lab-wide ✓
- Prediction lead time: P50 ≥ 10 seconds ✓

### Operational
- Deployment time: < 30 min per machine ✓
- Mean time to recovery: < 5 minutes ✓
- Dashboard query latency: < 1 second ✓
- Alert accuracy: > 95% (no false positives) ✓

## Resource Requirements

### Central Server
- **Compute**: 4 CPU, 16GB RAM (adequate for 50 machines)
- **Storage**: 500GB SSD (for InfluxDB + logs + Parquet exports)
- **Network**: 1Gbps Ethernet (lab network)
- **Cost**: ~$50-100/month (cloud VM or on-prem)

### Storage
- **Raw telemetry (1s, 7 days)**: ~3GB (compressed)
- **Hourly aggregates (90 days)**: ~100MB
- **Daily aggregates (1 year)**: ~10MB
- **Monthly Parquet exports**: ~5-10GB per month
- **Total steady-state**: ~10-15GB

### Network
- **Peak bandwidth**: 50 machines × 10 Hz × 1KB = 500KB/s < 1% of 1Gbps
- **Polling interval**: agents poll every 200ms (8 requests/machine/sec, very efficient)
- **Telemetry batch**: 5 points every 5 seconds (1KB/machine total)

## Known Limitations & Future Work

### Current Scope
✓ Push-based telemetry (agents report, not pulled)
✓ Central inference (single server, one model)
✓ JSON polling (simple, no RPC complexity)
✓ Graceful fallback (heuristic, cached decisions)
✓ Manual deployment (no k8s orchestration yet)

### Future Enhancements (Post-Launch)
- **Edge inference**: Deploy ONNX model to agents (< 100ms latency)
- **Hardware-specific models**: Separate models per hardware type
- **Predictive workload scaling**: Forecast lab load 5 minutes ahead
- **HA setup**: 2+ central servers with load balancing
- **Kubernetes**: Full orchestration if scaling beyond 50 machines
- **Machine learning retraining**: Monthly automated updates on collected data

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| Central server bottleneck | Medium | High inference latency | Batch optimization, load shedding, monitoring |
| Model accuracy drop | Low | Poor thermal control | Monthly retraining, offline validation, fallback heuristic |
| Network partitioning | Low | Machines offline, escalate to PERFORMANCE | Graceful fallback, cache decisions, alert operators |
| InfluxDB cardinality explosion | Very low | Slow queries, retention failure | Time-based sharding, metric aggregation, monitoring |
| Admin access not available | Medium | Can't control fan on some machines | Fallback intensity curve (still telemetry-driven) |

## Deployment Phases

### Phase 1-2: Pilot (Week 1-4)
- **Machines**: 5 (mixed OS, hardware)
- **Goal**: Validate architecture without scale
- **Risk**: Low (isolated pilots, can rollback easily)
- **Success gate**: Telemetry + inference working 48 hours stable

### Phase 3-4: Ramp (Week 5-8)
- **Machines**: 15 (add 10 more, diverse hardware)
- **Goal**: Validate scalability, latency, alerts
- **Risk**: Low-medium (agents learning, inference optimizing)
- **Success gate**: P95 latency < 200ms, no cascading failures

### Phase 5-6: Full Rollout (Week 9-12)
- **Machines**: 50 (all lab machines)
- **Goal**: Full-scale operation, resilience testing, model validation
- **Risk**: Low (all components tested, fallback proven)
- **Success gate**: 50 machines stable > 1 week, monthly retraining launched

## Recommendations

1. **Start with Phase 1-2 in parallel** (weeks 1-4): Get telemetry + inference working on 5 pilots. This proves the architecture works before scaling.

2. **Use managed InfluxDB** (if available): Reduce operational burden. Time-series databases are not trivial to manage (compaction, retention, replication).

3. **Monitor inference latency religiously**: P95 < 200ms is critical. If it drifts above 200ms, investigate immediately (CPU saturation, model size, feature engineering).

4. **Test graceful fallback aggressively** (Phase 5): Kill the central server, crash InfluxDB, introduce network latency. Verify agents never lose control of fans.

5. **Plan for monthly model retraining** from day one: Set up the data export + validation pipeline in Phase 4. This is required for long-term accuracy on heterogeneous hardware.

6. **Invest in agent robustness**: Agents are on 50 machines. A single crash in agent code can affect 50% of your thermal control. Test thoroughly.

7. **Use self-signed HTTPS** (or internal CA): Don't skip security. Certificate pinning optional for MVP.

## Success Criteria (Go/No-Go Decision Points)

**Week 2**: 5 machines streaming telemetry to central server < 1s
- Go: Proceed to Phase 2
- No-go: Debug telemetry pipeline, retry week 3

**Week 4**: Inference service computing decisions < 200ms P95
- Go: Proceed to Phase 3
- No-go: Optimize batch inference (profile, GPU, model size)

**Week 6**: Fan control working on all OSes (Windows/Linux/macOS)
- Go: Proceed to Phase 4
- No-go: Debug hardware abstraction, OS-specific drivers

**Week 8**: Grafana dashboard showing all 50 machines in real-time
- Go: Proceed to Phase 5
- No-go: Optimize InfluxDB queries, troubleshoot Prometheus scrape

**Week 10**: All resilience tests passing (central down, InfluxDB down, etc.)
- Go: Proceed to Phase 6
- No-go: Fix graceful degradation logic, retry tests

**Week 12**: Monthly retraining automated, 99.5% offline parity
- Go: Full launch, ongoing monitoring
- No-go: Debug model, investigate parity loss

---

## Documentation Provided

1. **SCALING_IMPLEMENTATION_PLAN.md** (70 pages)
   - Complete architecture design
   - Step-by-step 6-phase plan
   - Critical file manifest
   - Data flow diagrams
   - Graceful degradation scenarios

2. **SCALING_ARCHITECTURE_DIAGRAM.md** (50 pages)
   - High-level system architecture
   - Telemetry push flow (per second)
   - Inference pipeline (batched)
   - Decision polling (per agent)
   - InfluxDB schema
   - API endpoints
   - Fallback flows
   - Network topology

3. **SCALING_QUICK_START.md** (15 pages)
   - Week-by-week sprint checklist
   - Pre-phase 0 preparation
   - Daily tasks and milestones
   - Success criteria per week
   - Command reference

4. **SCALING_EXECUTIVE_SUMMARY.md** (this document)
   - High-level overview
   - Key decisions and trade-offs
   - Timeline and phases
   - Resource requirements
   - Success metrics
   - Risk mitigation

## Next Steps

1. **Review** this executive summary with stakeholders (IT, ops, lab managers)
2. **Allocate resources** for Phase 1-2 pilot (engineering, lab access, central server VM)
3. **Prepare infrastructure** (central server, InfluxDB, HTTPS certificates)
4. **Start Phase 1** (weeks 1-2): telemetry collection on 5 pilots
5. **Weekly status meetings** to track progress against checklist
6. **Iterate** based on pilot feedback before scaling to 50 machines

---

## Questions & Clarifications

**Q: What if a machine doesn't have a GPU?**  
A: `psutil` and WMI/sysfs handle missing GPU gracefully (zero or null values). Feature processor fills missing sensor data with defaults. Model still works.

**Q: What if we can't get admin access to some machines?**  
A: Telemetry collection works without admin (psutil, WMI read-only). Fan control degrades to fallback intensity curve (no HW access needed). System still operates, just less precisely.

**Q: What if the lab has poor WiFi connectivity?**  
A: Agents use exponential backoff + caching. Decisions cached locally for up to 1 second. If stale (> 2s), escalate to PERFORMANCE mode (safe default). No lost thermal control.

**Q: How do we prevent the central server from becoming a bottleneck?**  
A: Inference service is stateless + Gunicorn workers. Easy to scale to 8-16 workers. Batch orchestrator accumulates 100ms window (keeps load balanced). Monitor P95 latency.

**Q: Can we run this on Kubernetes?**  
A: Yes, but optional for MVP. Docker-compose is sufficient for 50 machines. K8s adds complexity (networking, storage, monitoring). Plan for Phase 7+ if scaling beyond 100 machines.

**Q: What's the fallback if InfluxDB fills up?**  
A: Retention policy auto-deletes oldest data (7 days raw, 90 days hourly, 1 year daily). Downsampling is automatic. If still full, manual purge can free space without losing recent decisions.

---

**Document Version**: 1.0  
**Date**: 2026-06-25  
**Status**: Ready for Stakeholder Review  
**Owner**: System Architecture Team  
**Next Review**: After Phase 1 (End of Week 2)
