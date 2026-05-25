import time
import yaml
import numpy as np
from pathlib import Path
from enum import Enum
import logging

logger = logging.getLogger(__name__)

from src.hardware.thermal_mode_controller import ThermalModeController

class CoolingState(Enum):
    QUIET = "QUIET"
    BALANCED = "BALANCED"
    PERFORMANCE = "PERFORMANCE"
    RECOVERY = "RECOVERY"
    FAILSAFE = "FAILSAFE"

class CoolingPolicyEngine:
    """
    Intelligent Adaptive Laptop Cooling Controller.
    Implements hysteresis, idle relaxation, smooth fan transitions, 
    and prevents permanent FAILSAFE triggers.
    """
    def __init__(self, config_path: str = "config/cooling_policy.yaml"):
        self.current_state = CoolingState.BALANCED
        self.current_fan_speed = 30.0
        self.target_fan_speed = 30.0
        
        self.last_update_time = time.time()
        
        # Hysteresis tracking
        self.condition_start_times = {
            "PERFORMANCE": 0.0,
            "FAILSAFE": 0.0,
            "RECOVERY": 0.0,
            "IDLE": 0.0
        }
        
        self.stabilization_active = False
        self.thermal_controller = ThermalModeController()
        self.current_thermal_mode = "BALANCED"
        self.laptop_mode_enabled = True # LAPTOP_ORCHESTRATION_MODE

        self.last_risk = 0.0
        
        # Added for thermal fixes & intelligence
        self.stable_duration = 0.0
        self.last_cpu_t = 40.0
        self.last_gpu_t = 40.0
        self.thermal_slope = 0.0
        self.prediction_momentum = 0.0
        self.escalation_reason = "NONE"
        
        # Intelligence state
        self.escalation_confidence = 0.0
        self.predictive_intent_class = "NOMINAL"
        self.acoustic_optimization_active = False
        self.equilibrium_bias_strength = 0.0
        self.recovery_stabilization_score = 100.0
        self.workload_fingerprint = "IDLE_BROWSER"
        self.thermal_phase = "EQUILIBRIUM"
        self.thermal_headroom = 40.0
        self.predictive_cooling_window = "NONE"

    def update(self, future_risk: float, current_telemetry: dict = None) -> tuple[float, str, bool, dict]:
        """
        Process the orchestration logic.
        Returns: (target_fan_speed, policy_state_name, stabilization_active, diagnostics)
        """
        now = time.time()
        dt = max(now - self.last_update_time, 0.001)
        self.last_update_time = now
        
        raw_prediction = future_risk
        
        if not current_telemetry:
            current_telemetry = {}
            
        cpu = current_telemetry.get("cpu", 0)
        gpu = current_telemetry.get("gpu", 0)
        cpu_t = current_telemetry.get("cpu_temp", 40)
        gpu_t = current_telemetry.get("gpu_temp", 40)
        pwr = current_telemetry.get("power_draw", 15.0) # approx if absent
        
        # Calculate thermal slope and momentum
        current_heat = cpu_t * 0.6 + gpu_t * 0.4
        last_heat = self.last_cpu_t * 0.6 + self.last_gpu_t * 0.4
        instant_slope = (current_heat - last_heat) / dt
        
        # THERMAL MOMENTUM FIX & RECOVERY DAMPENING
        if self.current_state == CoolingState.RECOVERY:
            # Momentum dampening during recovery
            self.thermal_slope = 0.1 * self.thermal_slope + 0.9 * instant_slope
            self.thermal_slope *= 0.8 # aggressive decay
            self.prediction_momentum *= 0.5
        else:
            self.thermal_slope = 0.3 * self.thermal_slope + 0.7 * instant_slope
            
        self.last_cpu_t = cpu_t
        self.last_gpu_t = gpu_t
        
        bottleneck_severity = max(cpu, gpu)
        is_idle = (cpu < 20 and gpu < 15)
        is_light_load = (cpu < 25 and gpu < 20)
        
        temps_stable = (abs(self.thermal_slope) < 0.2)
        no_escalation = (self.thermal_slope <= 0.0)
        no_bottleneck = (bottleneck_severity <= 60.0)
        
        risk_rising = (future_risk - self.last_risk) > 0.05
        if self.current_state != CoolingState.RECOVERY:
            self.prediction_momentum = future_risk - self.last_risk
        
        # RECOVERY TIMER BUG
        if risk_rising or self.thermal_slope > 0.3:
            self.stable_duration = 0.0
        elif temps_stable and no_escalation and no_bottleneck:
            self.stable_duration += dt
            
        # 1. WORKLOAD FINGERPRINTING ENGINE
        if gpu > 70 and pwr > 60:
            if self.stable_duration > 15:
                self.workload_fingerprint = "SUSTAINED_GPU_RENDER"
            elif instant_slope > 0.5:
                self.workload_fingerprint = "GAME_LOADING"
            else:
                self.workload_fingerprint = "BENCHMARK_LOOP"
        elif cpu > 75 and gpu < 30:
            if instant_slope > 0.8:
                self.workload_fingerprint = "SHADER_COMPILATION"
            else:
                self.workload_fingerprint = "CPU_COMPILE"
        elif gpu > 20 and pwr < 35 and cpu < 30:
            self.workload_fingerprint = "BACKGROUND_ACCELERATION"
        elif cpu < 20 and gpu <= 20:
            if pwr < 25:
                self.workload_fingerprint = "IDLE_BROWSER"
            else:
                self.workload_fingerprint = "BACKGROUND_UPDATE"
        elif self.current_state == CoolingState.RECOVERY:
            self.workload_fingerprint = "THERMAL_RECOVERY"
        else:
            self.workload_fingerprint = "LIGHT_PRODUCTIVITY"

        # IDLE DOMINANCE LOGIC
        is_idle_dominant = (cpu < 15 and gpu < 20 and self.thermal_slope <= 0.0 and pwr < 25.0 and no_bottleneck and self.workload_fingerprint in ["IDLE_BROWSER", "LIGHT_PRODUCTIVITY", "BACKGROUND_UPDATE", "BACKGROUND_ACCELERATION"])
        
        self.idle_duration_total = getattr(self, "idle_duration_total", 0.0)
        if is_idle_dominant:
            self.idle_duration_total += dt
        else:
            self.idle_duration_total = 0.0
            
        safe_idle_clamp_active = self.idle_duration_total > 60.0

        # 2. THERMAL PHASE MODELING
        if instant_slope > 1.0:
            self.thermal_phase = "INITIAL_RAMP"
        elif instant_slope > 0.3:
            self.thermal_phase = "EARLY_ESCALATION"
        elif bottleneck_severity > 80 and abs(instant_slope) < 0.2:
            self.thermal_phase = "THERMAL_SATURATION"
        elif bottleneck_severity > 50 and abs(instant_slope) < 0.2:
            self.thermal_phase = "SUSTAINED_LOAD"
        elif self.current_state == CoolingState.RECOVERY:
            if self.stable_duration > 10:
                self.thermal_phase = "COOLING_STABILIZATION"
            else:
                self.thermal_phase = "RECOVERY"
        else:
            self.thermal_phase = "EQUILIBRIUM"

        # 3. THERMAL CAPACITY ESTIMATION (Headroom Estimator)
        thermal_ceiling = 95.0
        current_max_temp = max(cpu_t, gpu_t)
        self.thermal_headroom = max(0.0, thermal_ceiling - current_max_temp)
            
        # THERMAL EQUILIBRIUM BIAS (8. FUTURE THERMAL TRAJECTORY MODELING)
        cooling_active = self.current_fan_speed > 40.0
        self.equilibrium_bias_strength = 0.0
        if temps_stable and is_light_load and cooling_active:
            self.equilibrium_bias_strength = 0.05 * dt
            future_risk = max(0.0, future_risk - self.equilibrium_bias_strength)
            
        # BOTTLENECK CONSISTENCY FIX
        if no_bottleneck and no_escalation and is_light_load and future_risk > 0.8:
            future_risk = 0.75 
            
        # STALE COMPOSITE RISK RESET & RECOVERY MOMENTUM DAMPENING
        if is_idle_dominant:
            # AGGRESSIVE EQUILIBRIUM RECOVERY
            future_risk = min(future_risk, self.last_risk * 0.70)
            self.prediction_momentum *= 0.2
            self.stable_duration += dt * 2.0 # Accelerate thermal saturation memory decay
            self.escalation_reason = "IDLE EQUILIBRIUM ACTIVE"
        elif self.stable_duration > 10.0:
            decay_factor = max(0.85, 0.98 - 0.01 * (self.stable_duration / 10.0))
            future_risk = min(future_risk, self.last_risk * decay_factor)
        elif self.current_state == CoolingState.RECOVERY:
            future_risk = min(future_risk, self.last_risk * 0.85) # Aggressive dampening
        elif self.current_state == CoolingState.BALANCED and is_light_load:
            future_risk = min(future_risk, self.last_risk * 0.98)
            
        # 4. PREDICTIVE COOLING WINDOWS & 9. CONTEXTUAL ORCHESTRATION STRATEGIES
        self.predictive_cooling_window = "NONE"
        self.predictive_intent_class = "NOMINAL"
        
        if self.thermal_phase == "INITIAL_RAMP" and self.workload_fingerprint in ["GAME_LOADING", "BENCHMARK_LOOP", "SUSTAINED_GPU_RENDER"]:
            if self.thermal_headroom > 20:
                self.predictive_cooling_window = "GPU spike expected in 6s"
                self.predictive_intent_class = "PREDICTIVE_COOLING_ACTIVE"
        elif self.workload_fingerprint == "SHADER_COMPILATION":
            self.predictive_intent_class = "TOLERATE_SHORT_BURST"
        elif self.thermal_slope > 1.5 and pwr > 75.0:
            self.predictive_intent_class = "HEAVY_WORKLOAD_INIT"
        elif self.thermal_slope > 0.5 and gpu > 80:
            self.predictive_intent_class = "SUSTAINED_GPU_RAMP"
        elif is_light_load and temps_stable:
            self.predictive_intent_class = "IDLE_CONVERGENCE"
            
        # ESCALATION CONFIDENCE FILTERING
        # Ignore weak predictions, don't escalate aggressively if confidence is low
        self.escalation_confidence = 0.0
        if future_risk > 0.4:
            base_conf = future_risk
            # Positive slope increases confidence, negative decreases
            conf_mod = self.thermal_slope * 0.2
            # Workload intent increases confidence
            if self.predictive_intent_class in ["HEAVY_WORKLOAD_INIT", "SUSTAINED_GPU_RAMP", "PREDICTIVE_COOLING_ACTIVE"]:
                conf_mod += 0.3
            elif self.predictive_intent_class == "TOLERATE_SHORT_BURST":
                conf_mod -= 0.2  # Reduce confidence for expected short spikes
            self.escalation_confidence = min(1.0, max(0.0, base_conf + conf_mod))
            
        # Optional fallback from earlier laptop mode logic
        if self.laptop_mode_enabled and is_light_load and future_risk > 0.5:
            future_risk = future_risk * 0.6
            
        self.last_risk = future_risk
        
        # Hysteresis Condition Checks
        failsafe_trigger = (future_risk > 0.85 or gpu_t > 88.0 or cpu_t > 92.0)
        
        # Track FAILSAFE condition
        if failsafe_trigger and not (no_bottleneck and no_escalation and is_light_load):
            if self.condition_start_times["FAILSAFE"] == 0:
                self.condition_start_times["FAILSAFE"] = now
                self.escalation_reason = "CRITICAL_RISK_OR_TEMP"
        else:
            self.condition_start_times["FAILSAFE"] = 0
            if self.current_state != CoolingState.FAILSAFE:
                self.escalation_reason = "NONE"
            
        # 7. DYNAMIC CONFIDENCE THRESHOLDS
        confidence_threshold = 0.6
        if self.workload_fingerprint in ["BENCHMARK_LOOP", "SUSTAINED_GPU_RENDER"]:
            confidence_threshold = 0.4
        elif self.workload_fingerprint in ["IDLE_BROWSER", "LIGHT_PRODUCTIVITY", "SHADER_COMPILATION", "BACKGROUND_UPDATE", "BACKGROUND_ACCELERATION"]:
            confidence_threshold = 0.90
            
        # Track PERFORMANCE condition (Requires sustained confidence)
        sustained_utilization = (not is_idle_dominant) and (not is_light_load) and pwr > 25.0
        if future_risk > 0.55 and self.escalation_confidence > confidence_threshold and sustained_utilization:
            if self.condition_start_times["PERFORMANCE"] == 0:
                self.condition_start_times["PERFORMANCE"] = now
        else:
            self.condition_start_times["PERFORMANCE"] = 0
            if future_risk > 0.55 and self.escalation_confidence <= confidence_threshold:
                if self.workload_fingerprint == "BACKGROUND_ACCELERATION":
                    self.escalation_reason = "BACKGROUND ACTIVITY FILTERED"
                else:
                    self.escalation_reason = "LOW-CONFIDENCE ESCALATION REJECTED"
            elif future_risk > 0.55 and not sustained_utilization:
                self.escalation_reason = "WAITING FOR SUSTAINED LOAD"
            
        # FAILSAFE EXIT CONDITIONS & Track RECOVERY condition
        if self.current_state == CoolingState.FAILSAFE:
            failsafe_exit_criteria = (
                future_risk < 0.45 and
                temps_stable and
                no_escalation and
                no_bottleneck and
                self.stable_duration >= 20.0
            )
            if failsafe_exit_criteria:
                if self.condition_start_times["RECOVERY"] == 0:
                    self.condition_start_times["RECOVERY"] = now
            else:
                self.condition_start_times["RECOVERY"] = 0
                
        # Track IDLE condition
        if is_idle and cpu_t < 60 and gpu_t < 55:
            if self.condition_start_times["IDLE"] == 0:
                self.condition_start_times["IDLE"] = now
        else:
            self.condition_start_times["IDLE"] = 0

        # State Transitions (Smoothing and Context-Aware)
        next_state = self.current_state
        
        failsafe_duration = (now - self.condition_start_times["FAILSAFE"]) if self.condition_start_times["FAILSAFE"] else 0
        perf_duration = (now - self.condition_start_times["PERFORMANCE"]) if self.condition_start_times["PERFORMANCE"] else 0
        recovery_duration = (now - self.condition_start_times["RECOVERY"]) if self.condition_start_times["RECOVERY"] else 0
        idle_duration = (now - self.condition_start_times["IDLE"]) if self.condition_start_times["IDLE"] else 0

        # SAFE IDLE CLAMP
        if safe_idle_clamp_active and self.current_state in [CoolingState.PERFORMANCE, CoolingState.FAILSAFE]:
            next_state = CoolingState.BALANCED
            self.escalation_reason = "SAFE IDLE CLAMP ACTIVE"

        # Emergency override check (instant if absolutely critical)
        elif cpu_t >= 95 or gpu_t >= 90:
            next_state = CoolingState.FAILSAFE
            self.escalation_reason = "EMERGENCY_TEMP"

        elif self.current_state != CoolingState.FAILSAFE:
            if failsafe_duration > 8.0:
                # Progressive escalation smoothing: Quiet -> Balanced -> Performance -> Failsafe
                if self.current_state == CoolingState.QUIET:
                    next_state = CoolingState.BALANCED
                    self.escalation_reason = "PROGRESSIVE_ESCALATION"
                elif self.current_state == CoolingState.BALANCED:
                    next_state = CoolingState.PERFORMANCE
                    self.escalation_reason = "PROGRESSIVE_ESCALATION"
                else:
                    next_state = CoolingState.FAILSAFE
            elif perf_duration > 5.0 and self.current_state in [CoolingState.BALANCED, CoolingState.QUIET, CoolingState.RECOVERY]:
                if self.current_state == CoolingState.QUIET:
                    next_state = CoolingState.BALANCED
                    self.escalation_reason = "PROGRESSIVE_ESCALATION"
                else:
                    next_state = CoolingState.PERFORMANCE
                    self.escalation_reason = "SUSTAINED_CONFIDENCE"

        # Idle Relaxation & Recovery from Failsafe
        if self.current_state == CoolingState.FAILSAFE:
            if recovery_duration > 0.0:
                next_state = CoolingState.RECOVERY
                self.escalation_reason = "RECOVERING"
            elif idle_duration > 30.0:
                next_state = CoolingState.RECOVERY
                self.escalation_reason = "IDLE_RECOVERY"

        if self.current_state == CoolingState.RECOVERY:
            # RECOVERY INTELLIGENCE
            # Reduce escalation sensitivity temporarily, prioritize normalization
            self.recovery_stabilization_score = min(100.0, self.stable_duration * 3.33) # 30s to 100%
            if (future_risk < 0.3 and self.stable_duration > 30.0) or idle_duration > 30.0:
                next_state = CoolingState.BALANCED
                self.escalation_reason = "NONE"
                
        if self.current_state == CoolingState.PERFORMANCE:
            if future_risk < 0.45 and perf_duration == 0:
                next_state = CoolingState.BALANCED
            elif idle_duration > 30.0:
                next_state = CoolingState.BALANCED

        if self.current_state == CoolingState.BALANCED:
            if idle_duration > 45.0 or (future_risk < 0.2 and cpu_t < 50) or is_idle_dominant:
                next_state = CoolingState.QUIET

        if self.current_state == CoolingState.QUIET:
            if future_risk > 0.35 and self.escalation_confidence > 0.5 and not is_idle_dominant:
                next_state = CoolingState.BALANCED

        self.current_state = next_state
        
        # Override to ensure idle clamp blocks PERFORMANCE/FAILSAFE
        if safe_idle_clamp_active and self.current_state in [CoolingState.PERFORMANCE, CoolingState.FAILSAFE]:
            self.current_state = CoolingState.BALANCED
            self.escalation_reason = "SAFE IDLE CLAMP ACTIVE"
        
        # ACOUSTIC COMFORT OPTIMIZATION
        self.acoustic_optimization_active = (self.current_state in [CoolingState.QUIET, CoolingState.BALANCED, CoolingState.RECOVERY]) and not risk_rising
        
        # Target Fan Speeds & FAN NORMALIZATION
        if self.current_state == CoolingState.FAILSAFE:
            self.target_fan_speed = 100.0
            self.stabilization_active = False
        elif self.current_state == CoolingState.PERFORMANCE:
            self.target_fan_speed = 85.0
            self.stabilization_active = False
        elif self.current_state == CoolingState.RECOVERY:
            # Gradually reduce fan speed, smooth ramp-down
            self.target_fan_speed = max(45.0, self.current_fan_speed - 2.0 * dt)
            self.stabilization_active = True
            if self.acoustic_optimization_active:
                self.escalation_reason = "ACOUSTIC RECOVERY ACTIVE"
        elif self.current_state == CoolingState.BALANCED:
            self.target_fan_speed = 45.0
            # 4. PREDICTIVE COOLING WINDOWS: Soft predictive ramping
            if self.predictive_intent_class == "PREDICTIVE_COOLING_ACTIVE":
                self.target_fan_speed = max(self.target_fan_speed, 65.0)
            self.stabilization_active = False
        else: # QUIET
            self.target_fan_speed = 30.0
            self.stabilization_active = False

        # 5. ACOUSTIC COMFORT MODELING (Fan Control Smoothing)
        ramp_up = 5.0    # max +5% RPM/sec increase
        ramp_down = 8.0  # max -8% RPM/sec decrease
        
        if is_idle_dominant:
            ramp_up = 0.5 # Aggressively limit fan ramp-up during idle
            ramp_down = 4.0
        elif self.acoustic_optimization_active or self.workload_fingerprint == "CUTSCENE":
            ramp_up = 1.5 # Very slow ramp up for acoustic comfort, avoid oscillation
            ramp_down = 3.0 # Slow decay to avoid jarring shifts
            
        delta = self.target_fan_speed - self.current_fan_speed
        
        if delta > 0:
            self.current_fan_speed += min(delta, ramp_up * dt)
        elif delta < 0:
            self.current_fan_speed -= min(abs(delta), ramp_down * dt)
            
        self.current_fan_speed = float(np.clip(self.current_fan_speed, 0.0, 100.0))

        # Apply Hardware Mode
        if self.current_state == CoolingState.RECOVERY:
            target_mode = "BALANCED"
        else:
            target_mode = self.current_state.value

        # Determine Transition Severity for adaptive hold duration
        trans_severity = "MEDIUM"
        if target_mode == "FAILSAFE" or self.current_state == CoolingState.FAILSAFE:
            trans_severity = "CRITICAL"
        elif target_mode == "PERFORMANCE":
            trans_severity = "HIGH"
        elif target_mode == "QUIET":
            trans_severity = "LOW"

        self.thermal_controller.set_mode(target_mode, reason=self.escalation_reason, severity=trans_severity)
        self.thermal_controller.reconcile()
        
        self.current_thermal_mode = self.thermal_controller.get_current_mode()

        # 11. ORCHESTRATION INTELLIGENCE SCORE
        ti_score = (self.escalation_confidence * 30) + (self.recovery_stabilization_score * 0.3) + (20 if self.acoustic_optimization_active else 0)
        if self.workload_fingerprint != "IDLE_BROWSER":
            ti_score += 10 # successful classification bonus
        if self.thermal_phase in ["COOLING_STABILIZATION", "EQUILIBRIUM"]:
            ti_score += 10 # stability bonus

        # DEBUG TELEMETRY (Orchestration Intelligence)
        diagnostics = {
            "current_composite_risk": round(future_risk, 4),
            "raw_prediction": round(raw_prediction, 4),
            "recovery_timer": round(recovery_duration, 2),
            "stable_duration": round(self.stable_duration, 2),
            "failsafe_latch_state": (self.current_state == CoolingState.FAILSAFE),
            "thermal_slope": round(self.thermal_slope, 4),
            "prediction_momentum": round(self.prediction_momentum, 4),
            "escalation_reason": self.escalation_reason,
            "escalation_confidence": round(self.escalation_confidence, 2),
            "predictive_intent_class": self.predictive_intent_class,
            "acoustic_optimization_active": self.acoustic_optimization_active,
            "equilibrium_bias_strength": round(self.equilibrium_bias_strength, 4),
            "recovery_stabilization_score": round(self.recovery_stabilization_score, 1),
            "workload_fingerprint": self.workload_fingerprint,
            "thermal_phase": self.thermal_phase,
            "thermal_headroom": round(self.thermal_headroom, 1),
            "predictive_cooling_window": self.predictive_cooling_window,
            "transition_intelligence_score": round(ti_score, 1),
            "idle_clamp_active": safe_idle_clamp_active,
            "hardware_controller": self.thermal_controller.get_telemetry()
        }

        return self.current_fan_speed, self.current_state.value, self.stabilization_active, diagnostics
