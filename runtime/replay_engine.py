import json
import time
from typing import List, Dict, Any, Callable

class ReplayEngine:
    def __init__(self, timeline_path: str):
        self.timeline_path = timeline_path
        self.timeline: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if self.timeline_path.endswith('.json'):
            with open(self.timeline_path, 'r') as f:
                self.timeline = json.load(f)

    def replay(self, callback: Callable[[Dict[str, Any]], None], speed_multiplier: float = 1.0):
        if not self.timeline:
            return

        start_time = time.time()
        first_frame_time = self.timeline[0]["timestamp"]

        for frame in self.timeline:
            elapsed = frame["timestamp"] - first_frame_time
            target_time = start_time + (elapsed / speed_multiplier)
            
            now = time.time()
            if target_time > now:
                time.sleep(target_time - now)
                
            callback(frame)
