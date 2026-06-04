# order_compare.py
# 2026-06-04 hoyeon.han: 발주내역 파일 비교 기능 (신규)
#
# 서버에 저장된 기존 발주내역(base)과 새로 올린 발주내역(new)을
# "일자·업체·비고 그룹 + 제품·과세구분 라인" 단위로 비교한다.
#
# - 순수 모듈: Streamlit에 의존하지 않으며 DataFrame/리스트만 입출력한다.
# - 전처리·집계 규칙은 Src/processing.py 의 get_sales_daily / get_purchase_daily 와
#   동일하게 재현하되, 마스터 조인·경리나라 형식변환·xlwt 저장은 하지 않는다.
# - 단일 날짜(date) 대신 여러 날짜(target_dates) 를 .isin() 으로 일반화했다.
# - to_num 은 processing.py 에서 재사용한다(중복 정의 금지).

import sys
from pathlib import Path
from typing import List, Union, IO

import pandas as pd
import numpy as np

# 단독 실행(스모크 테스트)과 Streamlit 페이지 양쪽에서 Src 모듈 import 가능하도록 경로 보강
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from processing import to_num  # 숫자 정규화 재사용 (중복 정의 금지)
from validators import DataValidator

# ==============================================================================
# 상수
# ==============================================================================

SHEET_HEADER_ROW = 3  # 발주내역 시트 헤더 위치 (processing.py 와 동일)

# 표준 비교 라인 스키마 (매출/매입 공통)
LINE_COLUMNS = [
    "거래일자",   # YYYY-MM-DD 문자열
    "거래처",     # 매출=업체명 / 매입=매입처
    "비고",       # 특이사항
    "품목명",     # 제품명 또는 "택배비"/"도선료"
    "과세구분",   # 과세 / 면세
    "반품유무",   # Y / N (택배비·도선료 라인은 N 고정)
    "라인종류",   # 제품 / 택배비 / 도선료
    "수량",       # 제품=수량합, 택배비·도선료=건수
    "금액",       # 제품=상품매출/매입 합, 택배비·도선료=단가×건수
    "단가",       # 제품=금액/수량, 택배비·도선료=배송비/도선료 단가
]

# 비교(merge) 기준 키
KEY_COLUMNS = ["거래일자", "거래처", "비고", "품목명", "과세구분", "반품유무", "라인종류"]

# 매출/매입별 컬럼 설정
_KIND_CONFIG = {
    "sales": {
        "vendor_col": "업체명",
        "amount_col": "상품매출",
        "delivery_col": "판매배송비",
        "ferry_col": "도선료",
        "required": DataValidator.REQUIRED_COLUMNS_SALES,
    },
    "purchase": {
        "vendor_col": "매입처",
        "amount_col": "상품매입",
        "delivery_col": "매입배송비",
        "ferry_col": "매입도선료",  # 원본 '도선료.1' 을 rename 후 사용
        "required": DataValidator.REQUIRED_COLUMNS_PURCHASE,
    },
}


# ==============================================================================
# 파일/날짜 유틸
# ==============================================================================

def read_order_sheet(source: Union[str, IO[bytes]], sheet_name: str) -> pd.DataFrame:
    """발주내역 시트를 읽는다.

    Args:
        source: 파일 경로(str) 또는 파일 객체(BytesIO 등)
        sheet_name: 읽을 시트명

    Returns:
        원본 발주내역 DataFrame (header=3 기준)
    """
    return pd.read_excel(
        source, engine="openpyxl", sheet_name=sheet_name, header=SHEET_HEADER_ROW
    )


def extract_order_dates(df: pd.DataFrame) -> List[pd.Timestamp]:
    """발주내역에서 출고일(날짜) 목록을 추출한다.

    파싱 실패(NaT)는 제외하고, 시각을 0시로 정규화한 뒤 중복 제거·정렬한다.

    Args:
        df: 발주내역 DataFrame

    Returns:
        정렬된 pd.Timestamp 리스트 (없으면 빈 리스트)
    """
    if "출고일" not in df.columns:
        return []
    s = pd.to_datetime(df["출고일"], errors="coerce").dropna().dt.normalize()
    return [pd.Timestamp(x) for x in sorted(s.unique())]


