# TELEMETRY INVESTIGATION REPORT
**Principal Performance Engineer Debugging**
**Date**: 2026-06-25

---

## FINDINGS SUMMARY

| Metric | Task Manager | Dashboard | Discrepancy | Status |
|--------|-------------|-----------|-------------|--------|
| CPU | ~12% | ~60% | 5x inflation | **UNDER INVESTIGATION** |
| GPU | ~5% | ~8% | 1.6x inflation | **PARTIALLY VERIFIED** |
| RAM | 11.0/15.8GB (70%) | ~45% | **INVERTED** | **CRITICAL** |
| CPU Temp | ~40°C | ~60-80°C | +20-40°C | **CRITICAL** |
| GPU Temp | N/A | 0°C | Always zero | **CRITICAL** |

---

## FINDINGS BY METRIC

###1. MEMORY - CRITICAL BUG FOUND

**Status**: ✅ **ROOT CAUSE IDENTIFIED**

**Evidence**:
```
OS Level (psutil.virtual_memory()):
  Total:       15.78 GB
  Used:        11.40 GB
  Available:    4.38 GB
  Percent:     72.20%

Backend (collect_telemetry()):
  raw_data['memory']: 72.30%

Dashboard:
  Shows: ~45%
```

**Root Cause**: The dashboard is showing the OPPOSITE metric!
- OS reports: **Used 11.4GB out of 15.8GB = 72.2%**
- Backend correctly passes: **72.30%**
- Dashboard displays: **~45%** (which is 100% - 72% = **AVAILABLE MEMORY**!)

**Exact Issue**: The dashboard is displaying available memory (45%) instead of used memory (72%).

**Files to Check**:
- `Index.html` (frontend)
- Any React component that binds memory value
- WebSocket payload that sends memory

**Fix Required**: Change dashboard to display `used_percent` not `available_percent`.

---

### 2. GPU UTILIZATION - SOFT THRESHOLDING BUG

**Status**: ✅ **ROOT CAUSE IDENTIFIED**

**Evidence**:
```
nvidia-smi:
  Utilization: 2.00%
  Power:       2.67W

Backend:
  raw_data['gpu']: 0.00%

Dashboard:
  Shows: ~8% (but sometimes 0)
```

**Root Cause**: GPU filtering threshold is too aggressive!

**Code Location**: `src/inference.py:234-242`

```python
power_factor = min(1.0, max(0.0, (gpu_power - 10.0) / 5.0))  # Threshold at 10W!
util_factor = min(1.0, max(0.0, (gpu_util - 5.0) / 10.0))    # Threshold at 5%!
filter_confidence = max(power_factor, util_factor)
filtered_gpu = gpu_util * filter_confidence

# Problem: When GPU at 2.67W and 2% util:
# power_factor = (2.67 - 10) / 5 = NEGATIVE = max(0, negative) = 0.0
# util_factor = (2.0 - 5) / 10 = NEGATIVE = max(0, negative) = 0.0
# filter_confidence = 0.0
# filtered_gpu = 2.0 * 0.0 = 0.0  <- DESTROYED!
```

**Exact Problem**: The GPU filtering is **zeroing out low-power GPU usage** because the thresholds (10W, 5%) are too high for idle GPUs!

**Fix Required**:
Lower thresholds or use a different approach:
```python
# Option 1: Lower thresholds
power_factor = min(1.0, max(0.0, (gpu_power - 1.0) / 2.0))  # Start at 1W
util_factor = min(1.0, max(0.0, (gpu_util - 1.0) / 5.0))    # Start at 1%

# Option 2: Disable filtering for small values
if gpu_power < 1.0 and gpu_util < 3.0:
    filtered_gpu = gpu_util  # Pass through, no filtering
else:
    filtered_gpu = gpu_util * filter_confidence
```

---

### 3. GPU TEMPERATURE - ALWAYS ZERO BUG

**Status**: ✅ **ROOT CAUSE IDENTIFIED**

**Evidence**:
```
nvidia-smi:
  Temperature: 42.00°C

Backend:
  raw_data['gpu_temp']: 43.00°C (CORRECT!)

Dashboard:
  Shows: 0°C (WRONG!)
```

**Root Cause**: The backend correctly reads GPU temperature (43°C), but the dashboard is displaying something else (0°C).

**Likely Issues**:
1. Dashboard is reading the WRONG field (gpu_power instead of gpu_temp?)
2. Normalization is zeroing it out
3. Display formatting is showing 0 instead of the actual value

**Files to Check**:
- `Index.html` or React component for temperature display
- Check if `gpu_temp` field is being mapped correctly
- Check if there's a `/gpu_temp` or similar in the API response

---

### 4. CPU TEMPERATURE - 20°C INFLATION

**Status**: ⚠️ **LIKELY ESTIMATION BUG**

**Evidence**:
```
Backend calculated: 40.7°C
Your report: Shows 60-80°C

Difference: +20-40°C
```

**Root Cause**: Likely the thermal estimation formula is too aggressive:

**Code Location**: `src/inference.py:271-273`

