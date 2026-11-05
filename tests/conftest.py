# 2026-07-06 hoyeon.han 셀러 정산서 테스트용 conftest 신규 작성
"""pytest 공용 설정: Src 경로 추가 + 무거운 발주내역 로딩 fixture (세션당 1회)."""

import sys
from datetime import date
from pathlib import Path

import pytest

# Src 디렉토리를 import 경로에 추가 (pages 와 동일한 flat import 구조)
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

TESTS_DIR = Path(__file__).parent
ORDER_XLSM = TESTS_DIR / "솔루미랩_발주내역_20260703 (4).xlsm"
ORDER_SHEET = "(누적)2026년 발주내역"
REFERENCE_XLS = TESTS_DIR / "리버후드정산내역서_2026-04_드엘리사 4차.xls"


@pytest.fixture(scope="session")
def orders_df():
    """발주내역 전체 로딩 (약 4만 행 — 세션당 1회만 읽음)."""
    import seller_settlement as ss

    if not ORDER_XLSM.exists():
        pytest.skip(f"테스트 원본 파일이 없습니다: {ORDER_XLSM}")
    return ss.load_orders(str(ORDER_XLSM), ORDER_SHEET)


# 2026-07-23 hoyeon.han: 매입 정산서 지원 추가 — 매입 컬럼 매핑으로 로딩한 발주내역
@pytest.fixture(scope="session")
def orders_df_purchase():
    """발주내역을 매입 매핑(COLUMN_MAP_PURCHASE)으로 로딩 (세션당 1회)."""
    import seller_settlement as ss

    if not ORDER_XLSM.exists():
        pytest.skip(f"테스트 원본 파일이 없습니다: {ORDER_XLSM}")
    return ss.load_orders(str(ORDER_XLSM), ORDER_SHEET, ss.COLUMN_MAP_PURCHASE)


@pytest.fixture(scope="session")
def filtered_april(orders_df):
    """참고 정산서와 동일 조건: 2026-04월 + 리버후드."""
    import seller_settlement as ss

    return ss.filter_orders(
        orders_df,
        vendor="리버후드",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
    )


# ===== 이카운트 정산서 (2026-09-01 hoyeon.han 신규) =====

# 실제 운영에서 받을 형식 — 구분:주문유형 / 특이사항:셀러명
ECOUNT_XLSX = TESTS_DIR / "이카운트_판매현황내역_20260901_정상.xlsx"
# 구분/특이사항이 서로 뒤바뀐 옛 형식 — 뒤바뀜 감지 테스트용
ECOUNT_XLSX_SWAPPED = TESTS_DIR / "이카운트_판매현황내역_20260901.xlsx"


@pytest.fixture(scope="session")
def ecount_parsed():
    """이카운트 판매현황내역 파싱 결과 (4561행 — 세션당 1회만 읽음)."""
    import ecount_settlement as es

    if not ECOUNT_XLSX.exists():
        pytest.skip(f"테스트 원본 파일이 없습니다: {ECOUNT_XLSX}")
    return es.parse_ecount_xlsx(str(ECOUNT_XLSX))


@pytest.fixture(scope="session")
def ecount_df(ecount_parsed):
    """이카운트 파싱 DataFrame."""
    return ecount_parsed["df"]


@pytest.fixture(scope="session")
def ecount_parsed_swapped():
    """구분/특이사항이 뒤바뀐 옛 형식 파싱 결과 (경고 감지 검증용)."""
    import ecount_settlement as es

    if not ECOUNT_XLSX_SWAPPED.exists():
        pytest.skip(f"테스트 원본 파일이 없습니다: {ECOUNT_XLSX_SWAPPED}")
    return es.parse_ecount_xlsx(str(ECOUNT_XLSX_SWAPPED))
