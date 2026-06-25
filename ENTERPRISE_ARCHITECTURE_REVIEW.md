# Enterprise Architecture Review: 50-Machine Scaling Plan
## Principal Systems Architect Assessment

**Date**: 2026-06-25  
**Review Scope**: Scaling from single-machine Lenovo Legion laptop to 50-machine university lab  
**Reviewer Lens**: AI-native distributed telemetry platform (Microsoft Azure / Google Cloud / NVIDIA)  
**Objective**: Identify architectural trade-offs, suggest improvements, minimize operational debt while preserving extensibility to 5,000+ machines  

---

## Executive Summary

The existing plan is **operationally pragmatic for a 50-machine pilot** but has **three critical architectural shortcomings** that will create technical debt at enterprise scale:

1. **Storage model is backwards**: PostgreSQL (transactional, ACID) should be the MVP database. InfluxDB should be deferred to Phase 4+ (when you have 500+ machines or need sub-second query latency). Current plan adds operational complexity for zero benefit in a 50-machine lab.

2. **Graph Neural Network is marginalized**: The GNN is coded as an auxiliary 25% weight in a fusion formula, not as a first-class spatial model. For 5,000+ machines distributed across racks/zones, the graph topology becomes critical. Build it correctly now (with proper adjacency definition, hot-swap capability) rather than refactoring later.

3. **MLOps lifecycle is missing**: No versioning, no A/B testing infrastructure, no canary deployment for models, no automated rollback. You'll retrain monthly but have no safe way to promote new models. This is fine for a lab, but the absence of the *structure* will cost 4+ weeks of engineering to bolt on at scale.

**Bottom Line**: The current plan works and is the right shape. Three specific areas need restructuring for enterprise readiness. Estimated effort: **1-2 weeks** of upfront design + implementation to fix these, then execute phases as planned.

---

## Part 1: Architectural Critique by Component

### 1. Storage Architecture — CRITICAL ISSUE

#### Current Design
```
Primary: InfluxDB (time-series optimized)
  - 7 days raw (1s interval) = ~30GB
  - 90 days hourly = ~1GB
  - Monthly exports to Parquet for retraining

Risk: Time-series DBs have operational complexity:
  - Cardinality management (50×N tags = explosion risk)
  - Compaction tuning (affects query latency)
  - Retention policy scheduling (downsampling jobs)
  - No transactions (difficult to guarantee consistency)
  - Query language learning curve (InfluxQL, Flux differ)
```

#### Why This Is Suboptimal for 50-Machine MVP
1. **Operational burden**: InfluxDB requires tuning. For 50 machines, your bottleneck is **not query latency**—it's data delivery. You're inserting ~500 decisions/sec (trivial), not 1M/sec.
2. **Cardinality explosion risk**: InfluxDB penalizes unbounded tags. With 50 machines × 10+ tag dimensions (machine_id, os, hardware_hash, zone, rack, etc.), you'll hit cardinality limits around machine 100.
3. **No transactions**: If InfluxDB crashes during a write, you lose a batch. PostgreSQL ACID guarantees let you replay without data loss.
4. **Query complexity**: Grafana + InfluxDB queries are less powerful than SQL. Complex incident analysis (e.g., "show me all FAILSAFE decisions on AMD machines during load spikes") requires InfluxQL gymnastics.

#### Improved Design (Enterprise Ready)

**Phase 1-3 (Weeks 1-8, MVP): PostgreSQL**
```sql
CREATE TABLE telemetry (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  os TEXT,
  hardware_hash TEXT,
  recorded_at TIMESTAMP NOT NULL,
  
  -- Raw metrics
  cpu FLOAT NOT NULL,
  gpu FLOAT,
  memory FLOAT NOT NULL,
  disk_io_bytes_per_sec INTEGER,
  network_io_bytes_per_sec INTEGER,
  
  -- Computed features (15-dim vector)
  feature_vector NUMERIC[] NOT NULL,  -- PostgreSQL native array type
  
  CONSTRAINT telemetry_pkey PRIMARY KEY (machine_id, recorded_at)
);

CREATE TABLE decisions (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  risk_score FLOAT NOT NULL,
  xgb_pred FLOAT NOT NULL,
  gnn_pred FLOAT NOT NULL,
  fused_score FLOAT NOT NULL,
  target_fan_pct INTEGER NOT NULL,
  mode TEXT NOT NULL,
  confidence FLOAT NOT NULL,
  policy_reason TEXT,
  inference_latency_ms INTEGER,
  
  CONSTRAINT decisions_pkey PRIMARY KEY (machine_id, recorded_at)
);

CREATE TABLE models (
  id SERIAL PRIMARY KEY,
  model_name TEXT NOT NULL,
  model_version TEXT NOT NULL,
  model_type TEXT NOT NULL,  -- 'xgboost', 'gnn'
  blob BYTEA NOT NULL,  -- pickle or ONNX
  created_at TIMESTAMP DEFAULT NOW(),
  promoted_to_production BOOLEAN DEFAULT FALSE,
  
  CONSTRAINT models_unique UNIQUE (model_name, model_version)
);

-- Indices for time-series queries
CREATE INDEX idx_telemetry_machine_time 
  ON telemetry (machine_id, recorded_at DESC);

CREATE INDEX idx_decisions_machine_time 
  ON decisions (machine_id, recorded_at DESC);

-- Partitioning for retention
-- In Phase 3, partition by week for automatic cleanup
ALTER TABLE telemetry PARTITION BY RANGE (recorded_at) ...
```

**Why PostgreSQL for MVP**:
- ✅ ACID transactions (if write fails, no data loss)
- ✅ Rich query language (SQL) for debugging & analysis
- ✅ No cardinality limits (add machine 1000 without schema changes)
- ✅ Mature, battle-tested (Stripe, GitHub use it for analytics)
- ✅ Single binary, easy to backup/restore
- ✅ Native JSON/array types for feature vectors
- ✅ Sufficient for 50 machines at 1s intervals (easily handles 500 writes/sec)
- ✅ Built-in partitioning for retention (automatic cleanup)

