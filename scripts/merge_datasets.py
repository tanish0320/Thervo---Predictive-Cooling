import pandas as pd
import numpy as np
import re
import os
import logging
from pathlib import Path
from datetime import datetime
import json
import csv
from collections import Counter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Strict Output Schema
TARGET_SCHEMA = [
    "timestamp", "cpu", "gpu", "memory", 
    "disk_io", "network_io", "source", "workload_label"
]

# Expanded Column Normalization Map
COLUMN_MAP = {
    # CPU
    "cpu": "cpu", "cpu_usage": "cpu", "cpu_util": "cpu", "cpu%": "cpu",
    # GPU
    "gpu": "gpu", "gpu_usage": "gpu", "gpu_util": "gpu", "gpu%": "gpu",
    # Memory
    "memory": "memory", "mem": "memory", "ram": "memory", "mem_usage": "memory",
    # Disk
    "disk_io": "disk_io", "disk": "disk_io", "disk_usage": "disk_io", 
    "disk_read": "disk_io", "disk_write": "disk_io", "disk_util": "disk_io",
    # Network
    "network_io": "network_io", "network": "network_io", "net": "network_io", 
    "network_usage": "network_io", "net_usage": "network_io", "upload": "network_io", 
    "download": "network_io", "net_io": "network_io"
}

# Workload Label Keywords
WORKLOAD_MAPPING = {
    "valorant": "gaming_mixed",
    "cs2": "gaming_mixed",
    "gpu_stress": "gpu_heavy",
    "gpu_test": "gpu_heavy",
    "gpu": "gpu_heavy",
    "cpu_stress": "cpu_heavy",
    "cpu_test": "cpu_heavy",
    "cpu": "cpu_heavy",
    "memory_test": "memory_heavy",
    "ram_test": "memory_heavy",
    "memory": "memory_heavy",
    "ram": "memory_heavy",
    "idle": "baseline_idle",
    "baseline": "baseline_idle",
    "disk and network": "disk_network_heavy"
}

def refine_label(path_str, current_label):
    path_lower = path_str.lower()
    if "cs2" in path_lower and ("update" in path_lower or "download" in path_lower):
        return "disk_network_heavy"
    if "disk" in path_lower and "network" in path_lower:
        return "disk_network_heavy"
    return current_label

def infer_metadata(file_path):
    path_str = str(file_path).lower()
    filename = file_path.stem.lower()
    source = filename
    label = "unknown"
    
    for kw, target_label in WORKLOAD_MAPPING.items():
        if kw in path_str:
            label = target_label
            if kw in filename:
                source = filename
            break
            
    label = refine_label(path_str, label)
    return source, label

