import pandas as pd
import numpy as np

def analyze_stabilization(df: pd.DataFrame, temp_target: float = 80.0) -> dict:
    """
    Evaluates stabilization metrics over a dataframe.
    """
    cpu_overshoot = df['cpu_temp'] - temp_target
    cpu_overshoot = cpu_overshoot[cpu_overshoot > 0].sum()
    
    gpu_overshoot = df['gpu_temp'] - temp_target
    gpu_overshoot = gpu_overshoot[gpu_overshoot > 0].sum()
    
    # Calculate recovery time (time spent above target)
    recovery_time = len(df[(df['cpu_temp'] > temp_target) | (df['gpu_temp'] > temp_target)])
    
    thermal_variance = df['cpu_temp'].var() + df['gpu_temp'].var()
    
    fan_variance = df['fan_speed'].var()
    
    return {
        "overshoot_severity": float(cpu_overshoot + gpu_overshoot),
        "recovery_time_sec": int(recovery_time),
        "thermal_variance": float(thermal_variance),
        "oscillation_amplitude": float(fan_variance)
    }
