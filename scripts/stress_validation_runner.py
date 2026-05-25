import os
import sys
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from training.comparison_runner import run_comparison

def stress_test():
    """
    Executes multiple real-world simulated stress tests and evaluates orchestration.
    """
    workloads = [
        "C_CPUBurst",           # CPU saturation / Cinebench
        "B_GPUSpike",           # Rendering / Blender
        "E_MixedChaos",         # Multitasking chaos
        "J_WorkloadTransition", # Transitions
        "M_WaveBurst"           # Gaming cycles
    ]
    
    print("========================================")
    print(" STARTING REAL WORKLOAD STRESS VALIDATION")
    print("========================================")
    
    for w in workloads:
        print(f"\n>> Validating Workload: {w}")
        run_comparison(rows=5000, scenario=w)
        
    print("\n[Stress Validation Runner] All stress scenarios completed successfully.")

if __name__ == "__main__":
    stress_test()
