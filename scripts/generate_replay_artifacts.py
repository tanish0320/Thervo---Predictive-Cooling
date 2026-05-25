import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runtime.live_runtime_manager import LiveRuntimeManager

def generate_artifacts():
    print("Generating deterministic replay artifacts...")
    manager = LiveRuntimeManager()
    
    # We will simulate 65 seconds to cover the full loop
    print("Simulating 65 seconds of runtime...")
    manager.start()
    
    time.sleep(65)
    
    print("Stopping and exporting...")
    manager.stop()
    print("Replay artifacts exported to artifacts/")

if __name__ == "__main__":
    generate_artifacts()
