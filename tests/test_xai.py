"""
tests/test_xai.py
------------------
Comprehensive Unit and Integration Test Suite for the Production XAI Layer.

Verifies:
1. GPU increase -> cooling increase explanation
2. CPU increase -> risk increase explanation
3. GPU/CPU decrease -> cooling decrease explanation
4. Risk crossing 0.72 -> cooling activation explanation
5. Risk below threshold -> no cooling explanation
6. Neighbor heat increase -> topology explanation
7. Manual override -> override explanation
8. First inference -> baseline explanation
9. Missing neighbor data handling
10. Missing telemetry handling
11. No significant change handling
12. Structured XAI output schema validity
13. Absence of fake confidence values
14. Terminology check (never claims measured temperature)
15. Distinction between global model importance and local decision reasoning
"""

import os
import sys
import pytest
import numpy as np

# Resolve path
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)
_SRC_DIR = os.path.join(_PROJECT_ROOT, 'src')
for p in [_SRC_DIR, _PROJECT_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from src.xai import DecisionExplainer, XAIHistory


@pytest.fixture
def explainer():
    return DecisionExplainer(cooling_threshold=0.72)


def test_gpu_increase_cooling_increase_explanation(explainer):
    """Test 1: GPU workload increase -> cooling increase explanation."""
    prev_tel = {"cpu": 50.0, "gpu": 61.0, "memory": 40.0, "disk_io": 1000.0, "network_io": 500.0}
    curr_tel = {"cpu": 55.0, "gpu": 79.0, "memory": 42.0, "disk_io": 1000.0, "network_io": 500.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=prev_tel,
        current_risk=0.77,
        previous_risk=0.68,
        current_cooling_strength=40.0,
        previous_cooling_strength=20.0,
        rack_id="RACK-A07"
    )

    assert explanation["decision"] == "COOLING_INCREASED"
    assert explanation["risk"]["delta"] == round(0.77 - 0.68, 4)
    assert explanation["cooling"]["delta"] == 20.0

    # Top reason should be GPU
    top_reason = explanation["primary_reasons"][0]
    assert top_reason["signal"] == "gpu"
    assert top_reason["direction"] == "increase"
    assert top_reason["delta"] == 18.0

    assert "GPU" in explanation["summary"]
    assert "increased" in explanation["summary"].lower()


def test_cpu_increase_risk_increase_explanation(explainer):
    """Test 2: CPU workload increase -> risk increase explanation."""
    prev_tel = {"cpu": 30.0, "gpu": 20.0, "memory": 40.0, "disk_io": 100.0, "network_io": 100.0}
    curr_tel = {"cpu": 85.0, "gpu": 20.0, "memory": 40.0, "disk_io": 100.0, "network_io": 100.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=prev_tel,
        current_risk=0.65,
        previous_risk=0.30,
        current_cooling_strength=30.0,
        previous_cooling_strength=0.0
    )

    top_reason = explanation["primary_reasons"][0]
    assert top_reason["signal"] == "cpu"
    assert top_reason["delta"] == 55.0
    assert explanation["thermal_context"]["delta"] > 0


def test_workload_decrease_cooling_decrease_explanation(explainer):
    """Test 3: GPU & CPU decrease -> cooling decrease explanation."""
    prev_tel = {"cpu": 80.0, "gpu": 85.0, "memory": 60.0, "disk_io": 1000.0, "network_io": 500.0}
    curr_tel = {"cpu": 40.0, "gpu": 30.0, "memory": 45.0, "disk_io": 500.0, "network_io": 200.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=prev_tel,
        current_risk=0.40,
        previous_risk=0.76,
        current_cooling_strength=20.0,
        previous_cooling_strength=60.0
    )

    assert explanation["decision"] == "COOLING_DECREASED"
    assert explanation["cooling"]["delta"] == -40.0
    assert "decreased" in explanation["summary"].lower() or "released" in explanation["summary"].lower()


def test_threshold_crossing_cooling_activation(explainer):
    """Test 4: Risk crossing 0.72 threshold -> cooling activation explanation."""
    prev_tel = {"cpu": 60.0, "gpu": 60.0, "memory": 50.0, "disk_io": 100.0, "network_io": 100.0}
    curr_tel = {"cpu": 75.0, "gpu": 80.0, "memory": 50.0, "disk_io": 100.0, "network_io": 100.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=prev_tel,
        current_risk=0.78,
        previous_risk=0.68,
        current_cooling_strength=50.0,
        previous_cooling_strength=0.0
    )

    assert explanation["decision"] == "COOLING_ACTIVATED"
    assert "crossing" in explanation["summary"].lower() or "exceeding" in explanation["summary"].lower()
    assert any("automatic cooling threshold of 72%" in step for step in explanation["decision_trace"])


def test_risk_below_threshold_no_cooling(explainer):
    """Test 5: Risk below threshold -> no cooling explanation."""
    prev_tel = {"cpu": 20.0, "gpu": 15.0, "memory": 30.0, "disk_io": 50.0, "network_io": 50.0}
    curr_tel = {"cpu": 25.0, "gpu": 18.0, "memory": 30.0, "disk_io": 50.0, "network_io": 50.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=prev_tel,
        current_risk=0.25,
        previous_risk=0.20,
        current_cooling_strength=0.0,
        previous_cooling_strength=0.0
    )

    assert explanation["decision"] == "NO_COOLING_REQUIRED"
    assert "No cooling required" in explanation["summary"]


def test_neighbor_heat_increase_topology_explanation(explainer):
    """Test 6: Neighbor heat increase -> topology influence explanation."""
    curr_tel = {"cpu": 50.0, "gpu": 50.0, "memory": 40.0, "disk_io": 100.0, "network_io": 100.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=curr_tel,
        current_risk=0.60,
        previous_risk=0.50,
        current_cooling_strength=30.0,
        previous_cooling_strength=30.0,
        neighbor_heat=0.85,
        previous_neighbor_heat=0.40,
        gnn_embedding=0.605,
        previous_gnn_embedding=0.470
    )

    neigh_ctx = explanation["neighbor_context"]
    assert neigh_ctx["has_neighbor_data"] is True
    assert neigh_ctx["delta"] > 0
    assert "Adjacent racks" in neigh_ctx["explanation"] or "thermally active" in neigh_ctx["explanation"]


def test_manual_override_explanation(explainer):
    """Test 7: Manual override explanation for deployment and removal."""
    curr_tel = {"cpu": 40.0, "gpu": 30.0, "memory": 40.0, "disk_io": 100.0, "network_io": 100.0}

    # Manual deployment
    exp_deploy = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=curr_tel,
        current_risk=0.45,
        previous_risk=0.45,
        current_cooling_strength=80.0,
        previous_cooling_strength=0.0,
        is_manual_override=True
    )
    assert exp_deploy["decision"] == "MANUAL_OVERRIDE_DEPLOYED"
    assert "operator override" in exp_deploy["summary"].lower()

    # Manual removal
    exp_remove = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=curr_tel,
        current_risk=0.85,
        previous_risk=0.85,
        current_cooling_strength=0.0,
        previous_cooling_strength=80.0,
        is_manual_override=True
    )
    assert exp_remove["decision"] == "MANUAL_OVERRIDE_REMOVED"
    assert "removed by operator override" in exp_remove["summary"].lower()


