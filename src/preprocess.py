import pandas as pd
import numpy as np
import os
from features import FeatureProcessor

def preprocess_pipeline(input_csv=os.path.join("..", "data", "raw", "telemetry_data.csv"), 
                        output_prefix=os.path.join("..", "data", "processed", "processed"),
                        state_path=os.path.join("..", "models", "preprocessor_state.pkl")):
    """
    ML Data Preprocessing Pipeline.
    Refactored to use shared FeatureProcessor for training-serving parity.
    """
    print(f"--- Starting Unified Preprocessing Pipeline for {input_csv} ---")
    
    if not os.path.exists(input_csv):
        print(f"Error: {input_csv} not found.")
        return

    # 1. Load Data
    df = pd.read_csv(input_csv)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    # 2. Data Cleaning
    print("Cleaning raw telemetry...")
    numeric_cols = ["cpu", "gpu", "memory", "disk_io", "network_io", "gpu_temp", "cpu_temp"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Batch cleaning (Safe to do in batch before feature engineering)
    df[numeric_cols] = df[numeric_cols].ffill().fillna(df[numeric_cols].median())
    
    # 3. Fit Processor
    # This step captures Min/Max scaling from the raw training data
    processor = FeatureProcessor()
    processor.fit(df)
    processor.save(state_path)

    # 4. Feature Engineering (Simulating Real-Time Loop for Parity)
    print("Engineering features via shared logic...")
    feature_list = []
    
    for _, row in df.iterrows():
        # Process every row individually using the exact same code the inference engine uses
        raw_point = row.to_dict()
        vector = processor.process_single(raw_point)
        feature_list.append(vector.flatten())

    # Create Features DataFrame
    X_df = pd.DataFrame(feature_list, columns=processor.FEATURE_NAMES)
    
    # 5. Label Generation (Batch logic remains from original script)
    print("Generating risk labels...")
    # risk_score = 0.6*(cpu/100) + 0.4*(gpu/100)
    df['risk_score'] = 0.6 * (df['cpu'] / 100.0) + 0.4 * (df['gpu'] / 100.0)
    
    def get_risk_level(score):
        if score < 0.35: return "LOW"
        if score < 0.55: return "MED"
        if score < 0.75: return "HIGH"
        return "CRITICAL"
    
    df['risk_level'] = df['risk_score'].apply(get_risk_level)

    # 6. Save Outputs
    processed_dir = os.path.join("..", "data", "processed")
    os.makedirs(processed_dir, exist_ok=True)
    
    # Save the combined dataset for inspection
    df_full = pd.concat([df.reset_index(drop=True), X_df], axis=1)
    df_full.to_csv(f"{output_prefix}_dataset.csv", index=False)
    
    # Save X and y separately for training
    X_df.to_csv(os.path.join(processed_dir, "X.csv"), index=False)
    df[['risk_score', 'risk_level']].to_csv(os.path.join(processed_dir, "y.csv"), index=False)
    
    print(f"\n--- Unified Preprocessing Complete ---")
    print(f"X: {os.path.join(processed_dir, 'X.csv')} (Shape: {X_df.shape})")
    print(f"y: {os.path.join(processed_dir, 'y.csv')}")
    print(f"State saved to: {state_path}")

if __name__ == "__main__":
    preprocess_pipeline()
