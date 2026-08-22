import time
import psutil
from typing import Dict, Any

class RuntimeHealthMonitor:
    def __init__(self):
        self.last_inference_time = time.time()
        self.last_telemetry_time = time.time()
        self.process = psutil.Process()
        self.start_memory = self.process.memory_info().rss
        self.state = "HEALTHY"

    def mark_inference(self):
        self.last_inference_time = time.time()

    def mark_telemetry(self):
        self.last_telemetry_time = time.time()

    def check_health(self) -> Dict[str, Any]:
        now = time.time()
        inference_lag = now - self.last_inference_time
        telemetry_lag = now - self.last_telemetry_time
        current_memory = self.process.memory_info().rss
        memory_growth = current_memory - self.start_memory

        issues = []
        if inference_lag > 3.0:
            issues.append(f"Inference stall detected ({inference_lag:.2f}s lag)")
        if telemetry_lag > 3.0:
            issues.append(f"Telemetry stall detected ({telemetry_lag:.2f}s lag)")
        if memory_growth > 500 * 1024 * 1024:  # 500MB growth
            issues.append("Excessive memory growth detected")

        if issues:
            self.state = "FAILSAFE"
        else:
            self.state = "HEALTHY"

        return {
            "status": self.state,
            "inference_lag_sec": inference_lag,
            "telemetry_lag_sec": telemetry_lag,
            "memory_growth_bytes": memory_growth,
            "issues": issues
        }