**Phase 4+ (After Pilot): Migrate to Hybrid**
```
PostgreSQL (warm, 30 days):
  - All telemetry + decisions (transactional)
  - All model versions + metadata
  - Audit logs

InfluxDB (cold, 2+ years):
  - Downsampled data (5min intervals)
  - Time-series analytics
  - Prometheus scrape target
  
TimescaleDB (optional, Phase 5):
  - PostgreSQL extension optimized for time-series
  - Enables InfluxDB-like compression
  - Keeps transactions, adds time-series performance
  
Parquet (export only):
  - Monthly snapshots for retraining
  - Immutable, compress to 10-20% of raw
  - Ideal for batch ML pipelines
```

#### Trade-Offs

| Aspect | PostgreSQL (MVP) | InfluxDB (Current Plan) | TimescaleDB (Phase 5) |
|--------|------------------|------------------------|------------------------|
| **Setup time** | 5 min | 10 min (Docker) | 5 min (extension) |
| **Query latency (100M rows)** | 100-500ms | 10-100ms | 10-50ms |
| **Cardinality limit** | None | 500M+ (then slows) | None |
| **Transactions** | ✅ Full ACID | ❌ None | ✅ Full ACID |
| **Backup/restore** | 1 command | Complex (snapshots) | 1 command |
| **Operational overhead** | Minimal | Medium (tuning) | Minimal |
| **Cost (AWS/GCP)** | $20/mo RDS | $50/mo managed InfluxDB | $20/mo RDS |
| **Suitable for 50 machines?** | **YES** | Overkill | Overkill |
| **Suitable for 5000 machines?** | Maybe (migrate Phase 4) | **YES** | **YES** |

#### Implementation Guidance

**MVP (Weeks 1-3): PostgreSQL only**
```python
# server/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(
    "postgresql://user:pass@localhost:5432/cooling_lab",
    pool_size=20,  # 50 machines → accept 20 concurrent connections
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Write telemetry
def write_telemetry_batch(session, machine_id, points):
    for p in points:
        session.add(Telemetry(
            machine_id=machine_id,
            recorded_at=datetime.fromisoformat(p['timestamp']),
            cpu=p['cpu'],
            gpu=p['gpu'],
            memory=p['memory'],
            feature_vector=p['features']  # 15-dim array
        ))
    session.commit()  # ACID guarantee
```

**Phase 4 (Week 8+): Add TimescaleDB**
```sql
-- Install TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Convert existing table to hypertable
SELECT create_hypertable('telemetry', 'recorded_at', if_not_exists => TRUE);

-- Automatic compression (compress data older than 7 days)
ALTER TABLE telemetry SET (
  timescaledb.compress = true,
  timescaledb.compress_segmentby = 'machine_id'
);

-- Query now gets InfluxDB-like speed with PostgreSQL safety
```

**Phase 5 (Week 12+): Archive to InfluxDB**
```python
# scripts/archive_to_influxdb.py
# Run nightly: export 30-day-old data to InfluxDB
# Keep warm data in PostgreSQL (transactional)
```

#### Decision: **IMPLEMENT**
- **MVP** (This week): PostgreSQL, skip InfluxDB setup
- **Phase 4** (Week 8): Add TimescaleDB extension (1-hour change)
- **Phase 5** (Week 12+): Archive cold data to InfluxDB if needed

**Savings**: 2-3 weeks of InfluxDB tuning/debugging deferred until you actually need sub-100ms query latency.

---

### 2. Graph Neural Network Architecture — CRITICAL ISSUE

#### Current Design
```python
# src/features.py: AnalyticGNN
gnn_pred = 0.7 * self_heat + 0.3 * avg(neighbor_heat)
risk_score = 0.75 * xgb_pred + 0.25 * gnn_pred
```

**Problems**:
1. **Hardcoded 0.7/0.3 weights**: No way to adjust without code changes
2. **Neighbor definition undefined**: What defines a "neighbor"? Adjacency matrix never explicitly defined or versioned
3. **No topology abstraction**: If your lab rearranges racks, the model breaks and you don't know it
4. **25% weight feels arbitrary**: Is this backed by validation, or is it a guess?
5. **Cannot evolve**: If you move to 500 machines across 5 racks, the graph becomes critical but you have no infrastructure to manage it
6. **No hot-swap**: Can't update the graph without restarting inference service

#### Improved Design (Enterprise Ready)

**Treat the GNN as a first-class artifact with versioning, topology management, and canary deployment**:

