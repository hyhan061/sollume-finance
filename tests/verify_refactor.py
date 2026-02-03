import pandas as pd
import sys
import os
import numpy as np

# Add Src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../Src")))

from processing import get_sales_daily, get_purchase_daily


def verify_results():
    date = "2025-12-01"
    file_path = "tests/mock_data.xlsx"
    master_path = "tests/mock_master.xlsx"

    print("Verifying results against baseline...")
    try:
        # 1. Verify Sales
        df_sales_new = get_sales_daily(
            file_path, date, master_file_path=master_path, use_db=False
        )
        # Read all as string to avoid type mismatch (csv type inference vs memory type)
        df_sales_base = pd.read_csv("tests/baseline_sales.csv", dtype=str).fillna("")

        # Convert new df to string/object for fair comparison
        df_sales_new = df_sales_new.astype(str)

        # Simple structural check first
        if len(df_sales_new) != len(df_sales_base):
            print(
                f"FAIL: Sales row count mismatch. New: {len(df_sales_new)}, Base: {len(df_sales_base)}"
            )
            return False

        # Reset index to ensure alignment
        pd.testing.assert_frame_equal(
            df_sales_base.sort_values("거래처명").reset_index(drop=True),
            df_sales_new.sort_values("거래처명").reset_index(drop=True),
            check_dtype=False,  # Types are aligned to str now
        )
        print("PASS: Sales data matches baseline.")

        # 2. Verify Purchase
        df_purchase_new = get_purchase_daily(
            file_path, date, master_file_path=master_path, use_db=False
        )
        df_purchase_base = pd.read_csv("tests/baseline_purchase.csv", dtype=str).fillna(
            ""
        )
        df_purchase_new = df_purchase_new.astype(str)

        pd.testing.assert_frame_equal(
            df_purchase_base.sort_values("거래처명").reset_index(drop=True),
            df_purchase_new.sort_values("거래처명").reset_index(drop=True),
            check_dtype=False,
        )
        df_sales_base = pd.read_csv("tests/baseline_sales.csv").fillna(
            ""
        )  # Load baseline, handle NaNs as empty string for comparison if needed

        # Normalize for comparison (csv reads all as string/object sometimes)
        # Better: compare values carefully.

        # Simple structural check first
        if len(df_sales_new) != len(df_sales_base):
            print(
                f"FAIL: Sales row count mismatch. New: {len(df_sales_new)}, Base: {len(df_sales_base)}"
            )
            return False

        # Check specific columns that were calculated
        cols_to_check = ["공급가액", "세액", "단가"]

        # Convert new df columns to appropriate types for comparison if they are not
        # The CSV read might interpret them differently.
        # Let's align types.
        for col in cols_to_check:
            # Round to avoid float precision issues in comparison
            if col in df_sales_base.columns:
                # Base is from CSV, might need cleaning
                pass

        # Exact DataFrame equality check (handling NaN)
        # Reset index to ensure alignment
        pd.testing.assert_frame_equal(
            df_sales_base.sort_values("거래처명").reset_index(drop=True),
            df_sales_new.sort_values("거래처명").reset_index(drop=True),
            check_dtype=False,  # Types might differ (CSV vs InMemory)
            atol=1e-8,  # Tolerance for floats
        )
        print("PASS: Sales data matches baseline.")

        # 2. Verify Purchase
        df_purchase_new = get_purchase_daily(
            file_path, date, master_file_path=master_path, use_db=False
        )
        df_purchase_base = pd.read_csv("tests/baseline_purchase.csv").fillna("")

        pd.testing.assert_frame_equal(
            df_purchase_base.sort_values("거래처명").reset_index(drop=True),
            df_purchase_new.sort_values("거래처명").reset_index(drop=True),
            check_dtype=False,
            atol=1e-8,
        )
        print("PASS: Purchase data matches baseline.")

        return True

    except AssertionError as e:
        print(f"FAIL: Data mismatch detected.\n{e}")
        return False
    except Exception as e:
        print(f"FAIL: Error during verification: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = verify_results()
    sys.exit(0 if success else 1)
