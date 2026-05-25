import os
import sys
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List, Tuple

# Resolve paths
_TRAIN_DIR = os.path.abspath(os.path.dirname(__file__))
_SRC_PATH = os.path.abspath(os.path.join(_TRAIN_DIR, '..', 'src'))
if _SRC_PATH not in sys.path:
    sys.path.insert(0, _SRC_PATH)

from constants import PREDICTION_HORIZON_STEPS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ThermalSimulator:
    """
    Telemetry-conditioned thermal simulation engine.
    Expands small real telemetry datasets into large-scale, behaviorally realistic datasets.
    """
    def __init__(self, raw_telemetry_path: str):
        self.raw_df = pd.read_csv(raw_telemetry_path)
        self.profiles = {}
        for lbl in self.raw_df['workload_label'].unique():
            self.profiles[lbl] = self.raw_df[self.raw_df['workload_label'] == lbl].reset_index(drop=True)
            
        # Default physics parameters
        self.alpha_cpu = 0.15
        self.alpha_gpu = 0.20
        self.beta_fan = 0.12
        self.thermal_inertia = 0.96 # Decay factor per step
        self.ambient_temp = 25.0
        
    def _sample_from_profile(self, profile_name: str, length: int, rng: np.random.Generator) -> pd.DataFrame:
        """Sample sequential workload from a real telemetry profile."""
        profile_df = self.profiles.get(profile_name, self.raw_df)
        n_available = len(profile_df)
        
        if length <= n_available:
            start_idx = rng.integers(0, n_available - length + 1)
            sampled = profile_df.iloc[start_idx : start_idx + length].copy()
        else:
            repeats = (length // n_available) + 1
            sampled = pd.concat([profile_df]*repeats, ignore_index=True).iloc[:length].copy()
            
        # Add physically plausible noise while maintaining sequential continuity
        sampled['cpu'] = np.clip(sampled['cpu'] + rng.normal(0, 1.0, length), 0, 100)
        sampled['gpu'] = np.clip(sampled['gpu'] + rng.normal(0, 1.0, length), 0, 100)
        sampled['memory'] = np.clip(sampled['memory'] + rng.normal(0, 0.5, length), 0, 100)
        sampled['disk_io'] = np.clip(sampled['disk_io'] * rng.uniform(0.9, 1.1, length), 0, None)
        sampled['network_io'] = np.clip(sampled['network_io'] * rng.uniform(0.9, 1.1, length), 0, None)
        
        return sampled.reset_index(drop=True)

    def generate_scenario_workload(self, scenario: str, length: int, rng: np.random.Generator) -> pd.DataFrame:
        """Generate workload telemetry for a specific scenario class."""
        if scenario == 'A_Idle':
            return self._sample_from_profile('baseline_idle', length, rng)
        elif scenario == 'B_GPUSpike':
            idle = self._sample_from_profile('baseline_idle', length // 4, rng)
            spike = self._sample_from_profile('gpu_heavy', length - (length // 4), rng)
            return pd.concat([idle, spike], ignore_index=True)
        elif scenario == 'C_CPUBurst':
            return self._sample_from_profile('cpu_heavy', length, rng)
        elif scenario == 'D_SustainedSaturation':
            cpu_sat = self._sample_from_profile('cpu_heavy', length // 2, rng)
            gpu_sat = self._sample_from_profile('gpu_heavy', length - (length // 2), rng)
            return pd.concat([cpu_sat, gpu_sat], ignore_index=True)
        elif scenario == 'E_MixedChaos':
            return self._sample_from_profile('gaming_mixed', length, rng)
        elif scenario == 'F_CoolingFailure':
            return self._sample_from_profile('gaming_mixed', length, rng)
        elif scenario == 'G_Cooldown':
            spike = self._sample_from_profile('cpu_heavy', length // 4, rng)
            idle = self._sample_from_profile('baseline_idle', length - (length // 4), rng)
            return pd.concat([spike, idle], ignore_index=True)
        elif scenario == 'H_PredictiveRecovery':
            # Aggressive ramp where predictive fan should catch it early
            idle = self._sample_from_profile('baseline_idle', length // 4, rng)
            spike = self._sample_from_profile('gpu_heavy', length // 2, rng)
            idle2 = self._sample_from_profile('baseline_idle', length - len(idle) - len(spike), rng)
            return pd.concat([idle, spike, idle2], ignore_index=True)
        elif scenario == 'I_OscillationStress':
            # Rapid fluctuations
            chunks = []
            chunk_size = length // 10
            for i in range(10):
                prof = 'cpu_heavy' if i % 2 == 0 else 'baseline_idle'
                if i == 9: chunk_size = length - sum(len(c) for c in chunks)
                chunks.append(self._sample_from_profile(prof, chunk_size, rng))
            return pd.concat(chunks, ignore_index=True)
        elif scenario == 'J_WorkloadTransition':
            c1 = self._sample_from_profile('baseline_idle', length // 4, rng)
            c2 = self._sample_from_profile('gaming_mixed', length // 4, rng)
            c3 = self._sample_from_profile('cpu_heavy', length // 4, rng)
            c4 = self._sample_from_profile('baseline_idle', length - len(c1) - len(c2) - len(c3), rng)
            return pd.concat([c1, c2, c3, c4], ignore_index=True)
        elif scenario == 'K_LongDrift':
            return self._sample_from_profile('mixed_compute', length, rng)
        elif scenario == 'L_FanLimited':
            return self._sample_from_profile('gpu_heavy', length, rng)
        elif scenario == 'M_WaveBurst':
            chunks = []
            chunk_size = length // 6
            for i in range(6):
                prof = 'gaming_mixed' if i % 2 == 0 else 'baseline_idle'
                if i == 5: chunk_size = length - sum(len(c) for c in chunks)
                chunks.append(self._sample_from_profile(prof, chunk_size, rng))
            return pd.concat(chunks, ignore_index=True)
        elif scenario == 'N_FalseAlarm':
            # Short spikes that shouldn't cause overheating
            idle1 = self._sample_from_profile('baseline_idle', int(length * 0.45), rng)
            spike = self._sample_from_profile('cpu_heavy', int(length * 0.1), rng)
            idle2 = self._sample_from_profile('baseline_idle', length - len(idle1) - len(spike), rng)
            return pd.concat([idle1, spike, idle2], ignore_index=True)
        elif scenario == 'O_JitterNoise':
            base = self._sample_from_profile('baseline_idle', length, rng)
            # Add heavy noise
            base['cpu'] = np.clip(base['cpu'] + rng.normal(0, 15.0, length), 0, 100)
            base['gpu'] = np.clip(base['gpu'] + rng.normal(0, 15.0, length), 0, 100)
            return base
        else:
            return self._sample_from_profile('baseline_idle', length, rng)

    def simulate_thermal_dynamics(self, df: pd.DataFrame, scenario: str, rng: np.random.Generator, predictive_fan: bool = True) -> pd.DataFrame:
        """Apply physics-inspired thermal update rules and fan orchestration."""
        n_steps = len(df)
        cpu_temps = np.zeros(n_steps)
        gpu_temps = np.zeros(n_steps)
        fan_speeds = np.zeros(n_steps)
        
        # Initial conditions
        cpu_t = self.ambient_temp + 10.0
        gpu_t = self.ambient_temp + 10.0
        fan_s = 20.0
        
        # Scenario modifiers
        fan_efficiency = 1.0
        if scenario == 'F_CoolingFailure':
            fan_efficiency = 0.3
        elif scenario == 'L_FanLimited':
            fan_efficiency = 0.6  # Restricted airflow
            
        ambient = self.ambient_temp + rng.normal(0, 1.0)
        
        # Extract arrays
        cpu_load = df['cpu'].values
        gpu_load = df['gpu'].values
        
        cpu_ewma = df['cpu'].ewm(span=30).mean().values
        gpu_ewma = df['gpu'].ewm(span=30).mean().values
        
        for i in range(n_steps):
            cpu_t = (self.thermal_inertia * cpu_t) + (self.alpha_cpu * cpu_load[i]) - (self.beta_fan * fan_s * fan_efficiency * (cpu_t - ambient) / 50.0) + (ambient * (1 - self.thermal_inertia))
            gpu_t = (self.thermal_inertia * gpu_t) + (self.alpha_gpu * gpu_load[i]) - (self.beta_fan * fan_s * fan_efficiency * (gpu_t - ambient) / 50.0) + (ambient * (1 - self.thermal_inertia))
            
            # Add small random noise
            cpu_t += rng.normal(0, 0.1)
            gpu_t += rng.normal(0, 0.1)
            
            cpu_temps[i] = cpu_t
            gpu_temps[i] = gpu_t
            
            target_fan = 20.0
            
            if predictive_fan and i < n_steps - 30:
                future_cpu_t_proxy = 35.0 + 0.5 * cpu_ewma[i+30]
                future_gpu_t_proxy = 40.0 + 0.5 * gpu_ewma[i+30]
                risk_cpu = np.clip((future_cpu_t_proxy - 35) / 50, 0, 1)
                risk_gpu = np.clip((future_gpu_t_proxy - 40) / 50, 0, 1)
                future_risk = max(risk_cpu, risk_gpu)
                
                if future_risk < 0.35:
                    target_fan = 30.0
                elif future_risk < 0.55:
                    target_fan = 50.0
                elif future_risk < 0.75:
                    target_fan = 75.0
                else:
                    target_fan = 100.0
            else:
                current_risk = max(np.clip((cpu_t - 35)/50, 0, 1), np.clip((gpu_t - 40)/50, 0, 1))
                if current_risk < 0.35:
                    target_fan = 30.0
                elif current_risk < 0.55:
                    target_fan = 50.0
                elif current_risk < 0.75:
                    target_fan = 75.0
                else:
                    target_fan = 100.0
                    
            if target_fan > fan_s:
                fan_s += 5.0
            elif target_fan < fan_s:
                fan_s -= 1.0
            
            fan_s = np.clip(fan_s, 20.0, 100.0)
            fan_speeds[i] = fan_s
            
        df['cpu_temp'] = cpu_temps
        df['gpu_temp'] = gpu_temps
        df['fan_speed'] = fan_speeds
        df['ambient_temp'] = ambient
        return df

    def annotate_events(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add thermal event labels to the dataset."""
        df['event_overheating'] = ((df['cpu_temp'] > 90.0) | (df['gpu_temp'] > 85.0)).astype(int)
        
        cpu_diff = df['cpu_temp'].diff(periods=20)
        gpu_diff = df['gpu_temp'].diff(periods=20)
        df['event_thermal_spike'] = ((cpu_diff > 8.0) | (gpu_diff > 8.0)).astype(int)
        
        # New Labels (Task 10)
        df['stabilization_success'] = (((df['cpu_temp'] <= 90.0) & (df['gpu_temp'] <= 85.0)) & ((df['cpu'] > 60.0) | (df['gpu'] > 60.0))).astype(int)
        df['throttling_avoided'] = df['stabilization_success'] # Simplification for now
        
        # False alarm / overreaction: fan high but temps very low
        df['cooling_overreaction'] = ((df['fan_speed'] > 70.0) & (df['cpu_temp'] < 50.0) & (df['gpu_temp'] < 50.0)).astype(int)
        
        # Efficiency scores
        df['cooling_efficiency_score'] = 100.0 - df['fan_speed'] # Higher is better, if not overheating
        df.loc[df['event_overheating'] == 1, 'cooling_efficiency_score'] = 0.0
        
        df['thermal_stability_score'] = 100.0 - (df['cpu_temp'].diff().abs() + df['gpu_temp'].diff().abs()) * 10
        df['thermal_stability_score'] = df['thermal_stability_score'].clip(0, 100).fillna(100)
        
        return df
        
    def generate_large_scale_dataset(self, total_rows: int, seed: int = 42, predictive_fan: bool = True) -> pd.DataFrame:
        """Orchestrate generation of the full multi-scenario dataset."""
        logger.info(f"Generating {total_rows} rows of simulated telemetry...")
        rng = np.random.default_rng(seed)
        
        # Task 1: Rebalance Probabilities
        # stable operation: 55-65%
        # elevated thermal load: 20-25%
        # high risk: 8-12%
        # overheating: 2-5%
        scenarios = [
            'A_Idle', 'K_LongDrift', 'G_Cooldown', 'N_FalseAlarm', 'O_JitterNoise', # Stable
            'J_WorkloadTransition', 'E_MixedChaos', 'M_WaveBurst', # Elevated
            'B_GPUSpike', 'C_CPUBurst', 'H_PredictiveRecovery', 'I_OscillationStress', # High risk
            'D_SustainedSaturation', 'F_CoolingFailure', 'L_FanLimited' # Overheating
        ]
        
        probs = [
            0.20, 0.15, 0.10, 0.10, 0.05, # Stable: 60%
            0.08, 0.08, 0.07, # Elevated: 23%
            0.04, 0.04, 0.03, 0.03, # High risk: 14%
            0.01, 0.01, 0.01 # Overheating: 3%
        ]
        
        chunks = []
        rows_generated = 0
        chunk_size = 5000 
        
        start_time = datetime.now()
        
        while rows_generated < total_rows:
            scenario = rng.choice(scenarios, p=probs)
            current_length = min(chunk_size, total_rows - rows_generated)
            
            df_chunk = self.generate_scenario_workload(scenario, current_length, rng)
            df_chunk = self.simulate_thermal_dynamics(df_chunk, scenario, rng, predictive_fan=predictive_fan)
            df_chunk['scenario'] = scenario
            
            timestamps = [start_time + timedelta(seconds=i) for i in range(rows_generated, rows_generated + current_length)]
            df_chunk['timestamp'] = [t.strftime("%Y-%m-%d %H:%M:%S") for t in timestamps]
            
            chunks.append(df_chunk)
            rows_generated += current_length
            
            if rows_generated % 50000 == 0:
                logger.info(f"Generated {rows_generated}/{total_rows} rows...")
                
        final_df = pd.concat(chunks, ignore_index=True)
        final_df = self.annotate_events(final_df)
        
        for horizon in [30, 60, 120]:
            cpu_risk = np.clip((final_df['cpu_temp'] - 35) / 50, 0, 1)
            gpu_risk = np.clip((final_df['gpu_temp'] - 40) / 50, 0, 1)
            current_risk = np.maximum(cpu_risk, gpu_risk)
            final_df[f'future_risk_{horizon}s'] = current_risk.shift(-horizon)
            
        logger.info(f"Dataset generation complete. Shape: {final_df.shape}")
        return final_df

def visualize_simulation(df_pred: pd.DataFrame, df_react: pd.DataFrame, save_path: str):
    """Generate comparative visualization plots (Task 14)."""
    fig, axes = plt.subplots(5, 1, figsize=(15, 15), sharex=True)
    
    time_idx = np.arange(len(df_pred))
    
    # 1. Workload
    axes[0].plot(time_idx, df_pred['cpu'], label='CPU Load %', alpha=0.8)
    axes[0].plot(time_idx, df_pred['gpu'], label='GPU Load %', alpha=0.8)
    axes[0].set_ylabel('Utilization (%)')
    axes[0].legend()
    axes[0].set_title('Simulated Workload Patterns')
    axes[0].grid(True)
    
    # 2. Predictive Temperatures
    axes[1].plot(time_idx, df_pred['cpu_temp'], label='Predictive CPU Temp °C', color='red')
    axes[1].plot(time_idx, df_pred['gpu_temp'], label='Predictive GPU Temp °C', color='orange')
    axes[1].axhline(y=90, color='r', linestyle='--', alpha=0.5, label='Overheating Threshold')
    axes[1].set_ylabel('Temp (°C)')
    axes[1].legend()
    axes[1].set_title('Predictive Orchestration: Stabilized Temperatures')
    axes[1].grid(True)
    
    # 3. Reactive Temperatures
    axes[2].plot(time_idx, df_react['cpu_temp'], label='Reactive CPU Temp °C', color='darkred', linestyle='--')
    axes[2].plot(time_idx, df_react['gpu_temp'], label='Reactive GPU Temp °C', color='darkorange', linestyle='--')
    axes[2].axhline(y=90, color='r', linestyle='--', alpha=0.5)
    axes[2].set_ylabel('Temp (°C)')
    axes[2].legend()
    axes[2].set_title('Reactive Orchestration: Elevated Temperatures')
    axes[2].grid(True)
    
    # 4. Fan Speed Comparison
    axes[3].plot(time_idx, df_pred['fan_speed'], label='Predictive Fan RPM (%)', color='blue')
    axes[3].plot(time_idx, df_react['fan_speed'], label='Reactive Fan RPM (%)', color='cyan', linestyle='--')
    axes[3].set_ylabel('Fan Speed (%)')
    axes[3].legend()
    axes[3].set_title('Fan Speed: Predictive vs Reactive')
    axes[3].grid(True)
    
    # 5. Risk & Events
    if 'future_risk_30s' in df_pred.columns:
        axes[4].plot(time_idx, df_pred['future_risk_30s'], label='Future Risk (30s)', color='purple')
    axes[4].plot(time_idx, df_pred['event_overheating'] * 1.0, label='Predictive Overheating Event', color='red', alpha=0.8)
    axes[4].plot(time_idx, df_react['event_overheating'] * 0.8, label='Reactive Overheating Event', color='darkred', linestyle='--', alpha=0.8)
    axes[4].set_ylabel('Risk / Events')
    axes[4].set_xlabel('Time (seconds)')
    axes[4].legend()
    axes[4].set_title('Risk & Overheating Prevention')
    axes[4].grid(True)
    
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()
    logger.info(f"Visualization saved to {save_path}")

def generate_and_save_dataset(
    n_rows: int = 150000, 
    seed: int = 42, 
    raw_path: str = 'data/raw/master_telemetry_dataset.csv',
    output_dir: str = 'data/simulated'
):
    os.makedirs(output_dir, exist_ok=True)
    
    sim = ThermalSimulator(raw_path)
    
    # Generate main dataset (Predictive)
    df_pred = sim.generate_large_scale_dataset(total_rows=n_rows, seed=seed, predictive_fan=True)
    
    # Generate reactive subset for comparison plotting
    rng_plot = np.random.default_rng(seed)
    df_plot_workload = sim.generate_scenario_workload('H_PredictiveRecovery', 1500, rng_plot)
    df_plot_pred = sim.simulate_thermal_dynamics(df_plot_workload.copy(), 'H_PredictiveRecovery', np.random.default_rng(seed), predictive_fan=True)
    df_plot_react = sim.simulate_thermal_dynamics(df_plot_workload.copy(), 'H_PredictiveRecovery', np.random.default_rng(seed), predictive_fan=False)
    df_plot_pred = sim.annotate_events(df_plot_pred)
    df_plot_react = sim.annotate_events(df_plot_react)
    
    # Save raw simulated dataframe
    sim_csv_path = os.path.join(output_dir, 'simulated_telemetry.csv')
    df_pred.to_csv(sim_csv_path, index=False)
    logger.info(f"Saved raw simulation to {sim_csv_path}")
    
    # Process through canonical V2 pipeline
    logger.info("Processing through V2 Feature Schema...")
    from data_processing import build_training_dataset
    state_path = os.path.join(output_dir, 'preprocessor_state.pkl')
    X, y, processor = build_training_dataset(df_pred, state_save_path=state_path)
    
    X_df = pd.DataFrame(X, columns=processor.FEATURE_NAMES)
    y_df = pd.DataFrame(y, columns=['target_risk'])
    
    X_df.to_csv(os.path.join(output_dir, 'X.csv'), index=False)
    y_df.to_csv(os.path.join(output_dir, 'y.csv'), index=False)
    
    processed_df = pd.concat([df_pred.iloc[:-PREDICTION_HORIZON_STEPS].reset_index(drop=True), X_df, y_df], axis=1)
    processed_df.to_csv(os.path.join(output_dir, 'processed_dataset.csv'), index=False)
    
    # Generate Metadata Registry
    metadata = {
        "dataset_type": "simulated_behavioral_advanced",
        "generated_rows": len(df_pred),
        "seed": seed,
        "scenarios_included": df_pred['scenario'].value_counts().to_dict(),
        "events": {
            "overheating_count": int(df_pred['event_overheating'].sum()),
            "thermal_spikes": int(df_pred['event_thermal_spike'].sum()),
            "stabilization_success": int(df_pred['stabilization_success'].sum()),
            "cooling_overreaction": int(df_pred['cooling_overreaction'].sum())
        },
        "cooling": {
            "mean_fan_speed": float(df_pred['fan_speed'].mean()),
            "mean_efficiency_score": float(df_pred['cooling_efficiency_score'].mean()),
            "mean_stability_score": float(df_pred['thermal_stability_score'].mean())
        },
        "ambient_temp": 25.0
    }
    
    with open(os.path.join(output_dir, 'metadata.json'), 'w') as f:
        json.dump(metadata, f, indent=4)
        
    viz_path = os.path.join(output_dir, 'simulation_timeline.png')
    visualize_simulation(df_plot_pred, df_plot_react, viz_path)
    
    logger.info("Generation complete.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Thermal Simulator")
    parser.add_argument('--rows', type=int, default=150000, help='Number of rows to generate')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--out', type=str, default='data/simulated', help='Output directory')
    args = parser.parse_args()
    
    generate_and_save_dataset(n_rows=args.rows, seed=args.seed, output_dir=args.out)
