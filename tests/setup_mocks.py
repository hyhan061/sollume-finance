import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime

# Add Src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../Src")))


# Mock Data Generation
def create_mock_data():
    data = {
        "출고일": ["2025-12-01"] * 5,
        "계산서": ["대상"] * 5,
        "업체명": ["테스트업체1", "테스트업체2", "이너바우어", "지앤제이", "유스랩"],
        "제품": ["상품A", "상품B", "상품C", "상품D", "상품E"],
        "수량": [10, 5, -2, 10, 10],  # -2는 반품
        "상품매출": [110000, 50000, -22000, 110000, 110000],
        "판매배송비": [2500, 0, 0, 0, 2500],
        "도선료": [0, 3000, 0, 0, 0],
        "과세구분": ["과세", "면세", "과세", "과세", "과세"],
        "매입처": ["테스트매입1", "테스트매입2", "이너바우어", "지앤제이", "유스랩"],
        "상품매입": [88000, 40000, -17600, 88000, 88000],
        "매입배송비": [2500, 0, 0, 2500, 2500],  # 지앤제이, 유스랩은 로직에서 0 처리됨
        "도선료.1": [0, 3000, 0, 3000, 3000],  # 지앤제이, 유스랩, 유라이크 로직 테스트
        "특이사항": ["", "", "", "빅웨이브즈", ""],
    }
    return pd.DataFrame(data)


def create_mock_master():
    data = {
        "거래처명_솔루미랩": [
            "테스트업체1",
            "테스트업체2",
            "이너바우어",
            "지앤제이",
            "유스랩",
            "테스트매입1",
            "테스트매입2",
        ],
        "사업자번호": [
            "123-45-67890",
            "098-76-54321",
            "111-22-33333",
            "444-55-66666",
            "777-88-99999",
            "123-12-12345",
            "987-98-98765",
        ],
    }
    return pd.DataFrame(data)


# Save mock files
def setup_mock_files():
    df = create_mock_data()
    # Create a valid excel file structure
    with pd.ExcelWriter("tests/mock_data.xlsx", engine="openpyxl") as writer:
        # Write header at row 3 (0-indexed) -> startrow=3
        df.to_excel(writer, sheet_name="(누적)2025년 발주내역", startrow=3, index=False)

    df_master = create_mock_master()
    df_master.to_excel("tests/mock_master.xlsx", sheet_name="거래처마스터", index=False)


if __name__ == "__main__":
    setup_mock_files()
    print("Mock files created in tests/")
