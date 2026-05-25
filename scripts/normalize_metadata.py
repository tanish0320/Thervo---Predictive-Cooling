import pandas as pd
import numpy as np
from pathlib import Path
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Standard Categories
STANDARD_SOURCES = [
    "idle", "cpu_stress", "gpu_stress", "memory_test", 
    "valorant", "cs2_gameplay", "cs2_update", "mixed_workload", "unknown_source"
]

STANDARD_LABELS = [
    "baseline_idle", "cpu_heavy", "gpu_heavy", "memory_heavy", 
    "disk_network_heavy", "gaming_mixed", "mixed_compute", "unknown_workload"
]

# Static Mapping Table (Initial Pass)
SOURCE_MAP = {
    "telemetry_data": "mixed_workload",
    "gpu and idle": "mixed_workload",
    "memory and cpu": "mixed_workload",
    "disk and network": "mixed_workload",
    "cpu": "cpu_stress",
    "gpu_stress": "gpu_stress",
    "memory_test": "memory_test",
    "valorant_match": "valorant",
    "valorant": "valorant",
    "cs2": "cs2_gameplay",
    "idle": "idle"
}

LABEL_MAP = {
    "baseline_idle": "baseline_idle",
    "cpu_heavy": "cpu_heavy",
    "gpu_heavy": "gpu_heavy",
    "memory_heavy": "memory_heavy",
    "disk_network_heavy": "disk_network_heavy",
    "gaming_mixed": "gaming_mixed",
    "mixed_compute": "mixed_compute"
}

def apply_heuristics(row, median_disk, median_net):
    """Apply heuristic rules based on telemetry values for a single row."""
    cpu = row['cpu']
    gpu = row['gpu']
    mem = row['memory']
    disk = row['disk_io']
    net = row['network_io']
    
    # 1. Baseline Idle (Very low activity)
    if cpu < 10 and gpu < 5 and mem < 40:
        return "baseline_idle"
    
    # 2. CPU Heavy
    if cpu > 70 and gpu < 40:
        return "cpu_heavy"
    
    # 3. GPU Heavy
    if gpu > 70:
        return "gpu_heavy"
    
    # 4. Memory Heavy
    if mem > 85:
        return "memory_heavy"
    
    # 5. Disk/Network Heavy (relative to median)
    # Using a 10x median threshold as 'extremely high'
    if disk > (median_disk * 10) or net > (median_net * 10):
        return "disk_network_heavy"
    
    # 6. Gaming Mixed (Simultaneous CPU + GPU)
    if cpu > 20 and gpu > 15:
        # Check for variability? Hard on single row. 
        # But gaming usually has both active.
        return "gaming_mixed"
    
    # 7. Mixed Compute (Fallback)
    return "mixed_compute"

