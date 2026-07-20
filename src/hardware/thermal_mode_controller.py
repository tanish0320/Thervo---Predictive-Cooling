import subprocess
import logging
import os
import time

logger = logging.getLogger(__name__)

class ThermalModeController:
    """
    Controller for Lenovo Legion Toolkit thermal/performance modes.
    Manages Quiet, Balanced, and Performance modes with hysteresis and safety fallbacks.
    Acts as the Single Source of Truth for hardware mode.
    """
    def __init__(self, cli_path=None):
        if cli_path is None:
            local_app_data = os.environ.get("LOCALAPPDATA", r"C:\Users\urbra\AppData\Local")
            self.cli_path = os.path.join(local_app_data, "Programs", "LenovoLegionToolkit", "llt.exe")
        else:
            self.cli_path = cli_path
            
        self.desired_mode = "BALANCED"
        self.actual_hardware_mode = "BALANCED"

        # ponytail: LLT CLI unresponsive backoff - avoid burning ~6s per tick
        # retrying a hardware call that's already known to fail; retry every
        # llt_backoff_sec instead of every reconcile(). Must be set before the
        # initial hardware query below, which reads these attributes.
        self.llt_unresponsive = False
        self.llt_backoff_sec = 60.0
        self.last_llt_failure_time = 0.0

        # Query initial hardware mode on startup to avoid boot desync
        self.actual_hardware_mode = self.get_current_mode_from_hardware()
        self.desired_mode = self.actual_hardware_mode
        self.sync_status = "SYNCED"

        self.last_transition_time = 0.0
        self.last_attempt_time = 0.0
        self.min_hold_duration = 30.0  # Dynamic hold duration
        self.adaptive_hold_duration = 30.0
        self.mode_transition_cooldown = 5.0

        self.last_transition_reason = "INIT"
        self.rejected_transitions = 0
        self.llt_response_status = "OK"
        
        logger.info(f"ThermalModeController initialized with CLI path: {self.cli_path}. Detected mode: {self.actual_hardware_mode}")

    def get_current_mode_from_hardware(self) -> str:
        """Queries actual hardware state from Lenovo Legion Toolkit."""
        if not os.path.exists(self.cli_path):
            return self.desired_mode
        if self.llt_unresponsive and (time.time() - self.last_llt_failure_time) < self.llt_backoff_sec:
            return self.actual_hardware_mode

        try:
            result = subprocess.run(
                [self.cli_path, "feature", "get", "power-mode"],
                capture_output=True,
                text=True,
                timeout=2.0
            )
            if result.returncode == 0:
                output = result.stdout.strip().upper()
                if "QUIET" in output:
                    return "QUIET"
                elif "BALANCE" in output:
                    return "BALANCED"
                elif "PERFORMANCE" in output:
                    return "PERFORMANCE"
        except Exception as e:
            logger.debug(f"Hardware verify failed: {e}")
            
        return self.actual_hardware_mode

    def get_current_mode(self) -> str:
        """Returns the actual confirmed hardware mode, NOT the optimistic desired mode."""
        return self.actual_hardware_mode

    def reconcile(self) -> bool:
        """State consistency validation. Ensures hardware matches desired."""
        now = time.time()
        
        # Periodic query to sync with manual changes (every 5 seconds)
        if not hasattr(self, "_last_hw_query_time"):
            self._last_hw_query_time = 0.0
            
        if (now - self._last_hw_query_time) >= 5.0:
            self._last_hw_query_time = now
            actual = self.get_current_mode_from_hardware()
            if actual != self.actual_hardware_mode:
                logger.info(f"Manual hardware mode change detected: {self.actual_hardware_mode} -> {actual}")
                self.actual_hardware_mode = actual
                self.desired_mode = actual
                self.sync_status = "SYNCED"
        
        if self.actual_hardware_mode == self.desired_mode:
            self.sync_status = "SYNCED"
            return True
            
        if (now - self.last_attempt_time) < self.mode_transition_cooldown:
            return False
            
        self.last_attempt_time = now
        self.sync_status = "PENDING"
        
        logger.info(f"Reconciling hardware mode to {self.desired_mode}")

        llt_in_backoff = self.llt_unresponsive and (now - self.last_llt_failure_time) < self.llt_backoff_sec

        if os.path.exists(self.cli_path) and not llt_in_backoff:
            try:
                cli_val = "balance" if self.desired_mode == "BALANCED" else self.desired_mode.lower()
                result = subprocess.run(
                    [self.cli_path, "feature", "set", "power-mode", cli_val],
                    capture_output=True,
                    text=True,
                    timeout=3.0
                )
                if result.returncode == 0:
                    self.llt_response_status = "OK"
                    self.llt_unresponsive = False
                else:
                    self.llt_response_status = f"ERROR: {result.stderr.strip()}"
                    logger.warning(f"LLT set failed: {self.llt_response_status}")
                    self.llt_unresponsive = True
                    self.last_llt_failure_time = now
            except Exception as e:
                self.llt_response_status = f"EXCEPTION: {e}"
                logger.error(self.llt_response_status)
                self.llt_unresponsive = True
                self.last_llt_failure_time = now

        # Verify immediately
        actual = self.get_current_mode_from_hardware()
        if actual == self.desired_mode:
            logger.info(f"Hardware verified: {actual}")
            self.actual_hardware_mode = actual
            self.sync_status = "SYNCED"
            self.last_transition_time = now
            return True
        else:
            logger.warning(f"Hardware verification failed. Expected {self.desired_mode}, got {actual}")
            self.actual_hardware_mode = actual
            self.sync_status = "DESYNCED"
            return False

    def set_mode(self, mode: str, reason: str = "POLICY", severity: str = "MEDIUM") -> bool:
        """
        Request a mode change. Enforces adaptive minimum hold duration and cooldown.
        """
        mode = mode.upper()
        if mode not in ["QUIET", "BALANCED", "PERFORMANCE", "FAILSAFE"]:
            logger.warning(f"Invalid mode requested: {mode}")
            return False
            
        target_mode = "PERFORMANCE" if mode == "FAILSAFE" else mode
        now = time.time()
        
        # Adaptive hold duration calculation
        if severity == "LOW":
            self.adaptive_hold_duration = 10.0
        elif severity == "MEDIUM":
            self.adaptive_hold_duration = 20.0
        elif severity == "HIGH":
            self.adaptive_hold_duration = 30.0
        elif severity == "CRITICAL" or mode == "FAILSAFE":
            self.adaptive_hold_duration = 60.0
        else:
            self.adaptive_hold_duration = self.min_hold_duration
        
        if target_mode != self.desired_mode:
            # FAILSAFE bypasses all hold duration limits
            if mode != "FAILSAFE":
                # Check hold duration
                if (now - self.last_transition_time) < self.adaptive_hold_duration:
                    logger.debug(f"Adaptive Hysteresis active. Holding {self.actual_hardware_mode}.")
                    self.rejected_transitions += 1
                    return False
                    
                # Check cooldown (between successful transitions)
                if (now - self.last_transition_time) < self.mode_transition_cooldown:
                    self.rejected_transitions += 1
                    return False

            logger.info(f"Requested mode change: {self.desired_mode} -> {target_mode} ({reason} - Severity: {severity})")
            self.desired_mode = target_mode
            self.last_transition_reason = reason
            self.sync_status = "PENDING"
            
        return self.reconcile()

    def get_telemetry(self) -> dict:
        """Returns debug telemetry for UI visibility."""
        now = time.time()
        lock_timer = max(0.0, self.adaptive_hold_duration - (now - self.last_transition_time))
        cooldown_timer = max(0.0, self.mode_transition_cooldown - (now - self.last_attempt_time))
        
        return {
            "desired_mode": self.desired_mode,
            "actual_hardware_mode": self.actual_hardware_mode,
            "last_transition_reason": self.last_transition_reason,
            "transition_lock_timer": round(lock_timer, 1),
            "transition_cooldown_timer": round(cooldown_timer, 1),
            "adaptive_hold_duration": self.adaptive_hold_duration,
            "hardware_sync_status": self.sync_status,
            "rejected_transitions": self.rejected_transitions,
            "llt_response_status": self.llt_response_status
        }