def test_first_inference_baseline_explanation(explainer):
    """Test 8: First inference cycle baseline explanation."""
    curr_tel = {"cpu": 40.0, "gpu": 35.0, "memory": 50.0, "disk_io": 200.0, "network_io": 100.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=None,
        current_risk=0.32,
        previous_risk=None,
        current_cooling_strength=0.0,
        previous_cooling_strength=None
    )

    assert explanation["decision"] == "NO_COOLING_REQUIRED"
    assert explanation["risk"]["delta"] == 0.0
    assert "Initial" in explanation["decision_trace"][0] or "baseline" in explanation["summary"].lower()


def test_missing_neighbor_data_fallback(explainer):
    """Test 9: Missing neighbor data handling."""
    curr_tel = {"cpu": 50.0, "gpu": 50.0, "memory": 40.0, "disk_io": 100.0, "network_io": 100.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=curr_tel,
        current_risk=0.50,
        previous_risk=0.50,
        neighbor_heat=None,
        gnn_embedding=None
    )

    neigh_ctx = explanation["neighbor_context"]
    assert neigh_ctx["has_neighbor_data"] is False
    assert "unavailable" in neigh_ctx["explanation"].lower()


def test_missing_telemetry_graceful_degradation(explainer):
    """Test 10: Missing/partial telemetry graceful degradation."""
    partial_tel = {"cpu": 50.0}  # Missing gpu, memory, etc.

    explanation = explainer.explain_decision(
        current_telemetry=partial_tel,
        previous_telemetry=None,
        current_risk=0.30,
        previous_risk=None
    )

    assert explanation is not None
    assert "risk" in explanation
    assert explanation["signal_details"]["cpu"]["current"] == 50.0
    assert explanation["signal_details"]["gpu"]["current"] == 0.0