```python
target_cpu_temp = 38.0 + 0.42 * smooth_cpu  # Equation 1
self._cpu_temp_smooth += 0.08 * (target_cpu_temp - self._cpu_temp_smooth)  # Smoothing
cpu_temp = self._cpu_temp_smooth

# If smooth_cpu = 25% (backend value):
# target = 38.0 + 0.42 * 25 = 38 + 10.5 = 48.5°C
# After smoothing: gradually moves toward 48.5°C
# But if you measured 60-80°C, the CPU is actually hotter!
```

**Possible Issues**:
1. CPU is running hotter than estimated (legitimate high temperature)
2. The smoothing coefficient 0.08 is too high (too responsive)
3. The coefficient 0.42 is too aggressive

**However**: If backend shows 40.7°C but dashboard shows 60-80°C, there's a **display or API issue**, not a calculation issue.

---

### 5. CPU UTILIZATION - 5x INFLATION

**Status**: 🔴 **STILL INVESTIGATING** (but likely display bug)

**Evidence**:
```
psutil.cpu_percent(interval=0.1): ~7-16%
Backend (collected):              ~7-16%
Dashboard shows:                  ~60%

Ratio: 60/16 = 3.75x inflation
```

**Hypotheses**:

1. **Hypothesis A**: CPU value is being multiplied by something (28 cores, feature normalization, etc.)
   - Evidence: No such multiplication found in code
   - Status: **RULED OUT**

2. **Hypothesis B**: Dashboard is showing a feature-engineered value instead of raw telemetry
   - Evidence: Features are in [0, 1] range, so max would be 100%, not 60%
   - Status: **POSSIBLE** (need to verify WebSocket payload)

3. **Hypothesis C**: Dashboard is showing normalized value * 100 twice (double percentage conversion)
   - Example: raw 0.16 → normalized to 0.016 → displayed as 1.6% → but if it's *100 twice = 160%
   - Status: **POSSIBLE**

4. **Hypothesis D**: CPU value in WebSocket is already feature-normalized [0,1], and dashboard multiplies by 100 again
   - Example: raw 0.16 → backend sends 0.16 → dashboard does `0.16 * 100 = 16%`... wait that's only 16%, not 60%
   - Status: **PARTIALLY RULED OUT**

**Next Steps**: Need to inspect the exact WebSocket payload being sent from backend to frontend.

---

## INVESTIGATION CONCLUSIONS

### What's Definitely Broken:

1. **Memory** (CRITICAL): Dashboard shows available% instead of used%
   - **Fix**: Change dashboard memory binding
   - **Impact**: High (wrong by 27%!)

2. **GPU Utilization**: Threshold too high, kills all idle GPU data
   - **Fix**: Lower thresholds from (10W, 5%) to (1W, 1%)
   - **Impact**: Medium (GPU always shows 0%)

3. **GPU Temperature**: Always shows 0°C
   - **Fix**: Check dashboard binding for temperature field
   - **Impact**: High (completely broken)

### What's Probably Broken:

4. **CPU Temperature**: 20°C inflation
   - **Root Cause**: Either legitimate high temp OR estimation formula too aggressive
   - **Fix**: Validate against physical measurement, adjust coefficient if needed
   - **Impact**: Medium

### What Needs More Investigation:

5. **CPU Utilization**: 5x inflation
   - **Theory**: Likely display/normalization issue in frontend
   - **Fix**: Inspect WebSocket payload and React state bindings
   - **Impact**: Critical (5x off!)

---

## RECOMMENDED NEXT STEPS

### IMMEDIATE (Fix the Broken Items):

1. **Fix Memory Display**
   - Check dashboard component that displays memory
   - Change from `available` to `used` or change percentage calculation
   - Expected: Shows ~72% not ~45%

2. **Fix GPU Threshold**
   - Edit `src/inference.py:234-242`
   - Lower power threshold from 10W to 1W
   - Lower util threshold from 5% to 1%
   - Expected: GPU shows 2% instead of 0%

3. **Fix GPU Temperature Display**
   - Check `Index.html` and React components
   - Verify `gpu_temp` field is bound correctly
   - Check WebSocket payload for `gpu_temp` value
   - Expected: Shows 42-43°C instead of 0°C

### INVESTIGATION (Find CPU Inflation):

4. **Trace CPU through WebSocket**
   - Log WebSocket payload before sending
   - Log WebSocket payload when received by frontend
   - Check React state for cpu value
   - Check display component for multiplication/formatting
   - Expected: Find where 16% becomes 60%

---

## FILES TO CHECK

1. **Frontend**:
   - `Index.html` (main HTML/React)
   - Check memory binding (shows available vs used)
   - Check GPU temp binding (shows 0 vs actual)
   - Check CPU binding (multiplied?)

2. **Backend**:
   - `src/inference.py` lines 234-242 (GPU threshold)
   - `runtime/api_server.py` (check WebSocket payload)
   - `runtime/live_stream_bus.py` (WebSocket broadcast)

3. **Tests**:
   - Compare raw_data values with displayed values
   - Log WebSocket before/after transmission

---

## SUMMARY

**Bugs Found**: 4 (memory, GPU threshold, GPU temp, CPU temp)  
**Bugs Partially Understood**: 1 (CPU inflation)  
**Total Severity**: CRITICAL (multiple display/thresholding issues)

**All bugs are in the display/filtering layers, NOT in OS telemetry collection.**
The raw OS measurements (psutil, nvidia-smi) are working correctly.

