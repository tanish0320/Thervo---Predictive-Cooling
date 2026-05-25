import pandas as pd
import numpy as np

def analyze_cooling_efficiency(df: pd.DataFrame, temp_threshold: float = 80.0) -> dict:
    """
    Evaluates cooling performance vs cost.
    """
    avg_fan = df['fan_speed'].mean()
    
    # Performance = % of time under threshold
    time_under_thresh = len(df[(df['cpu_temp'] <= temp_threshold) & (df['gpu_temp'] <= temp_threshold)])
    performance = time_under_thresh / max(1, len(df))
    
    # Wasted cooling = high fan when temps are low
    wasted = len(df[(df['fan_speed'] > 70) & (df['cpu_temp'] < 50) & (df['gpu_temp'] < 50)])
    
    # Efficiency Score = (Performance * 100) / (avg_fan + 1)
    efficiency = (performance * 100.0) / (avg_fan / 100.0 + 0.01)
    
    return {
        "avg_cooling_cost_percent": float(avg_fan),
        "cooling_performance_ratio": float(performance),
        "wasted_cooling_events": wasted,
        "efficiency_score": float(efficiency)
    }
