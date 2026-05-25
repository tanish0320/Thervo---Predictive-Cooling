import pandas as pd
import numpy as np

def calculate_lead_time(df: pd.DataFrame, risk_threshold: float = 0.5, temp_threshold: float = 85.0) -> dict:
    """
    Computes lead time: thermal_event_time - prediction_threshold_crossing_time
    """
    # Find events where temperature exceeded threshold
    overheat_idx = df.index[(df['cpu_temp'] > temp_threshold) | (df['gpu_temp'] > temp_threshold)].tolist()
    
    # Find events where future_risk crossed threshold
    risk_idx = df.index[df['future_risk'] > risk_threshold].tolist()
    
    lead_times = []
    missed = 0
    false_positives = 0
    
    # Simple matching: for each overheat, find the closest previous risk alert
    # This assumes sequential time-series (1 step = 1 sec)
    for oh_i in overheat_idx:
        prior_risks = [r for r in risk_idx if r < oh_i]
        if prior_risks:
            # Check if it's within a reasonable window (e.g., 180 seconds)
            closest = prior_risks[-1]
            if (oh_i - closest) <= 180:
                lead_times.append(oh_i - closest)
            else:
                missed += 1
        else:
            missed += 1
            
    # False positives: Risk alert but no overheat within 120s
    for r_i in risk_idx:
        subseq_oh = [oh for oh in overheat_idx if r_i < oh <= (r_i + 120)]
        if not subseq_oh:
            false_positives += 1
            
    if lead_times:
        return {
            "avg_lead_time_sec": float(np.mean(lead_times)),
            "max_lead_time_sec": int(np.max(lead_times)),
            "min_lead_time_sec": int(np.min(lead_times)),
            "missed_events": missed,
            "false_positive_events": false_positives,
            "stabilization_success_rate": 1.0 - (missed / max(1, len(overheat_idx)))
        }
    else:
        return {
            "avg_lead_time_sec": 0.0,
            "max_lead_time_sec": 0,
            "min_lead_time_sec": 0,
            "missed_events": missed,
            "false_positive_events": len(risk_idx),
            "stabilization_success_rate": 1.0 if not overheat_idx else 0.0
        }
