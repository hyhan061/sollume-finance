# 2026-08-10 hoyeon.han 발주내역 요약 수량 0 행 누락 수정에 따른 테스트 신규 작성
"""period_summary 모듈 검증 — 수량 0 행 처리.

수수료 항목(에이전시 결제수수료 등)은 수량 0 으로 금액만 입력하는 운영 관례라,
필터에서 수량 0 을 배제하면 요약 합계가 일별 전표(processing.py)와 어긋난다.
_process_sales_daily / _process_buy_daily 는 순수 함수라 DataFrame 을 직접
만들어 호출한다.
"""

from datetime import datetime

import numpy as np
import pandas as pd

import period_summary as ps

TARGET = datetime(2026, 6, 18)


def _sales_df(rows: list[dict]) -> pd.DataFrame:
    """매출 처리에 필요한 최소 컬럼을 갖춘 발주내역 DataFrame."""
    base = {
        "출고일": TARGET,
        "계산서": "대상",
        "업체명": "유라이크",
        "특이사항": "",
        "제품": "테스트상품",
        "수량": 1,
        "상품매출": 10000,
        "판매배송비": 0,
        "도선료": 0,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def _buy_df(rows: list[dict]) -> pd.DataFrame:
    """매입 처리에 필요한 최소 컬럼을 갖춘 발주내역 DataFrame."""
    base = {
        "출고일": TARGET,
        "매입처": "에이원컴퍼니",
        # _apply_vendor_rules 가 매입처별 규칙 판정에 '업체명'을 참조한다
        "업체명": "유라이크",
        "특이사항": "",
        "제품": "테스트상품",
        "수량": 1,
        "상품매입": 8000,
        "매입배송비": 0,
        "도선료.1": 0,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


# ===== 수량 0 행 포함 =====


def test_sales_zero_qty_amount_only_row_included():
    """수량 0 이고 금액만 있는 수수료 행이 포함되고 단가는 0."""
    df = _sales_df(
        [
            {"제품": "일반상품", "수량": 5, "상품매출": 50000},
            {"제품": "에이전시 결제수수료", "수량": 0, "상품매출": -8431461},
        ]
    )
    today, summary, total = ps._process_sales_daily(df, TARGET)

    assert len(today) == 2
    fee = today[today["제품"] == "에이전시 결제수수료"]
    assert len(fee) == 1
    assert int(fee["상품매출"].iloc[0]) == -8431461
    assert float(fee["단가"].iloc[0]) == 0.0
    # 업체별 합계에도 음수 수수료가 반영된다
    assert int(total) == 50000 - 8431461


def test_buy_zero_qty_amount_only_row_included():
    """매입도 동일하게 수량 0 행을 포함한다."""
    df = _buy_df(
        [
            {"제품": "일반상품", "수량": 5, "상품매입": 40000},
            {"제품": "에이전시 결제수수료", "수량": 0, "상품매입": -6609205},
        ]
    )
    today, summary, total = ps._process_buy_daily(df, TARGET)

    assert len(today) == 2
    fee = today[today["제품"] == "에이전시 결제수수료"]
    assert float(fee["단가"].iloc[0]) == 0.0
    assert int(total) == 40000 - 6609205


def test_zero_qty_zero_amount_row_included():
    """수량 0 이고 금액도 비어있는 행도 그대로 포함한다 (기존 금액 OR 조건 유지)."""
    df = _sales_df(
        [
            {"제품": "일반상품", "수량": 5, "상품매출": 50000},
            {
                "제품": "빈금액상품",
                "수량": 0,
                "상품매출": 0,
                "판매배송비": np.nan,
                "도선료": np.nan,
            },
        ]
    )
    today, _, _ = ps._process_sales_daily(df, TARGET)
    assert set(today["제품"]) == {"일반상품", "빈금액상품"}


# ===== 0 나누기 방어 =====


def test_unit_price_has_no_inf_or_nan():
    """수량이 0/NaN 이어도 단가에 inf 나 NaN 이 생기지 않는다."""
    df = _sales_df(
        [
            {"수량": 4, "상품매출": 40000},
            {"수량": 0, "상품매출": -8431461},
            {"수량": np.nan, "상품매출": 12345},
            {"수량": -2, "상품매출": -20000},
        ]
    )
    today, _, _ = ps._process_sales_daily(df, TARGET)

    unit = today["단가"].to_numpy(dtype=float)
    assert np.isfinite(unit).all()
    # 반품(음수 수량)은 기존대로 정상 계산되어야 한다
    assert float(today[today["수량"] == -2]["단가"].iloc[0]) == 10000.0


def test_unit_price_no_runtime_warning():
    """수량 0 행이 있어도 0 나누기 RuntimeWarning 이 발생하지 않는다."""
    import warnings

    df = _sales_df([{"수량": 0, "상품매출": -8431461}])
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        ps._process_sales_daily(df, TARGET)


# ===== 기존 동작 회귀 확인 =====


def test_normal_rows_unchanged():
    """수량이 있는 일반 행의 단가/합계는 기존과 동일하다."""
    df = _sales_df(
        [
            {"수량": 4, "상품매출": 40000},
            {"수량": 10, "상품매출": 150000, "판매배송비": 3000, "도선료": 500},
        ]
    )
    today, summary, total = ps._process_sales_daily(df, TARGET)

    assert len(today) == 2
    assert float(today[today["수량"] == 4]["단가"].iloc[0]) == 10000.0
    assert float(today[today["수량"] == 10]["단가"].iloc[0]) == 15000.0
    assert int(total) == 40000 + 150000 + 3000 + 500


def test_empty_result_returns_empty_frames():
    """필터 결과가 0행이면 빈 DataFrame 을 반환한다 (기존 동작)."""
    df = _sales_df([{"계산서": "제외"}])
    today, summary, total = ps._process_sales_daily(df, TARGET)

    assert len(today) == 0
    assert len(summary) == 0
    assert total == 0.0
