import json
import csv
import os
from typing import Dict, Any

class FinalBenchmarkExporter:
    def __init__(self, output_dir: str = "artifacts"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def export_report(self, metrics: Dict[str, Any], session_id: str):
        # Export JSON
        json_path = os.path.join(self.output_dir, f"benchmark_{session_id}.json")
        with open(json_path, 'w') as f:
            json.dump(metrics, f, indent=2)
            
        # Export Markdown
        md_path = os.path.join(self.output_dir, f"benchmark_{session_id}.md")
        with open(md_path, 'w') as f:
            f.write("# Predictive Cooling Benchmark Report\n\n")
            for k, v in metrics.items():
                f.write(f"- **{k}**: {v}\n")
                
        return json_path, md_path