# ==============================================================================
# 비교 라인 생성
# ==============================================================================

def _empty_lines() -> pd.DataFrame:
    """빈 비교 라인 테이블(스키마 유지)."""
    return pd.DataFrame(columns=LINE_COLUMNS)


def _build_fee_line(
    df: pd.DataFrame, kind: str, vendor_col: str, fee_col: str, item_name: str
) -> pd.DataFrame:
    """배송비/도선료 라인을 만든다(processing.py 의 택배비/도선료 집계와 동일).

    - 매출은 fee != 0, 매입은 fee > 0 으로 필터(원본 부호 처리 차이 유지).
    - (출고일, 거래처, 비고, 과세구분) 으로 묶어 금액 합계·건수를 집계한다.
      (비교 키에 단가가 없으므로 단가별로 쪼개지 않는다 — 키 중복 방지)
    """
    if kind == "sales":
        sub = df[df[fee_col] != 0]
    else:
        sub = df[df[fee_col] > 0]

    if sub.empty:
        return _empty_lines()

    # 2026-06-04 hoyeon.han: 단가별로 쪼개지 않고 (일자·거래처·비고·과세구분)
    # 그룹 합계로 1개 라인을 만든다. 단가를 키에 넣으면 같은 그룹에 단가가 다른
    # 배송비가 둘 이상일 때 비교 키(단가 미포함)가 중복되어 다대다 merge가 발생한다.
    g = (
        sub.groupby(["출고일", vendor_col, "특이사항", "과세구분"], dropna=False)
        .agg(수량=(fee_col, "count"), 금액=(fee_col, "sum"))
        .reset_index()
    )
    g = g.rename(columns={vendor_col: "거래처", "특이사항": "비고"})
    g["품목명"] = item_name
    g["반품유무"] = "N"
    g["라인종류"] = item_name
    g["단가"] = np.where(g["수량"] == 0, 0, g["금액"] / g["수량"])
    g["거래일자"] = g["출고일"].dt.strftime("%Y-%m-%d")
    return g[LINE_COLUMNS]