```python
# server/graph_config.py
"""
Graph Neural Network configuration and topology management.
Defines the thermal zone model and inter-zone influence.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import json
from datetime import datetime

@dataclass
class ThermalZone:
    """Represents a physical thermal region (rack, chassis, zone)."""
    zone_id: str
    name: str
    machines: List[str]  # machine IDs in this zone
    neighbors: List[str]  # adjacent zone IDs
    spatial_weight: float = 0.7  # self-heat weight
    adjacency_weight: float = 0.3  # neighbor influence

class GraphTopology:
    """
    Versioned, hot-swappable graph topology for GNN model.
    
    Example (10-machine lab, 2 racks):
    {
      "version": "1.0.0",
      "topology_date": "2026-06-25",
      "zones": {
        "rack_a": {
          "machines": ["m1", "m2", "m3", "m4", "m5"],
          "neighbors": ["rack_b"],
          "spatial_weight": 0.7,
          "adjacency_weight": 0.3
        },
        "rack_b": {
          "machines": ["m6", "m7", "m8", "m9", "m10"],
          "neighbors": ["rack_a"],
          "spatial_weight": 0.7,
          "adjacency_weight": 0.3
        }
      },
      "model_fusion_weights": {
        "xgboost_weight": 0.75,
        "gnn_weight": 0.25
      }
    }
    """
    
    def __init__(self, config_json: dict, version: str):
        self.config = config_json
        self.version = version
        self.zones: Dict[str, ThermalZone] = {}
        self._parse_config()
        
    def _parse_config(self):
        """Parse zone definitions from config."""
        for zone_id, zone_data in self.config['zones'].items():
            self.zones[zone_id] = ThermalZone(
                zone_id=zone_id,
                name=zone_data.get('name', zone_id),
                machines=zone_data['machines'],
                neighbors=zone_data['neighbors'],
                spatial_weight=zone_data.get('spatial_weight', 0.7),
                adjacency_weight=zone_data.get('adjacency_weight', 0.3)
            )
    
    def get_neighbors_for_machine(self, machine_id: str) -> List[str]:
        """Get all neighbor machines for a given machine."""
        neighbors = []
        for machine_zone_id, zone in self.zones.items():
            if machine_id in zone.machines:
                # Found the zone, get neighbors
                for neighbor_zone_id in zone.neighbors:
                    neighbors.extend(self.zones[neighbor_zone_id].machines)
                break
        return neighbors
    
    def to_adjacency_matrix(self, machine_ids: List[str]) -> Dict[str, float]:
        """
        Build normalized adjacency matrix for GNN inference.
        Returns: {machine_i: {machine_j: weight, ...}}
        """
        adj = {m: {} for m in machine_ids}
        for m in machine_ids:
            neighbors = self.get_neighbors_for_machine(m)
            # Self-heat
            adj[m][m] = self.zones[self._get_zone_for_machine(m)].spatial_weight
            # Neighbor influence
            for n in neighbors:
                if n in machine_ids:
                    adj[m][n] = (
                        self.zones[self._get_zone_for_machine(m)].adjacency_weight 
                        / len(neighbors)
                    )
        return adj
    
    def _get_zone_for_machine(self, machine_id: str) -> str:
        for zone_id, zone in self.zones.items():
            if machine_id in zone.machines:
                return zone_id
        raise ValueError(f"Machine {machine_id} not in topology")


# server/inference_service.py
class AnalyticGNN:
    """GNN inference using versioned topology."""
    
    def __init__(self, topology: GraphTopology, xgb_pred: float):
        self.topology = topology
        self.xgb_pred = xgb_pred
    
    def predict(self, machine_id: str, telemetry: Dict, peer_telemetry: Dict) -> float:
        """
        Compute GNN prediction using versioned topology.
        
        Args:
          machine_id: target machine
          telemetry: this machine's telemetry
          peer_telemetry: {neighbor_id: telemetry_dict}
        
        Returns:
          gnn_risk_score [0, 1]
        """
        zone_id = self.topology._get_zone_for_machine(machine_id)
        zone = self.topology.zones[zone_id]
        
        # Self-heat
        self_heat = (telemetry['cpu'] + telemetry['gpu']) / 2.0
        
        # Neighbor average
        neighbor_heats = []
        for neighbor_id in self.topology.get_neighbors_for_machine(machine_id):
            if neighbor_id in peer_telemetry:
                n_heat = (peer_telemetry[neighbor_id]['cpu'] + peer_telemetry[neighbor_id]['gpu']) / 2.0
                neighbor_heats.append(n_heat)
        
        avg_neighbor_heat = sum(neighbor_heats) / len(neighbor_heats) if neighbor_heats else 0.0
        
        # Spatial fusion
        gnn_score = (
            zone.spatial_weight * self_heat +
            zone.adjacency_weight * avg_neighbor_heat
        )
        
        return gnn_score


# server/decision_cache.py
class CachedDecisionWithProvenance:
    """Decision + model provenance for debugging."""
    
    def __init__(self, machine_id: str, decision: dict, topology_version: str, model_version: str):
        self.machine_id = machine_id
        self.decision = decision
        self.topology_version = topology_version
        self.model_version = model_version
        self.timestamp = datetime.now()
    
    def to_dict(self):
        return {
            **self.decision,
            '_topology_version': self.topology_version,
            '_model_version': self.model_version,
            '_decision_age_ms': (datetime.now() - self.timestamp).total_seconds() * 1000
        }
```

#### Graph Configuration File (Versioned)

```json
# server/graph_topology_v1.0.0.json
{
  "version": "1.0.0",
  "topology_date": "2026-06-25",
  "description": "Initial 50-machine lab topology: 2 racks × 25 machines",
  
  "zones": {
    "rack_north": {
      "machines": ["m01", "m02", ..., "m25"],
      "neighbors": ["rack_south"],
      "spatial_weight": 0.7,
      "adjacency_weight": 0.3,
      "cooling_circuit": "A"
    },
    "rack_south": {
      "machines": ["m26", "m27", ..., "m50"],
      "neighbors": ["rack_north"],
      "spatial_weight": 0.7,
      "adjacency_weight": 0.3,
      "cooling_circuit": "A"
    }
  },
  
  "model_fusion_weights": {
    "xgboost_weight": 0.75,
    "gnn_weight": 0.25,
    "reason": "Validated on training set"
  },
  
  "changelog": [
    {
      "date": "2026-06-25",
      "author": "architect",
      "change": "Initial topology, 2 racks",
      "validation_f1": 0.87
    }
  ]
}
```

#### Automated Graph Validation

```python
# server/graph_validator.py
class GraphValidator:
    """Validate topology consistency."""
    
    @staticmethod
    def validate(topology: GraphTopology, machine_ids: List[str]) -> (bool, List[str]):
        """
        Returns: (is_valid, error_list)
        """
        errors = []
        
        # Check: all machines in topology exist
        all_topology_machines = set()
        for zone in topology.zones.values():
            all_topology_machines.update(zone.machines)
        
        missing = set(machine_ids) - all_topology_machines
        if missing:
            errors.append(f"Machines in lab but not in topology: {missing}")
        
        extra = all_topology_machines - set(machine_ids)
        if extra:
            errors.append(f"Machines in topology but offline: {extra}")
        
        # Check: no cycles
        visited = set()
        def has_cycle(zone_id, visited_path):
            if zone_id in visited_path:
                return True
            visited_path.add(zone_id)
            for neighbor in topology.zones[zone_id].neighbors:
                if has_cycle(neighbor, visited_path.copy()):
                    return True
            return False
        
        for zone_id in topology.zones.keys():
            if has_cycle(zone_id, set()):
                errors.append(f"Topology has cycle starting at {zone_id}")
        
        # Check: weights sum to 1.0 per zone
        for zone_id, zone in topology.zones.items():
            total = zone.spatial_weight + zone.adjacency_weight
            if abs(total - 1.0) > 0.01:
                errors.append(f"Zone {zone_id} weights sum to {total}, not 1.0")
        
        return (len(errors) == 0, errors)
```

#### Hot-Swap Topology at Runtime (Phase 4+)

