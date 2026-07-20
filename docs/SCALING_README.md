# Scaling Plan Documentation Index

This directory contains a complete, step-by-step implementation plan to scale the predictive cooling system from a single Lenovo Legion laptop to 50 lab computers.

## Quick Start

**New to this plan?** Start here:
1. Read **SCALING_EXECUTIVE_SUMMARY.md** (20 min) — high-level overview
2. Skim **SCALING_DECISION_TREE.md** (10 min) — architecture decisions
3. Review **SCALING_QUICK_START.md** (15 min) — week-by-week checklist

**Ready to implement?** Use:
- **SCALING_QUICK_START.md** as your daily sprint guide
- **SCALING_IMPLEMENTATION_PLAN.md** as your detailed reference
- **SCALING_ARCHITECTURE_DIAGRAM.md** for technical deep-dives

---

## Document Overview

### 1. SCALING_EXECUTIVE_SUMMARY.md (16 KB, 20 min read)

**Audience**: Managers, stakeholders, tech leads

**Contains**:
- Problem statement & solution overview
- Key design decisions (push vs pull, central vs edge, etc.)
- 12-week implementation timeline
- Resource requirements (compute, storage, network)
- Success metrics & KPIs
- Risk mitigation strategies
- Go/no-go decision points

**Use when**: Presenting to stakeholders, planning budget, understanding trade-offs

---

### 2. SCALING_IMPLEMENTATION_PLAN.md (48 KB, detailed reference)

**Audience**: Engineers, architects

**Contains**:
- Part 1: Detailed decision matrix (7 sections, 20 pages)
  - Telemetry collection (push vs pull)
  - Inference orchestration (central vs edge)
  - Storage architecture (InfluxDB, Parquet, retention)
  - Actuation & hardware abstraction
  - Hardware abstraction & telemetry portability
  - Monitoring & observability
  - Graceful degradation strategy

- Part 2: Step-by-step roadmap (6 phases, 30 pages)
  - Phase 1: Centralize Telemetry (weeks 1-2)
  - Phase 2: Centralize Inference (weeks 3-4)
  - Phase 3: Edge Actuation (weeks 5-6)
  - Phase 4: Lab-wide Dashboard (weeks 7-8)
  - Phase 5: Graceful Degradation (weeks 9-10)
  - Phase 6: Monitoring & Validation (weeks 11-12)

- Part 3: Critical files & code artifacts (manifest)
- Part 4: Deployment & testing strategy
- Part 5: Data flow diagram (ASCII art)
- Part 6: Phased rollout strategy (pilot → ramp → full)
- Part 7: Configuration & secrets management
- Part 8: Success metrics
- Part 9: Known risks & mitigations
- Part 10: Future enhancements (edge inference, HA, K8s)

**Use when**: Planning implementation, understanding detailed architecture, resolving design questions

---

### 3. SCALING_ARCHITECTURE_DIAGRAM.md (50 KB, visual reference)

**Audience**: Engineers, architects, technical reviewers

**Contains**:
- Part 1: High-level system architecture (ASCII diagram, 100 lines)
- Part 2: Telemetry push flow per second (timeline)
- Part 3: Inference pipeline batched (100ms windows)
- Part 4: Decision polling by agents (200ms interval)
- Part 5: InfluxDB data model (schema, retention, cardinality)
- Part 6: API endpoints summary (FastAPI)
- Part 7: Fallback decision flow (central unavailable scenario)
- Part 8: Network topology (lab infrastructure)
- Part 9: Graceful degradation scenarios (6 failure modes)

**Use when**: Understanding data flow, designing APIs, debugging integration issues, explaining to team

---

### 4. SCALING_QUICK_START.md (21 KB, sprint guide)

**Audience**: Engineers, daily operations

**Contains**:
- Pre-Phase 0: Preparation checklist
- Phase 1-6: Week-by-week sprint plans
  - Monday-Friday tasks per week
  - File names to create
  - Testing/deployment steps
  - Success criteria per week

- Key success metrics (telemetry, inference, thermal, operational)
- Command reference (Docker, curl, systemctl, PowerShell)
- Go/no-go decision points per week

**Use when**: Daily stand-ups, weekly planning, tracking progress, testing

---

### 5. SCALING_DECISION_TREE.md (22 KB, quick reference)

**Audience**: Engineers, architects, decision makers

