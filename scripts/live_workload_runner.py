import time
from typing import Optional

class LiveWorkloadRunner:
    def __init__(self):
        self.current_workload: Optional[str] = None
        self.phases = []

    def run_workload(self, name: str, duration: int):
        self.current_workload = name
        start_time = time.time()
        print(f"Starting workload: {name} for {duration}s")
        
        end_time = start_time + duration
        while time.time() < end_time:
            time.sleep(1)
            
        self.phases.append({
            "name": name,
            "duration": duration,
            "start": start_time,
            "end": end_time
        })
        self.current_workload = None
        print(f"Finished workload: {name}")

    def run_automated_suite(self):
        workloads = [
            ("CS2_Sim", 30),
            ("Blender_Sim", 45),
            ("Mixed_Multitasking", 20)
        ]
        for name, duration in workloads:
            self.run_workload(name, duration)
            time.sleep(5)  # Cooldown between workloads

if __name__ == "__main__":
    runner = LiveWorkloadRunner()
    runner.run_automated_suite()