```python
# server/inference_service.py
class InferenceService:
    def __init__(self):
        self.topology = self._load_latest_topology()
        self.topology_version = self._get_topology_version()
    
    def reload_topology(self, new_topology_version: str):
        """Hot-swap topology without restarting inference."""
        try:
            new_topology = self._load_topology_version(new_topology_version)
            is_valid, errors = GraphValidator.validate(new_topology, self.machine_ids)
            if not is_valid:
                raise ValueError(f"Invalid topology: {errors}")
            
            # Validation passed, swap
            self.topology = new_topology
            self.topology_version = new_topology_version
            logger.info(f"Topology reloaded: {new_topology_version}")
        except Exception as e:
            logger.error(f"Failed to reload topology: {e}")
            # Keep old topology, alert ops
```

#### Trade-Offs

| Aspect | Current (Hardcoded) | Improved (Versioned) |
|--------|---------------------|----------------------|
| **Topology changes** | Code deploy required | JSON config file, hot-swap |
| **Debugging** | "Why did this machine get wrong decision?" → guess | Decision includes topology version |
| **Scaling to 500 machines** | Rewrite inference code | Add zones, validate, promote |
| **A/B testing** | Not possible (monolithic) | Deploy topology v1.0 vs v1.1 to canary machines |
| **Audit trail** | None | Full changelog with dates, validation metrics |
| **Cardinality limit** | 50 machines | Unlimited (zones decouple from machine count) |

#### Implementation Guidance

**Week 1 (MVP): Define Topology**
```python
# server/graph_topology_v1.0.0.json
# Write topology for your actual 50-machine lab layout
# Ask lab ops: which machines are near each other thermally?
```

**Week 6 (Phase 3): Integrate into Inference**
```python
# Load topology at startup
# Pass to AnalyticGNN instead of hardcoded weights
# Validate topology matches lab reality
```

**Week 10 (Phase 5): Enable Hot-Swap**
```python
# Add /admin/reload_topology endpoint
# Test swapping between topology versions
```

**Week 16+ (Post-Launch): Optimize Weights**
```
# Retrain on 3 months of data
# Validate if spatial_weight should be 0.7 or 0.65
# Create topology v1.1.0 with validated weights
# Canary deploy to 5 machines, then full rollout
```

#### Decision: **IMPLEMENT**
- **MVP** (This week): Create `server/graph_topology_v1.0.0.json` for your lab layout
- **Phase 2** (Week 4): Integrate into AnalyticGNN
- **Phase 5** (Week 10): Add hot-swap capability
- **Phase 6+** (Post-launch): Iterate on weights with validation

**Savings**: No additional complexity now; prevents refactoring later when 500 machines expose the current design's limits.

---

### 3. MLOps Lifecycle — MISSING ENTIRELY

#### Current State
```
Training:
  ✓ retrain_monthly.py exists
  ✓ Can export Parquet from InfluxDB

Deployment:
  ✗ No versioning (which model is running right now?)
  ✗ No A/B testing (can't compare old vs new)
  ✗ No canary (no way to test new model on 1 machine first)
  ✗ No rollback (if new model is bad, you restart service = downtime)
  ✗ No shadow mode (model predicts but doesn't influence decisions)
  ✗ No metrics (can't measure "did this model improve accuracy?")
```

#### Improved Design (Enterprise Ready)

**MLOps Artifacts**:

```python
# server/models.py
from enum import Enum
from datetime import datetime
from dataclasses import dataclass

class ModelStatus(Enum):
    TRAINING = "training"
    VALIDATION = "validation"
    SHADOW = "shadow"  # predicts but doesn't influence decisions
    CANARY = "canary"  # 5% of machines
    STAGING = "staging"  # 20% of machines
    PRODUCTION = "production"  # all machines
    DEPRECATED = "deprecated"

@dataclass
class ModelVersion:
    name: str  # "xgboost_thermal"
    version: str  # "1.0.0" (semver)
    model_type: str  # "xgboost" or "gnn"
    artifact_uri: str  # "s3://bucket/models/xgboost_thermal/1.0.0.pkl"
    
    # Provenance
    training_date: datetime
    training_data_source: str  # "parquet://2026-05-01_to_2026-06-01"
    training_machine_count: int  # trained on 50 machines
    git_commit: str  # model training code version
    
    # Metrics
    validation_metrics: dict  # {f1: 0.87, precision: 0.89, recall: 0.85}
    test_metrics: dict  # metrics on held-out test set
    
    # Status
    status: ModelStatus
    promoted_by: str  # "architect@example.com"
    promoted_at: datetime
    
    # Rollout policy
    canary_machine_ids: List[str]  # for canary deployment
    canary_duration_hours: int
    canary_success_metric: str  # "lead_time_p50 >= 10s"


class ModelRegistry:
    """Central registry of all models (training, testing, production)."""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def register_new_model(self, version: ModelVersion) -> str:
        """Register a newly trained model."""
        # Save to database
        self.db.add(version)
        self.db.commit()
        return version.version
    
    def get_production_models(self) -> Dict[str, ModelVersion]:
        """Return current production models."""
        return {
            "xgboost": self.db.query(ModelVersion).filter_by(
                name="xgboost_thermal",
                status=ModelStatus.PRODUCTION
            ).order_by(ModelVersion.promoted_at.desc()).first(),
            "gnn": self.db.query(ModelVersion).filter_by(
                name="gnn_topology",
                status=ModelStatus.PRODUCTION
            ).order_by(ModelVersion.promoted_at.desc()).first(),
        }
    
    def promote_model(self, version_id: str, target_status: ModelStatus, approved_by: str):
        """Promote model through deployment pipeline."""
        version = self.db.query(ModelVersion).filter_by(version=version_id).first()
        
        # Validate transitions
        allowed_transitions = {
            ModelStatus.VALIDATION: [ModelStatus.SHADOW, ModelStatus.DEPRECATED],
            ModelStatus.SHADOW: [ModelStatus.CANARY, ModelStatus.DEPRECATED],
            ModelStatus.CANARY: [ModelStatus.STAGING, ModelStatus.DEPRECATED],
            ModelStatus.STAGING: [ModelStatus.PRODUCTION, ModelStatus.DEPRECATED],
            ModelStatus.PRODUCTION: [ModelStatus.DEPRECATED],
        }
        
        if target_status not in allowed_transitions.get(version.status, []):
            raise ValueError(f"Cannot transition from {version.status} to {target_status}")
        
        version.status = target_status
        version.promoted_by = approved_by
        version.promoted_at = datetime.now()
        self.db.commit()
        
        logger.info(f"Promoted {version.name}/{version.version} to {target_status}")


# server/inference_service.py
class InferenceServiceWithMLOps:
    """Inference service that respects model versioning."""
    
    def __init__(self, model_registry: ModelRegistry, feature_processor):
        self.registry = model_registry
        self.features = feature_processor
        self.production_models = self._load_production_models()
        self.shadow_models = self._load_shadow_models()
        self.canary_machines = self._get_canary_machines()
    
    def _load_production_models(self):
        """Load current production models."""
        prod = self.registry.get_production_models()
        return {
            'xgb': pickle.load(open(prod['xgboost'].artifact_uri)),
            'gnn_topology': GraphTopology(
                json.load(open(prod['gnn'].artifact_uri))
            )
        }
    
    def predict(self, machine_id: str, features: List[float]) -> dict:
        """
        Inference with A/B testing capability.
        
        Returns:
          {
            'xgb_pred': 0.45,
            'gnn_pred': 0.42,
            'fused': 0.44,
            'model_version': '1.0.0',
            'ab_test': 'control' or 'treatment',
            'shadow_prediction': {...} (if shadow model active)
          }
        """
        # Production prediction
        xgb_pred = self.production_models['xgb'].predict([features])[0]
        
        # Shadow model (if any)
        shadow_pred = None
        if self.shadow_models:
            shadow_pred = {
                'xgb': self.shadow_models['xgb'].predict([features])[0],
                'version': self.shadow_models['version']
            }
        
        # Canary model (5% of machines)
        canary_pred = None
        if machine_id in self.canary_machines and self.canary_models:
            canary_pred = {
                'xgb': self.canary_models['xgb'].predict([features])[0],
                'version': self.canary_models['version']
            }
        
        result = {
            'xgb_pred': xgb_pred,
            'model_version': self.registry.get_production_models()['xgboost'].version,
            'shadow_prediction': shadow_pred,
            'canary_prediction': canary_pred,
        }
        
        return result
```