**Contains**:
- Architecture decision flowchart (7 major decisions)
  - Push vs Pull (telemetry collection)
  - Central vs Edge (inference)
  - JSON polling vs RPC (decision communication)
  - InfluxDB vs Prometheus (storage)
  - Graceful fallback vs Admin requirement
  - Fallback to heuristic vs Freeze decision
  - Heartbeat vs Last decision age (health check)

- Decision impact matrix (latency, complexity, robustness, scalability)
- File architecture summary (50 new files organized)
- Latency budget breakdown (200ms agent poll cycle)
- Weekly rhythm calendar
- One-page go/no-go checklist
- Day 1 deployment checklist (central server)

**Use when**: Reviewing architecture decisions, onboarding new team members, defending trade-offs

---

## How to Use These Documents

### For Project Managers
1. Read **SCALING_EXECUTIVE_SUMMARY.md** (20 min)
2. Skim **SCALING_QUICK_START.md** for timeline (10 min)
3. Share timeline + resource requirements with stakeholders
4. Use go/no-go gates in **SCALING_DECISION_TREE.md** for weekly tracking

### For Architects
1. Read **SCALING_IMPLEMENTATION_PLAN.md** (60 min)
2. Review **SCALING_ARCHITECTURE_DIAGRAM.md** for details (40 min)
3. Discuss trade-offs from **SCALING_DECISION_TREE.md** with team
4. Use decision matrix to justify design choices

### For Implementation Engineers
1. Read **SCALING_QUICK_START.md** (15 min)
2. Use as daily sprint guide, one phase at a time
3. Reference **SCALING_IMPLEMENTATION_PLAN.md** for detailed specs
4. Consult **SCALING_ARCHITECTURE_DIAGRAM.md** for API/data flow questions
5. Use **SCALING_DECISION_TREE.md** to understand why each decision was made

### For QA/Testers
1. Read **SCALING_QUICK_START.md** for test milestones
2. Use **SCALING_IMPLEMENTATION_PLAN.md** Part 4 (deployment & testing)
3. Reference **SCALING_ARCHITECTURE_DIAGRAM.md** Part 9 (failure scenarios)
4. Execute tests from **SCALING_QUICK_START.md** at each phase gate

### For Operations
1. Read **SCALING_QUICK_START.md** deployment checklist
2. Reference **SCALING_DECISION_TREE.md** for Day 1 central server setup
3. Use **SCALING_ARCHITECTURE_DIAGRAM.md** for understanding system topology
4. Monitor success metrics from **SCALING_EXECUTIVE_SUMMARY.md**

---

## Key Numbers at a Glance

### Timeline
- **Total**: 12 weeks (3 months)
- **Pilot**: Weeks 1-4 (5 machines)
- **Ramp**: Weeks 5-8 (15 machines)
- **Full deployment**: Weeks 9-12 (50 machines)

### Performance Targets
| Metric | Target | Critical? |
|--------|--------|-----------|
| Telemetry latency (collection → central) | < 1s P95 | Yes |
| Inference latency (100ms batch) | < 200ms P95 | Yes |
| Decision polling interval | 200ms | Yes |
| Total decision latency | < 300ms | Yes |
| Peak temperature (50 machines) | < 85°C | Yes |
| Model prediction lead time | ≥ 10s P50 | No (monitoring) |
| Dashboard query latency | < 1s | No (observability) |

### Resource Requirements
- **Central server**: 4 CPU, 16GB RAM, 500GB SSD (VM or on-prem)
- **Storage**: ~3GB/week (InfluxDB compressed)
- **Network**: < 1% of 1Gbps lab network
- **Cost**: ~$50-100/month cloud compute (optional)

### Code
- **New files**: ~50 (mostly < 200 LOC)
- **Modified files**: 6 (refactoring existing)
- **Total new LOC**: ~5,000 (moderate expansion)

---

## Phases Overview

### Phase 1: Centralize Telemetry (Weeks 1-2)
**Goal**: 50 agents pushing telemetry to central server every 5 seconds

**Files to create**: 9 (agents/ + server/ ingest)  
**Success gate**: 5 machines → server < 1s, zero data loss  
**Risk level**: Low

### Phase 2: Centralize Inference (Weeks 3-4)
**Goal**: Central server predicting risk for 50 machines every 100ms

