import time
from typing import Dict, Any

class HardwareValidationMode:
    def __init__(self):
        self.commanded_rpms = []
        self.actual_rpms = []

    def log_command(self, timestamp: float, rpm: int):
        self.commanded_rpms.append({"timestamp": timestamp, "rpm": rpm})

    def log_actual(self, timestamp: float, rpm: int):
        self.actual_rpms.append({"timestamp": timestamp, "rpm": rpm})

    def validate(self) -> Dict[str, Any]:
        # Calculate lag and saturation
        lag = 0.0
        saturation = False
        
        if self.commanded_rpms and self.actual_rpms:
            latest_cmd = self.commanded_rpms[-1]
            latest_act = self.actual_rpms[-1]
            
            # Simple lag calculation (time difference for similar RPM)
            lag = abs(latest_act["timestamp"] - latest_cmd["timestamp"])
            
            if latest_cmd["rpm"] >= 100 and latest_act["rpm"] < 95:
                saturation = True
                
        return {
            "hardware_lag_sec": lag,
            "rpm_saturation_detected": saturation,
            "stabilization_quality": "GOOD" if lag < 2.0 else "POOR"
        }