#### Deployment Pipeline (Automated)

```yaml
# training/mlops_pipeline.yaml (DAG for monthly retraining)
name: monthly_retrain
schedule: "0 2 1 * *"  # 2am on 1st of month

stages:
  - stage: collect_data
    tasks:
      - export_parquet_from_postgres
      - validate_data_schema
      - calculate_statistics
  
  - stage: train
    tasks:
      - train_xgboost_model
      - train_gnn_model
  
  - stage: validate
    tasks:
      - test_xgboost_accuracy  # F1, precision, recall
      - test_gnn_accuracy
      - test_training_serving_parity
      - test_latency_sla  # < 200ms P95
  
  - stage: register
    tasks:
      - register_models_in_registry
      - generate_model_cards  # documentation
      - notify_team  # "new models available for promotion"
  
  - stage: manual_approval
    requires: ["human"]
    tasks:
      - wait_for_approval
      - promote_to_shadow  # run shadow mode
      - schedule_canary_promotion  # if shadow looks good, promote to 5 machines in 7 days


# Example workflow:
# Week 1: Export data, train, validate, register
# Week 2-3: Shadow mode (model predicts, we compare)
# Week 3: If shadow looks good, promote canary (5 machines)
# Week 3-4: Canary monitoring (alert if metrics worse than production)
# Week 4: Full rollout if all success criteria met
```

#### Model Card (Documentation)

```markdown
# Model Card: XGBoost Thermal Risk (v1.1.0)

## Model Details
- **Model**: XGBoost Regressor
- **Task**: Thermal risk prediction (0-30 seconds ahead)
- **Input**: 15-dimensional feature vector
- **Output**: Risk score [0.0, 1.0]
- **Training Date**: 2026-06-20
- **Training Data**: 50 machines, 30 days, 2.6M samples
- **Code**: https://github.com/cooling-project/main/commit/abc123

## Performance
- **F1 Score**: 0.87 (threshold 0.5)
- **Precision**: 0.89 (low false positives)
- **Recall**: 0.85 (catches most high-risk events)
- **Latency**: 0.8ms per sample (batch of 50)
- **Lead Time P50**: 12 seconds

### Performance by Hardware Type
- Dell XPS: F1=0.88, Lead Time=13s
- Lenovo ThinkPad: F1=0.86, Lead Time=11s
- ASUS VivoBook: F1=0.86, Lead Time=12s

### Known Limitations
- Trained only on university lab workloads (heavy ML training)
- May underperform on office workloads (light document editing)
- Requires retraining monthly as hardware/workload patterns shift

## Provenance & Governance
- **Promoted By**: architect@university.edu
- **Promoted At**: 2026-06-21 14:30 UTC
- **Previous Version**: 1.0.0 (F1=0.84)
- **A/B Test Result**: v1.1.0 10% better lead time than v1.0.0 on canary

## Recommended Use
- Production deployment for 50-machine lab
- Canary testing for 500+ machine deployments
- Shadow mode for model experimentation
```

#### Metrics Collection

