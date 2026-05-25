# src/constants.py

FEATURE_SCHEMA_VERSION = "v2_15feature"

FEATURE_DIM = 15

PREDICTION_HORIZON_SEC = 30
SAMPLING_RATE_HZ = 1
PREDICTION_HORIZON_STEPS = PREDICTION_HORIZON_SEC * SAMPLING_RATE_HZ

FEATURE_IDX = {
    "cpu_norm": 0,
    "gpu_norm": 1,
    "mem_norm": 2,
    "disk_io_norm": 3,
    "net_io_norm": 4,
    "heat_norm": 5,
    "cpu_roll_5": 6,
    "gpu_roll_5": 7,
    "heat_roll_5": 8,
    "cpu_roll_10": 9,
    "gpu_roll_10": 10,
    "heat_roll_10": 11,
    "cpu_delta": 12,
    "gpu_delta": 13,
    "heat_delta": 14,
}

FEATURE_NAMES = [
    "cpu_norm",
    "gpu_norm",
    "mem_norm",
    "disk_io_norm",
    "net_io_norm",
    "heat_norm",
    "cpu_roll_5",
    "gpu_roll_5",
    "heat_roll_5",
    "cpu_roll_10",
    "gpu_roll_10",
    "heat_roll_10",
    "cpu_delta",
    "gpu_delta",
    "heat_delta",
]
