import time
import sys
import os
import psutil

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.inference import InferenceEngine
from src.cooling_policy import CoolingPolicyEngine
from src.fan_controller import HardwareFanController

def benchmark_latency():
    """
    Tracks preprocessing, inference, and orchestration latency.
    """
    print("Warming up benchmark engine...")
    engine = InferenceEngine(run_parity_check=False)
    policy = CoolingPolicyEngine()
    controller = HardwareFanController("runtime/bench_target.json")
    
    raw = {'timestamp': '0', 'cpu': 50, 'gpu': 50, 'memory': 50, 'disk_io': 100, 'network_io': 100, 'cpu_temp': 40, 'gpu_temp': 40}
    
    latencies = {'preprocess': [], 'inference': [], 'orchestration': [], 'write': [], 'total': []}
    
    for _ in range(100):
        t0 = time.perf_counter()
        
        # Preprocessing inside predict
        t1 = time.perf_counter()
        risk, lvl, gnn = engine.predict(raw)
        
        t2 = time.perf_counter()
        target, state, stab = policy.update(risk, raw)
        
        t3 = time.perf_counter()
        controller.write_target(risk, target, state, stab)
        
        t4 = time.perf_counter()
        
        latencies['inference'].append((t2 - t1) * 1000)
        latencies['orchestration'].append((t3 - t2) * 1000)
        latencies['write'].append((t4 - t3) * 1000)
        latencies['total'].append((t4 - t0) * 1000)
        
    print("\n--- LATENCY BENCHMARK RESULTS ---")
    for k, v in latencies.items():
        if v:
            print(f"Avg {k:15s} : {sum(v)/len(v):.2f} ms")
            
    avg_total = sum(latencies['total'])/len(latencies['total'])
    assert avg_total < 50.0, f"Total control-loop latency exceeds 50ms ({avg_total:.2f}ms)"
    print("Assertion Passed: Total loop < 50ms")

if __name__ == "__main__":
    benchmark_latency()