```python
# server/ml_metrics.py
class MLMetricsCollector:
    """Collect ML performance metrics for A/B testing."""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def record_decision(self, machine_id: str, decision: dict, actual_outcome: dict, 
                       model_version: str, ab_variant: str):
        """
        Record a decision + outcome for metrics calculation.
        
        Args:
          decision: {'risk_score': 0.45, 'fan_pct': 55, 'model': '1.0.0'}
          actual_outcome: {
            'throttling_occurred': False,
            'peak_temp_after_30s': 65.2,
            'failsafe_triggered': False,
            'time_to_thermal_recovery_s': 45
          }
          ab_variant: 'control' or 'treatment'
        """
        metric = MLMetric(
            machine_id=machine_id,
            model_version=model_version,
            ab_variant=ab_variant,
            prediction=decision['risk_score'],
            outcome=actual_outcome,
            timestamp=datetime.now()
        )
        self.db.add(metric)
        self.db.commit()
    
    def compare_models(self, version_a: str, version_b: str, days: int = 7):
        """
        Compare two model versions on the same data.
        Returns: {'lead_time_diff': 1.2, 'p_value': 0.042, ...}
        """
        metrics_a = self.db.query(MLMetric).filter_by(
            model_version=version_a
        ).filter(
            MLMetric.timestamp >= datetime.now() - timedelta(days=days)
        ).all()
        
        metrics_b = self.db.query(MLMetric).filter_by(
            model_version=version_b
        ).filter(
            MLMetric.timestamp >= datetime.now() - timedelta(days=days)
        ).all()
        
        # Compute summary statistics
        lead_time_a = [m.actual_outcome.get('lead_time_s', 0) for m in metrics_a]
        lead_time_b = [m.actual_outcome.get('lead_time_s', 0) for m in metrics_b]
        
        from scipy import stats
        t_stat, p_value = stats.ttest_ind(lead_time_a, lead_time_b)
        
        return {
            'model_a': version_a,
            'model_b': version_b,
            'lead_time_a_p50': np.percentile(lead_time_a, 50),
            'lead_time_b_p50': np.percentile(lead_time_b, 50),
            'difference': np.percentile(lead_time_b, 50) - np.percentile(lead_time_a, 50),
            'p_value': p_value,
            'significant': p_value < 0.05,
            'sample_count_a': len(metrics_a),
            'sample_count_b': len(metrics_b)
        }
```

#### Trade-Offs

| Aspect | Current | Improved |
|--------|---------|----------|
| **Model lifecycle** | Train → pickle → restart service | Train → validate → shadow → canary → staging → production |
| **Rollback time** | 30 min (manual redeploy) | 5 min (API call) |
| **A/B testing** | Not possible | Full support (shadow, canary, staging) |
| **Model debugging** | "Which model is running?" → guess | Model version in every decision |
| **Scaling cost** | Retraining = downtime | Canary deployment = 1% impact |
| **Audit trail** | None | Full provenance (who promoted, when, why) |

#### Implementation Guidance

**Week 2 (MVP): Add Model Registry**
```python
# Create models table in database
# Write register_new_model() function
# Start recording model version in every decision
```

**Week 6 (Phase 3): Add Staging Logic**
```python
# Implement shadow mode (predict but don't influence decisions)
# Store shadow predictions in database
# Implement canary deployment (5 machines = 10% of traffic)
```

**Week 10 (Phase 5): Add Metrics**
```python
# Collect outcomes (thermal recovery time, lead time, etc.)
# Compare production vs shadow: statistical test
# Compare canary vs production: statistical test
```

**Week 13 (Post-Launch): Automate Promotion**
```
# Monthly retraining pipeline completes
# Validate metrics
# Auto-promote to shadow (no human needed)
# Alert if shadow metrics degrade > 5%
# Manual gate for canary (team reviews, approves)
```

#### Decision: **IMPLEMENT**
- **MVP** (Week 2): Model registry + versioning
- **Phase 3** (Week 6): Shadow + canary deployment
- **Phase 5** (Week 10): Metrics collection + A/B test framework
- **Post-Launch**: Automate promotion pipeline

**Savings**: No delays in MVP; sets up safe, low-risk model deployment for life of system.

---

## Part 2: Component-by-Component Review

### A. Telemetry Collection — GOOD

✅ **Push model is correct** (agents own retry logic)
✅ **Batching (5 points every 5s) is right** (reduces overhead)
✅ **HTTPS + cert pinning planned** (security)
⚠️ **Suggestion**: Add request signing (HMAC-SHA256) in addition to TLS for defense in depth

```python
# Add message signing to prevent tampering
import hmac
import hashlib

def sign_telemetry(data: dict, secret: str) -> str:
    message = json.dumps(data, sort_keys=True)
    return hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

# Request
payload = {"machine_id": "m1", "telemetry": [...]}
signature = sign_telemetry(payload, API_SECRET)
headers = {"X-Signature": signature}
```

### B. Inference Orchestration — GOOD with Caveats

✅ **Central inference makes sense for 50 machines**
✅ **Batching every 100ms is reasonable**
⚠️ **Latency budget is tight**: 200ms end-to-end. Monitor closely.
⚠️ **No GPU specified**: What if central server has no GPU? Model inference will be 5-10x slower.

```python
# server/inference_service.py
class InferenceService:
    def __init__(self, device='cuda' if torch.cuda.is_available() else 'cpu'):
        self.device = device
        logger.info(f"Using device: {self.device}")
        
        # Warn if CPU-only
        if self.device == 'cpu':
            logger.warning("No GPU detected. Inference latency may exceed SLA.")
```

**Recommendation**: For MVP, assume CPU is acceptable (XGBoost + AnalyticGNN are fast on CPU). If P95 latency > 250ms in Phase 2, add GPU.

### C. Actuation & Fallback — GOOD

✅ **Graceful fallback is robust**
✅ **Fallback fan curve (intensity-based) is conservative**
✅ **Per-OS driver abstraction is well-designed**

⚠️ **One gap**: No feedback loop. When agent applies fan decision, it doesn't report back actual RPM. This makes debugging hard ("Did the fan actually spin up?").

```python
# agents/policy_executor.py
def apply_and_report(self, decision: dict) -> dict:
    """Apply decision and report actual result."""
    try:
        self.fan_controller.set_fan_percent(decision['target_fan_pct'])
        
        # Read back actual state
        actual_rpm = self.fan_controller.get_actual_rpm()
        actual_temp = self.telemetry_reader.get_cpu_temp()
        
        return {
            'decision': decision,
            'actual_rpm': actual_rpm,
            'actual_temp': actual_temp,
            'timestamp': datetime.now(),
            'status': 'success'
        }
    except Exception as e:
        return {
            'decision': decision,
            'error': str(e),
            'timestamp': datetime.now(),
            'status': 'failed'
        }
```

### D. Dashboard & Observability — NEEDS REFINEMENT

Current plan: "Grafana + Prometheus + InfluxDB"

⚠️ **Three-layer stack is complex for MVP**. For 50 machines with PostgreSQL:

**Simpler alternative**:
```
PostgreSQL (store data) 
  ↓
  → Metabase (dashboarding)
     OR
  → Streamlit (real-time view)
  
Prometheus scrapes PostgreSQL exporter (optional Phase 4)
```

**Why**: Metabase or Streamlit connect directly to PostgreSQL with zero configuration. Avoid InfluxDB+Prometheus complexity until you have 500+ machines.

