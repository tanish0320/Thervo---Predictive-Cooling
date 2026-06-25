import time
import math
import logging
from enum import Enum
from collections import deque
from src.hardware.thermal_mode_controller import ThermalModeController as HardwareController

class ThermalMode(Enum):
    """Expanded thermal operation modes for semantic runtime."""
    QUIET = 1
    BALANCED = 2
    PERFORMANCE = 3
    FAILSAFE = 4
    SILENT_RECOVERY = 5

class WorkloadPhase(Enum):
    """Semantic workload fingerprints."""
    IDLE = 1
    INITIAL_RAMP = 2
    SUSTAINED_LOAD = 3
    COOLDOWN = 4
    BACKGROUND_NOISE = 5

class ThermalModeController:
    """
    Advanced runtime predictive thermal orchestration engine.
    
    Includes:
    - Adaptive Telemetry Rate (dynamic polling Hz)
    - Context-Aware Adaptive EMA Smoothing
    - Risk Velocity & Acceleration Prediction
    - Cooling Effectiveness Feedback (Δrisk / Δfan_rpm)
    - Thermal Saturation Prediction (ETA)
    - Prediction Stability Confidence
    - Session Heat Accumulation (soak)
    - Silent Recovery Mode
    """
    
    MIN_MODE_HOLD_SECONDS = 15.0
    PERFORMANCE_ENTER_THRESHOLD = 0.85
    PERFORMANCE_EXIT_THRESHOLD = 0.70
    FAILSAFE_THRESHOLD = 0.95
    
    COOLDOWN_MAX_SWITCHES = 5
    COOLDOWN_WINDOW_SECONDS = 120.0
    
    def __init__(self):
        self.hardware_controller = HardwareController()
        
        # Initialize active_mode based on current actual hardware mode to prevent boot desync
        hw_init = self.hardware_controller.actual_hardware_mode
        if hw_init == "PERFORMANCE":
            self.active_mode = ThermalMode.PERFORMANCE
        elif hw_init == "BALANCED":
            self.active_mode = ThermalMode.BALANCED
        else:
            self.active_mode = ThermalMode.QUIET
            
        self.previous_smoothed_risk = 0.0
        self.last_switch_time = 0.0
        self.switch_history = deque()
        self.cooldown_locked = False
        
        self.last_raw_risk = 0.0
        self.risk_velocity = 0.0
        self.thermal_acceleration = 0.0
        self.last_fan_rpm = 0.0
        self.cooling_effectiveness = 1.0
        self.thermal_soak_accumulation = 0.0
        self.prediction_stability_confidence = 1.0
        self.current_alpha = 0.20
        
        self.risk_history = deque(maxlen=10)
        self.gpu_power_history = deque(maxlen=10)
        self.semantic_status = "SYSTEM BOOT"
        
        self.last_eval_time = time.time()
        
    def _log(self, tag: str, message: str):
        print(f"[{tag}] {message}")
        
    def get_telemetry_polling_rate(self) -> int:
        """Returns dynamically adjusted polling Hz based on active mode."""
        if self.active_mode == ThermalMode.QUIET:
            return 2
        elif self.active_mode == ThermalMode.BALANCED:
            return 4
        elif self.active_mode == ThermalMode.PERFORMANCE:
            return 8
        elif self.active_mode == ThermalMode.FAILSAFE:
            return 12
        elif self.active_mode == ThermalMode.SILENT_RECOVERY:
            return 2
        return 2

    def get_adaptive_ema_alpha(self, phase: WorkloadPhase) -> float:
        """Context-aware EMA. Calmer idle, faster gaming response."""
        if self.active_mode == ThermalMode.FAILSAFE or phase == WorkloadPhase.INITIAL_RAMP:
            return 0.60
        elif phase == WorkloadPhase.SUSTAINED_LOAD:
            return 0.40
        elif phase == WorkloadPhase.IDLE or phase == WorkloadPhase.BACKGROUND_NOISE:
            return 0.40  # Increased from 0.10 to aggressively decay stale risk during idle
        return 0.25

    def _calculate_velocity_and_acceleration(self, current_risk: float, dt: float):
        if dt <= 0:
            dt = 0.1
        velocity = (current_risk - self.last_raw_risk) / dt
        self.thermal_acceleration = (velocity - self.risk_velocity) / dt
        self.risk_velocity = velocity
        self.last_raw_risk = current_risk
        
    def _update_cooling_effectiveness(self, current_risk: float, current_fan_rpm: float):
        """Track whether cooling actions actually reduce risk."""
        delta_risk = current_risk - self.last_raw_risk
        delta_fan = current_fan_rpm - self.last_fan_rpm
        if delta_fan > 50:
            # Effectiveness is negative risk change per positive fan change
            self.cooling_effectiveness = - (delta_risk / (delta_fan / 1000.0))
        self.last_fan_rpm = current_fan_rpm

    def _estimate_saturation_eta(self, current_risk: float) -> float:
        """Predict time-to-saturation based on risk velocity."""
        if self.risk_velocity > 0.001:
            return max(0.0, (1.0 - current_risk) / self.risk_velocity)
        return float('inf')

    def _calculate_stability_confidence(self):
        """Measure inference oscillation and volatility."""
        if len(self.risk_history) < 2:
            self.prediction_stability_confidence = 1.0
            return
            
        direction_changes = 0
        for i in range(1, len(self.risk_history) - 1):
            diff1 = self.risk_history[i] - self.risk_history[i-1]
            diff2 = self.risk_history[i+1] - self.risk_history[i]
            if diff1 * diff2 < 0:
                direction_changes += 1
                
        penalty = min(1.0, direction_changes * 0.15)
        self.prediction_stability_confidence = max(0.1, 1.0 - penalty)
        
    def _evaluate_gpu_transient(self, gpu_power: float) -> float:
        """Monitor sudden power ramp velocity."""
        self.gpu_power_history.append(gpu_power)
        if len(self.gpu_power_history) < 2:
            return 0.0
        return self.gpu_power_history[-1] - self.gpu_power_history[0]

    def _update_heat_accumulation(self, current_risk: float, dt: float):
        """Track long-session chassis saturation and thermal fatigue."""
        if current_risk > 0.5:
            self.thermal_soak_accumulation += (current_risk - 0.5) * dt
        else:
            self.thermal_soak_accumulation = max(0.0, self.thermal_soak_accumulation - dt * 0.5)

    def _update_cooldown_status(self, current_time: float):
        """Cleans up expired switch history and updates cooldown lock status."""
        while self.switch_history and (current_time - self.switch_history[0]) > self.COOLDOWN_WINDOW_SECONDS:
            self.switch_history.popleft()
            
        if len(self.switch_history) >= self.COOLDOWN_MAX_SWITCHES:
            if not self.cooldown_locked:
                self.cooldown_locked = True
                self._log("COOLDOWN_LOCK", "Too many mode transitions. Locking state for stability.")
        else:
            if self.cooldown_locked and len(self.switch_history) < 2:
                self.cooldown_locked = False
                self._log("COOLDOWN_UNLOCK", "State transition lock released.")

    def switch_mode(self, target_mode: ThermalMode, reason: str = ""):
        current_time = time.time()
        
        # Determine target hardware mode and severity mapping
        hw_mode = "BALANCED"
        severity = "MEDIUM"
        
        if target_mode == ThermalMode.FAILSAFE:
            hw_mode = "FAILSAFE"
            severity = "CRITICAL"
        elif target_mode == ThermalMode.PERFORMANCE:
            hw_mode = "PERFORMANCE"
            severity = "HIGH"
        elif target_mode == ThermalMode.QUIET:
            hw_mode = "QUIET"
            severity = "LOW"
        elif target_mode == ThermalMode.SILENT_RECOVERY:
            hw_mode = "QUIET"
            severity = "LOW"

        success = self.hardware_controller.set_mode(hw_mode, reason=reason, severity=severity)
        if success:
            self.active_mode = target_mode
            self.last_switch_time = current_time
            self.switch_history.append(current_time)
            self._log("SWITCH", f"Transitioned to {self.active_mode.name} - {reason}")
            self.hardware_controller.reconcile()
        else:
            self._log("SWITCH_REJECTED", f"Hardware controller rejected transition to {target_mode.name}")
        
    def evaluate(self, 
                 raw_risk: float, 
                 gpu_power: float = 0.0, 
                 current_fan_rpm: float = 0.0,
                 workload_phase: WorkloadPhase = WorkloadPhase.IDLE) -> dict:
        """
        Main predictive orchestration hook. Returns rich telemetry dict.
        """
        current_time = time.time()
        dt = current_time - self.last_eval_time
        self.last_eval_time = current_time

        try:
            if math.isnan(raw_risk):
                raw_risk = self.last_raw_risk
            raw_risk = max(0.0, min(1.0, raw_risk))
            self.risk_history.append(raw_risk)

            # Update switch throttling/cooldown status
            self._update_cooldown_status(current_time)

            # 1. Advanced Metrics Calculation
            self._calculate_velocity_and_acceleration(raw_risk, dt)
            self._update_cooling_effectiveness(raw_risk, current_fan_rpm)
            self._estimate_saturation_eta(raw_risk)
            self._calculate_stability_confidence()
            gpu_transient = self._evaluate_gpu_transient(gpu_power)
            self._update_heat_accumulation(raw_risk, dt)

            # 2. Adaptive Smoothing (Confidence Weighted)
            self.current_alpha = self.get_adaptive_ema_alpha(workload_phase) * self.prediction_stability_confidence
            smoothed_risk = (self.current_alpha * raw_risk) + ((1.0 - self.current_alpha) * self.previous_smoothed_risk)
            
            # Idle-Dominant Clamp: aggressively suppress performance escalation and decay stale memory
            if workload_phase == WorkloadPhase.IDLE:
                smoothed_risk = min(smoothed_risk, 0.25)
                self.thermal_soak_accumulation = max(0.0, self.thermal_soak_accumulation - dt * 10.0)

            self.previous_smoothed_risk = smoothed_risk

            # 3. Background Process Filtering
            if workload_phase == WorkloadPhase.BACKGROUND_NOISE and smoothed_risk < 0.6:
                self.semantic_status = "BACKGROUND PROCESS FILTERED"
                return self._build_telemetry()

            # 4. Predictive Pre-cooling
            predictive_pre_cooling = False
            if workload_phase == WorkloadPhase.INITIAL_RAMP and gpu_transient > 15.0 and self.risk_velocity > 0.05:
                predictive_pre_cooling = True
                self.semantic_status = "PREDICTIVE PRE-COOLING ACTIVE"

            # 5. Core State Machine & Hysteresis
            switch_target = None
            reason = ""
            
            # Dynamically match active mode's adaptive hold duration from hardware controller
            active_hold_duration = 20.0
            if self.active_mode == ThermalMode.FAILSAFE:
                active_hold_duration = 0.0
            elif self.active_mode == ThermalMode.PERFORMANCE:
                active_hold_duration = 30.0
            elif self.active_mode in (ThermalMode.QUIET, ThermalMode.SILENT_RECOVERY):
                active_hold_duration = 10.0
                
            hold_expired = (current_time - self.last_switch_time) >= active_hold_duration
            
            # Heat soak forces earlier cooling triggers
            soak_penalty = min(0.15, self.thermal_soak_accumulation * 0.001)
            enter_thresh = max(0.50, self.PERFORMANCE_ENTER_THRESHOLD - soak_penalty)
            exit_thresh = max(0.40, self.PERFORMANCE_EXIT_THRESHOLD - soak_penalty)

            if self.active_mode in (ThermalMode.QUIET, ThermalMode.SILENT_RECOVERY, ThermalMode.BALANCED):
                if smoothed_risk >= self.FAILSAFE_THRESHOLD:
                    switch_target = ThermalMode.FAILSAFE
                    reason = "CRITICAL RISK ESCALATION"
                elif (smoothed_risk > enter_thresh or predictive_pre_cooling) and workload_phase != WorkloadPhase.BACKGROUND_NOISE:
                    switch_target = ThermalMode.PERFORMANCE
                    reason = "SUSTAINED LOAD DETECTED"
                    if predictive_pre_cooling:
                        reason = "PREDICTIVE GPU TRANSIENT"
                elif smoothed_risk > 0.45 and self.active_mode in (ThermalMode.QUIET, ThermalMode.SILENT_RECOVERY):
                    switch_target = ThermalMode.BALANCED
                    reason = "MODERATE LOAD ESCALATION"
                    
            elif self.active_mode == ThermalMode.PERFORMANCE:
                if smoothed_risk >= self.FAILSAFE_THRESHOLD:
                    switch_target = ThermalMode.FAILSAFE
                    reason = "CRITICAL RISK ESCALATION"
                elif smoothed_risk < exit_thresh and workload_phase in (WorkloadPhase.COOLDOWN, WorkloadPhase.IDLE):
                    switch_target = ThermalMode.SILENT_RECOVERY
                    reason = "WORKLOAD CONCLUDED - SILENT RECOVERY"
                elif smoothed_risk < exit_thresh:
                    switch_target = ThermalMode.BALANCED
                    reason = "LOAD RELAXED"

            elif self.active_mode == ThermalMode.FAILSAFE:
                if smoothed_risk < 0.70:
                    switch_target = ThermalMode.PERFORMANCE
                    reason = "RECOVERY SUCCESSFUL"
                    
            elif self.active_mode == ThermalMode.BALANCED:
                 if smoothed_risk < exit_thresh - 0.10:
                     switch_target = ThermalMode.QUIET
                     reason = "EQUILIBRIUM ACHIEVED"

            elif self.active_mode == ThermalMode.SILENT_RECOVERY:
                if smoothed_risk < 0.30 and self.thermal_soak_accumulation < 50:
                    switch_target = ThermalMode.QUIET
                    reason = "EQUILIBRIUM ACHIEVED"

            if switch_target and switch_target != self.active_mode:
                if self.cooldown_locked and switch_target != ThermalMode.FAILSAFE:
                    self._log("COOLDOWN_BLOCKED", f"Blocked transition to {switch_target.name} due to active cooldown lock.")
                elif hold_expired or switch_target == ThermalMode.FAILSAFE:
                    self.switch_mode(switch_target, reason)
                else:
                    self._log("HOLD", f"Hold timer blocking transition to {switch_target.name}")

            # Update semantic status safely if not already explicitly set
            if not predictive_pre_cooling:
                if self.cooldown_locked:
                    self.semantic_status = "COOLDOWN LOCK ACTIVE"
                elif self.active_mode == ThermalMode.SILENT_RECOVERY:
                    self.semantic_status = "SILENT RECOVERY ACTIVE"
                elif self.thermal_soak_accumulation > 200:
                    self.semantic_status = "SESSION HEAT ACCUMULATION DETECTED"
                elif self.cooling_effectiveness < 0.1 and current_fan_rpm > 3000:
                    self.semantic_status = "COOLING EFFECTIVENESS REDUCED"
                elif self.risk_velocity > 0.1:
                    self.semantic_status = "RISK VELOCITY INCREASING"
                elif self._estimate_saturation_eta(smoothed_risk) < 60:
                    self.semantic_status = "THERMAL SATURATION APPROACHING"
                else:
                    self.semantic_status = f"MODE: {self.active_mode.name}"

            return self._build_telemetry()

        except Exception as e:
            self._log("CRITICAL", f"Evaluation exception: {e}")
            if self.active_mode != ThermalMode.QUIET:
                self.switch_mode(ThermalMode.QUIET, "EXCEPTION FAILSAFE")
            return self._build_telemetry()

    def update(self, future_risk: float, current_telemetry: dict = None) -> tuple[float, str, bool, dict]:
        """
        Drop-in replacement for CoolingPolicyEngine.update.
        """
        if current_telemetry is None:
            current_telemetry = {}
            
        cpu = current_telemetry.get("cpu", current_telemetry.get("cpu_util", 0))
        gpu = current_telemetry.get("gpu", current_telemetry.get("gpu_util", 0))
        cpu_t = current_telemetry.get("cpu_temp", 40)
        gpu_t = current_telemetry.get("gpu_temp", 40)
        pwr = current_telemetry.get("power_draw", 15.0)
        cpu_p = current_telemetry.get("cpu_power", 7.0 + 85.0 * (cpu / 100.0))
        gpu_p = current_telemetry.get("gpu_power", 0.0)

        # Robust True Idle Detection (Low Package Power + Low dGPU power/util + Stable Thermals)
        is_safe_idle = (cpu < 25 and gpu < 10 and cpu_p < 20.0 and gpu_p < 15.0 and max(cpu_t, gpu_t) < 62.0)

        if gpu > 70:
            wp_phase = WorkloadPhase.SUSTAINED_LOAD
            fingerprint = "SUSTAINED_GPU_RENDER"
        elif cpu > 70 and gpu < 30:
            wp_phase = WorkloadPhase.SUSTAINED_LOAD
            fingerprint = "CPU_COMPILE"
        elif is_safe_idle:
            wp_phase = WorkloadPhase.IDLE
            fingerprint = "IDLE_BROWSER"
            # Override future_risk to enforce idle baseline
            future_risk = min(future_risk, 0.20)
        else:
            wp_phase = WorkloadPhase.INITIAL_RAMP
            fingerprint = "LIGHT_PRODUCTIVITY"
            
        # Get current RPM for feedback
        current_rpm = self.last_fan_rpm # Approximate

        # Call evaluate
        diagnostics = self.evaluate(future_risk, gpu_power=pwr, current_fan_rpm=current_rpm, workload_phase=wp_phase)
        
        # Calculate target fan based on mode
        target_fan = 30.0
        is_stabilizing = False
        
        if self.active_mode == ThermalMode.FAILSAFE:
            target_fan = 100.0
        elif self.active_mode == ThermalMode.PERFORMANCE:
            target_fan = 85.0
        elif self.active_mode == ThermalMode.BALANCED:
            target_fan = 55.0
        elif self.active_mode == ThermalMode.SILENT_RECOVERY:
            target_fan = 45.0
            is_stabilizing = True
        elif self.active_mode == ThermalMode.QUIET:
            target_fan = 30.0

        # Simulate fan rpm reaching target for next iteration (simple model)
        self.last_fan_rpm = target_fan * 50.0  # 100% -> 5000 RPM

        # Add remaining frontend required fields
        diagnostics["workload_fingerprint"] = fingerprint
        diagnostics["thermal_phase"] = wp_phase.name
        diagnostics["thermal_headroom"] = max(0.0, 95.0 - max(cpu_t, gpu_t))
        diagnostics["predictive_cooling_window"] = "NONE"
        diagnostics["escalation_reason"] = self.semantic_status
        diagnostics["idle_clamp_active"] = (wp_phase == WorkloadPhase.IDLE)
        diagnostics["transition_intelligence_score"] = self.prediction_stability_confidence * 100
        diagnostics["acoustic_optimization_active"] = (self.active_mode in [ThermalMode.QUIET, ThermalMode.SILENT_RECOVERY])
        
        # Hardware Controller output
        self.hardware_controller.reconcile()
        
        # Sync high-level mode with hardware controller (handles manual changes / init)
        if self.hardware_controller.sync_status == "SYNCED":
            hw_mode = self.hardware_controller.actual_hardware_mode
            if hw_mode == "PERFORMANCE" and self.active_mode not in (ThermalMode.PERFORMANCE, ThermalMode.FAILSAFE):
                self.active_mode = ThermalMode.PERFORMANCE
                self.last_switch_time = time.time()
            elif hw_mode == "BALANCED" and self.active_mode != ThermalMode.BALANCED:
                self.active_mode = ThermalMode.BALANCED
                self.last_switch_time = time.time()
            elif hw_mode == "QUIET" and self.active_mode not in (ThermalMode.QUIET, ThermalMode.SILENT_RECOVERY):
                self.active_mode = ThermalMode.QUIET
                self.last_switch_time = time.time()
            
        diagnostics["hardware_controller"] = self.hardware_controller.get_telemetry()

        return target_fan, self.active_mode.name, is_stabilizing, diagnostics

    def _build_telemetry(self) -> dict:
        """Packages rich orchestration state for UI and dashboards."""
        eta = self._estimate_saturation_eta(self.previous_smoothed_risk)
        return {
            "active_mode": self.active_mode.name,
            "semantic_status": self.semantic_status,
            "telemetry_hz": self.get_telemetry_polling_rate(),
            "adaptive_ema_alpha": round(self.current_alpha, 3),
            "smoothed_risk": round(self.previous_smoothed_risk, 3),
            "risk_velocity": round(self.risk_velocity, 4),
            "thermal_acceleration": round(self.thermal_acceleration, 4),
            "cooling_effectiveness_score": round(self.cooling_effectiveness, 3),
            "saturation_eta_seconds": round(eta, 1) if eta != float('inf') else -1.0,
            "prediction_stability": round(self.prediction_stability_confidence, 2),
            "thermal_soak_accumulation": round(self.thermal_soak_accumulation, 1),
            "gpu_power_transient_score": round(self._evaluate_gpu_transient(self.gpu_power_history[-1] if self.gpu_power_history else 0), 2),
            "forecast_30s": round(min(1.0, max(0.0, self.previous_smoothed_risk + self.risk_velocity * 30)), 3),
            "forecast_60s": round(min(1.0, max(0.0, self.previous_smoothed_risk + self.risk_velocity * 60)), 3),
            "forecast_120s": round(min(1.0, max(0.0, self.previous_smoothed_risk + self.risk_velocity * 120)), 3),
        }
