import time
from typing import Dict, Any

class LiveLeadTimeMonitor:
    def __init__(self):
        self.predictions = []
        self.thermal_events = []
        self.current_lead_time = 0.0

    def record_prediction(self, timestamp: float, risk_score: float):
        if risk_score > 0.8:
            self.predictions.append({"timestamp": timestamp, "risk": risk_score})

    def record_thermal_event(self, timestamp: float, temperature: float):
        if temperature > 85.0:  # Threshold for thermal event
            self.thermal_events.append({"timestamp": timestamp, "temp": temperature})
            self._update_lead_time()

    def _update_lead_time(self):
        if not self.predictions or not self.thermal_events:
            return
        
        latest_event = self.thermal_events[-1]["timestamp"]
        # Find the prediction that happened before this event
        valid_preds = [p for p in self.predictions if p["timestamp"] < latest_event]
        if valid_preds:
            earliest_valid = valid_preds[0]["timestamp"]
            self.current_lead_time = latest_event - earliest_valid

    def get_metrics(self) -> Dict[str, Any]:
        success_prob = 1.0 if self.current_lead_time > 0 else 0.0
        return {
            "current_lead_time_sec": self.current_lead_time,
            "prediction_before_spike": self.current_lead_time > 0,
            "stabilization_success_probability": success_prob
        }