**Recommendation (MVP)**:
```python
# scripts/dashboard_streamlit.py
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

st.title("Cooling Lab Thermal Dashboard")

# Query PostgreSQL directly
@st.cache_data(ttl=5)
def get_latest_temps():
    with get_db() as session:
        query = """
        SELECT machine_id, recorded_at, cpu, gpu, memory
        FROM telemetry
        WHERE recorded_at >= NOW() - INTERVAL '1 hour'
        ORDER BY recorded_at DESC
        """
        return pd.read_sql(query, session.connection())

data = get_latest_temps()

# Show live thermal map
st.line_chart(data.set_index('recorded_at')[['cpu', 'gpu']])

# Show alerts
alerts = query_alerts(last_hours=1)
st.warning(f"⚠️ {len(alerts)} alerts in last hour")
for alert in alerts:
    st.write(f"  - {alert['machine_id']}: {alert['message']}")
```

**Cost**: 2 hours to set up Streamlit. Value: Real-time dashboard, no DevOps overhead.

---

## Part 3: Deployment Architecture for Windows Lab

#### Current Gap
Plan assumes "Linux VM or Kubernetes" for central server. But you're in a **Windows lab environment**.

#### Improved Design

**Central Server Options (in priority order)**:

1. **Windows Server VM (Recommended for Lab)**
   ```
   - Host: Windows Server 2022 on-prem or cloud
   - Runtime: Python 3.11 + FastAPI (uvicorn)
   - Database: PostgreSQL (via WSL2 or Docker Desktop)
   - Monitoring: Streamlit + cron jobs
   
   Setup (30 min):
     1. Install Python 3.11
     2. Install PostgreSQL (Windows installer)
     3. pip install -r requirements.txt
     4. systemctl enable cooling-server (via NSSM service wrapper)
     5. Test: curl http://localhost:8000/health
   ```

2. **Docker Desktop on Windows (Also Good)**
   ```
   # docker-compose.yml
   services:
     postgres:
       image: postgres:16
       environment:
         POSTGRES_DB: cooling_lab
     
     server:
       build: .
       depends_on:
         - postgres
       ports:
         - "8000:8000"
   
   # Run: docker-compose up -d
   ```

3. **Azure VMs with Bicep IaC (Enterprise)**
   ```
   # Deploy from Windows admin workstation
   az deployment group create \
     --resource-group cooling-lab \
     --template-file bicep/cooling-server.bicep
   ```

**Agent Deployment on Windows Lab Machines**:

```powershell
# scripts/deploy_agent_windows.ps1
param(
    [string]$CentralServerUrl = "https://cooling-server.lab:8000",
    [string]$ApiKey = "secret-key-here"
)

# 1. Create C:\ProgramData\CoolingAgent\
$agent_dir = "C:\ProgramData\CoolingAgent"
New-Item -ItemType Directory -Path $agent_dir -Force

# 2. Copy agent code
Copy-Item -Path "agents\*" -Destination $agent_dir -Recurse

# 3. Create config
@{
    server_url = $CentralServerUrl
    api_key = $ApiKey
    machine_id = (hostname.exe)
    interval_sec = 5
} | ConvertTo-Json | Out-File "$agent_dir\config.json"

# 4. Install as Windows Service (using NSSM)
# Download nssm.exe if not present
if (-not (Test-Path "C:\tools\nssm.exe")) {
    # Download from nssm GitHub
}

C:\tools\nssm.exe install CoolingAgent `
    "C:\Python311\python.exe" `
    "-m agents.telemetry_agent --config C:\ProgramData\CoolingAgent\config.json"

# 5. Start service
Start-Service -Name CoolingAgent

# 6. Verify
Get-Service -Name CoolingAgent
Get-EventLog -LogName Application -Source CoolingAgent -Newest 10
```

**Agent Configuration (Per Machine)**:
```json
// C:\ProgramData\CoolingAgent\config.json
{
  "server_url": "https://cooling-server.lab:8000",
  "api_key": "machine-specific-token",
  "machine_id": "LAPTOP-ABC123",
  "telemetry_interval_sec": 1,
  "batch_size": 5,
  "batch_interval_sec": 5,
  "decision_poll_interval_ms": 200,
  "max_retries": 3,
  "retry_backoff_base_ms": 100,
  "cert_verify": true,
  "cert_path": "C:\\ProgramData\\CoolingAgent\\ca.crt",
  "log_level": "INFO",
  "log_path": "C:\\ProgramData\\CoolingAgent\\agent.log"
}
```

**Secure Agent Provisioning**:
```powershell
# scripts/provision_agent_secure.ps1
# Run once per machine to securely store API key

param([string]$MachineId)

# 1. Generate machine-specific API key on server
$api_key = Invoke-WebRequest `
    -Uri "https://cooling-server.lab:8000/admin/provision" `
    -Method POST `
    -Body (@{machine_id = $MachineId} | ConvertTo-Json) `
    -UseBasicAuthentication `
    -Credential $admin_cred | ConvertFrom-Json

# 2. Store in Windows Credential Manager (encrypted)
cmdkey /add:cooling-server /user:$MachineId /pass:$api_key.token