def build_compare_lines(
    df_src: pd.DataFrame, kind: str, target_dates
) -> pd.DataFrame:
    """발주내역에서 비교용 라인 테이블을 만든다.

    Args:
        df_src: 발주내역 원본 DataFrame
        kind: "sales"(매출) 또는 "purchase"(매입)
        target_dates: 비교 대상 날짜(Timestamp/문자열) 반복가능 객체

    Returns:
        표준 비교 라인 DataFrame (LINE_COLUMNS). 데이터 없으면 빈 DataFrame.
    """
    if kind not in _KIND_CONFIG:
        raise ValueError(f"kind 는 'sales' 또는 'purchase' 여야 합니다: {kind}")

    cfg = _KIND_CONFIG[kind]
    vendor = cfg["vendor_col"]
    amount = cfg["amount_col"]
    delivery = cfg["delivery_col"]
    ferry = cfg["ferry_col"]

    # 필수 컬럼 검증 (원본 컬럼명 기준 → 매입은 '도선료.1' 검증 후 rename)
    DataValidator.validate_columns(df_src, cfg["required"], "발주내역")

    df = df_src.copy()
    if kind == "purchase" and "도선료.1" in df.columns:
        df = df.rename(columns={"도선료.1": "매입도선료"})

    # 날짜 정규화 + 대상 날짜 필터
    df["출고일"] = pd.to_datetime(df["출고일"], errors="coerce")
    target_set = {pd.Timestamp(d).normalize() for d in target_dates}
    if not target_set:
        return _empty_lines()
    df = df[df["출고일"].dt.normalize().isin(target_set)].copy()

    # 매출/매입별 행 필터 (processing.py 와 동일)
    if kind == "sales":
        df = df[df["계산서"] == "대상"].copy()
    else:
        df = df[
            (df["특이사항"] != "솔루미재고")
            & (~df["매입처"].isin(["당사재고", "솔루미랩"]))
        ].copy()

    if df.empty:
        return _empty_lines()

    # 출고일을 날짜(0시)로 정규화 → 집계 키 일관성 보장
    df["출고일"] = df["출고일"].dt.normalize()

    # 전처리: 숫자 변환 후 결측 0 (object fillna downcasting 경고 회피)
    df["특이사항"] = df["특이사항"].fillna("")
    df[amount] = to_num(df[amount]).fillna(0)
    df["수량"] = to_num(df["수량"])
    df[delivery] = to_num(df[delivery]).fillna(0)
    df[ferry] = to_num(df[ferry]).fillna(0)

    # 유효 데이터: 상품금액/배송비/도선료 중 하나라도 0이 아닌 행
    df = df[(df[amount] != 0) | (df[delivery] != 0) | (df[ferry] != 0)].copy()
    if df.empty:
        return _empty_lines()

    # 반품유무
    df["반품유무"] = np.where(df["수량"] < 0, "Y", "N")

    # 업체별 특수 처리 (집계 전, processing.py 와 동일 순서)
    if kind == "sales":
        # 이너바우어* → 이너바우어 통합
        df.loc[df[vendor].str.startswith("이너바우어", na=False), vendor] = "이너바우어"
    else:
        # 지앤제이: 매입배송비·매입도선료 0
        df.loc[df[vendor] == "지앤제이", delivery] = 0
        df.loc[df[vendor] == "지앤제이", ferry] = 0
        # 유스랩: 매입배송비·매입도선료 0
        df.loc[df[vendor] == "유스랩", delivery] = 0
        df.loc[df[vendor] == "유스랩", ferry] = 0
        # 유라이크: 매입도선료 0
        df.loc[df[vendor] == "유라이크", ferry] = 0
        # 빅웨이브즈 특이사항 보정 (업체명 컬럼이 있을 때만)
        if "업체명" in df.columns:
            df.loc[
                (df[vendor].isin(["지앤제이", "유스랩"]))
                & (df["업체명"] == "빅웨이브즈"),
                "특이사항",
            ] = "빅웨이브즈"

    # 제품 라인 집계
    prod = (
        df.groupby(
            ["출고일", vendor, "특이사항", "제품", "과세구분", "반품유무"],
            dropna=False,
        )[["수량", amount]]
        .sum()
        .reset_index()
    )
    prod = prod.rename(
        columns={vendor: "거래처", "특이사항": "비고", "제품": "품목명", amount: "금액"}
    )
    prod["라인종류"] = "제품"
    prod["단가"] = np.where(prod["수량"] == 0, 0, prod["금액"] / prod["수량"])
    prod["거래일자"] = prod["출고일"].dt.strftime("%Y-%m-%d")
    prod = prod[LINE_COLUMNS]

    # 택배비·도선료 라인
    fee_delivery = _build_fee_line(df, kind, vendor, delivery, "택배비")
    fee_ferry = _build_fee_line(df, kind, vendor, ferry, "도선료")

    parts = [p for p in (prod, fee_delivery, fee_ferry) if not p.empty]
    if not parts:
        return _empty_lines()

    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values(
        ["거래일자", "거래처", "비고", "라인종류", "품목명"]
    ).reset_index(drop=True)
    return out


# ==============================================================================
# 비교
# ==============================================================================

