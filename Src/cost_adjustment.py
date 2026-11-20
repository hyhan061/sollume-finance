# 2026-11-20 hoyeon.han: 이카운트 정산서 비용조정 엑셀 반영 신규 모듈
"""비용조정 엑셀 → 이카운트 정산서 1회성 반영.

정산서는 이카운트 데이터로 만들고, 비용조정 엑셀을 올리면 그 내용을 **올린 그대로**
정산서에 더한다. 자동 연결·매칭·중복 판정·이력 저장은 하지 않는다.

- 한 행 = 조정 1건. 수량·금액은 정산서에 보이는 부호 그대로 입력한다.
- 품목·수량·상품금액은 함께 입력하거나 함께 비운다(비우면 배송비·도선료만 있는 행).
- 일자를 비우면 오늘 날짜(정산서 생성일)로 본다.
- 조정유형은 정산서 비고 옆 칸에 값만 표시한다(seller_settlement.ADJ_TYPE_COL).

본 모듈의 모든 함수는 순수 함수(Streamlit/세션상태 의존 없음)로 작성한다.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import seller_settlement as ss
from settlement import TYPE_PURCHASE, TYPE_SALE

# ===== 양식 정의 =====

COL_DATE = "일자"
COL_TYPE = "조정유형"
COL_SELLER = "특이사항"
COL_ITEM = "품목"
COL_QTY = "수량"
COL_AMOUNT = "상품금액"
COL_DELIVERY = "배송비"
COL_FERRY = "도선료"
COL_CATEGORY = "구분"
COL_CONSIGNEE = "수하인명"
COL_PHONE = "연락처1"
COL_ADDRESS = "수하인주소"
COL_MEMO = "메모"

# 업로드 양식 열 순서 (양식 다운로드·문서 기준). 실제 업로드는 열 순서 자유.
TEMPLATE_COLS = [
    COL_DATE, COL_TYPE, COL_SELLER, COL_ITEM, COL_QTY, COL_AMOUNT,
    COL_DELIVERY, COL_FERRY, COL_CATEGORY, COL_CONSIGNEE, COL_PHONE,
    COL_ADDRESS, COL_MEMO,
]
REQUIRED_COLS = [COL_TYPE, COL_SELLER]

# 같은 열로 인정하는 다른 이름 (공백 제거 후 비교)
COLUMN_ALIASES = {
    "제품": COL_ITEM,
    "상품매출": COL_AMOUNT,
    "판매배송비": COL_DELIVERY,
    "반품비": COL_DELIVERY,
    "특이사항(셀러)": COL_SELLER,
    "셀러": COL_SELLER,
}

# 이카운트 원본과 같은 비용 품목명 (ecount_settlement.FEE_ITEMS 와 동일 표기)
FEE_ITEM_DELIVERY = "배송비"
FEE_ITEM_FERRY = "도선료"

ROW_COL = "_행"  # 엑셀 행 번호 (헤더=1행 → 데이터 2행부터)
BLANK_DATE_COL = "_일자빈칸"  # 일자를 비워 오늘로 채운 행

TEMPLATE_SHEET = "비용조정"
GUIDE_SHEET = "작성안내"
EXAMPLE_SELLER = "예시셀러"  # 예시 행을 지우지 않고 올려도 반영되지 않도록 가상 셀러명

_DATE_PATTERNS = (
    (re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$"), None),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), None),
)
_MINUS_CHARS = ("−", "–", "—", "－")  # −, –, —, －


# ===== 값 정리 =====


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if value is pd.NaT:
        return True
    return isinstance(value, str) and value.strip() == ""


def _text(value: Any) -> str:
    if _is_blank(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("\xa0", " ").strip()


def _parse_int(value: Any, label: str) -> tuple[int | None, str]:
    """(정수 또는 None(빈칸), 오류 메시지)."""
    if _is_blank(value):
        return None, ""
    if isinstance(value, bool):
        return None, f"{label} 값을 숫자로 읽을 수 없습니다: {value}"
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        s = str(value).strip().replace(",", "").replace(" ", "")
        for ch in _MINUS_CHARS:
            s = s.replace(ch, "-")
        try:
            num = float(s)
        except ValueError:
            return None, f"{label} 값을 숫자로 읽을 수 없습니다: {value}"
    if pd.isna(num):
        return None, f"{label} 값을 숫자로 읽을 수 없습니다: {value}"
    if not float(num).is_integer():
        return None, f"{label}은(는) 정수로 입력하세요: {value}"
    return int(num), ""


def _parse_date(value: Any) -> tuple[pd.Timestamp | None, str]:
    """(날짜 또는 None(빈칸), 오류 메시지)."""
    if _is_blank(value):
        return None, ""
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).normalize(), ""
    s = _text(value)
    for pattern, _ in _DATE_PATTERNS:
        m = pattern.match(s)
        if m:
            try:
                return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3))), ""
            except ValueError:
                break
    return None, f"일자를 날짜로 읽을 수 없습니다: {value} (예: 2026-11-16)"


# ===== 파일 읽기 =====


def _as_buffer(source: Any) -> Any:
    if isinstance(source, (bytes, bytearray, memoryview)):
        return io.BytesIO(bytes(source))
    if hasattr(source, "seek"):
        source.seek(0)
    return source


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """헤더 공백 제거 + 별칭을 표준 열 이름으로. 이미 표준 열이 있으면 별칭은 무시."""
    out = df.copy()
    out.columns = [re.sub(r"\s+", "", str(c)) for c in out.columns]
    rename = {}
    for col in out.columns:
        target = COLUMN_ALIASES.get(col)
        if target and target not in out.columns and target not in rename.values():
            rename[col] = target
    return out.rename(columns=rename)


def missing_required_columns(df: pd.DataFrame) -> list[str]:
    cols = set(normalize_columns(df).columns)
    return [c for c in REQUIRED_COLS if c not in cols]


def list_sheet_names(source: Any) -> list[str]:
    wb = load_workbook(_as_buffer(source), read_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def find_default_sheet(source: Any) -> str | None:
    """필수 열(조정유형·특이사항)이 1행에 있는 첫 시트. 없으면 None."""
    wb = load_workbook(_as_buffer(source), read_only=True)
    try:
        for ws in wb.worksheets:
            header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            cols = normalize_columns(pd.DataFrame(columns=[_text(v) for v in header])).columns
            if all(c in cols for c in REQUIRED_COLS):
                return ws.title
        return None
    finally:
        wb.close()


def read_adjustment_sheet(source: Any, sheet_name: str) -> pd.DataFrame:
    """선택 시트를 헤더 1행 기준 원시 DataFrame 으로 읽는다(값 변환 없음)."""
    return pd.read_excel(_as_buffer(source), sheet_name=sheet_name, header=0, dtype=object)


# ===== 검증·정리 =====


def parse_adjustments(raw: pd.DataFrame, today: date) -> dict[str, Any]:
    """원시 시트를 검증·정리한다.

    Returns:
        {
          'rows': 정리된 조정 행 DataFrame (오류가 없을 때만 의미 있음),
          'errors': DataFrame[행, 사유] — 1건이라도 있으면 화면에서 반영을 중단,
          'blank_date_count': 일자를 비워 오늘로 채운 행 수,
        }

    Raises:
        ValueError: 필수 열(조정유형·특이사항)이 없을 때 (한글 안내)
    """
    df = normalize_columns(raw)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            "필수 열이 없습니다: " + ", ".join(missing)
            + " — '비용조정 양식 받기'의 양식을 확인하세요."
        )

    today_ts = pd.Timestamp(today).normalize()
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    known = [c for c in TEMPLATE_COLS if c in df.columns]

    for pos, (_, src) in enumerate(df.iterrows()):
        excel_row = pos + 2
        if all(_is_blank(src.get(c)) for c in known):
            continue  # 완전히 빈 행
        problems: list[str] = []

        when, err = _parse_date(src.get(COL_DATE))
        if err:
            problems.append(err)
        blank_date = when is None and not err
        if blank_date:
            when = today_ts

        adj_type = _text(src.get(COL_TYPE))
        if not adj_type:
            problems.append("조정유형이 비어 있습니다")

        item = _text(src.get(COL_ITEM))
        qty, err_q = _parse_int(src.get(COL_QTY), COL_QTY)
        amount, err_a = _parse_int(src.get(COL_AMOUNT), COL_AMOUNT)
        delivery, err_d = _parse_int(src.get(COL_DELIVERY), COL_DELIVERY)
        ferry, err_f = _parse_int(src.get(COL_FERRY), COL_FERRY)
        num_errors = [e for e in (err_q, err_a, err_d, err_f) if e]
        problems.extend(num_errors)

        product_given = {
            COL_ITEM: bool(item),
            COL_QTY: not _is_blank(src.get(COL_QTY)),
            COL_AMOUNT: not _is_blank(src.get(COL_AMOUNT)),
        }
        has_product = all(product_given.values())
        if any(product_given.values()) and not has_product:
            empty = [k for k, v in product_given.items() if not v]
            problems.append(
                "품목·수량·상품금액은 함께 입력하세요 (비어 있음: " + ", ".join(empty) + ")"
            )
        if has_product and qty == 0 and not err_q:
            problems.append("수량이 0이면 단가를 계산할 수 없습니다")
        if not num_errors and not has_product and not any(product_given.values()):
            if not (delivery or ferry):
                problems.append("상품금액·배송비·도선료 중 하나 이상 입력하세요")

        if problems:
            errors.append({"행": excel_row, "사유": "; ".join(problems)})
            continue

        seller = _text(src.get(COL_SELLER)) or ss.SHEET_GENERAL
        records.append({
            ROW_COL: excel_row,
            COL_DATE: when,
            BLANK_DATE_COL: blank_date,
            COL_TYPE: adj_type,
            COL_SELLER: seller,
            COL_ITEM: item if has_product else "",
            COL_QTY: float(qty) if has_product else float("nan"),
            COL_AMOUNT: float(amount) if has_product else float("nan"),
            COL_DELIVERY: int(delivery or 0),
            COL_FERRY: int(ferry or 0),
            COL_CATEGORY: _text(src.get(COL_CATEGORY)),
            COL_CONSIGNEE: _text(src.get(COL_CONSIGNEE)),
            COL_PHONE: _text(src.get(COL_PHONE)),
            COL_ADDRESS: _text(src.get(COL_ADDRESS)),
            COL_MEMO: _text(src.get(COL_MEMO)),
        })

    row_cols = [ROW_COL, COL_DATE, BLANK_DATE_COL] + [
        c for c in TEMPLATE_COLS if c != COL_DATE
    ]
    rows = pd.DataFrame(records, columns=row_cols)
    if not rows.empty:
        rows[COL_DATE] = pd.to_datetime(rows[COL_DATE])
    return {
        "rows": rows,
        "errors": pd.DataFrame(errors, columns=["행", "사유"]),
        "blank_date_count": int(rows[BLANK_DATE_COL].sum()) if not rows.empty else 0,
    }


def split_by_sellers(
    rows: pd.DataFrame, sellers: Iterable[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(이번 정산서 셀러 행, 다른 셀러 행). 다른 셀러 행은 오류가 아니다."""
    wanted = {str(s).strip() for s in sellers}
    mask = rows[COL_SELLER].astype(str).str.strip().isin(wanted)
    return rows[mask].copy().reset_index(drop=True), rows[~mask].copy().reset_index(drop=True)


