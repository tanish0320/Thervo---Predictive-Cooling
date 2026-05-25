import pandas as pd

def validate_events(df: pd.DataFrame) -> dict:
    """
    Detects overheating events, sustained saturation, and cooling failure.
    Validates if predictive orchestration successfully prevented escalation.
    """
    overheats = len(df[(df['cpu_temp'] > 90) | (df['gpu_temp'] > 85)])
    spikes = df['event_thermal_spike'].sum()
    
    sustained_sat = 0
    # Find rolling 60s windows where load is > 90%
    if len(df) > 60:
        cpu_roll = df['cpu'].rolling(60).mean()
        sustained_sat = len(cpu_roll[cpu_roll > 90.0])
        
    return {
        "overheating_frames": overheats,
        "thermal_spikes_count": spikes,
        "sustained_saturation_frames": sustained_sat,
        "escalation_prevented": overheats == 0
    }