def compare_orders(base_lines: pd.DataFrame, new_lines: pd.DataFrame) -> pd.DataFrame:
    """기존(base)·신규(new) 비교 라인을 outer merge 해 차이를 계산한다.

    Returns:
        KEY_COLUMNS + [수량_기존/신규/차, 금액_기존/신규/차, 단가_기존/신규, 변경유형]
        변경유형 ∈ {추가, 삭제, 변경, 동일}
    """
    base = base_lines if not base_lines.empty else _empty_lines()
    new = new_lines if not new_lines.empty else _empty_lines()

    merged = pd.merge(
        base,
        new,
        on=KEY_COLUMNS,
        how="outer",
        indicator=True,
        suffixes=("_기존", "_신규"),
    )

    for col in [
        "수량_기존",
        "수량_신규",
        "금액_기존",
        "금액_신규",
        "단가_기존",
        "단가_신규",
    ]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

    merged["수량차"] = merged["수량_신규"] - merged["수량_기존"]
    merged["금액차"] = merged["금액_신규"] - merged["금액_기존"]

    merged["변경유형"] = np.select(
        [
            merged["_merge"] == "right_only",
            merged["_merge"] == "left_only",
            (merged["수량차"] == 0) & (merged["금액차"] == 0),
        ],
        ["추가", "삭제", "동일"],
        default="변경",
    )

    cols = KEY_COLUMNS + [
        "수량_기존",
        "수량_신규",
        "수량차",
        "금액_기존",
        "금액_신규",
        "금액차",
        "단가_기존",
        "단가_신규",
        "변경유형",
    ]
    merged = merged[cols].sort_values(
        ["거래일자", "거래처", "비고", "라인종류", "품목명"]
    ).reset_index(drop=True)
    return merged


def summarize_by_group(diff_df: pd.DataFrame) -> pd.DataFrame:
    """비교 결과를 (일자·거래처·비고) 그룹 단위로 요약한다(보조 표).

    Returns:
        [거래일자, 거래처, 비고, 추가, 삭제, 변경, 동일, 금액차합계]
    """
    cols = ["거래일자", "거래처", "비고", "추가", "삭제", "변경", "동일", "금액차합계"]
    if diff_df.empty:
        return pd.DataFrame(columns=cols)

    d = diff_df.copy()
    d["추가"] = (d["변경유형"] == "추가").astype(int)
    d["삭제"] = (d["변경유형"] == "삭제").astype(int)
    d["변경"] = (d["변경유형"] == "변경").astype(int)
    d["동일"] = (d["변경유형"] == "동일").astype(int)

    summary = (
        d.groupby(["거래일자", "거래처", "비고"], dropna=False)
        .agg(
            추가=("추가", "sum"),
            삭제=("삭제", "sum"),
            변경=("변경", "sum"),
            동일=("동일", "sum"),
            금액차합계=("금액차", "sum"),
        )
        .reset_index()
    )
    return summary[cols]


# ==============================================================================
# 스모크 테스트 (단독 실행: python Src/order_compare.py)
# ==============================================================================

