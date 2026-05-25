from typing import Dict, Any

class DualRuntimeComparison:
    def __init__(self):
        self.predictive_state = {}
        self.reactive_state = {}
        self.history = []

    def update_predictive(self, state: Dict[str, Any]):
        self.predictive_state = state

    def update_reactive(self, state: Dict[str, Any]):
        self.reactive_state = state

    def synchronize(self, timestamp: float):
        frame = {
            "timestamp": timestamp,
            "predictive": self.predictive_state.copy(),
            "reactive": self.reactive_state.copy()
        }
        self.history.append(frame)

    def get_comparison(self) -> Dict[str, Any]:
        if not self.history:
            return {}
        latest = self.history[-1]
        return {
            "predictive_rpm": latest["predictive"].get("rpm", 0),
            "reactive_rpm": latest["reactive"].get("rpm", 0),
            "rpm_diff": latest["predictive"].get("rpm", 0) - latest["reactive"].get("rpm", 0)
        }
