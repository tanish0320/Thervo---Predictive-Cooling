# Explainable AI (XAI) & Decision Explanation Layer

## 1. Purpose

The Explainable AI (XAI) layer of the AI-Driven Sensor-Free Predictive Cooling System provides transparent, audit-ready explanations for every cooling orchestration decision. 

In data center operations, infrastructure engineers and SREs require complete visibility into why an automated control system deploys, increases, attenuates, or releases cooling capacity. Black-box recommendations build operator distrust; the XAI layer bridges this gap by communicating the causal sequence of software telemetry changes, heat proxy inferences, neighbor thermal context, model predictions, and policy thresholds that triggered each cooling action.

> [!IMPORTANT]
> **SENSOR-FREE OBSERVATIONAL PARADIGM**
> This system is software-telemetry-driven and operates **without physical hardware temperature sensors**. All thermal assessments represent **inferred thermal load**, **heat proxies**, and **predicted thermal risk**. Explanations never claim direct measurement of physical temperature.
>
> Furthermore, the XAI layer is strictly **observational** and operates outside the inference decision loop. It reads current and previous system state to construct explanations without altering XGBoost predictions, composite risk fusion scores, action thresholds, or fan actuation targets.

---

## 2. Architecture

The XAI module resides in `src/xai.py` and is fully decoupled from the UI dashboard. It exposes standard classes and functions consumed by the runtime engine (`src/inference.py`), cooling controllers, event loggers, API servers, and test suites.

```
Software Telemetry (CPU, GPU, RAM, Disk, Net)
       │
       ▼
Feature Processor (15 canonical features)
       │
       ▼
Inferred Heat Proxy (0.6 * CPU + 0.4 * GPU)
       │
       ▼
Analytic GNN / Topology Context (0.7 * Self + 0.3 * Neighbor)
       │
       ▼
XGBoost Risk Model + Composite Fusion (0.75 * XGB + 0.25 * GNN)
       │
       ▼
Cooling Policy Engine (Threshold: 0.72)
       │
       ├──────────────────────────────────────────┐
       ▼                                          ▼
Hardware Fan Actuation                  DecisionExplainer (src/xai.py)
                                                  │
                                                  ├─ Telemetry Signal Analysis
                                                  ├─ Heat Proxy Reasoning
                                                  ├─ Neighbor Topology Context
                                                  ├─ Decision State Classification
                                                  ├─ Step-by-Step Causal Trace
                                                  └─ Human-Readable Operator Summary
```

---

## 3. What the System Explains

The XAI engine evaluates the transition from the previous inference cycle to the current cycle and answers:

1. **Why cooling increased** — Identifies specific workload surges and rising thermal risk.
2. **Why cooling decreased** — Tracks declining utilization and thermal risk attenuation.
3. **Why cooling was activated** — Highlights risk crossing the 0.72 automatic threshold.
4. **Why cooling was released** — Documents risk dropping below threshold and returning to nominal state.
5. **Why cooling remained unchanged** — Explains stable workload equilibrium.
6. **Which telemetry signals contributed** — Ranks primary contributors (CPU, GPU, Memory, Disk, Net).
7. **How workload changes affected inferred heat proxy** — Quantifies heat proxy shift (\(0.6 \cdot \text{CPU} + 0.4 \cdot \text{GPU}\)).
8. **How neighboring racks affected thermal risk** — Details spatial influence via Analytic GNN (\(0.7 \cdot \text{Self} + 0.3 \cdot \text{Neighbor}\)).
9. **How predicted risk score transitioned** — Shows risk score movement (e.g. 68% → 77%).
10. **Manual override actions** — Explicitly distinguishes operator intervention from AI automation.

---

## 4. Telemetry Signal Analysis

For each workload telemetry signal, the explainer calculates absolute change, percentage change, and direction:

$$\text{delta} = x_{\text{current}} - x_{\text{previous}}$$
$$\text{pct\_change} = \left( \frac{\text{delta}}{x_{\text{previous}}} \right) \times 100\%$$

To prevent noisy explanations, the system filters out minor signal jitter (below 0.5% delta) and ranks top contributors by magnitude.

---

## 5. Heat Proxy Reasoning

Because physical temperature sensors are not required, thermal load is inferred deterministically:

$$\text{heat\_norm} = 0.6 \cdot \text{cpu\_norm} + 0.4 \cdot \text{gpu\_norm}$$

The explainer isolates how GPU and CPU changes drove the heat proxy:
- *Example:* "Inferred heat proxy increased 12.1% primarily due to increased GPU (+18.4%) and CPU (+9.7%) workload."

---

## 6. Topology & Neighbor Context Reasoning

Spatial heat accumulation is modeled using a lightweight topology formula:

$$\text{gnn\_embedding} = 0.7 \cdot \text{self\_heat} + 0.3 \cdot \text{neighbor\_heat}$$

- **Self Thermal Contribution:** 70% weight
- **Neighbor Thermal Contribution:** 30% weight

*Explanation Example:*  
> "Adjacent racks became more thermally active (neighbor heat proxy: 49.0%, delta: +7.0%), increasing the rack's inferred thermal context."

