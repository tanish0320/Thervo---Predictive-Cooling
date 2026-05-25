import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class HardwareFanController:
    """
    Hardware abstraction layer for fan control.
    Writes target states to a shared runtime interface for external 
    tools (like FanControl or LibreHardwareMonitor) to consume.
    """
    def __init__(self, target_file_path: str = "runtime/fan_target.json"):
        self.target_file_path = target_file_path
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.target_file_path)), exist_ok=True)
        
    def write_target(self, future_risk: float, target_fan_percent: float, policy_state: str, stabilization_active: bool):
        """
        Write the orchestration command to the shared interface.
        """
        payload = {
            "timestamp": datetime.now().isoformat(),
            "future_risk": float(future_risk),
            "target_fan_percent": float(target_fan_percent),
            "policy_state": policy_state,
            "stabilization_active": stabilization_active
        }
        
        try:
            # Write to temporary file then rename to ensure atomicity
            temp_path = self.target_file_path + ".tmp"
            with open(temp_path, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(temp_path, self.target_file_path)
        except Exception as e:
            logger.error(f"Failed to write fan target to {self.target_file_path}: {e}")
