import pandas as pd
import sys
import os
import numpy as np

# Add Src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../Src")))

from processing import get_sales_daily, get_purchase_daily


def generate_baseline():
    date = "2025-12-01"
    file_path = "tests/mock_data.xlsx"
    master_path = "tests/mock_master.xlsx"

    print("Generating baseline data...")
    try:
        # Generate Sales Baseline
        df_sales = get_sales_daily(
            file_path, date, master_file_path=master_path, use_db=False
        )
        df_sales.to_csv("tests/baseline_sales.csv", index=False)
        print(f"Sales baseline saved: {len(df_sales)} rows")

        # Generate Purchase Baseline
        df_purchase = get_purchase_daily(
            file_path, date, master_file_path=master_path, use_db=False
        )
        df_purchase.to_csv("tests/baseline_purchase.csv", index=False)
        print(f"Purchase baseline saved: {len(df_purchase)} rows")

        return True
    except Exception as e:
        print(f"Error generating baseline: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = generate_baseline()
    sys.exit(0 if success else 1)
