import csv
import json
import time
import os
from typing import Dict, Any, List

class DemoRecorder:
    def __init__(self, output_dir: str = "artifacts"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.timeline: List[Dict[str, Any]] = []
        self.start_time = time.time()
        self.session_id = int(self.start_time)

    def record_frame(self, state: Dict[str, Any]):
        frame = state.copy()
        frame["timestamp"] = time.time()
        frame["elapsed_sec"] = frame["timestamp"] - self.start_time
        self.timeline.append(frame)

    def export(self):
        # Export CSV
        if not self.timeline:
            return None, None
        
        csv_path = os.path.join(self.output_dir, f"demo_timeline_{self.session_id}.csv")
        keys = set()
        for frame in self.timeline:
            keys.update(frame.keys())
        keys = sorted(list(keys))
        
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.timeline)

        # Export JSON
        json_path = os.path.join(self.output_dir, f"demo_timeline_{self.session_id}.json")
        with open(json_path, "w") as f:
            json.dump(self.timeline, f, indent=2)

        return csv_path, json_path
