import threading
from typing import Callable, Dict, List, Any

class LiveStreamBus:
    def __init__(self):
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []
        self._lock = threading.Lock()
        self._latest_state: Dict[str, Any] = {}

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]):
        with self._lock:
            self._subscribers.append(callback)

    def publish(self, telemetry_data: Dict[str, Any]):
        with self._lock:
            self._latest_state.update(telemetry_data)
            for subscriber in self._subscribers:
                try:
                    subscriber(telemetry_data)
                except Exception as e:
                    print(f"Error in stream bus subscriber: {e}")

    def get_latest_state(self) -> Dict[str, Any]:
        with self._lock:
            return self._latest_state.copy()