def main():
    data_path = Path("data/raw/master_telemetry_dataset.csv")
    summary_path = Path("data/raw/dataset_summary.txt")
    report_path = Path("data/raw/label_cleanup_report.txt")
    
    if not data_path.exists():
        logger.error(f"Dataset not found at {data_path}")
        return

    # Load Dataset
    df = pd.read_csv(data_path)
    initial_df = df.copy()
    
    logger.info(f"Loaded {len(df)} rows for normalization.")
    
    # Calculate Medians for heuristics
    median_disk = df['disk_io'].median()
    median_net = df['network_io'].median()
    # Handle zeros to avoid 10*0=0
    if median_disk == 0: median_disk = df[df['disk_io'] > 0]['disk_io'].median() or 1000
    if median_net == 0: median_net = df[df['network_io'] > 0]['network_io'].median() or 100
    
    # 1. Apply Source Mapping
    df['source'] = df['source'].str.lower().map(lambda x: SOURCE_MAP.get(x, "unknown_source"))
    
    # 2. Refine CS2 Source (Gameplay vs Update)
    # If source is cs2 and disk/net are high, it might be an update
    df.loc[(df['source'] == 'cs2_gameplay') & ((df['disk_io'] > median_disk*5) | (df['network_io'] > median_net*5)), 'source'] = 'cs2_update'

    # 3. Initial Label Normalization
    df['workload_label'] = df['workload_label'].str.lower().map(lambda x: LABEL_MAP.get(x, "unknown_workload"))

    # 4. Heuristic Inference for Unknowns or Mixed categories
    # We apply heuristics to 'unknown_workload' or specifically requested mixed sources
    mask = (df['workload_label'] == 'unknown_workload') | (df['source'] == 'mixed_workload')
    
    heuristic_results = df[mask].apply(lambda r: apply_heuristics(r, median_disk, median_net), axis=1)
    df.loc[mask, 'workload_label'] = heuristic_results
    
    # 5. Final Source Alignment
    # Ensure source matches workload if it was idle but labeled otherwise, etc.
    # If label is baseline_idle, source should be idle unless it's a known stress test
    df.loc[(df['workload_label'] == 'baseline_idle') & (df['source'] == 'unknown_source'), 'source'] = 'idle'
    
    # Final check: Ensure labels/sources are in standard lists
    df['source'] = df['source'].apply(lambda x: x if x in STANDARD_SOURCES else "unknown_source")
    df['workload_label'] = df['workload_label'].apply(lambda x: x if x in STANDARD_LABELS else "unknown_workload")

    # Validation & Reporting
    report_lines = [
        "METADATA NORMALIZATION REPORT",
        "=============================",
        f"Processed at: {datetime.now()}",
        "",
        "--- SOURCE DISTRIBUTION (BEFORE -> AFTER) ---"
    ]
    
    before_src = initial_df['source'].value_counts()
    after_src = df['source'].value_counts()
    
    for src in set(before_src.index) | set(after_src.index):
        b = before_src.get(src, 0)
        a = after_src.get(src, 0)
        report_lines.append(f"{src:20} | {b:6} -> {a:6}")
        
    report_lines.append("\n--- WORKLOAD DISTRIBUTION (BEFORE -> AFTER) ---")
    before_lbl = initial_df['workload_label'].value_counts()
    after_lbl = df['workload_label'].value_counts()
    
    for lbl in set(before_lbl.index) | set(after_lbl.index):
        b = before_lbl.get(lbl, 0)
        a = after_lbl.get(lbl, 0)
        report_lines.append(f"{lbl:20} | {b:6} -> {a:6}")
        
    # Heuristic Decisions summary
    report_lines.append("\n--- HEURISTIC INFERENCE SUMMARY ---")
    report_lines.append(f"Heuristics applied to {mask.sum()} rows.")
    report_lines.append("Heuristic Result counts:")
    report_lines.append(heuristic_results.value_counts().to_string())
    
    unresolved = (df['workload_label'] == 'unknown_workload').sum()
    report_lines.append(f"\nUnresolved Workload Labels: {unresolved}")
    
    report_text = "\n".join(report_lines)
    with open(report_path, 'w') as f:
        f.write(report_text)
        
    # Overwrite Master
    df.to_csv(data_path, index=False)
    logger.info(f"Saved normalized dataset to {data_path}")
    
    # Update Summary
    summary_text = ""
    if summary_path.exists():
        with open(summary_path, 'r') as f:
            summary_text = f.read()
            
    # Simple replace of the distribution sections
    # (Actually it's better to just regenerate or append)
    summary_update = [
        "\n--- METADATA NORMALIZATION (Standardized) ---",
        f"Total Standardized Rows: {len(df)}",
        "Standard Sources:",
        after_src.to_string(),
        "Standard Labels:",
        after_lbl.to_string()
    ]
    
    with open(summary_path, 'a') as f:
        f.write("\n".join(summary_update))
        
    print("\n" + "="*40)
    print("METADATA NORMALIZATION COMPLETE")
    print("="*40)
    print(report_text)

if __name__ == "__main__":
    main()