def test_no_significant_change(explainer):
    """Test 11: No significant change handling."""
    tel = {"cpu": 50.0, "gpu": 50.0, "memory": 50.0, "disk_io": 100.0, "network_io": 100.0}

    explanation = explainer.explain_decision(
        current_telemetry=tel,
        previous_telemetry=tel,
        current_risk=0.50,
        previous_risk=0.50,
        current_cooling_strength=30.0,
        previous_cooling_strength=30.0
    )

    assert explanation["decision"] == "COOLING_MAINTAINED"
    assert len(explanation["primary_reasons"]) == 0
    assert "no significant" in explanation["decision_trace"][0].lower() or "steady" in explanation["summary"].lower()


def test_structured_xai_output_schema(explainer):
    """Test 12: Validate structured XAI output schema completeness."""
    curr_tel = {"cpu": 60.0, "gpu": 70.0, "memory": 50.0, "disk_io": 500.0, "network_io": 200.0}
    prev_tel = {"cpu": 50.0, "gpu": 50.0, "memory": 50.0, "disk_io": 500.0, "network_io": 200.0}

    output = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=prev_tel,
        current_risk=0.75,
        previous_risk=0.55,
        current_cooling_strength=50.0,
        previous_cooling_strength=20.0,
        rack_id="RACK-B12",
        epoch=42
    )

    required_keys = [
        "rack_id", "timestamp", "epoch", "decision", "headline", "risk",
        "cooling", "primary_reasons", "signal_details", "thermal_context",
        "neighbor_context", "model_context", "decision_trace", "summary"
    ]

    for key in required_keys:
        assert key in output, f"Missing key '{key}' in XAI output schema"

    assert output["rack_id"] == "RACK-B12"
    assert output["epoch"] == 42
    assert isinstance(output["decision_trace"], list)
    assert isinstance(output["summary"], str)


def test_no_fake_confidence_values(explainer):
    """Test 13: Ensure XAI output contains no manufactured confidence probabilities."""
    curr_tel = {"cpu": 50.0, "gpu": 50.0, "memory": 40.0, "disk_io": 100.0, "network_io": 100.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        current_risk=0.50
    )

    summary_str = explanation["summary"].lower()
    trace_str = " ".join(explanation["decision_trace"]).lower()

    # Must not contain manufactured percentage phrases like "94% confidence"
    assert "confidence" not in summary_str
    assert "94%" not in summary_str
    assert "94%" not in trace_str


def test_terminology_sensor_free_checks(explainer):
    """Test 14: Ensure explanations never falsely claim measured physical temperature."""
    curr_tel = {"cpu": 80.0, "gpu": 90.0, "memory": 70.0, "disk_io": 100.0, "network_io": 100.0}
    prev_tel = {"cpu": 40.0, "gpu": 40.0, "memory": 50.0, "disk_io": 100.0, "network_io": 100.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        previous_telemetry=prev_tel,
        current_risk=0.80,
        previous_risk=0.40,
        current_cooling_strength=60.0,
        previous_cooling_strength=0.0
    )

    text_content = (explanation["summary"] + " " + " ".join(explanation["decision_trace"])).lower()

    # Forbidden sensor-claiming phrases
    assert "temperature increased" not in text_content
    assert "measured temperature" not in text_content
    assert "temperature sensor" not in text_content

    # Allowed sensor-free proxy terminology
    assert ("inferred heat" in text_content or "heat proxy" in text_content or "thermal risk" in text_content)


def test_global_vs_local_importance_distinction(explainer):
    """Test 15: Correctly distinguishes global feature importance from local decision trace."""
    curr_tel = {"cpu": 50.0, "gpu": 80.0, "memory": 40.0, "disk_io": 100.0, "network_io": 100.0}

    explanation = explainer.explain_decision(
        current_telemetry=curr_tel,
        current_risk=0.70
    )

    model_ctx = explanation["model_context"]
    assert model_ctx["importance_type"] == "global"
    assert "global" in model_ctx["description"].lower()

    # Local reasoning is represented separately in primary_reasons and decision_trace
    assert len(explanation["decision_trace"]) > 0
    assert explanation["decision_trace"] != model_ctx["feature_importance"]


def test_xai_history_buffer():
    """Test XAIHistory rolling buffer capacity and retrieval."""
    history = XAIHistory(max_capacity=5)
    explainer = DecisionExplainer()

    for i in range(10):
        exp = explainer.explain_decision(
            current_telemetry={"cpu": float(i * 10)},
            current_risk=0.1 * i,
            epoch=i
        )
        history.add(exp)

    assert len(history) == 5
    assert history.get_latest()["epoch"] == 9
    assert history.get_recent(3)[0]["epoch"] == 7
