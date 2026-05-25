# training/metrics.py

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

def calculate_regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Calculate standard regression metrics."""
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae = float(mean_absolute_error(y_true, y_pred))
    r2 = float(r2_score(y_true, y_pred))
    return {
        "rmse": rmse,
        "mae": mae,
        "r2": r2
    }

def evaluate_predictive_performance(
    y_true: np.ndarray, 
    y_pred: np.ndarray, 
    threshold: float = 0.5,
    sampling_rate_hz: int = 1
) -> Dict[str, float]:
    """
    Evaluate event-based predictive thermal forecasting performance (Task 8 & Task 9).
    
    Metrics:
    - Average Lead Time (sec): How early the prediction rises above the threshold before the actual event.
    - False Cooling Rate: Unnecessary cooling activations / total cooling activations.
    - Missed Thermal Event Rate: Overheating events not predicted / total overheating events.
    """
    # Binary classification of cooling activation (risk > threshold)
    actual_high = (y_true >= threshold).astype(int)
    pred_high = (y_pred >= threshold).astype(int)
    
    # 1. False Cooling Rate (unnecessary activations)
    cooling_activations = np.sum(pred_high)
    if cooling_activations > 0:
        unnecessary = np.sum((pred_high == 1) & (actual_high == 0))
        false_cooling_rate = float(unnecessary / cooling_activations)
    else:
        false_cooling_rate = 0.0
        
    # 2. Missed Thermal Event Rate (actual high risk steps not predicted high)
    total_high_events = np.sum(actual_high)
    if total_high_events > 0:
        missed = np.sum((actual_high == 1) & (pred_high == 0))
        missed_event_rate = float(missed / total_high_events)
    else:
        missed_event_rate = 0.0
        
    # 3. Lead Time (steps/seconds)
    # Detect transitions from low to high risk in ground truth
    lead_times = []
    
    for i in range(1, len(actual_high)):
        # Transition to high risk (escalation start)
        if actual_high[i] == 1 and actual_high[i - 1] == 0:
            # Look backwards up to 45 steps (prediction window) to see when the prediction first rose
            t_event = i
            t_pred = None
            # Search backwards for the first time prediction crossed threshold
            for j in range(max(0, t_event - 45), t_event):
                if pred_high[j] == 1:
                    t_pred = j
                    break
            
            if t_pred is not None:
                lead_time_seconds = (t_event - t_pred) / sampling_rate_hz
                lead_times.append(lead_time_seconds)
                
    avg_lead_time = float(np.mean(lead_times)) if lead_times else 0.0
    
    return {
        "avg_lead_time_sec": avg_lead_time,
        "false_cooling_rate": false_cooling_rate,
        "missed_event_rate": missed_event_rate,
        "total_cooling_activations": int(cooling_activations),
        "total_high_risk_steps": int(total_high_events)
    }

def print_performance_summary(reg_metrics: Dict[str, float], event_metrics: Dict[str, float], latency_stats: Dict[str, float] = None):
    """Print a clean evaluation summary."""
    print("=" * 60)
    print("  PREDICTIVE THERMAL FORECASTING METRICS")
    print("=" * 60)
    print("  Regression Metrics:")
    print(f"    RMSE                     : {reg_metrics['rmse']:.6f}")
    print(f"    MAE                      : {reg_metrics['mae']:.6f}")
    print(f"    R² Score                 : {reg_metrics['r2']:.6f}")
    print("-" * 60)
    print("  Event-Based Metrics (Threshold = 0.5):")
    print(f"    Avg Lead Time before Spike: {event_metrics['avg_lead_time_sec']:.1f} sec")
    print(f"    False Cooling Rate       : {event_metrics['false_cooling_rate'] * 100:.1f}%")
    print(f"    Missed Thermal Event Rate: {event_metrics['missed_event_rate'] * 100:.1f}%")
    print(f"    Total Cooling Activations: {event_metrics['total_cooling_activations']}")
    print(f"    Total High Risk Steps    : {event_metrics['total_high_risk_steps']}")
    if latency_stats:
        print("-" * 60)
        print("  Latency & SLA:")
        print(f"    Mean Preprocess Latency  : {latency_stats.get('mean_preprocess_ms', 0.0):.3f} ms")
        print(f"    Mean Inference Latency   : {latency_stats.get('mean_inference_ms', 0.0):.3f} ms")
        print(f"    SLA Compliance Rate      : {latency_stats.get('sla_compliance_percent', 100.0):.2f}%")
    print("=" * 60)
