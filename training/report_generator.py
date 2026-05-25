import json
import pandas as pd
from training.lead_time_analysis import calculate_lead_time
from training.stabilization_analysis import analyze_stabilization
from training.rpm_oscillation_analysis import analyze_rpm_oscillation
from training.cooling_efficiency import analyze_cooling_efficiency

def generate_comparative_report(pred_df: pd.DataFrame, react_df: pd.DataFrame, output_path: str = "data/simulated/comparative_report.json"):
    """
    Generates a full comparative research report between Predictive and Reactive cooling.
    """
    report = {
        "predictive": {
            "lead_time": calculate_lead_time(pred_df),
            "stabilization": analyze_stabilization(pred_df),
            "oscillation": analyze_rpm_oscillation(pred_df),
            "efficiency": analyze_cooling_efficiency(pred_df)
        },
        "reactive": {
            "lead_time": calculate_lead_time(react_df),
            "stabilization": analyze_stabilization(react_df),
            "oscillation": analyze_rpm_oscillation(react_df),
            "efficiency": analyze_cooling_efficiency(react_df)
        },
        "comparison": {}
    }
    
    # Comparisons
    p_stab = report["predictive"]["stabilization"]["recovery_time_sec"]
    r_stab = report["reactive"]["stabilization"]["recovery_time_sec"]
    report["comparison"]["recovery_time_reduction_sec"] = max(0, r_stab - p_stab)
    
    p_eff = report["predictive"]["efficiency"]["efficiency_score"]
    r_eff = report["reactive"]["efficiency"]["efficiency_score"]
    report["comparison"]["efficiency_improvement_percent"] = max(0, ((p_eff - r_eff) / max(1, r_eff)) * 100)
    
    with open(output_path, "w") as f:
        json.dump(report, f, indent=4)
        
    print(f"Report generated successfully at {output_path}")