if __name__ == "__main__":
    # 합성 발주내역 (발주내역 시트 컬럼 일부)
    def _make_df(rows):
        return pd.DataFrame(rows)

    base_rows = [
        # 출고일, 계산서, 업체명, 제품, 수량, 상품매출, 판매배송비, 도선료, 과세구분, 특이사항,
        # 매입처, 상품매입, 매입배송비, 도선료.1
        {
            "출고일": "2025-05-01", "계산서": "대상", "업체명": "A업체", "제품": "사과",
            "수량": 10, "상품매출": 11000, "판매배송비": 0, "도선료": 0,
            "과세구분": "과세", "특이사항": "",
            "매입처": "X상사", "상품매입": 8800, "매입배송비": 0, "도선료.1": 0,
        },
        {
            "출고일": "2025-05-01", "계산서": "대상", "업체명": "A업체", "제품": "배",
            "수량": 5, "상품매출": 5500, "판매배송비": 0, "도선료": 0,
            "과세구분": "과세", "특이사항": "",
            "매입처": "X상사", "상품매입": 4400, "매입배송비": 0, "도선료.1": 0,
        },
        {
            "출고일": "2025-05-02", "계산서": "대상", "업체명": "A업체", "제품": "포도",
            "수량": 2, "상품매출": 3000, "판매배송비": 2500, "도선료": 0,
            "과세구분": "면세", "특이사항": "주문1",
            "매입처": "Y상사", "상품매입": 2000, "매입배송비": 2500, "도선료.1": 0,
        },
    ]
    new_rows = [
        # 사과: 수량/금액 변경
        {
            "출고일": "2025-05-01", "계산서": "대상", "업체명": "A업체", "제품": "사과",
            "수량": 12, "상품매출": 13200, "판매배송비": 0, "도선료": 0,
            "과세구분": "과세", "특이사항": "",
            "매입처": "X상사", "상품매입": 10560, "매입배송비": 0, "도선료.1": 0,
        },
        # 배: 삭제 (new 에 없음)
        # 귤: 추가
        {
            "출고일": "2025-05-01", "계산서": "대상", "업체명": "A업체", "제품": "귤",
            "수량": 4, "상품매출": 4400, "판매배송비": 0, "도선료": 0,
            "과세구분": "과세", "특이사항": "",
            "매입처": "X상사", "상품매입": 3520, "매입배송비": 0, "도선료.1": 0,
        },
        # 포도: 동일 (수량/금액 그대로)
        {
            "출고일": "2025-05-02", "계산서": "대상", "업체명": "A업체", "제품": "포도",
            "수량": 2, "상품매출": 3000, "판매배송비": 2500, "도선료": 0,
            "과세구분": "면세", "특이사항": "주문1",
            "매입처": "Y상사", "상품매입": 2000, "매입배송비": 2500, "도선료.1": 0,
        },
    ]

    base_df = _make_df(base_rows)
    new_df = _make_df(new_rows)

    dates = sorted(set(extract_order_dates(base_df)) | set(extract_order_dates(new_df)))
    print("대상 날짜:", [d.strftime("%Y-%m-%d") for d in dates])

    # ---- 매출 비교 ----
    base_sales = build_compare_lines(base_df, "sales", dates)
    new_sales = build_compare_lines(new_df, "sales", dates)
    diff_sales = compare_orders(base_sales, new_sales)
    print("\n[매출 비교]")
    print(diff_sales[["거래일자", "품목명", "라인종류", "수량차", "금액차", "변경유형"]].to_string(index=False))

    type_map = dict(
        zip(diff_sales["품목명"] + "@" + diff_sales["거래일자"], diff_sales["변경유형"])
    )
    assert type_map.get("사과@2025-05-01") == "변경", type_map
    assert type_map.get("배@2025-05-01") == "삭제", type_map
    assert type_map.get("귤@2025-05-01") == "추가", type_map
    assert type_map.get("포도@2025-05-02") == "동일", type_map
    # 포도 주문의 택배비(면세) 라인도 동일해야 함
    fee_rows = diff_sales[diff_sales["라인종류"] == "택배비"]
    assert (fee_rows["변경유형"] == "동일").all(), fee_rows

    # ---- 매입 비교 ----
    base_buy = build_compare_lines(base_df, "purchase", dates)
    new_buy = build_compare_lines(new_df, "purchase", dates)
    diff_buy = compare_orders(base_buy, new_buy)
    print("\n[매입 비교]")
    print(diff_buy[["거래일자", "거래처", "품목명", "라인종류", "수량차", "금액차", "변경유형"]].to_string(index=False))

    buy_map = dict(
        zip(diff_buy["품목명"] + "@" + diff_buy["거래일자"], diff_buy["변경유형"])
    )
    assert buy_map.get("사과@2025-05-01") == "변경", buy_map
    assert buy_map.get("배@2025-05-01") == "삭제", buy_map
    assert buy_map.get("귤@2025-05-01") == "추가", buy_map

    # ---- 그룹 요약 ----
    summary = summarize_by_group(diff_sales)
    print("\n[매출 그룹 요약]")
    print(summary.to_string(index=False))

    # ---- 빈 입력 처리 ----
    empty_diff = compare_orders(_empty_lines(), _empty_lines())
    assert empty_diff.empty
    assert list(summarize_by_group(_empty_lines()).columns)  # 컬럼 유지

    print("\n✅ 모든 스모크 테스트 통과")