**Files to create**: 5 (server/ inference)  
**Success gate**: P95 latency < 200ms, InfluxDB storing data  
**Risk level**: Low

### Phase 3: Edge Actuation (Weeks 5-6)
**Goal**: Agents fetching decisions, applying hardware-specific fan control

**Files to create**: 7 (drivers/ + agents/ execution)  
**Success gate**: Fan control working on Windows/Linux/macOS  
**Risk level**: Low-Medium

### Phase 4: Lab-wide Dashboard (Weeks 7-8)
**Goal**: Grafana showing thermal curves + alerts for all 50 machines

**Files to create**: 5 (server/ monitoring + scripts/)  
**Success gate**: Dashboard real-time, alerts working, exports automated  
**Risk level**: Low

### Phase 5: Graceful Degradation (Weeks 9-10)
**Goal**: System survives partial failures (central down, InfluxDB offline, network issues)

**Files to create**: 4 (server/ + tests/)  
**Success gate**: All resilience tests passing  
**Risk level**: Medium (complexity)

### Phase 6: Validation & Retraining (Weeks 11-12)
**Goal**: Model performing well on heterogeneous hardware, monthly retraining automated

**Files to create**: 3 (training/ + scripts/)  
**Success gate**: Offline parity > 99.5%, retraining automated  
**Risk level**: Low

---

## Critical Decisions & Rationale

| Decision | Why This? | Alternative | Trade-off |
|----------|-----------|------------|-----------|
| **Push telemetry** | Agents own retry/backoff, low central load | Pull (simpler agents) | Agents more complex |
| **Central inference** | Model consistency, easy to retrain | Edge (lower latency) | 100ms + network latency |
| **JSON polling** | Simple, cache-friendly, HTTP | RPC/gRPC (faster) | Slightly higher latency |
| **InfluxDB** | Time-series optimized, retention policies | Prometheus (metrics-only) | Extra storage complexity |
| **Graceful fallback** | Always operational, no admin required | Escalate always (simpler) | Less precise on failure |
| **Central server bottleneck** | Mitigated by batching, Gunicorn workers | Edge inference (future) | Initial latency added |

---

## Troubleshooting Guide

### Telemetry Collection Slow
**Symptom**: Telemetry arriving > 1 second after collection  
**Check**: 
1. Agent network connectivity (ping central server)
2. Batch size (should be 5) and interval (should be 5s)
3. Central server load (CPU, memory, disk I/O)
4. Firewall rules (HTTPS port 8000)

### Inference Latency High
**Symptom**: P95 latency > 300ms, decisions stale  
**Check**:
1. XGBoost model size (should load in < 1ms)
2. Feature preprocessing (should be < 20ms)
3. Batch window (should be 100ms, not longer)
4. Gunicorn workers (should be 4-8)
5. GPU availability (if using ONNX with GPU)

### Fan Control Not Working
**Symptom**: Agents poll decisions but fan doesn't change  
**Check**:
1. Hardware driver available (WMI, sysfs, IOKit)
2. Fallback fan curve engaged (if driver unavailable)
3. Fan control permissions (may need sudo for sysfs)
4. Decision cache (verify fresh decisions arriving)
5. Log files (agent logging)

### InfluxDB Disk Full
**Symptom**: Write errors, decisions not stored  
**Check**:
1. Retention policies (should auto-delete old data)
2. Cardinality (high cardinality = storage explosion)
3. Downsampling tasks (should be running)
4. Disk space (check `df -h`)
5. Manual cleanup: oldest data can be deleted

### Grafana Dashboard Slow
**Symptom**: Queries taking > 5 seconds  
**Check**:
1. InfluxDB query performance (test query directly)
2. Data cardinality (too many unique tag values?)
3. Time range (dashboard loading 1+ month of data?)
4. Aggregation functions (downsampling?)
5. Grafana refresh rate (lower refresh = less load)

---

## Glossary

