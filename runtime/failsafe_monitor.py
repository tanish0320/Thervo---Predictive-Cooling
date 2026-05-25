import json
import logging
import os
import time

logger = logging.getLogger(__name__)

class FailsafeMonitor:
    """
    Monitors runtime streams for anomalies and enforces fail-safes.
    """
    def __init__(self):
        self.last_inference_time = time.time()
        self.MAX_STALL_SECONDS = 5.0
        
    def check_telemetry(self, raw_data: dict) -> bool:
        """Returns True if safe, False if fail-safe needed."""
        for k in ['cpu', 'gpu', 'memory', 'disk_io', 'network_io']:
            if k not in raw_data or raw_data[k] is None:
                logger.error(f"Missing or invalid telemetry: {k}")
                return False
        return True
        
    def check_predictions(self, future_risk: float) -> bool:
        if future_risk is None or future_risk != future_risk: # NaN check
            logger.error("Invalid prediction: NaN")
            return False
        if future_risk < 0 or future_risk > 1.0:
            logger.error(f"Invalid prediction bounds: {future_risk}")
            return False
        return True
        
    def enforce_failsafe(self, fan_controller, reason: str):
        """Forces fan to 100%."""
        logger.critical(f"FAIL-SAFE TRIGGERED: {reason}. Forcing Fan=100%")
        if fan_controller:
            fan_controller.write_target(1.0, 100.0, "CRITICAL", False)
