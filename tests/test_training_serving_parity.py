import os
import sys
import numpy as np
import pandas as pd

# Resolve paths so we can import from src and training
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)
_SRC_PATH = os.path.join(_PROJECT_ROOT, 'src')
_TRAINING_PATH = os.path.join(_PROJECT_ROOT, 'training')

for p in [_SRC_PATH, _TRAINING_PATH, _PROJECT_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from features import FeatureProcessor
from constants import FEATURE_DIM, FEATURE_NAMES
from core.fusion import assert_parity

def test_files_exist():
    """Assert that the models and states are trained and saved."""
    model_path = os.path.join(_PROJECT_ROOT, 'models', 'cooling_model.pkl')
    state_path = os.path.join(_PROJECT_ROOT, 'models', 'preprocessor_state.pkl')
    assert os.path.exists(model_path), f"cooling_model.pkl does not exist at {model_path}"
    assert os.path.exists(state_path), f"preprocessor_state.pkl does not exist at {state_path}"

def test_feature_processor_deterministic_parity():
    """
    Generate synthetic telemetry and assert that two independent FeatureProcessor
    instances loaded with the same preprocessor state process a series of
    telemetry records sequentially and output identical 15-feature matrices.
    """
    state_path = os.path.join(_PROJECT_ROOT, 'models', 'preprocessor_state.pkl')
    
    proc_train = FeatureProcessor()
    proc_train.load(state_path)
    
    proc_infer = FeatureProcessor()
    proc_infer.load(state_path)
    
    # Generate random telemetry frames
    np.random.seed(1337)
    n_samples = 50
    raw_data = {
        'cpu': np.random.uniform(10.0, 95.0, n_samples),
        'gpu': np.random.uniform(10.0, 90.0, n_samples),
        'memory': np.random.uniform(20.0, 85.0, n_samples),
        'disk_io': np.random.uniform(1000.0, 5000000.0, n_samples),
        'network_io': np.random.uniform(1000.0, 2000000.0, n_samples),
    }
    df = pd.DataFrame(raw_data)
    
    # Sequentially feed and assert parity step-by-step
    for idx, row in df.iterrows():
        point = row.to_dict()
        vec_train = proc_train.process_single(point)
        vec_infer = proc_infer.process_single(point)
        
        # Verify shape
        assert vec_train.shape == (1, FEATURE_DIM)
        assert vec_infer.shape == (1, FEATURE_DIM)
        
        # Verify content parity
        assert_parity(vec_train, vec_infer, label=f"Parity check at step {idx}")

def test_feature_processor_range_and_finite_checks():
    """
    Assert that all feature vectors outputs are strictly clipped to [0.0, 1.0],
    contain no non-finite values (NaN, Inf), and match the V2 feature dim (15).
    """
    state_path = os.path.join(_PROJECT_ROOT, 'models', 'preprocessor_state.pkl')
    proc = FeatureProcessor()
    proc.load(state_path)
    
    # Generate wild/edge-case telemetry points
    edge_cases = [
        # Zeroes/idle
        {'cpu': 0.0, 'gpu': 0.0, 'memory': 0.0, 'disk_io': 0.0, 'network_io': 0.0},
        # High overload
        {'cpu': 150.0, 'gpu': 200.0, 'memory': 120.0, 'disk_io': 1e12, 'network_io': 1e12},
        # Typical values
        {'cpu': 50.0, 'gpu': 40.0, 'memory': 60.0, 'disk_io': 10000.0, 'network_io': 5000.0},
    ]
    
    for case in edge_cases:
        vec = proc.process_single(case)
        assert vec.shape == (1, FEATURE_DIM)
        assert np.all(np.isfinite(vec)), f"Non-finite values found in {vec} for case {case}"
        assert np.all(vec >= 0.0), f"Negative value found in {vec} for case {case}"
        assert np.all(vec <= 1.0), f"Value > 1.0 found in {vec} for case {case}"

if __name__ == "__main__":
    print("Running training-serving parity tests...")
    test_files_exist()
    print("  test_files_exist: PASS")
    test_feature_processor_deterministic_parity()
    print("  test_feature_processor_deterministic_parity: PASS")
    test_feature_processor_range_and_finite_checks()
    print("  test_feature_processor_range_and_finite_checks: PASS")
    print("All tests passed successfully!")
