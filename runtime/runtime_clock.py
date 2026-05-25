import time
import threading

class RuntimeClock:
    def __init__(self):
        self._start_time = time.time()
        self._lock = threading.Lock()
        
    def get_time(self) -> float:
        """Returns the synchronized real-time timestamp since epoch."""
        return time.time()
        
    def get_elapsed(self) -> float:
        """Returns elapsed time since the clock was initialized."""
        return time.time() - self._start_time
        
    def sync_sleep(self, duration: float):
        """Sleeps for a specific duration in a synchronized manner."""
        time.sleep(duration)
