import sys
import os
import argparse
import numpy as np
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from training.thermal_simulator import ThermalSimulator
from training.report_generator import generate_comparative_report

def run_comparison(rows: int = 15000, scenario: str = "H_PredictiveRecovery"):
    """
    Executes Predictive vs Reactive benchmarking on a specific scenario.
    """
    sim = ThermalSimulator('data/raw/master_telemetry_dataset.csv')
    rng = np.random.default_rng(42)
    
    # 1. Generate workload
    workload = sim.generate_scenario_workload(scenario, rows, rng)
    
    # 2. Run Predictive
    print(f"Running Predictive Simulation for {scenario}...")
    pred_df = sim.simulate_thermal_dynamics(workload.copy(), scenario, np.random.default_rng(42), predictive_fan=True)
    pred_df = sim.annotate_events(pred_df)
    
    # Calculate future risk proxy for analytics
    for h in [30]:
        cpu_risk = np.clip((pred_df['cpu_temp'] - 35) / 50, 0, 1)
        gpu_risk = np.clip((pred_df['gpu_temp'] - 40) / 50, 0, 1)
        pred_df['future_risk'] = np.maximum(cpu_risk, gpu_risk).shift(-h).fillna(0)
        
    # 3. Run Reactive
    print(f"Running Reactive Simulation for {scenario}...")
    react_df = sim.simulate_thermal_dynamics(workload.copy(), scenario, np.random.default_rng(42), predictive_fan=False)
    react_df = sim.annotate_events(react_df)
    
    for h in [30]:
        cpu_risk = np.clip((react_df['cpu_temp'] - 35) / 50, 0, 1)
        gpu_risk = np.clip((react_df['gpu_temp'] - 40) / 50, 0, 1)
        react_df['future_risk'] = np.maximum(cpu_risk, gpu_risk).shift(-h).fillna(0)
    
    # 4. Generate Output Report
    out_dir = "data/simulated"
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, f"comparative_report_{scenario}.json")
    generate_comparative_report(pred_df, react_df, report_path)
    
    # 5. Export Data
    pred_df.to_csv(os.path.join(out_dir, f"predictive_{scenario}.csv"), index=False)
    react_df.to_csv(os.path.join(out_dir, f"reactive_{scenario}.csv"), index=False)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=str, default="H_PredictiveRecovery")
    parser.add_argument("--rows", type=int, default=15000)
    args = parser.parse_args()
    
    run_comparison(args.rows, args.scenario)