def out_of_period_rows(rows: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """직접 입력한 일자가 정산 기간 밖인 행 (빈칸→오늘로 채운 행은 제외)."""
    if rows.empty:
        return rows.copy()
    dates = pd.to_datetime(rows[COL_DATE])
    outside = (dates < pd.Timestamp(start)) | (dates > pd.Timestamp(end))
    return rows[outside & ~rows[BLANK_DATE_COL].astype(bool)].copy()


# ===== 정산서 변환 =====


def _has_product(rows: pd.DataFrame) -> pd.Series:
    return rows[COL_ITEM].astype(str).str.strip().ne("")


def _base_order_record(row: pd.Series, vendor: str) -> dict[str, Any]:
    c = ss.COLUMN_MAP_SALE
    return {
        c["date"]: pd.Timestamp(row[COL_DATE]).normalize(),
        c["vendor"]: vendor,
        c["category"]: row[COL_CATEGORY] or row[COL_TYPE],
        c["consignee"]: row[COL_CONSIGNEE],
        c["address"]: row[COL_ADDRESS],
        c["phone1"]: row[COL_PHONE],
        c["phone2"]: "",
        c["seller"]: row[COL_SELLER],
        c["delivery"]: 0.0,
        c["ferry"]: 0.0,
        ss.ADJ_TYPE_COL: row[COL_TYPE],
    }


def _order_columns() -> list[str]:
    return [ss.COLUMN_MAP_SALE[k] for k in ss.DETAIL_LOGICAL_COLS] + [ss.ADJ_TYPE_COL]


def to_aggregate_rows(rows: pd.DataFrame, vendor: str) -> pd.DataFrame:
    """집계용 행 (to_order_settlement_df 13열 + 조정유형).

    이카운트 원본처럼 배송비·도선료는 별도 품목 줄('배송비'·'도선료', 수량 1)로 만든다.
    """
    c = ss.COLUMN_MAP_SALE
    recs: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        base = _base_order_record(row, vendor)
        if str(row[COL_ITEM]).strip():
            recs.append({**base, c["product"]: row[COL_ITEM],
                         c["qty"]: float(row[COL_QTY]), c["amount"]: float(row[COL_AMOUNT])})
        for item, col in ((FEE_ITEM_DELIVERY, COL_DELIVERY), (FEE_ITEM_FERRY, COL_FERRY)):
            if row[col]:
                recs.append({**base, c["product"]: item,
                             c["qty"]: 1.0, c["amount"]: float(row[col])})
    out = pd.DataFrame(recs, columns=_order_columns())
    out[c["date"]] = pd.to_datetime(out[c["date"]])
    return out


def to_detail_rows(rows: pd.DataFrame, vendor: str) -> pd.DataFrame:
    """상세내역용 행 (조정 1건 = 1행, 배송비·도선료는 비용 열로)."""
    c = ss.COLUMN_MAP_SALE
    recs: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        base = _base_order_record(row, vendor)
        if str(row[COL_ITEM]).strip():
            product, qty, amount = row[COL_ITEM], float(row[COL_QTY]), float(row[COL_AMOUNT])
        else:
            product = FEE_ITEM_DELIVERY if row[COL_DELIVERY] else FEE_ITEM_FERRY
            qty, amount = float("nan"), 0.0
        recs.append({**base, c["product"]: product, c["qty"]: qty, c["amount"]: amount,
                     c["delivery"]: float(row[COL_DELIVERY]),
                     c["ferry"]: float(row[COL_FERRY])})
    out = pd.DataFrame(recs, columns=_order_columns())
    out[c["date"]] = pd.to_datetime(out[c["date"]])
    return out


def build_adjustment_sheet_df(rows: pd.DataFrame, doc_type: str = TYPE_SALE) -> pd.DataFrame:
    """'비용조정내역' 시트 (반영된 조정 행을 입력 그대로). 매입은 매입 열 이름·수하인 열 제외."""
    c = ss.COLUMN_MAP_PURCHASE if doc_type == TYPE_PURCHASE else ss.COLUMN_MAP_SALE
    data = {
        COL_DATE: pd.to_datetime(rows[COL_DATE]).dt.strftime("%Y-%m-%d"),
        ss.ADJ_TYPE_COL: rows[COL_TYPE],
        c["category"]: rows[COL_CATEGORY],
        c["seller"]: rows[COL_SELLER],
        c["product"]: rows[COL_ITEM],
        c["qty"]: rows[COL_QTY],
        c["amount"]: rows[COL_AMOUNT],
        c["delivery"]: rows[COL_DELIVERY],
        c["ferry"]: rows[COL_FERRY],
    }
    if doc_type != TYPE_PURCHASE:
        data[c["consignee"]] = rows[COL_CONSIGNEE]
        data[c["phone1"]] = rows[COL_PHONE]
        data[c["address"]] = rows[COL_ADDRESS]
    data[COL_MEMO] = rows[COL_MEMO]
    return pd.DataFrame(data).reset_index(drop=True)


def summarize(rows: pd.DataFrame) -> dict[str, int]:
    """반영 합계: 건수 / 상품금액 / 배송비 / 도선료 / 순조정액."""
    amount = int(pd.to_numeric(rows[COL_AMOUNT], errors="coerce").fillna(0).sum())
    delivery = int(rows[COL_DELIVERY].sum()) if not rows.empty else 0
    ferry = int(rows[COL_FERRY].sum()) if not rows.empty else 0
    return {"건수": int(len(rows)), "상품금액": amount, "배송비": delivery,
            "도선료": ferry, "순조정액": amount + delivery + ferry}


def summarize_by_type(rows: pd.DataFrame) -> pd.DataFrame:
    """조정유형별 소계 (첫 등장 순서)."""
    out = []
    for adj_type, group in rows.groupby(COL_TYPE, sort=False):
        out.append({ss.ADJ_TYPE_COL: adj_type, **summarize(group)})
    return pd.DataFrame(
        out, columns=[ss.ADJ_TYPE_COL, "건수", "상품금액", "배송비", "도선료", "순조정액"]
    )


# ===== 양식 다운로드 =====

_GUIDE_ROWS = [
    ("일자", "선택", "정산서 작성일자. 비우면 오늘 날짜(정산서 생성일)로 반영", "2026-11-16"),
    ("조정유형", "필수", "자유 입력. 정산서 비고 옆 칸에 그대로 표시", "반품완료 / 반품접수 / 판매수수료"),
    ("특이사항", "필수(열)", "셀러명. 정산 화면의 셀러명과 같아야 반영. 비우면 '일반'", "러브지나 8차"),
    ("품목", "조건부", "정산서에 표시할 품목명 그대로 (자동 변환 없음)", "사파이어쿨링 X2(A10) 변경"),
    ("수량", "조건부", "정산서에 보이는 부호 그대로, 정수 (반품은 음수)", "-1"),
    ("상품금액", "조건부", "정산서에 보이는 부호 그대로, 정수", "-282000"),
    ("배송비", "선택", "보이는 부호 그대로, 정수. '배송비' 줄로 표시", "6600"),
    ("도선료", "선택", "보이는 부호 그대로, 정수. '도선료' 줄로 표시", "3000"),
    ("구분", "선택", "상세내역 '구분' 칸. 비우면 조정유형", "변심반품"),
    ("수하인명", "선택", "상세내역 표시용", "홍길동"),
    ("연락처1", "선택", "상세내역 표시용", "010-0000-0000"),
    ("수하인주소", "선택", "상세내역 표시용", "서울특별시 ..."),
    ("메모", "선택", "비용조정내역 시트에만 표시", "반품배송비만 청구"),
]

_GUIDE_NOTES = [
    "· 1행은 헤더입니다. 열 순서는 자유이며 양식에 없는 열은 무시합니다.",
    "· 품목·수량·상품금액은 셋 다 입력하거나 셋 다 비웁니다(셋 다 비우면 배송비·도선료만 있는 행).",
    "· 한 행에는 상품금액·배송비·도선료 중 하나 이상이 있어야 합니다.",
    "· 업로드한 내용은 이번 정산서에만 1회 그대로 반영되며 기록되지 않습니다.",
    "· 여기서 반영한 반품 등이 나중에 이카운트에 입력되면 다음 회차 정산에 다시 포함되니 확인하세요.",
    f"· 예시 행(특이사항 '{EXAMPLE_SELLER}')은 지우고 작성하세요.",
]


def build_template_xlsx() -> bytes:
    """비용조정 업로드 양식 (.xlsx bytes): 헤더 + 예시 3행 + 작성안내 시트."""
    wb = Workbook()
    ws = wb.active
    ws.title = TEMPLATE_SHEET
    header_fill = PatternFill(start_color="FFD9E1F2", end_color="FFD9E1F2", fill_type="solid")
    ws.append(TEMPLATE_COLS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    example_date = datetime(2026, 11, 16)
    examples = [
        [example_date, "반품완료", EXAMPLE_SELLER, "사파이어쿨링 X2(A10) 변경", -1, -282000,
         6600, None, "변심반품", "홍길동", "010-0000-0000", "서울특별시 ...", None],
        [example_date, "반품배송비", EXAMPLE_SELLER, None, None, None,
         6600, None, "변심반품", "김철수", "010-0000-0000", "부산광역시 ...", "반품배송비만 청구"],
        [example_date, "판매수수료", EXAMPLE_SELLER, "판매수수료", 1, -50000,
         None, None, None, None, None, None, "11월 판매수수료"],
    ]
    for values in examples:
        ws.append(values)
    for r in range(2, 2 + len(examples)):
        ws.cell(row=r, column=1).number_format = "yyyy-mm-dd"
        for col in (COL_QTY, COL_AMOUNT, COL_DELIVERY, COL_FERRY):
            ws.cell(row=r, column=TEMPLATE_COLS.index(col) + 1).number_format = "#,##0"
    widths = {COL_DATE: 12, COL_TYPE: 14, COL_SELLER: 16, COL_ITEM: 32, COL_QTY: 8,
              COL_AMOUNT: 12, COL_DELIVERY: 10, COL_FERRY: 10, COL_CATEGORY: 12,
              COL_CONSIGNEE: 10, COL_PHONE: 15, COL_ADDRESS: 30, COL_MEMO: 20}
    for i, name in enumerate(TEMPLATE_COLS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(name, 12)
    ws.freeze_panes = "A2"

    guide = wb.create_sheet(GUIDE_SHEET)
    guide.append(["열 이름", "필수", "입력 규칙", "예"])
    for cell in guide[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    for values in _GUIDE_ROWS:
        guide.append(list(values))
    guide.append([])
    for note in _GUIDE_NOTES:
        guide.append([note])
    for col, width in zip("ABCD", (12, 10, 60, 32)):
        guide.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
