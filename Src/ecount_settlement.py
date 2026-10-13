"""이카운트(ECOUNT) 판매현황내역 → 정산서 변환 로직 / 2026-09-01 hoyeon.han

# 2026-10-13 hoyeon.han: 출력은 build_ecount_sheet_plan을 통해 기존 발주내역의
# seller_settlement 집계·상세내역·작성기를 사용한다. 아래 파이프라인 설명은
# 2026-09-01 최초 구현 기록이며 현재 화면의 출력 연결은 변경되었다.

# 2026-09-01 hoyeon.han: 이카운트 정산서 생성 신규 모듈

이카운트 ERP에서 내려받은 '판매현황내역' .xlsx 를 파싱해,
기존 정산서 파이프라인(Src/settlement.py)이 그대로 쓸 수 있는 형태로 만든다.

핵심 설계
---------
`parse_ecount_xlsx()` 의 반환 dict 는 `settlement.parse_settlement_xls()` 의
반환 계약(title / period_text / start_date / end_date / doc_type / df)을
그대로 지키는 상위집합이다. 따라서 파싱 이후 단계
(filter_by_period → extract_vendors → filter_by_vendor → drop_unused_columns
 → apply_mapping → split_into_sheets → write_settlement_xlsx)는
`settlement.py` 의 기존 함수를 한 줄도 고치지 않고 재사용한다.

본 모듈의 모든 함수는 순수 함수(Streamlit/세션상태 의존 없음)로 작성한다.

이카운트 원본 구조 (실측)
------------------------
- 시트 1개: '판매현황내역'
- 1행 A1: '회사명 : (주)솔루미랩 / 2026/08/01  ~ 2026/09/01'  (회사명 + 조회기간)
- 2행: 머리글 (일자 | 거래처명 | 품목명 | 구분 | 수량 | 단가(F:H 병합) |
                배송비 | 도선료 | 합계 | 특이사항 | 수하인명 | 연락처1 | 수하인주소)
- 3행~: 데이터. 일자는 'YYYYMMDD' 8자리 문자열
- 하단 3행: 월소계('2026/08  계') / 총합계 / 출력일시 → 제외 대상
- 빈 셀은 '\xa0'(non-breaking space)
- 합계 = 단가 + 배송비 + 도선료  (수량 x 단가 아님. 단가 컬럼이 실질 금액)
- 배송비/도선료 컬럼은 전 행 0이고, 품목명이 '배송비'/'도선료'인 별도 행으로 존재

컬럼 대응
--------
    거래처명   → 회사명      (거래처 선택 기준)
    일자       → 작성일자    (YYYYMMDD → YYYY-MM-DD)
    품목명     → 품목
    특이사항   → 비고        (셀러명 / 시트 분할 기준)
    구분       → 구분        (주문유형 / 필터 전용, 출력에서는 제외됨)
"""

import re
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

# 기존 정산서 상수 재사용 (seller_settlement.py 와 동일한 flat-import 선례)
from settlement import TYPE_SALE
# 2026-10-13 hoyeon.han: 발주내역 정산서의 집계·상세내역·시트 계획 재사용.
import seller_settlement as ss

# ===== 상수 =====

SHEET_NAME_DEFAULT = "판매현황내역"
# 기존 정산서(.xls)의 A1 제목과 동일하게 고정 → 출력물 제목이 일관된다
TITLE_DEFAULT = "품목별판매현황"

# 이카운트 원본에 반드시 있어야 하는 머리글
REQUIRED_SOURCE_COLS = [
    "일자",
    "거래처명",
    "품목명",
    "구분",
    "수량",
    "단가",
    "합계",
    "특이사항",
]

# 원본 머리글 → 정산서 파이프라인 컬럼명
RENAME_MAP = {
    # '일자' → '작성일자' 는 날짜 정규화 단계에서 직접 만든다 (여기 넣으면 중복 발생)
    "거래처명": "회사명",
    "품목명": "품목",
    "특이사항": "비고",
}

# 파싱 후 df 가 갖는 컬럼 순서
PARSED_COLS = [
    "작성일자",
    "회사명",
    "품목",
    "구분",
    "수량",
    "단가",
    "합계",
    "비고",
    "수하인명",
    "연락처1",
    "수하인주소",
]
# 2026-10-13 hoyeon.han: 상세내역과 비용 중복 검증에 필요한 원본 열 보존.
PARSED_COLS += ["연락처2", "배송비", "도선료"]