If neighboring rack telemetry is missing, the system gracefully degrades:  
> "Neighbor thermal context was unavailable; thermal risk evaluated using local rack workload telemetry."

---

## 7. XGBoost Model Importance vs. Local Decision Reasoning

The XAI module strictly distinguishes between **Global Model Feature Importance** and **Local Decision Attribution**:

- **Global Feature Importance:** Pre-trained model feature weights (e.g. `gpu_norm`: 0.28, `cpu_norm`: 0.22). Labeled explicitly as `"importance_type": "global"`.
- **Local Decision Reasoning:** Computed step-by-step from actual telemetry deltas during the current cycle transition.

> [!CAUTION]
> The system does not claim SHAP-style local causality unless exact SHAP values are computed. Global model feature importance is provided as supporting context only.

---

## 8. Decision State Classification

Transitions are classified into canonical decision codes:

| Decision Code | Trigger Condition |
| :--- | :--- |
| `COOLING_ACTIVATED` | Risk crosses 0.72 threshold upward or fan ramps from 0% to >0% |
| `COOLING_INCREASED` | Thermal risk increases while active, requiring higher fan intensity |
| `COOLING_DECREASED` | Thermal risk declines, allowing fan speed attenuation |
| `COOLING_RELEASED` | Thermal risk drops below threshold, turning off active cooling (0%) |
| `COOLING_MAINTAINED` | Cooling strength remains steady during sustained load |
| `NO_COOLING_REQUIRED` | Thermal risk remains below the 0.72 action threshold |
| `MANUAL_OVERRIDE_DEPLOYED` | Operator manually forced cooling deployment |
| `MANUAL_OVERRIDE_REMOVED` | Operator manually removed active cooling |

---

## 9. Decision Trace & Example Outputs

### Structured JSON Output Schema

```json
{
    "rack_id": "RACK-A07",
    "timestamp": "2026-08-22 20:41:28",
    "epoch": 123,
    "decision": "COOLING_INCREASED",
    "headline": "Cooling Increased",
    "risk": {
        "previous": 0.68,
        "current": 0.77,
        "delta": 0.09,
        "previous_level": "HIGH",
        "current_level": "CRITICAL"
    },
    "cooling": {
        "previous_strength": 20.0,
        "current_strength": 40.0,
        "delta": 20.0,
        "threshold": 0.72,
        "is_manual_override": false
    },
    "primary_reasons": [
        {
            "signal": "gpu",
            "previous": 61.0,
            "current": 79.0,
            "delta": 18.0,
            "direction": "increase",
            "pct_change": 29.5
        },
        {
            "signal": "cpu",
            "previous": 52.0,
            "current": 61.7,
            "delta": 9.7,
            "direction": "increase",
            "pct_change": 18.7
        }
    ],
    "thermal_context": {
        "previous_heat_norm": 0.54,
        "current_heat_norm": 0.66,
        "delta": 0.12,
        "pct_change": 22.2,
        "explanation": "Inferred heat proxy increased 22.2% based on workload telemetry."
    },
    "neighbor_context": {
        "previous": 0.42,
        "current": 0.49,
        "delta": 0.07,
        "self_heat_contribution": 0.7,
        "neighbor_heat_contribution": 0.3,
        "has_neighbor_data": true,
        "gnn_embedding": 0.609,
        "explanation": "Adjacent racks became more thermally active (neighbor heat proxy: 49.0%, delta: +7.0%), increasing thermal context."
    },
    "model_context": {
        "xgb_prediction": 0.75,
        "gnn_embedding": 0.609,
        "composite_risk": 0.77,
        "feature_importance": {
            "gpu_norm": 0.28,
            "cpu_norm": 0.22,
            "heat_norm": 0.18
        },
        "importance_type": "global"
    },
    "decision_trace": [
        "GPU utilization increased by 18.0% (61.0% -> 79.0%)",
        "CPU utilization increased by 9.7% (52.0% -> 61.7%)",
        "Inferred heat proxy increased by 22.2%",
        "Neighbor thermal context increased by 7.0%",
        "Predicted thermal risk changed from 68.0% to 77.0%",
        "Risk crossed the automatic cooling threshold of 72%",
        "Cooling intensity increased from 20% to 40%"
    ],
    "summary": "Cooling increased from 20% to 40% because GPU (+18.0%), CPU (+9.7%) and neighboring racks became more thermally active. Predicted thermal risk rose from 68.0% to 77.0%, exceeding the 72% threshold."
}
```

---

## 10. Limitations

1. **Model Decision Context vs. Physical Causality:** The XAI layer explains why the AI model chose a specific cooling action based on trained patterns. It does not guarantee physical fluid dynamics causality.
2. **Sensor-Free Assumption:** Thermal state is inferred from compute workload. If hardware exhibits non-workload thermal spikes (e.g. ambient HVAC failure), workload telemetry alone will not detect it unless power/thermal throttling limits telemetry.
3. **No Manufactured Confidence Values:** The system does not output arbitrary probability values (e.g. "94% confidence"). Reliability is verified via feature validation and parity tests.
