"""
TELEMETRY VALIDATION SUITE
Principal Performance Engineer Debugging

Purpose: Trace every metric from OS to dashboard without assumptions.
Validate CPU, GPU, Memory, Temperature against Task Manager.

Pipeline trace:
  OS (psutil/nvidia-smi)
    ↓
  collect_telemetry()
    ↓
  Filtering
    ↓
  Feature Engineering
    ↓
  Normalization
    ↓
  Prediction
    ↓
  API Response
    ↓
  WebSocket
    ↓
  Dashboard Display
"""

import os
import sys
import time
import psutil
import subprocess
import json
from datetime import datetime

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.inference import InferenceEngine
from src.features import FeatureProcessor


class TelemetryValidator:
    """Instrument and validate every stage of the telemetry pipeline."""

    def __init__(self):
        print("[INIT] Loading InferenceEngine...")
        try:
            self.engine = InferenceEngine(run_parity_check=False)
            print("      [OK] Engine loaded")
        except Exception as e:
            print(f"      [ERROR] {e}")
            self.engine = None

        # For disk/network counters
        dk_init = psutil.disk_io_counters()
        nk_init = psutil.net_io_counters()
        self.dk_prev = {"val": (dk_init.read_bytes + dk_init.write_bytes) if dk_init else 0, "time": time.monotonic()}
        self.nk_prev = {"val": (nk_init.bytes_sent + nk_init.bytes_recv) if nk_init else 0, "time": time.monotonic()}

        self.validation_log = []

    def get_raw_os_metrics(self):
        """Stage 1: Get raw metrics directly from OS (no processing)."""
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'cpu_percent_interval_none': psutil.cpu_percent(interval=None),
            'cpu_percent_interval_01': psutil.cpu_percent(interval=0.1),
            'cpu_times': psutil.cpu_times_percent(),
            'virtual_memory': psutil.virtual_memory(),
            'gpu_nvidia_smi': self._query_nvidia_smi(),
            'process_cpu': psutil.Process(os.getpid()).cpu_percent(interval=None),
        }
        return metrics

    def _query_nvidia_smi(self):
        """Query nvidia-smi for GPU metrics."""
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=1
            )
            if res.returncode == 0:
                parts = res.stdout.strip().split(",")
                if len(parts) >= 5:
                    return {
                        'util': float(parts[0].strip()),
                        'mem_used': float(parts[1].strip()),
                        'mem_total': float(parts[2].strip()),
                        'temp': float(parts[3].strip()),
                        'power': float(parts[4].strip()),
                    }
        except Exception as e:
            pass
        return None

    def get_backend_telemetry(self):
        """Stage 2: Get telemetry from backend (after all processing)."""
        if not self.engine:
            return None

        raw_data, self.dk_prev, self.nk_prev = self.engine.collect_telemetry(self.dk_prev, self.nk_prev)
        return raw_data

    def trace_feature_engineering(self, raw_data):
        """Stage 3: Trace feature engineering."""
        if not self.engine or not raw_data:
            return None

        # Manually process to see what happens
        processor = FeatureProcessor()
        processor.load("models/preprocessor_state.pkl")

        # Process the raw data
        features = processor.process_single(raw_data)

        return {
            'raw': raw_data,
            'features': features,
            'feature_names': ['cpu_norm', 'gpu_norm', 'mem_norm', 'disk_io_norm', 'net_io_norm', 'heat_norm',
                            'cpu_roll_5', 'gpu_roll_5', 'heat_roll_5', 'cpu_roll_10', 'gpu_roll_10', 'heat_roll_10',
                            'cpu_delta', 'gpu_delta', 'heat_delta']
        }

    def validate_cpu(self, os_metrics, backend_data):
        """Validate CPU metric through entire pipeline."""
        print("\n" + "="*70)
        print("CPU VALIDATION")
        print("="*70)

        # OS Level
        cpu_none = os_metrics['cpu_percent_interval_none']
        cpu_01 = os_metrics['cpu_percent_interval_01']
        cpu_times = os_metrics['cpu_times']

        print(f"\n[OS LEVEL - RAW]")
        print(f"  psutil.cpu_percent(interval=None):   {cpu_none:6.2f}%")
        print(f"  psutil.cpu_percent(interval=0.1):    {cpu_01:6.2f}%")
        print(f"  psutil.cpu_times_percent():")
        print(f"    - user:     {cpu_times.user:6.2f}%")
        print(f"    - system:   {cpu_times.system:6.2f}%")
        print(f"    - idle:     {cpu_times.idle:6.2f}%")
        print(f"  Current process CPU:                 {os_metrics['process_cpu']:6.2f}%")

        # Backend Level
        if backend_data:
            backend_cpu = backend_data.get('cpu', -1)
            print(f"\n[BACKEND - After collect_telemetry()]")
            print(f"  raw_data['cpu']:                     {backend_cpu:6.2f}%")

            # Check if it matches raw OS
            delta_none = abs(backend_cpu - cpu_none)
            delta_01 = abs(backend_cpu - cpu_01)
            print(f"\n[DELTA CHECK]")
            print(f"  |backend - psutil(None)|:            {delta_none:6.2f}%")
            print(f"  |backend - psutil(0.1)|:             {delta_01:6.2f}%")

            if delta_none < 2 and delta_01 < 2:
                print(f"  [OK] Backend CPU matches OS metrics")
            else:
                print(f"  [ALERT] Backend CPU does NOT match OS!")
                print(f"         This suggests filtering or incorrect measurement")

        return {
            'os_none': cpu_none,
            'os_01': cpu_01,
            'backend': backend_data.get('cpu', -1) if backend_data else -1,
        }

    def validate_memory(self, os_metrics, backend_data):
        """Validate memory metric."""
        print("\n" + "="*70)
        print("MEMORY VALIDATION")
        print("="*70)

        # OS Level
        mem = os_metrics['virtual_memory']
        total = mem.total / (1024**3)
        used = mem.used / (1024**3)
        available = mem.available / (1024**3)
        percent = mem.percent

        print(f"\n[OS LEVEL - RAW (psutil.virtual_memory())]")
        print(f"  Total:        {total:7.2f} GB")
        print(f"  Used:         {used:7.2f} GB")
        print(f"  Available:    {available:7.2f} GB")
        print(f"  Percent:      {percent:6.2f}%")

        # Backend Level
        if backend_data:
            backend_mem = backend_data.get('memory', -1)
            print(f"\n[BACKEND - After collect_telemetry()]")
            print(f"  raw_data['memory']:                  {backend_mem:6.2f}%")

            # Check if it matches
            delta = abs(backend_mem - percent)
            print(f"\n[DELTA CHECK]")
            print(f"  |backend - os_percent|:              {delta:6.2f}%")

            if delta < 2:
                print(f"  [OK] Backend memory matches OS")
            else:
                print(f"  [ALERT] Backend memory does NOT match OS!")
                print(f"         Dashboard shows {backend_mem:.1f}% but OS shows {percent:.1f}%")
                print(f"         Difference: {delta:.1f}%")

        return {
            'os_percent': percent,
            'os_used_gb': used,
            'os_total_gb': total,
            'backend': backend_data.get('memory', -1) if backend_data else -1,
        }

    def validate_gpu(self, os_metrics, backend_data):
        """Validate GPU metric."""
        print("\n" + "="*70)
        print("GPU VALIDATION")
        print("="*70)

        # OS Level
        nvidia = os_metrics['gpu_nvidia_smi']
        if nvidia:
            print(f"\n[OS LEVEL - nvidia-smi]")
            print(f"  Utilization:  {nvidia['util']:6.2f}%")
            print(f"  Memory Used:  {nvidia['mem_used']:6.2f} MB")
            print(f"  Memory Total: {nvidia['mem_total']:6.2f} MB")
            print(f"  Temperature:  {nvidia['temp']:6.2f}°C")
            print(f"  Power Draw:   {nvidia['power']:6.2f}W")
        else:
            print(f"\n[OS LEVEL - nvidia-smi]")
            print(f"  [ERROR] nvidia-smi query failed or not available")

        # Backend Level
        if backend_data:
            backend_gpu = backend_data.get('gpu', -1)
            backend_gpu_temp = backend_data.get('gpu_temp', -1)
            backend_gpu_power = backend_data.get('gpu_power', -1)

            print(f"\n[BACKEND - After collect_telemetry()]")
            print(f"  raw_data['gpu']:                     {backend_gpu:6.2f}%")
            print(f"  raw_data['gpu_temp']:                {backend_gpu_temp:6.2f}°C")
            print(f"  raw_data['gpu_power']:               {backend_gpu_power:6.2f}W")

            if nvidia:
                delta_util = abs(backend_gpu - nvidia['util'])
                delta_temp = abs(backend_gpu_temp - nvidia['temp'])

                print(f"\n[DELTA CHECK]")
                print(f"  |backend - nvidia(util)|:            {delta_util:6.2f}%")
                print(f"  |backend - nvidia(temp)|:            {delta_temp:6.2f}°C")

                if delta_util < 2 and delta_temp < 3:
                    print(f"  [OK] Backend GPU matches OS")
                else:
                    print(f"  [ALERT] Backend GPU does NOT match!")
                    if delta_util >= 2:
                        print(f"         GPU util: backend {backend_gpu:.1f}% vs nvidia {nvidia['util']:.1f}%")
                    if delta_temp >= 3:
                        print(f"         GPU temp: backend {backend_gpu_temp:.1f}°C vs nvidia {nvidia['temp']:.1f}°C")

        return {
            'os_util': nvidia['util'] if nvidia else -1,
            'os_temp': nvidia['temp'] if nvidia else -1,
            'backend_util': backend_data.get('gpu', -1) if backend_data else -1,
            'backend_temp': backend_data.get('gpu_temp', -1) if backend_data else -1,
        }

    def validate_temperature(self, backend_data):
        """Validate temperature values."""
        print("\n" + "="*70)
        print("TEMPERATURE VALIDATION")
        print("="*70)

        if backend_data:
            cpu_temp = backend_data.get('cpu_temp', -1)
            gpu_temp = backend_data.get('gpu_temp', -1)

            print(f"\n[BACKEND]")
            print(f"  CPU Temperature:  {cpu_temp:6.2f}°C")
            print(f"  GPU Temperature:  {gpu_temp:6.2f}°C")

            # Check for unrealistic values
            print(f"\n[VALIDATION]")
            if cpu_temp > 0 and cpu_temp < 30:
                print(f"  [ALERT] CPU temp {cpu_temp:.1f}°C is suspiciously low")
            elif cpu_temp > 100:
                print(f"  [ALERT] CPU temp {cpu_temp:.1f}°C is suspiciously high")
            else:
                print(f"  [OK] CPU temp {cpu_temp:.1f}°C is reasonable")

            if gpu_temp == 0:
                print(f"  [ALERT] GPU temp is 0°C - likely not reading sensor or using fallback")
            elif gpu_temp > 100:
                print(f"  [ALERT] GPU temp {gpu_temp:.1f}°C is unrealistic")

    def run_validation(self):
        """Run complete validation suite."""
        print("\n" + "="*70)
        print("= TELEMETRY VALIDATION SUITE - PRINCIPAL PERFORMANCE ENGINEER")
        print("="*70)

        print("\n[PHASE 1] Collecting OS metrics (no processing)...")
        os_metrics = self.get_raw_os_metrics()

        print("[PHASE 2] Collecting backend telemetry (with processing)...")
        backend_data = self.get_backend_telemetry()

        # Validate each metric
        cpu_validation = self.validate_cpu(os_metrics, backend_data)
        mem_validation = self.validate_memory(os_metrics, backend_data)
        gpu_validation = self.validate_gpu(os_metrics, backend_data)
        self.validate_temperature(backend_data)

        # Summary
        print("\n" + "="*70)
        print("VALIDATION SUMMARY")
        print("="*70)

        print(f"\nCPU:")
        print(f"  OS (interval=None):  {cpu_validation['os_none']:6.2f}%")
        print(f"  OS (interval=0.1):   {cpu_validation['os_01']:6.2f}%")
        print(f"  Backend:             {cpu_validation['backend']:6.2f}%")

        print(f"\nMemory:")
        print(f"  OS:                  {mem_validation['os_percent']:6.2f}%")
        print(f"  Backend:             {mem_validation['backend']:6.2f}%")
        print(f"  Difference:          {abs(mem_validation['os_percent'] - mem_validation['backend']):6.2f}%")

        print(f"\nGPU:")
        print(f"  OS Util:             {gpu_validation['os_util']:6.2f}%")
        print(f"  Backend Util:        {gpu_validation['backend_util']:6.2f}%")
        print(f"  OS Temp:             {gpu_validation['os_temp']:6.2f}°C")
        print(f"  Backend Temp:        {gpu_validation['backend_temp']:6.2f}°C")


if __name__ == "__main__":
    validator = TelemetryValidator()
    validator.run_validation()