COL_ORDER_TYPE = "구분"  # 주문유형 (발주/반품 등)
COL_REMARK = "비고"  # 셀러명

NBSP = "\xa0"

DATE8_RE = re.compile(r"^\d{8}$")
# A1 조회기간: '2026/08/01  ~ 2026/09/01'
PERIOD_RE = re.compile(
    r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*~\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})"
)
COMPANY_PREFIX_RE = re.compile(r"^\s*회사명\s*[:：]\s*")
FOOTER_TOTAL_LABEL = "총합계"

# 주문유형으로 인정하는 단어 (부분일치 — '변심반품)' 같은 오타/신규 유형 대응)
ORDER_TYPE_HINTS = (
    "발주",
    "구매",
    "반품",
    "로켓그로스",
    "마감",
    "증정",
    "샘플",
    "취소",
    "물류대행",
    "AS",
)
# 구분/특이사항 뒤바뀜 의심 판정 기준
SWAP_SCORE_MARGIN = 0.20
SWAP_MIN_SCORE = 0.50
SWAP_MIN_ROWS = 20

# 단가 처리 모드.
# 2026-09-01 사용자 결정: 이카운트 원본 단가를 그대로 사용(raw).
# recalc(= 합계 ÷ 수량)는 나중에 필요해질 때를 대비해 파라미터로만 남겨둔다.
UNIT_RAW = "raw"
UNIT_RECALC = "recalc"


# ===== 내부 헬퍼 =====


def _clean_series(s: pd.Series) -> pd.Series:
    """\xa0 / 공백 / pandas 결측 문자열 정리."""
    return (
        s.astype(str)
        .str.replace(NBSP, "", regex=False)
        .str.strip()
        .replace({"nan": "", "None": "", "NaT": "", "<NA>": ""})
    )


