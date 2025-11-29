"""
Phase 1 기반 구조 테스트
exceptions, logger, validators 모듈의 동작 확인

작성일: 2025-11-29
작성자: hoyeon.han
"""

import sys
from pathlib import Path

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

from Src.exceptions import (
    ErrorCategory,
    ErrorSeverity,
    MasterFileNotFoundError,
    SheetNotFoundError,
    NoDataForDateError,
    EmptyFileError,
    BusinessNumberMissingWarning
)
from Src.logger import get_logger
from Src.validators import DataValidator
import pandas as pd


def test_exceptions():
    """예외 클래스 테스트"""
    print("=" * 60)
    print("1. 예외 클래스 테스트")
    print("=" * 60)

    # MasterFileNotFoundError 테스트
    try:
        raise MasterFileNotFoundError("Src/거래처마스터.xlsx")
    except MasterFileNotFoundError as e:
        print(f"✓ MasterFileNotFoundError")
        print(f"  오류 ID: {e.error_id}")
        print(f"  카테고리: {e.category.value}")
        print(f"  심각도: {e.severity.value}")
        print(f"  메시지: {e.user_message}")
        print(f"  해결 힌트: {len(e.solution_hints)}개")
        print()

    # EmptyFileError 테스트
    try:
        raise EmptyFileError("test.xlsx", 0)
    except EmptyFileError as e:
        print(f"✓ EmptyFileError")
        print(f"  오류 ID: {e.error_id}")
        print(f"  메시지: {e.user_message}")
        print()

    # BusinessNumberMissingWarning 테스트
    try:
        raise BusinessNumberMissingWarning(["업체A", "업체B", "업체C"])
    except BusinessNumberMissingWarning as e:
        print(f"✓ BusinessNumberMissingWarning")
        print(f"  심각도: {e.severity.value} (WARNING)")
        print(f"  메시지: {e.user_message}")
        print()

    print("✅ 예외 클래스 테스트 완료\n")


def test_logger():
    """로거 테스트"""
    print("=" * 60)
    print("2. 로거 테스트")
    print("=" * 60)

    logger = get_logger()

    # 정보 로그
    logger.log_info("테스트 정보 로그", test_type="info")
    print("✓ 정보 로그 기록")

    # 경고 로그
    logger.log_warning("테스트 경고 로그", test_type="warning")
    print("✓ 경고 로그 기록")

    # 오류 로그
    try:
        raise ValueError("테스트 오류")
    except ValueError as e:
        logger.log_error("테스트 오류 로그", error=e, test_type="error")
        print("✓ 오류 로그 기록")

    # 처리 시작 로그
    logger.log_processing_start("test.xlsx", "2025-11-29", 1024)
    print("✓ 처리 시작 로그 기록")

    # 처리 성공 로그
    logger.log_processing_success("test.xlsx", "2025-11-29", 10, 5, 1.5)
    print("✓ 처리 성공 로그 기록")

    # 성능 로그
    logger.log_performance("데이터 처리", 2.5, 1000)
    print("✓ 성능 로그 기록")

    # 커스텀 예외 로그
    try:
        raise NoDataForDateError("2025-11-29", 100)
    except NoDataForDateError as e:
        logger.log_custom_exception(e)
        print("✓ 커스텀 예외 로그 기록")

    print()
    print("로그 파일 생성 확인:")
    log_dir = Path("logs")
    if log_dir.exists():
        log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.json"))
        for log_file in sorted(log_files):
            size = log_file.stat().st_size
            print(f"  - {log_file.name} ({size} bytes)")

    print("\n✅ 로거 테스트 완료\n")


def test_validators():
    """검증 레이어 테스트"""
    print("=" * 60)
    print("3. 검증 레이어 테스트")
    print("=" * 60)

    # 테스트용 데이터프레임 생성
    df_test = pd.DataFrame({
        '출고일': ['2025-11-29', '2025-11-29', 'invalid'],
        '계산서': ['대상', '대상', '대상'],
        '업체명': ['업체A', '업체B', '업체C'],
        '제품': ['제품1', '제품2', '제품3'],
        '수량': [10, 0, 5],
        '상품매출': [10000, 5000, -1000],
        '판매배송비': [0, 0, 0],
        '도선료': [0, 0, 0],
        '과세구분': ['과세', '과세', '면세'],
        '특이사항': ['', '', '']
    })

    # 컬럼 검증
    try:
        DataValidator.validate_columns(
            df_test,
            DataValidator.REQUIRED_COLUMNS_SALES,
            '테스트시트'
        )
        print("✓ 필수 컬럼 검증 통과")
    except Exception as e:
        print(f"✗ 컬럼 검증 실패: {e}")

    # 데이터 존재 확인
    try:
        DataValidator.validate_date_data_exists(df_test, '2025-11-29', 3)
        print("✓ 데이터 존재 확인 통과")
    except Exception as e:
        print(f"✗ 데이터 존재 확인 실패: {e}")

    # 데이터 일관성 검증
    warnings = DataValidator.validate_data_consistency(df_test)
    if warnings:
        print(f"⚠ 데이터 일관성 경고 {len(warnings)}개:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("✓ 데이터 일관성 검증 통과")

    # 마스터 데이터 조인 검증
    df_result = df_test.copy()
    df_result['사업자번호'] = [None, '123-45-67890', None]
    df_result['거래처명'] = df_result['업체명']

    warnings = DataValidator.validate_master_data_join(df_result, len(df_test))
    if warnings:
        print(f"⚠ 마스터 조인 경고 {len(warnings)}개:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("✓ 마스터 조인 검증 통과")

    print("\n✅ 검증 레이어 테스트 완료\n")


def test_integration():
    """통합 테스트"""
    print("=" * 60)
    print("4. 통합 테스트")
    print("=" * 60)

    logger = get_logger()

    # 시나리오: 파일 처리 실패
    try:
        # 파일 없음 예외 발생
        raise MasterFileNotFoundError("Src/거래처마스터.xlsx")
    except MasterFileNotFoundError as e:
        # 로거에 기록
        logger.log_custom_exception(e)
        print(f"✓ 예외 발생 및 로깅: {e.error_id}")

    # 시나리오: 데이터 검증 경고
    df_test = pd.DataFrame({
        '수량': [10, 0, 5],
        '상품매출': [10000, 5000, -1000],
    })

    warnings = DataValidator.validate_data_consistency(df_test)
    if warnings:
        for w in warnings:
            logger.log_warning(f"데이터 검증 경고: {w}")
        print(f"✓ 경고 {len(warnings)}개 로깅 완료")

    print("\n✅ 통합 테스트 완료\n")


def main():
    """메인 테스트 실행"""
    print("\n" + "=" * 60)
    print("Phase 1 기반 구조 테스트 시작")
    print("=" * 60 + "\n")

    try:
        test_exceptions()
        test_logger()
        test_validators()
        test_integration()

        print("=" * 60)
        print("🎉 모든 테스트 완료!")
        print("=" * 60)
        print("\n다음 단계:")
        print("1. logs/ 디렉토리의 로그 파일 확인")
        print("2. Phase 2: processing.py 개선 진행")
        print()

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