# 3. Deploy agent with config pointing to Credential Manager
# agents/telemetry_agent.py checks Credential Manager for API key
```

---

## Part 4: Capacity Planning & Bottleneck Analysis

### Scalability Limits (Current Architecture)

| Component | MVP (50 machines) | Phase 4 (500 machines) | Phase 6+ (5000 machines) |
|-----------|------|------|------|
| **Central Server CPU** | 2 cores (sufficient) | 4 cores (marginal) | 8+ cores (add replicas) |
| **Central Server Memory** | 8GB | 16GB | 32GB+ |
| **Database (PostgreSQL)** | 1-2GB storage | 10-20GB | 100GB+ (shard) |
| **Network (inference requests)** | ~50 req/s | ~500 req/s | ~5000 req/s → 2-3 central servers |
| **Decision latency P95** | 200ms | 300ms (degrading) | 500ms+ → need edge inference |
| **Bottleneck** | None (headroom) | Central inference latency | Central network → distributed inference |

### Scaling Path (Roadmap)

**Phase 1-3 (MVP, 50 machines)**:
- Single central server (2 CPU, 8GB RAM, PostgreSQL local)
- All inference centralized
- Acceptable latency: 200ms P95

**Phase 4 (Ramp, 500 machines)**:
- Upgrade to 4 CPU, 16GB RAM
- Add PostgreSQL read replicas (Grafana queries don't block writes)
- Monitor P95 latency; if > 250ms, optimize batch size
- **Do NOT scale to 5000 yet** — save complexity

**Phase 5+ (Enterprise, 5000+ machines)**:
- Central server 1: Telemetry ingestion + decision cache
- Central server 2: Model inference (load-balanced)
- Central server 3: Database + analytics
- Agents download ONNX model, run local inference (hidden latency)
- Central server only coordinates policy + collects metrics

---

## Part 5: Recommended Implementation Sequence

### Critical Path (What to Build First)

```
Week 1-2 (Telemetry MVP):
  □ PostgreSQL schema (telemetry + decisions tables)
  □ Agent code (collect 1/s, batch 5/5s, push HTTPS)
  □ Central ingestion (POST /ingest endpoint)
  ✓ Deploy on 5 test machines
  ✓ Verify < 1s latency

Week 3-4 (Inference MVP):
  □ Central inference service (load models, predict)
  □ Policy engine wrapper (per-machine state)
  □ Decision cache (GET /decision/{machine_id})
  ✓ Test P95 latency < 200ms

Week 5-6 (Actuation MVP):
  □ Hardware-specific drivers (Windows/Linux/macOS)
  □ Fallback fan curve
  □ Policy executor (poll decisions, apply control)
  ✓ Fan control working on all OSes

[Optional Week 6: Add topology versioning + MLOps]

Week 7-8 (Observability MVP):
  □ Streamlit dashboard (PostgreSQL → charts)
  □ Alert rules (temp > 90C, machine offline)
  □ Monthly retraining script

Week 9-12 (Hardening):
  □ Graceful fallback (cache, escalation)
  □ Resilience tests
  □ Model validation
  □ Full 50-machine rollout
```

---

## Part 6: Trade-Offs Summary

### For MVP (This Week)

| Area | Skip | Use Instead | Cost |
|------|------|-------------|------|
| InfluxDB | Use PostgreSQL | PostgreSQL time-series | 0 days (simpler) |
| Prometheus/Grafana | Use Streamlit | Streamlit dashboard | 2 hours |
| RPC/gRPC | Use JSON polling | HTTP GET decisions | 0 days (simpler) |
| Kubernetes | Use Docker/systemd | Container or system service | 0 days (simpler) |
| GNN versioning | Define topology JSON | graph_topology_v1.0.0.json | 2 hours |
| MLOps pipeline | Add model registry table | Model versioning in DB | 1 day |

**Total delay from deferred architecture**: 0 days (all are additive, not blocking)
**Complexity reduced**: 60% (InfluxDB + Prometheus + Grafana → Streamlit)

### For Enterprise Scale (Post-MVP)

| Phase | Add | Reason | Timeline |
|-------|-----|--------|----------|
| Phase 4 | TimescaleDB extension | Sub-100ms queries, still ACID | Weeks 8-10 |
| Phase 5 | ONNX model format | Agents run local inference | Weeks 10-12 |
| Phase 5+ | InfluxDB (cold storage) | Archive 30+ day old data | Week 12+ |
| Phase 6+ | Distributed inference | 5000+ machines, latency critical | Post-launch |
| Phase 7+ | Kubernetes/Terraform | Multi-region, self-healing | Enterprise stage |

---

## Final Recommendations

### What to Implement This Week

1. **Replace InfluxDB with PostgreSQL** (MVP only)
   - Create schema (5 tables: telemetry, decisions, models, alerts, metrics)
   - No operational overhead
   - Rich query language for debugging
   - **Effort**: 1 day

2. **Define Graph Topology Explicitly**
   - `server/graph_topology_v1.0.0.json` (your lab layout)
   - Write topology validation logic
   - Integrate into AnalyticGNN
   - **Effort**: 1 day

3. **Add Model Registry**
   - Create `models` table
   - Version every model (semver)
   - Record training data + metrics
   - **Effort**: 1 day

4. **Add Request Signing** (Security)
   - HMAC-SHA256 on telemetry payloads
   - Verify on central server
   - **Effort**: 0.5 day

5. **Streamlit Dashboard** (Instead of Grafana)
   - Query PostgreSQL directly
   - Real-time thermal curves
   - Alerts panel
   - **Effort**: 2 days

**Total**: ~1 week of upfront architecture work → prevents 4+ weeks of technical debt later.

### Go/No-Go Decision Criteria

**Green Light for Phase 1-3**:
- [ ] PostgreSQL schema passes data validation tests
- [ ] Agent can collect and push telemetry < 1s
- [ ] Central inference latency < 200ms P95
- [ ] Fan control working on all OSes
- [ ] Graph topology matches lab reality
- [ ] Model registry records versions

**Yellow Flag** (Investigate):
- [ ] PostgreSQL query latency > 500ms on dashboard
- [ ] Inference latency > 250ms P95
- [ ] Agent crashes > 1x per week
- [ ] Decision cache hit rate < 95%

**Red Flag** (Design issue):
- [ ] Telemetry loss > 0.5%
- [ ] Central server CPU > 80% sustained
- [ ] Rollback time > 30 min
- [ ] No safe way to test new models

---

## Conclusion

The current scaling plan is **operationally sound**. Three focused improvements will make it **enterprise-ready without delaying MVP**:

1. **Use PostgreSQL for MVP** (defer InfluxDB to Phase 5)
2. **Make GNN topology explicit and versioned** (enable scaling to 5000+)
3. **Add MLOps lifecycle** (safe model deployment + rollback)

**Effort**: 1-2 weeks of upfront design + implementation
**Benefit**: Prevents 4+ weeks of refactoring at scale; clean migration path to 5000+ machines

The architecture is already well-shaped. These changes are surgical, not fundamental rewrites. Execute.

---

**Document Version**: 1.0  
**Review Date**: 2026-06-25  
**Reviewed By**: Principal Systems Architect (Cloud AI Platforms)  
**Status**: Ready for Implementation  
**Next Review**: End of Phase 2 (Week 4)

