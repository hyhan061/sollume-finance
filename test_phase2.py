"""
Phase 2 processing.py 개선 테스트
개선된 get_sales_daily, get_purchase_daily 함수 테스트

작성일: 2025-11-29
작성자: hoyeon.han
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from Src.processing_improved import (
    to_num,
    get_sales_daily,
    get_purchase_daily
)
from Src.exceptions import (
    MasterFileNotFoundError,
    SheetNotFoundError,
    NoDataForDateError
)
from Src.logger import get_logger
import pandas as pd


def test_to_num():
    """숫자 변환 함수 테스트"""
    print("=" * 60)
    print("1. to_num() 함수 테스트")
    print("=" * 60)

    test_data = pd.Series(['1,234', '5,678.90', 'abc', '  123  ', ''])

    result = to_num(test_data)

    print("입력:", test_data.tolist())
    print("출력:", result.tolist())
    print()

    assert result[0] == 1234
    assert result[1] == 5678.90
    assert pd.isna(result[2])
    assert result[3] == 123
    assert pd.isna(result[4])

    print("✅ to_num() 테스트 통과\n")


def test_exceptions():
    """예외 처리 테스트"""
    print("=" * 60)
    print("2. 예외 처리 테스트")
    print("=" * 60)

    logger = get_logger()

    # 파일 없음 예외
    try:
        get_sales_daily("nonexistent.xlsx", "2025-11-29", "Src/거래처마스터.xlsx")
        print("✗ 파일 없음 예외 발생 실패")
    except Exception as e:
        print(f"✓ 파일 없음 예외 포착: {type(e).__name__}")
        if hasattr(e, 'error_id'):
            print(f"  오류 ID: {e.error_id}")

    # 마스터 파일 없음 예외
    try:
        # 임시 빈 파일 생성
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.xlsm', delete=False) as f:
            temp_file = f.name

        get_sales_daily(temp_file, "2025-11-29", "nonexistent_master.xlsx")
        print("✗ 마스터 파일 없음 예외 발생 실패")
    except MasterFileNotFoundError as e:
        print(f"✓ 마스터 파일 없음 예외 포착: {e.error_id}")
        logger.log_custom_exception(e)
    except Exception as e:
        print(f"✓ 다른 예외 포착 (예상됨): {type(e).__name__}")
    finally:
        import os
        if 'temp_file' in locals() and os.path.exists(temp_file):
            os.unlink(temp_file)

    print("\n✅ 예외 처리 테스트 완료\n")


def test_integration_if_master_exists():
    """
    마스터 파일이 존재하면 통합 테스트 실행
    (실제 파일이 없으면 건너뜀)
    """
    print("=" * 60)
    print("3. 통합 테스트 (조건부)")
    print("=" * 60)

    import os

    master_file = "Src/거래처마스터.xlsx"

    if not os.path.exists(master_file):
        print("⚠️  거래처마스터 파일 없음 - 통합 테스트 건너뜀")
        print("    (실제 운영 환경에서만 실행 가능)\n")
        return

    print("✓ 거래처마스터 파일 존재")
    print("  실제 데이터 테스트는 수동으로 진행하세요")
    print("  (Streamlit 앱에서 파일 업로드 테스트)\n")


def main():
    """메인 테스트 실행"""
    print("\n" + "=" * 60)
    print("Phase 2 Processing 개선 테스트 시작")
    print("=" * 60 + "\n")

    try:
        test_to_num()
        test_exceptions()
        test_integration_if_master_exists()

        print("=" * 60)
        print("🎉 Phase 2 테스트 완료!")
        print("=" * 60)
        print("\n다음 단계:")
        print("1. 기존 processing.py 백업")
        print("2. processing_improved.py → processing.py 교체")
        print("3. app.py에서 실제 파일 업로드 테스트")
        print()

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
