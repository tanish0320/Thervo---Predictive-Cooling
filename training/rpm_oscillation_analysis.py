import pandas as pd
import numpy as np

def analyze_rpm_oscillation(df: pd.DataFrame) -> dict:
    """
    Detects unstable RPM switching and rapid oscillation.
    """
    # Calculate first and second derivatives of fan speed
    fan_diff = df['fan_speed'].diff().fillna(0)
    fan_accel = fan_diff.diff().fillna(0)
    
    # Count rapid reversals (sign changes in velocity where delta is significant)
    reversals = 0
    for i in range(1, len(fan_diff)):
        if (fan_diff.iloc[i] * fan_diff.iloc[i-1] < 0) and (abs(fan_diff.iloc[i]) > 2.0):
            reversals += 1
            
    # Thrashing: standard deviation of fan acceleration
    thrashing_idx = float(fan_accel.std())
    
    return {
        "rapid_reversals": reversals,
        "thrashing_index": thrashing_idx,
        "is_stable": reversals < (len(df) / 100) # Arbitrary threshold for stability
    }
