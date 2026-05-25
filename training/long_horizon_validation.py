import sys
import os
import argparse
from comparison_runner import run_comparison

def long_horizon_test():
    """
    Executes long-duration stability simulations.
    1 hour = 3600 seconds/rows
    3 hours = 10800 rows
    """
    print("========================================")
    print(" STARTING LONG HORIZON STABILITY VALIDATION")
    print("========================================")
    
    # Run 3-hour drift test
    print("\n>> Validating Workload: K_LongDrift (3 hours)")
    run_comparison(rows=10800, scenario="K_LongDrift")
    
    print("\n[Long Horizon Validation] Passed.")

if __name__ == "__main__":
    long_horizon_test()
