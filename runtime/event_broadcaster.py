import time
from typing import Callable, List, Dict, Any

class EventBroadcaster:
    def __init__(self):
        self._listeners: List[Callable[[str, Dict[str, Any]], None]] = []

    def subscribe(self, callback: Callable[[str, Dict[str, Any]], None]):
        self._listeners.append(callback)

    def broadcast(self, event_type: str, payload: Dict[str, Any]):
        payload['timestamp'] = time.time()
        payload['event_type'] = event_type
        for listener in self._listeners:
            listener(event_type, payload)

    def emit_overheating_warning(self, temp: float, threshold: float):
        self.broadcast("OVERHEATING_WARNING", {"temperature": temp, "threshold": threshold})

    def emit_predictive_stabilization(self, future_risk: float, target_rpm: int):
        self.broadcast("PREDICTIVE_STABILIZATION", {"future_risk": future_risk, "target_rpm": target_rpm})

    def emit_rpm_ramp(self, current_rpm: int, target_rpm: int):
        self.broadcast("RPM_RAMP", {"current_rpm": current_rpm, "target_rpm": target_rpm})
        
    def emit_cooling_intervention(self, action: str):
        self.broadcast("COOLING_INTERVENTION", {"action": action})

    def emit_failsafe_trigger(self, reason: str):
        self.broadcast("FAILSAFE_TRIGGER", {"reason": reason})

    def emit_lead_time_alert(self, lead_time_ms: float):
        self.broadcast("LEAD_TIME_ALERT", {"lead_time_ms": lead_time_ms})