def _to_number(s: pd.Series) -> pd.Series:
    """'24.0000000000' / '1,500' 형태 문자열을 숫자로. 실패는 0."""
    cleaned = (
        s.astype(str)
        .str.replace(NBSP, "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


def _read_raw(
    file_path_or_buffer: Any, sheet_name: str | None
) -> tuple[pd.DataFrame, str, list[str]]:
    """이카운트 .xlsx 를 머리글 없이(header=None) 읽어 원시 행렬을 반환.

    header=1 로 읽지 않는 이유: 단가 컬럼이 F:H 로 병합되어 있어 pandas 가
    'Unnamed: 6/7' 같은 팬텀 컬럼을 만드는데, 그 명명 규칙은 pandas 버전에
    의존한다. header=None 으로 읽고 '머리글이 빈 컬럼'을 드롭하는 편이 안전하다.

    Returns:
        (원시 DataFrame, 사용한 시트명, 전체 시트명 목록)
    """
    # 업로드 객체는 재파싱 시 포인터가 끝에 가 있을 수 있다
    if hasattr(file_path_or_buffer, "seek"):
        try:
            file_path_or_buffer.seek(0)
        except (OSError, ValueError):
            pass

    try:
        book = pd.ExcelFile(file_path_or_buffer, engine="openpyxl")
    except Exception as e:  # noqa: BLE001 - 총무 직원 대상 안내 메시지로 변환
        raise ValueError(
            "파일을 열 수 없습니다. 이카운트에서 내려받은 .xlsx 파일인지 "
            f"확인하세요. (원인: {e})"
        ) from e

    sheet_names = list(book.sheet_names)
    if not sheet_names:
        raise ValueError("엑셀 파일에 시트가 없습니다.")

    if sheet_name and sheet_name in sheet_names:
        used = sheet_name
    elif SHEET_NAME_DEFAULT in sheet_names:
        used = SHEET_NAME_DEFAULT
    else:
        used = sheet_names[0]

    raw = book.parse(used, header=None, dtype=str)
    return raw, used, sheet_names


def _split_header_and_body(raw: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """원시 행렬을 (A1 텍스트, 머리글 적용된 본문) 으로 분리.

    1행 = 회사명/기간, 2행 = 머리글, 3행~ = 데이터.
    머리글이 빈 컬럼(F:H 병합으로 생긴 팬텀)은 여기서 제거한다.
    """
    if raw.shape[0] < 3:
        raise ValueError(
            "이카운트 원본 파일의 행 수가 부족합니다. "
            "2행이 머리글이고 3행부터 데이터가 있어야 합니다."
        )

    a1 = "" if pd.isna(raw.iat[0, 0]) else str(raw.iat[0, 0])

    names = [
        "" if pd.isna(x) else str(x).replace(NBSP, "").strip()
        for x in raw.iloc[1].tolist()
    ]
    body = raw.iloc[2:].copy()
    body.columns = names
    # 병합셀 팬텀 컬럼 제거
    body = body.loc[:, [c for c in body.columns if c != ""]]

    # 중복 머리글 가드 — 방치하면 df['합계'] 가 DataFrame 을 반환해
    # 이후 계산이 에러 없이 전부 어긋난다
    dups = sorted({c for c in body.columns if list(body.columns).count(c) > 1})
    if dups:
        raise ValueError(
            f"머리글에 중복된 열 이름이 있습니다: {', '.join(dups)}. "
            "이카운트 조회 조건을 확인하세요."
        )

    return a1, body.reset_index(drop=True)


def _order_type_score(s: pd.Series) -> float:
    """시리즈의 비공란 값 중 주문유형 단어를 포함하는 비율(0.0~1.0)."""
    vals = [v for v in _clean_series(s).tolist() if v]
    if not vals:
        return 0.0
    hit = sum(1 for v in vals if any(h in v for h in ORDER_TYPE_HINTS))
    return hit / len(vals)


# ===== 공개 함수 =====


def parse_ecount_header(a1_text: str) -> tuple[str, date | None, date | None]:
    """A1 텍스트에서 (회사명, 시작일, 종료일) 추출.

    예: '회사명 : (주)솔루미랩 / 2026/08/01  ~ 2026/09/01'
        → ('(주)솔루미랩', date(2026,8,1), date(2026,9,1))

    기간을 먼저 찾고 그 앞부분에서 회사명을 떼어내므로,
    회사명 안에 '/' 가 들어 있어도 안전하다.
    """
    text = str(a1_text or "").replace(NBSP, " ").strip()

    start: date | None = None
    end: date | None = None
    m = PERIOD_RE.search(text)
    if m:
        try:
            start = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            end = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        except ValueError:
            start = end = None
        company_part = text[: m.start()]
    else:
        company_part = text

    company = COMPANY_PREFIX_RE.sub("", company_part).strip()
    company = company.rstrip("/").strip()
    return company, start, end


def parse_ecount_xlsx(
    file_path_or_buffer: Any,
    sheet_name: str | None = None,
    unit_price_mode: str = UNIT_RAW,
) -> dict[str, Any]:
    """이카운트 판매현황내역 .xlsx 파싱.

    Returns:
        {
          # settlement.parse_settlement_xls() 와 동일한 계약
          'title':       '품목별판매현황',
          'period_text': A1 원문,
          'start_date':  date,
          'end_date':    date,
          'doc_type':    '매출',
          'df':          DataFrame(PARSED_COLS),
          # 이카운트 전용 부가정보
          'company', 'sheet_name', 'sheet_names', 'raw_rows', 'dropped_rows',
          'invalid_date_rows', 'footer_total', 'footer_qty',
          'period_from_data', 'unit_price_mode', 'swap_warning',
        }
    """
    raw, used_sheet, sheet_names = _read_raw(file_path_or_buffer, sheet_name)
    a1, df = _split_header_and_body(raw)
    raw_rows = len(df)

    missing = [c for c in REQUIRED_SOURCE_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            "이카운트 판매현황내역 형식이 아닙니다. "
            f"필수 열이 없습니다: {', '.join(missing)}"
        )

    # 전 컬럼 \xa0/공백 정리
    for c in df.columns:
        df[c] = _clean_series(df[c])

    # 푸터('총합계') 캡처 — 유효행 필터보다 먼저 해야 검산이 가능하다
    label = df["일자"].str.replace(r"\s+", "", regex=True)
    foot = df[label == FOOTER_TOTAL_LABEL]
    footer_total = float(_to_number(foot["합계"]).iloc[0]) if len(foot) else None
    footer_qty = float(_to_number(foot["수량"]).iloc[0]) if len(foot) else None

    # 유효행 필터 — 일자가 YYYYMMDD 8자리인 행만.
    # 월소계('2026/08  계') / 총합계 / 출력일시가 한 번에 걸러진다.
    valid = df["일자"].str.fullmatch(r"\d{8}").fillna(False)
    dropped_rows = int((~valid).sum())
    df = df[valid].copy()
    if df.empty:
        raise ValueError(
            "유효한 데이터 행이 없습니다. "
            "일자가 YYYYMMDD 8자리인 행이 하나도 없습니다."
        )

    # 날짜 정규화. 20260231 같은 불가능한 날짜만 탈락시키고 카운트로 알린다
    # (1건 때문에 월 전체를 막지 않는다)
    parsed_date = pd.to_datetime(df["일자"], format="%Y%m%d", errors="coerce")
    invalid_date_rows = int(parsed_date.isna().sum())
    if invalid_date_rows:
        df = df[parsed_date.notna()].copy()
        parsed_date = parsed_date[parsed_date.notna()]
    if df.empty:
        raise ValueError("유효한 날짜를 가진 데이터 행이 없습니다.")
    df["작성일자"] = parsed_date.dt.strftime("%Y-%m-%d")
    # 2026-09-01 hoyeon.han: 원본 '일자'를 남겨두면 아래 rename 에서 '작성일자'가
    # 중복 생성되어 df[PARSED_COLS] 가 컬럼을 두 번 집는다 → 여기서 제거한다
    df = df.drop(columns=["일자"])

    # 숫자 변환
    for c in ["수량", "단가", "합계"]:
        df[c] = _to_number(df[c])
    for c in ["배송비", "도선료"]:
        if c in df.columns:
            df[c] = _to_number(df[c])

    # 단가 확정
    if unit_price_mode == UNIT_RECALC:
        # 합계 ÷ 수량. 수량 0 행은 0으로 둔다(0 나눗셈 회피)
        # 0 나눗셈 회피: 수량 0 은 NaN 으로 만든 뒤 0 으로 되돌린다.
        # (pd.NA 는 float 캐스팅에서 TypeError 가 나므로 np.nan 을 쓴다)
        df["단가"] = (
            (df["합계"] / df["수량"].replace(0, np.nan)).fillna(0.0).round(0)
        )
    # UNIT_RAW: 이카운트 원본 단가 그대로 사용 (2026-09-01 사용자 결정)

    # 기존 설명 보존:
    # 컬럼 rename + 순서 확정.
    # 배송비/도선료 컬럼은 전 행 0이고 합계에 이미 포함되어 있으므로 제외한다
    # (품목명이 '배송비'/'도선료'인 별도 행으로 이미 반영됨).
    # 2026-10-13 hoyeon.han: 원본 비용 열을 보존해 지원 양식인지 출력 전 검증한다.
    df = df.rename(columns={k: v for k, v in RENAME_MAP.items() if k in df.columns})
    for c in PARSED_COLS:
        if c not in df.columns:
            # df[c] = ""
            # 2026-10-13 hoyeon.han: 선택 비용 열이 없는 파일은 숫자 0으로 보충.
            df[c] = 0.0 if c in ("배송비", "도선료") else ""
    df = df[PARSED_COLS].reset_index(drop=True)

    # 조회기간 — A1 인식 실패 시 데이터 일자 범위로 폴백
    company, start_date, end_date = parse_ecount_header(a1)
    period_from_data = False
    if start_date is None or end_date is None:
        start_date = date.fromisoformat(str(df["작성일자"].min()))
        end_date = date.fromisoformat(str(df["작성일자"].max()))
        period_from_data = True

    return {
        "title": TITLE_DEFAULT,
        "period_text": a1.replace(NBSP, " ").strip(),
        "start_date": start_date,
        "end_date": end_date,
        "doc_type": TYPE_SALE,  # 판매현황내역 → 항상 매출
        "df": df,
        "company": company,
        "sheet_name": used_sheet,
        "sheet_names": sheet_names,
        "raw_rows": raw_rows,
        "dropped_rows": dropped_rows,
        "invalid_date_rows": invalid_date_rows,
        "footer_total": footer_total,
        "footer_qty": footer_qty,
        "period_from_data": period_from_data,
        "unit_price_mode": unit_price_mode,
        "swap_warning": detect_swap_suspicion(df),
    }


# 2026-10-13 hoyeon.han: 원본 단가는 보존하고 출력만 기존 정산서 규칙으로 변환.
def to_order_settlement_df(df: pd.DataFrame) -> pd.DataFrame:
    """이카운트 원본 행을 기존 매출 정산서의 13열 입력으로 변환한다.

    합계는 이미 정산금액이므로 전액 상품매출에 대응한다. 배송비·도선료는
    원본의 별도 품목 행을 유지하고, 비용 컬럼으로 다시 생성하지 않는다.
    원본 비용 컬럼에 금액이 있으면 포함 관계를 추정하지 않고 생성 중단한다.
    원본 DataFrame과 원본 단가는 수정하지 않는다.
    """
    required = ["작성일자", "회사명", "품목", "구분", "수량", "합계", "비고"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError("정산서 변환에 필요한 열이 없습니다: " + ", ".join(missing))
    for fee_col in ("배송비", "도선료"):
        if fee_col in df.columns and _to_number(df[fee_col]).ne(0).any():
            raise ValueError(
                f"원본 '{fee_col}' 열에 0이 아닌 금액이 있습니다. "
                "현재 지원 양식은 배송비·도선료를 별도 품목 행으로 표시합니다. "
                "중복 정산을 막기 위해 생성을 중단했습니다. 원본 양식을 확인하세요."
            )

    dates = pd.to_datetime(df["작성일자"], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise ValueError("정산서 변환 중 유효하지 않은 날짜가 발견되었습니다. 원본을 확인하세요.")

    # 2026-10-13 hoyeon.han: 공유 작성기의 정수 반올림으로 원본 총계가 바뀌지 않게
    # 수량·금액의 지원 범위를 확인한다. 원본 단가 및 계산 단가의 소수는 허용한다.
    numeric = {}
    for source in ("수량", "합계"):
        values = _to_number(df[source])
        if not np.isfinite(values).all() or values.ne(values.round()).any():
            raise ValueError(
                f"원본 '{source}' 열에 정수 단위가 아닌 값이 있습니다. "
                "기존 정산서 양식은 수량·금액을 정수로 출력하므로 "
                "합계가 달라지지 않도록 생성을 중단했습니다. 원본을 확인하세요."
            )
        numeric[source] = values

    source_map = {
        "vendor": "회사명", "category": "구분", "consignee": "수하인명",
        "address": "수하인주소", "product": "품목", "phone1": "연락처1",
        "phone2": "연락처2", "seller": "비고",
    }
    out = pd.DataFrame(index=df.index)
    out[ss.COLUMN_MAP_SALE["date"]] = dates
    for logical, source in source_map.items():
        values = df[source] if source in df.columns else pd.Series("", index=df.index)
        out[ss.COLUMN_MAP_SALE[logical]] = _clean_series(values)
    seller_col = ss.COLUMN_MAP_SALE["seller"]
    out[seller_col] = out[seller_col].replace("", ss.SHEET_GENERAL)
    # out[ss.COLUMN_MAP_SALE["qty"]] = _to_number(df["수량"])
    # out[ss.COLUMN_MAP_SALE["amount"]] = _to_number(df["합계"])
    # 2026-10-13 hoyeon.han: 정수 단위 검증을 통과한 값만 공유 작성기에 전달.
    out[ss.COLUMN_MAP_SALE["qty"]] = numeric["수량"]
    out[ss.COLUMN_MAP_SALE["amount"]] = numeric["합계"]
    out[ss.COLUMN_MAP_SALE["delivery"]] = 0.0
    out[ss.COLUMN_MAP_SALE["ferry"]] = 0.0
    return out[[ss.COLUMN_MAP_SALE[k] for k in ss.DETAIL_LOGICAL_COLS]].reset_index(drop=True)


# 2026-10-13 hoyeon.han: 요약·상세·전체 시트를 기존 발주내역과 같은 계획으로 작성.
def build_ecount_sheet_plan(
    df: pd.DataFrame,
    remark_to_sheet: dict[str, str] | None = None,
    item_mapping: dict[str, str] | None = None,
    detail_mode: str = ss.DETAIL_MODE_SINGLE,
    include_overall: bool = True,
) -> dict[str, Any]:
    """필터된 이카운트 행을 집계한다. 단가=행 금액/수량(기존 4자리 규칙)."""
    orders = to_order_settlement_df(df)
    sellers = ss.extract_sellers(orders)
    return ss.build_sheet_plan(
        orders,
        sellers,
        seller_to_sheet=remark_to_sheet,
        item_mapping=item_mapping,
        detail_mode=detail_mode,
        include_overall=include_overall,
    )


def extract_order_types(df: pd.DataFrame) -> list[str]:
    """구분(주문유형) 목록을 건수 많은 순으로. 빈 값은 제외."""
    if COL_ORDER_TYPE not in df.columns:
        return []
    s = _clean_series(df[COL_ORDER_TYPE])
    counts = s[s != ""].value_counts()
    return [str(v) for v in counts.index]


def filter_by_order_types(
    df: pd.DataFrame, order_types: list[str] | None
) -> pd.DataFrame:
    """구분(주문유형)으로 필터. None 이면 전체 반환."""
    if order_types is None or COL_ORDER_TYPE not in df.columns:
        return df.copy()
    wanted = {str(t).strip() for t in order_types}
    s = _clean_series(df[COL_ORDER_TYPE])
    return df[s.isin(wanted)].copy()


def verify_totals(
    df: pd.DataFrame,
    footer_total: float | None,
    footer_qty: float | None = None,
) -> dict[str, Any]:
    """읽어들인 합계/수량을 원본 푸터('총합계')와 대조.

    향후 이카운트 양식이 바뀌어 열이 밀리는 경우를 즉시 잡아내기 위한 안전장치.
    """
    calc_total = float(df["합계"].sum()) if "합계" in df.columns else 0.0
    calc_qty = float(df["수량"].sum()) if "수량" in df.columns else 0.0

    result: dict[str, Any] = {
        "checked": footer_total is not None,
        "calc_total": calc_total,
        "calc_qty": calc_qty,
        "footer_total": footer_total,
        "footer_qty": footer_qty,
        "total_diff": None,
        "qty_diff": None,
        "matches": None,
    }
    if footer_total is not None:
        result["total_diff"] = calc_total - float(footer_total)
        result["matches"] = abs(result["total_diff"]) < 1.0
    if footer_qty is not None:
        result["qty_diff"] = calc_qty - float(footer_qty)
    return result


def detect_swap_suspicion(df: pd.DataFrame) -> dict[str, Any] | None:
    """구분/특이사항이 뒤바뀐 파일인지 의심 여부 판정.

    2026-09-01 사용자 결정에 따라 자동 교정은 하지 않는다. 다만 옛 파일
    (구분에 셀러명, 특이사항에 주문유형)을 올렸을 때 시트 이름이
    '발주'/'변심반품'으로 만들어진 채 에러 없이 잘못된 정산서가 나가는 것을
    막기 위해, 화면에서 경고를 띄울 근거만 만들어 준다.

    Returns:
        의심되지 않으면 None. 의심되면 점수와 샘플 값이 담긴 dict.
    """
    if COL_ORDER_TYPE not in df.columns or COL_REMARK not in df.columns:
        return None

    type_vals = [v for v in _clean_series(df[COL_ORDER_TYPE]).tolist() if v]
    remark_vals = [v for v in _clean_series(df[COL_REMARK]).tolist() if v]
    if len(type_vals) < SWAP_MIN_ROWS or len(remark_vals) < SWAP_MIN_ROWS:
        return None

    score_type = _order_type_score(df[COL_ORDER_TYPE])
    score_remark = _order_type_score(df[COL_REMARK])

    suspicious = (
        score_remark >= SWAP_MIN_SCORE and score_remark > score_type + SWAP_SCORE_MARGIN
    )
    if not suspicious:
        return None

    return {
        "score_order_type": round(score_type, 4),
        "score_remark": round(score_remark, 4),
        "sample_order_types": list(pd.Series(type_vals).value_counts().head(5).index),
        "sample_remarks": list(pd.Series(remark_vals).value_counts().head(5).index),
    }


def summarize_vendors(df: pd.DataFrame) -> pd.DataFrame:
    """거래처별 건수/수량/금액 요약 (등장 순서 유지)."""
    if "회사명" not in df.columns:
        return pd.DataFrame(columns=["거래처", "건수", "수량", "금액"])
    out = (
        df.groupby("회사명", sort=False)
        .agg(건수=("회사명", "size"), 수량=("수량", "sum"), 금액=("합계", "sum"))
        .reset_index()
        .rename(columns={"회사명": "거래처"})
    )
    out["수량"] = out["수량"].round().astype(int)
    out["금액"] = out["금액"].round().astype(int)
    return out