class TelemetryParser:
    def __init__(self):
        self.debug_stats = {}
        
    def log_debug(self, file_path, total_lines, parsed_rows, skipped_lines, fallbacks_used):
        filename = Path(file_path).name
        success_rate = (parsed_rows / total_lines * 100) if total_lines > 0 else 0
        self.debug_stats[filename] = {
            "lines": total_lines,
            "parsed": parsed_rows,
            "skipped": len(skipped_lines),
            "skipped_examples": skipped_lines[:10],
            "success_rate": success_rate,
            "fallbacks": fallbacks_used
        }

    def stage1_pandas(self, file_path):
        """Stage 1: Standard Pandas CSV parsing."""
        try:
            return pd.read_csv(file_path, skipinitialspace=True, on_bad_lines='error', engine='c')
        except Exception:
            return None

    def stage2_auto_delimiter(self, file_path):
        """Stage 2: Auto-detect delimiter."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                sample = f.read(8192)
                if not sample: return None
                sniffer = csv.Sniffer()
                # Try common delimiters if Sniffer fails
                delims = [',', ';', '\t', '|']
                dialect = None
                try:
                    dialect = sniffer.sniff(sample, delimiters=delims)
                    delim = dialect.delimiter
                except Exception:
                    # Naive count if sniffer fails
                    counts = {d: sample.count(d) for d in delims}
                    delim = max(counts, key=counts.get)
                    if counts[delim] == 0: delim = ','
                
                f.seek(0)
                return pd.read_csv(f, sep=delim, skipinitialspace=True, on_bad_lines='skip')
        except Exception:
            return None

    def stage3_regex(self, line):
        """Stage 3: Regex extraction for various patterns."""
        data = {}
        
        # 1. Look for Key Value patterns (e.g., CPU 9.8%, Disk 123 B/s, cpu=45)
        # Matches "Key [=:]? Value[%]? [Unit]?"
        # Keys to look for
        keys = r'cpu|gpu|memory|mem|ram|disk_io|disk|network_io|net|network|upload|download|timestamp|gpu_t|cpu_t'
        pattern = rf'(?P<key>{keys})\s*[=:]?\s*(?P<val>[\d\.\-T\s:]+)(?P<suffix>%|\s*B/s|\s*Â°C)?'
        
        matches = re.finditer(pattern, line, re.IGNORECASE)
        found = False
        for m in matches:
            key = m.group('key').lower()
            val = m.group('val').strip()
            
            if key == 'timestamp':
                data['timestamp'] = val
                continue
                
            try:
                # Some logs have 'Tick 1', we ignore that
                if key == 'tick': continue
                
                # Extract first float/int from val
                val_match = re.search(r'[\d\.]+', val)
                if val_match:
                    data[key] = float(val_match.group())
                    found = True
            except ValueError:
                pass
        
        # 2. Standalone timestamp extraction if not found
        if 'timestamp' not in data:
            ts_match = re.search(r'(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[\.\d]*)', line)
            if ts_match:
                data['timestamp'] = ts_match.group(1)
        
        return data if found or 'timestamp' in data else None

    def stage4_json(self, line):
        """Stage 4: JSON fragment extraction."""
        try:
            if '{' in line and '}' in line:
                json_match = re.search(r'\{.*\}', line)
                if json_match:
                    return json.loads(json_match.group())
        except Exception:
            pass
        return None

    def parse_file(self, file_path):
        filename = Path(file_path).name
        logger.info(f"Parsing {filename}...")
        
        total_lines = 0
        rows = []
        skipped_lines = []
        fallbacks = Counter()
        
        # Line-by-line parsing for maximum reliability
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    total_lines += 1
                    line = line.strip()
                    if not line: continue
                    
                    # Try JSON first (Stage 4)
                    data = self.stage4_json(line)
                    if data:
                        rows.append(data)
                        fallbacks['stage4_json'] += 1
                        continue
                        
                    # Try Regex (Stage 3)
                    data = self.stage3_regex(line)
                    if data:
                        rows.append(data)
                        fallbacks['stage3_regex'] += 1
                        continue
                    
                    # If line has many delimiters, it might be a CSV line without headers
                    # We only try this if we have no other choice or if it's the first line
                    if total_lines == 1:
                        # Try bulk parsing if it looks like a clean CSV
                        df_bulk = self.stage1_pandas(file_path)
                        if df_bulk is None:
                            df_bulk = self.stage2_auto_delimiter(file_path)
                        
                        if df_bulk is not None and not df_bulk.empty:
                            # Verify if any headers match
                            norm_cols = [COLUMN_MAP.get(c.lower(), c.lower()) for c in df_bulk.columns]
                            if any(c in TARGET_SCHEMA or c in ['gpu_temp', 'cpu_temp'] for c in norm_cols):
                                fallbacks['bulk_csv'] += 1
                                rows = df_bulk.to_dict('records')
                                total_lines = len(df_bulk)
                                self.log_debug(file_path, total_lines, len(rows), [], fallbacks)
                                return df_bulk
                    
                    skipped_lines.append(line)
        except Exception as e:
            logger.error(f"Failed to read {filename}: {e}")
            
        self.log_debug(file_path, total_lines, len(rows), skipped_lines, fallbacks)
        return pd.DataFrame(rows) if rows else None

def normalize_dataframe(df, source, workload_label):
    if df is None or df.empty:
        return None
    
    # Use copy to avoid SettingWithCopyWarning
    df = df.copy()
    
    # 1. Strip whitespace from headers and lower case
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # 2. Map aliases (comprehensive)
    df = df.rename(columns=COLUMN_MAP)
    
    # 3. Handle missing timestamp
    if 'timestamp' not in df.columns:
        df['timestamp'] = pd.date_range(start=datetime.now(), periods=len(df), freq='s')
    else:
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        
    # 4. Add metadata
    df['source'] = source
    df['workload_label'] = workload_label
    
    # 5. Ensure all target columns exist
    for col in TARGET_SCHEMA:
        if col not in df.columns:
            df[col] = np.nan
            
    # Keep only target schema
    cols_to_keep = [c for c in TARGET_SCHEMA if c in df.columns]
    return df[cols_to_keep]

def clean_data(df):
    if df is None or df.empty:
        return None, 0
    
    initial_rows = len(df)
    df = df.drop_duplicates().copy()
    
    telemetry_cols = ["cpu", "gpu", "memory", "disk_io", "network_io"]
    for col in telemetry_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        else:
            df[col] = np.nan
        
    df = df.dropna(subset=telemetry_cols, how='all').copy()
    
    df['cpu'] = df['cpu'].clip(0, 100)
    df['gpu'] = df['gpu'].clip(0, 100)
    df['memory'] = df['memory'].clip(0, 100)
    df['disk_io'] = df['disk_io'].clip(lower=0)
    df['network_io'] = df['network_io'].clip(lower=0)
    
    df[telemetry_cols] = df[telemetry_cols].ffill().fillna(0)
    df = df.dropna(subset=['timestamp']).copy()
    
    rows_removed = initial_rows - len(df)
    return df, rows_removed

def main():
    input_dirs = [Path("datasets"), Path("logs")]
    output_path = Path("data/raw/master_telemetry_dataset.csv")
    summary_path = Path("data/raw/dataset_summary.txt")
    debug_path = Path("data/raw/parsing_debug_report.txt")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    parser = TelemetryParser()
    all_dfs = []
    processed_files = set()
    
    for input_dir in input_dirs:
        if not input_dir.exists(): continue
        
        files = list(input_dir.rglob("*.csv")) + list(input_dir.rglob("*.log"))
        for file_path in files:
            if file_path.name in processed_files: continue
            processed_files.add(file_path.name)
            
            source, label = infer_metadata(file_path)
            df_raw = parser.parse_file(file_path)
            
            if df_raw is not None and not df_raw.empty:
                df_norm = normalize_dataframe(df_raw, source, label)
                df_clean, _ = clean_data(df_norm)
                
                if df_clean is not None and not df_clean.empty:
                    all_dfs.append(df_clean)
                else:
                    logger.warning(f"No valid data in {file_path.name} after cleaning.")
            else:
                logger.warning(f"Could not parse {file_path.name} or file is empty.")
            
    if not all_dfs:
        logger.error("No data collected.")
        return
        
    master_df = pd.concat(all_dfs, ignore_index=True)
    master_df = master_df.sort_values('timestamp').drop_duplicates()
    master_df.to_csv(output_path, index=False)
    
    # Generate Debug Report
    debug_lines = ["PER-FILE PARSING DIAGNOSTICS\n" + "="*30 + "\n"]
    for file, stats in parser.debug_stats.items():
        debug_lines.append(f"File: {file}")
        debug_lines.append(f"Lines: {stats['lines']}")
        debug_lines.append(f"Parsed: {stats['parsed']}")
        debug_lines.append(f"Skipped: {stats['skipped']}")
        debug_lines.append(f"Success Rate: {stats['success_rate']:.2f}%")
        debug_lines.append(f"Fallbacks Used: {dict(stats['fallbacks'])}")
        if stats['skipped_examples']:
            debug_lines.append("Skipped Examples:")
            for ex in stats['skipped_examples']:
                debug_lines.append(f"  > {ex}")
        debug_lines.append("-" * 20)
    
    with open(debug_path, 'w') as f:
        f.write("\n".join(debug_lines))
        
    # Generate Summary
    summary = [
        "TELEMETRY DATASET SUMMARY",
        "="*30,
        f"Total Files Processed: {len(parser.debug_stats)}",
        f"Total Rows Merged: {len(master_df)}",
        "",
        "--- WORKLOAD DISTRIBUTION ---",
        master_df['workload_label'].value_counts().to_string(),
        "",
        "--- SOURCE DISTRIBUTION ---",
        master_df['source'].value_counts().to_string(),
        "",
        "--- TELEMETRY RANGES ---"
    ]
    for col in ["cpu", "gpu", "memory", "disk_io", "network_io"]:
        summary.append(f"{col:10} | Min: {master_df[col].min():8.2f} | Max: {master_df[col].max():8.2f} | Mean: {master_df[col].mean():8.2f}")
        
    summary_text = "\n".join(summary)
    with open(summary_path, 'w') as f:
        f.write(summary_text)
        
    print("\n" + "="*40)
    print("INGESTION COMPLETE")
    print(f"Total Rows Extracted: {len(master_df)}")
    print("="*40)
    print(summary_text)

if __name__ == "__main__":
    main()