| Term | Definition |
|------|-----------|
| **Agent** | Python process on each machine collecting telemetry + executing policies |
| **Central server** | Linux VM running inference + caching + orchestration |
| **Telemetry** | Raw metrics (CPU, GPU, memory, disk I/O, network I/O) collected every 1 second |
| **Decision** | Policy output (target fan %, mode, confidence) computed every 100ms |
| **Risk score** | XGBoost + AnalyticGNN prediction of thermal risk 30 seconds ahead |
| **Inference latency** | Time from batch accumulation to decision computation |
| **Decision latency** | Time from decision computation to agent receipt |
| **Actuation latency** | Time from decision receipt to fan control change |
| **InfluxDB** | Time-series database storing telemetry + decisions + alerts |
| **Parquet** | Columnar data format for exporting training data monthly |
| **Graceful fallback** | System degrades safely when components fail (no total loss) |
| **Heuristic fallback** | Intensity-based fan curve when XGBoost unavailable |
| **Decision cache** | In-memory storage of latest decision per machine |
| **TTL (Time-to-live)** | Cache validity period; decisions > TTL marked stale |

---

## FAQ

**Q: Can we run this on Kubernetes?**  
A: Yes, but not required for MVP. Docker-compose is sufficient for 50 machines. Plan K8s for Phase 7+ if scaling beyond 100 machines.

**Q: What if we can't get admin access?**  
A: Telemetry collection always works (psutil, WMI read-only, sysfs read-only). Fan control degrades to fallback curve (still thermal-driven, just less precise).

**Q: How much data do we store?**  
A: ~3GB per week (InfluxDB compressed). 7-day retention = ~3GB, 90-day hourly = ~100MB, monthly Parquet = ~5-10GB.

**Q: What if inference server crashes?**  
A: Agents use cached decisions for up to 1 second, then escalate to PERFORMANCE mode (safe default, 85% fan). No lost thermal control.

**Q: Can we update the model without restarting?**  
A: Yes, version inference models (cooling_model_v1.pkl, cooling_model_v2.pkl). Load new version in central server, agents continue using old decisions until new decisions arrive.

**Q: How do we handle new machines joining the lab?**  
A: New machine gets agent installed via systemd/launchd/Task Scheduler. First telemetry push auto-registers machine in central server. No manual configuration needed.

**Q: What's the maximum number of machines this architecture supports?**  
A: Central server can handle 50-100 machines easily (batching + Gunicorn workers). Beyond 100, consider edge inference or load balancing multiple central servers. InfluxDB cardinality will be the limiting factor.

---

## Contact & Support

- **Architecture Owner**: System Architecture Team
- **Implementation Lead**: [TBD]
- **Operations**: [TBD]
- **Questions**: See decision matrix in SCALING_IMPLEMENTATION_PLAN.md

---

## Document Status

| Document | Version | Date | Status |
|----------|---------|------|--------|
| SCALING_EXECUTIVE_SUMMARY.md | 1.0 | 2026-06-25 | Ready |
| SCALING_IMPLEMENTATION_PLAN.md | 1.0 | 2026-06-25 | Ready |
| SCALING_ARCHITECTURE_DIAGRAM.md | 1.0 | 2026-06-25 | Ready |
| SCALING_QUICK_START.md | 1.0 | 2026-06-25 | Ready |
| SCALING_DECISION_TREE.md | 1.0 | 2026-06-25 | Ready |
| SCALING_README.md | 1.0 | 2026-06-25 | Ready |

**Next Review**: End of Week 2 (Phase 1 completion)

---

## Quick Reference Card

```
START HERE:
1. SCALING_EXECUTIVE_SUMMARY.md (20 min) → understand problem + solution
2. SCALING_DECISION_TREE.md (10 min) → review architecture decisions
3. SCALING_QUICK_START.md (15 min) → start Phase 1

FOR IMPLEMENTATION:
- Reference SCALING_IMPLEMENTATION_PLAN.md (detailed specs)
- Consult SCALING_ARCHITECTURE_DIAGRAM.md (data flow, APIs)
- Use SCALING_QUICK_START.md (daily checklist)

FOR TROUBLESHOOTING:
- Check Troubleshooting Guide above
- Consult failure scenarios in SCALING_ARCHITECTURE_DIAGRAM.md Part 9
- Review graceful degradation in SCALING_IMPLEMENTATION_PLAN.md Part 1

GO/NO-GO GATES:
- Week 2: Telemetry < 1s ✓
- Week 4: Inference < 200ms ✓
- Week 6: Fan control working ✓
- Week 8: Dashboard live ✓
- Week 10: Resilience tested ✓
- Week 12: Model validated ✓
```

---

**How to navigate these documents**: All documents link to each other. Start with the EXECUTIVE_SUMMARY or DECISION_TREE, then dive into specific sections based on your role and needs.

Good luck with the scaling project!
