# 2026-11-20 hoyeon.han: 이카운트 정산서 비용조정 엑셀 반영 테스트 신규 작성
"""비용조정 엑셀(1회성, 올린 그대로 반영) 검증.

- 양식 읽기·검증: 필수 열, 별칭, 조건부 규칙, 일자 빈칸 → 오늘
- 변환: 집계용(상품·배송비·도선료 별도 줄) / 상세용(비용은 열) / 비용조정내역
- 집계·작성기: 조정 줄은 이카운트 줄과 합치지 않고, 비고 옆(G열)에 값만 표시
- 실제 이카운트 파일 + 첨부 ③의 조정 15건(가명) → 합계 660,181,300원
"""

import io
import sys
from datetime import date
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SRC_DIR = _TESTS_DIR.parent / "Src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import cost_adjustment as ca
import ecount_settlement as es
import seller_settlement as ss
import settlement as st_mod

TODAY = date(2026, 11, 20)
X2 = "사파이어쿨링 X2(A10) 변경"
STERILIZER = "유라이크 살균소독기"
SELLER = "러브지나 8차"


def _raw(*rows, columns=None):
    """업로드 엑셀을 읽은 것과 같은 원시 DataFrame (헤더 1행 기준)."""
    columns = columns or ca.TEMPLATE_COLS
    return pd.DataFrame([dict(zip(columns, r)) for r in rows], columns=columns)


def _row(**kw):
    """양식 열 순서의 한 행. 지정하지 않은 열은 빈칸."""
    return tuple(kw.get(c) for c in ca.TEMPLATE_COLS)


def _parse(*rows, today=TODAY, columns=None):
    return ca.parse_adjustments(_raw(*rows, columns=columns), today=today)


# ===== 양식·검증 =====


def test_missing_required_columns_raises_korean_message():
    raw = pd.DataFrame({"일자": ["2026-11-16"], "품목": [X2]})
    with pytest.raises(ValueError) as e:
        ca.parse_adjustments(raw, today=TODAY)
    assert "조정유형" in str(e.value)
    assert "특이사항" in str(e.value)


def test_column_aliases_are_accepted():
    cols = ["일자", "조정유형", "셀러", "제품", "수량", "상품매출", "반품비"]
    res = _parse(
        ("2026-11-16", "반품완료", SELLER, X2, -1, -282000, 6600), columns=cols
    )
    assert res["errors"].empty
    row = res["rows"].iloc[0]
    assert row["특이사항"] == SELLER
    assert row["품목"] == X2
    assert row["상품금액"] == -282000
    assert row["배송비"] == 6600


def test_blank_date_becomes_today_and_is_flagged():
    res = _parse(
        _row(조정유형="판매수수료", 특이사항=SELLER, 품목="판매수수료", 수량=1, 상품금액=-50000)
    )
    assert res["errors"].empty
    row = res["rows"].iloc[0]
    assert row["일자"] == pd.Timestamp(TODAY)
    assert bool(row["_일자빈칸"]) is True
    assert res["blank_date_count"] == 1


def test_missing_date_column_means_all_today():
    cols = ["조정유형", "특이사항", "배송비"]
    res = _parse(("반품배송비", SELLER, 6600), columns=cols)
    assert res["errors"].empty
    assert res["rows"].iloc[0]["일자"] == pd.Timestamp(TODAY)


@pytest.mark.parametrize(
    "value", ["2026-11-16", "2026.11.16", "2026/11/16", "20261116",
              pd.Timestamp("2026-11-16"), date(2026, 11, 16)],
)
def test_date_formats(value):
    res = _parse(_row(일자=value, 조정유형="반품배송비", 특이사항=SELLER, 배송비=6600))
    assert res["errors"].empty
    assert res["rows"].iloc[0]["일자"] == pd.Timestamp("2026-11-16")
    assert bool(res["rows"].iloc[0]["_일자빈칸"]) is False


def test_numbers_with_commas_and_unicode_minus():
    res = _parse(
        _row(일자="2026-11-16", 조정유형="반품완료", 특이사항=SELLER, 품목=X2,
             수량="−1", 상품금액="-282,000", 배송비="6,600")
    )
    assert res["errors"].empty
    row = res["rows"].iloc[0]
    assert (row["수량"], row["상품금액"], row["배송비"]) == (-1, -282000, 6600)


def test_row_errors_stop_with_excel_row_numbers():
    res = _parse(
        _row(일자="2026-11-16", 조정유형="반품완료", 특이사항=SELLER, 품목=X2, 상품금액=-282000),
        _row(일자="2026-11-16", 조정유형="반품완료", 특이사항=SELLER, 품목=X2, 수량=0, 상품금액=-1),
        _row(일자="2026-11-16", 조정유형="", 특이사항=SELLER, 배송비=6600),
        _row(일자="11월16일", 조정유형="반품배송비", 특이사항=SELLER, 배송비=6600),
        _row(일자="2026-11-16", 조정유형="반품배송비", 특이사항=SELLER),
        _row(일자="2026-11-16", 조정유형="반품완료", 특이사항=SELLER, 품목=X2, 수량=-1, 상품금액=-1.5),
        _row(일자="2026-11-16", 조정유형="반품배송비", 특이사항=SELLER, 배송비="육천"),
    )
    errors = res["errors"]
    assert errors["행"].tolist() == [2, 3, 4, 5, 6, 7, 8]
    reasons = errors["사유"].tolist()
    assert "수량" in reasons[0] and "함께" in reasons[0]
    assert "0" in reasons[1]
    assert "조정유형" in reasons[2]
    assert "일자" in reasons[3]
    assert "하나 이상" in reasons[4]
    assert "정수" in reasons[5]
    assert "배송비" in reasons[6]


def test_blank_rows_are_ignored_and_row_numbers_kept():
    res = _parse(
        _row(),
        _row(일자="2026-11-16", 조정유형="반품배송비", 특이사항=SELLER, 배송비=6600),
    )
    assert res["errors"].empty
    assert len(res["rows"]) == 1
    assert res["rows"].iloc[0]["_행"] == 3


def test_blank_seller_becomes_general():
    res = _parse(_row(일자="2026-11-16", 조정유형="판매수수료", 품목="판매수수료",
                      수량=1, 상품금액=-50000))
    assert res["rows"].iloc[0]["특이사항"] == ss.SHEET_GENERAL


def test_split_by_sellers():
    res = _parse(
        _row(일자="2026-11-16", 조정유형="반품배송비", 특이사항=SELLER, 배송비=6600),
        _row(일자="2026-11-16", 조정유형="반품배송비", 특이사항="러브지나 7차", 배송비=6600),
    )
    applied, excluded = ca.split_by_sellers(res["rows"], [SELLER])
    assert applied["특이사항"].tolist() == [SELLER]
    assert excluded["특이사항"].tolist() == ["러브지나 7차"]


def test_out_of_period_only_for_entered_dates():
    res = _parse(
        _row(일자="2026-11-17", 조정유형="반품접수", 특이사항=SELLER, 배송비=6600),
        _row(일자="2026-11-16", 조정유형="반품완료", 특이사항=SELLER, 배송비=6600),
        _row(조정유형="반품배송비", 특이사항=SELLER, 배송비=6600),  # 빈칸 → 오늘(기간 밖)
    )
    out = ca.out_of_period_rows(res["rows"], date(2026, 11, 1), date(2026, 11, 16))
    assert out["_행"].tolist() == [2]


def test_find_adjustment_sheet_and_read(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "메모"
    wb.active.append(["아무거나"])
    ws = wb.create_sheet("조정")
    ws.append(ca.TEMPLATE_COLS)
    ws.append(list(_row(일자="2026-11-16", 조정유형="반품배송비", 특이사항=SELLER, 배송비=6600)))
    path = tmp_path / "adj.xlsx"
    wb.save(path)
    data = path.read_bytes()
    assert ca.list_sheet_names(data) == ["메모", "조정"]
    assert ca.find_default_sheet(data) == "조정"
    res = ca.parse_adjustments(ca.read_adjustment_sheet(data, "조정"), today=TODAY)
    assert res["errors"].empty and len(res["rows"]) == 1


def test_template_xlsx_parses_without_errors():
    data = ca.build_template_xlsx()
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "작성안내" in wb.sheetnames
    sheet = ca.find_default_sheet(data)
    res = ca.parse_adjustments(ca.read_adjustment_sheet(data, sheet), today=TODAY)
    assert res["errors"].empty
    assert len(res["rows"]) == 3


# ===== 변환 =====


def _applied_sample():
    return _parse(
        _row(일자="2026-11-16", 조정유형="반품완료", 특이사항=SELLER, 품목=X2, 수량=-1,
             상품금액=-282000, 배송비=6600, 도선료=3000, 구분="변심반품",
             수하인명="홍길동", 연락처1="010-0000-0000", 수하인주소="제주"),
        _row(일자="2026-11-16", 조정유형="반품배송비", 특이사항=SELLER, 배송비=6600),
        _row(일자="2026-11-16", 조정유형="판매수수료", 특이사항=SELLER, 품목="판매수수료",
             수량=1, 상품금액=-50000, 메모="11월"),
    )["rows"]


def test_to_aggregate_rows_splits_product_and_fees():
    agg = ca.to_aggregate_rows(_applied_sample(), vendor="㈜테스트")
    c = ss.COLUMN_MAP_SALE
    assert agg[c["product"]].tolist() == [X2, "배송비", "도선료", "배송비", "판매수수료"]
    assert agg[c["qty"]].tolist() == [-1, 1, 1, 1, 1]
    assert agg[c["amount"]].tolist() == [-282000, 6600, 3000, 6600, -50000]
    assert agg[ss.ADJ_TYPE_COL].tolist() == ["반품완료"] * 3 + ["반품배송비", "판매수수료"]
    assert (agg[c["delivery"]] == 0).all() and (agg[c["ferry"]] == 0).all()
    assert (agg[c["vendor"]] == "㈜테스트").all()
    assert agg[c["category"]].tolist()[0] == "변심반품"
    assert agg[c["category"]].tolist()[-1] == "판매수수료"  # 구분 비면 조정유형


def test_to_detail_rows_one_row_per_adjustment():
    det = ca.to_detail_rows(_applied_sample(), vendor="㈜테스트")
    c = ss.COLUMN_MAP_SALE
    assert len(det) == 3
    first = det.iloc[0]
    assert (first[c["product"]], first[c["amount"]], first[c["delivery"]], first[c["ferry"]]) == (
        X2, -282000, 6600, 3000)
    assert first[c["consignee"]] == "홍길동"
    fee_only = det.iloc[1]
    assert fee_only[c["product"]] == "배송비"
    assert pd.isna(fee_only[c["qty"]])
    assert fee_only[c["amount"]] == 0 and fee_only[c["delivery"]] == 6600
    assert det[ss.ADJ_TYPE_COL].tolist() == ["반품완료", "반품배송비", "판매수수료"]


def test_adjustment_sheet_df_sale_and_purchase():
    sale = ca.build_adjustment_sheet_df(_applied_sample(), st_mod.TYPE_SALE)
    assert list(sale.columns) == [
        "일자", ss.ADJ_TYPE_COL, "구분", "특이사항", "제품", "수량", "상품매출",
        "판매배송비", "도선료", "수하인명", "연락처1", "수하인주소", "메모"]
    assert sale["일자"].tolist()[0] == "2026-11-16"
    assert sale["제품"].tolist()[1] == ""  # 입력 그대로 (빈칸)
    purchase = ca.build_adjustment_sheet_df(_applied_sample(), st_mod.TYPE_PURCHASE)
    assert "상품매입" in purchase.columns and "매입배송비" in purchase.columns
    assert "수하인명" not in purchase.columns


def test_summarize():
    s = ca.summarize(_applied_sample())
    assert s == {"건수": 3, "상품금액": -332000, "배송비": 13200, "도선료": 3000,
                 "순조정액": -315800}
    by_type = ca.summarize_by_type(_applied_sample())
    assert by_type.set_index(ss.ADJ_TYPE_COL).loc["반품완료", "순조정액"] == -272400


# ===== 집계·작성기 =====


def _orders(*rows):
    """to_order_settlement_df 결과와 같은 13열 주문 행."""
    c = ss.COLUMN_MAP_SALE
    recs = []
    for d, item, qty, amt in rows:
        recs.append({
            c["date"]: pd.Timestamp(d), c["vendor"]: "㈜테스트", c["category"]: "발주",
            c["consignee"]: "", c["address"]: "", c["product"]: item,
            c["phone1"]: "", c["phone2"]: "", c["seller"]: SELLER,
            c["qty"]: qty, c["amount"]: amt, c["delivery"]: 0.0, c["ferry"]: 0.0,
        })
    return pd.DataFrame(recs)[[c[k] for k in ss.DETAIL_LOGICAL_COLS]]


def test_aggregate_without_adjustment_column_is_unchanged():
    out = ss.aggregate_item_sheet(_orders(("2026-11-16", X2, 1, 282000)))
    assert list(out.columns) == list(st_mod.OUTPUT_COLS)


def test_aggregate_keeps_adjustment_lines_separate_and_after_ecount():
    orders = _orders(("2026-11-16", "배송비", 2, 13200), ("2026-11-16", X2, -1, -282000),
                     ("2026-11-17", X2, 3, 846000))
    agg = ca.to_aggregate_rows(_parse(
        _row(일자="2026-11-16", 조정유형="반품완료", 특이사항=SELLER, 품목=X2, 수량=-1,
             상품금액=-282000, 배송비=6600),
    )["rows"], vendor="㈜테스트")
    out = ss.aggregate_item_sheet(pd.concat([orders, agg], ignore_index=True))
    assert list(out.columns) == list(st_mod.OUTPUT_COLS) + [ss.ADJ_TYPE_COL]
    rows = out[["작성일자", "품목", "수량", "합계", ss.ADJ_TYPE_COL]].values.tolist()
    assert rows == [
        ["2026-11-16", "배송비", 2, 13200, ""],
        ["2026-11-16", X2, -1, -282000, ""],
        ["2026-11-16", "배송비", 1, 6600, "반품완료"],
        ["2026-11-16", X2, -1, -282000, "반품완료"],
        ["2026-11-17", X2, 3, 846000, ""],
    ]


def test_writer_adjustment_value_column_without_header(tmp_path):
    orders = _orders(("2026-11-16", X2, 2, 564000))
    applied = _applied_sample()
    agg = ca.to_aggregate_rows(applied, vendor="㈜테스트")
    plan = ss.build_sheet_plan(pd.concat([orders, agg], ignore_index=True), [SELLER])
    plan["detail_df"] = ss.build_detail_df(
        pd.concat([orders, ca.to_detail_rows(applied, vendor="㈜테스트")], ignore_index=True),
        [SELLER])
    plan["adjustments_df"] = ca.build_adjustment_sheet_df(applied, st_mod.TYPE_SALE)
    out = tmp_path / "out.xlsx"
    ss.write_seller_settlement_xlsx(str(out), ss.TITLE_SALE, "기간", plan)

    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == [SELLER, ss.DETAIL_SHEET_NAME, ss.ADJ_SHEET_NAME]
    ws = wb[SELLER]
    assert sorted(str(r) for r in ws.merged_cells.ranges) == ["A1:F1", "A2:F2"]
    assert ws["F3"].value == "비고"
    assert ws["G3"].value in (None, "")
    assert ws["G3"].fill.fill_type is None
    g_values = [ws.cell(row=r, column=7).value for r in range(4, ws.max_row)]
    assert "반품완료" in g_values and "판매수수료" in g_values
    assert ws.cell(row=4, column=7).value in (None, "")  # 이카운트 줄은 빈칸
    total_row = ws.max_row
    assert ws.cell(row=total_row, column=5).value == 564000 - 332000 + 13200 + 3000

    wd = wb[ss.DETAIL_SHEET_NAME]
    last_col = wd.max_column
    assert last_col == 14
    assert wd.cell(row=1, column=last_col).value in (None, "")
    assert wd.cell(row=3, column=last_col).value == "반품완료"
    assert wd.cell(row=4, column=10).value in (None, "")  # 배송비만 행의 수량은 빈칸

    wa = wb[ss.ADJ_SHEET_NAME]
    assert wa["B1"].value == ss.ADJ_TYPE_COL
    total = 2 + 3
    assert wa.cell(row=total, column=7).value == -332000
    assert wa.cell(row=total + 3, column=7).value == -315800


def test_writer_rejects_reserved_adjustment_sheet_name(tmp_path):
    plan = ss.build_sheet_plan(_orders(("2026-11-16", X2, 1, 282000)), [SELLER],
                               seller_to_sheet={SELLER: ss.ADJ_SHEET_NAME})
    plan["adjustments_df"] = ca.build_adjustment_sheet_df(_applied_sample(), st_mod.TYPE_SALE)
    with pytest.raises(ValueError, match="비용조정내역"):
        ss.write_seller_settlement_xlsx(str(tmp_path / "x.xlsx"), ss.TITLE_SALE, "기간", plan)


# ===== build_ecount_sheet_plan =====


def _ecount_df(*rows):
    """이카운트 파싱 결과(PARSED_COLS)와 같은 합성 행."""
    recs = []
    for d, item, qty, amt in rows:
        recs.append({
            "작성일자": d, "회사명": "㈜테스트", "품목": item, "구분": "발주",
            "수량": qty, "단가": amt, "합계": amt, "비고": SELLER, "수하인명": "",
            "연락처1": "", "수하인주소": "", "연락처2": "", "배송비": 0, "도선료": 0,
        })
    return pd.DataFrame(recs, columns=es.PARSED_COLS)


def test_build_plan_without_adjustments_has_no_adjustment_sheet():
    plan = es.build_ecount_sheet_plan(_ecount_df(("2026-11-16", X2, 1, 282000)))
    assert plan.get("adjustments_df") is None
    assert list(plan["seller_sheets"][SELLER].columns) == list(st_mod.OUTPUT_COLS)


def test_build_plan_sale_with_adjustments():
    df = _ecount_df(("2026-11-16", X2, 2, 564000))
    plan = es.build_ecount_sheet_plan(df, adjustments=_applied_sample())
    sheet = plan["seller_sheets"][SELLER]
    assert int(sheet["합계"].sum()) == 564000 - 315800
    assert len(plan["detail_df"]) == 1 + 3
    assert plan["detail_df"][ss.ADJ_TYPE_COL].tolist() == ["", "반품완료", "반품배송비", "판매수수료"]
    assert len(plan["adjustments_df"]) == 3
    assert int(plan["overall_df"]["합계"].sum()) == 564000 - 315800


def test_build_plan_sale_detail_none_still_has_adjustment_sheet():
    plan = es.build_ecount_sheet_plan(
        _ecount_df(("2026-11-16", X2, 1, 282000)), adjustments=_applied_sample(),
        detail_mode=ss.DETAIL_MODE_NONE)
    assert plan["detail_df"] is None
    assert len(plan["adjustments_df"]) == 3


def test_build_plan_purchase_with_adjustments(tmp_path):
    df = _ecount_df(("2026-11-16", X2, 2, 400000))
    plan = es.build_ecount_sheet_plan(df, adjustments=_applied_sample(),
                                      doc_type=st_mod.TYPE_PURCHASE)
    assert int(plan["seller_sheets"][SELLER]["합계"].sum()) == 400000 - 315800
    assert "상품매입" in plan["adjustments_df"].columns
    out = tmp_path / "p.xlsx"
    ss.write_seller_settlement_xlsx(str(out), ss.TITLE_PURCHASE, "기간", plan,
                                    column_map=ss.COLUMN_MAP_PURCHASE)
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["전체", SELLER, ss.ADJ_SHEET_NAME]


# ===== 실제 이카운트 파일 대조 (첨부 ③의 조정 15건, 가명) =====

ECOUNT_1117 = _TESTS_DIR / "이카운트_판매현황내역_20261117.xlsx"

# (일자, 조정유형, 품목, 수량, 상품금액, 배송비) — 금액은 수기 반영본 ③과 동일
_REAL_ADJ = [
    ("2026-11-16", "반품완료", X2, -1, -282000, 0),
    ("2026-11-16", "반품완료", X2, -1, -282000, 6600),
    ("2026-11-16", "반품완료", STERILIZER, -1, -43200, 3300),
    ("2026-11-16", "반품완료", X2, -1, -282000, 6600),
    ("2026-11-16", "반품완료", X2, -1, -282000, 6600),
    ("2026-11-16", "반품완료", X2, -1, -282000, 6600),
    ("2026-11-11", "반품접수", X2, -1, -282000, 6600),
    ("2026-11-11", "반품접수", X2, -1, -282000, 6600),
    ("2026-11-11", "반품접수", X2, -1, -282000, 0),
    ("2026-11-12", "반품접수", X2, -1, -282000, 6600),
    ("2026-11-12", "반품접수", X2, -1, -282000, 6600),
    ("2026-11-12", "반품접수", X2, -1, -282000, 0),
    ("2026-11-16", "반품접수", X2, -1, -282000, 6600),
    ("2026-11-16", "반품접수", STERILIZER, -1, -43200, 6600),
    ("2026-11-17", "반품접수", X2, -1, -282000, 6600),
]


@pytest.fixture(scope="module")
def ecount_1117_rows():
    if not ECOUNT_1117.is_file():
        pytest.skip(f"테스트 원본 파일이 없습니다: {ECOUNT_1117}")
    parsed = es.parse_ecount_xlsx(str(ECOUNT_1117), expected_doc_type=st_mod.TYPE_SALE)
    df = st_mod.filter_by_period(parsed["df"], date(2026, 11, 1), date(2026, 11, 16))
    df = st_mod.filter_by_vendor(df, "㈜씨씨오와이")
    return df[df["비고"].fillna("").str.strip() == SELLER].copy()


def test_real_ecount_with_15_adjustments_matches_manual_total(ecount_1117_rows):
    rows = [
        _row(일자=d, 조정유형=t, 특이사항=SELLER, 품목=item, 수량=q, 상품금액=a, 배송비=f,
             구분="변심반품", 수하인명=f"고객{i}")
        for i, (d, t, item, q, a, f) in enumerate(_REAL_ADJ, start=1)
    ]
    res = _parse(*rows)
    assert res["errors"].empty
    applied, excluded = ca.split_by_sellers(res["rows"], [SELLER])
    assert len(applied) == 15 and excluded.empty
    assert ca.out_of_period_rows(applied, date(2026, 11, 1), date(2026, 11, 16))["_행"].tolist() == [16]

    base = es.build_ecount_sheet_plan(ecount_1117_rows)
    plan = es.build_ecount_sheet_plan(ecount_1117_rows, adjustments=applied)
    base_sheet = base["seller_sheets"][SELLER]
    sheet = plan["seller_sheets"][SELLER]

    # 반영 전: ① 정산서와 동일
    assert (len(base_sheet), int(base_sheet["수량"].sum()), int(base_sheet["합계"].sum())) == (
        28, 2661, 663857800)
    # 이카운트 28줄은 그대로, 조정 줄만 추가
    ecount_lines = sheet[sheet[ss.ADJ_TYPE_COL] == ""].drop(columns=[ss.ADJ_TYPE_COL])
    pd.testing.assert_frame_equal(ecount_lines.reset_index(drop=True), base_sheet)
    # 합계: ③ 수기 반영본과 동일
    assert int(sheet["합계"].sum()) == 660181300
    assert int(sheet["수량"].sum()) == 2658

    assert len(plan["detail_df"]) == 2634 + 15
    adj = plan["adjustments_df"]
    assert int(adj["상품매출"].sum()) == -3752400
    assert int(adj["판매배송비"].sum()) == 75900
    assert ca.summarize(applied)["순조정액"] == -3676500


# ===== 화면 (AppTest) =====
# AppTest 는 file_uploader 를 지원하지 않으므로 비용조정 업로더만 가짜 파일로 대체한다.
# 로그인·권한·합성 이카운트 상태는 기존 화면 테스트 fixture 를 그대로 쓴다.
from test_ecount_settlement import (  # noqa: E402,F401  (pytest fixture 재사용)
    _assert_ecount_seller_ui_clean,
    ecount_seller_ui_app,
    ecount_seller_ui_parsed,
    ecount_ui_authenticated_session,
)


class _FakeUpload:
    def __init__(self, data: bytes, name: str = "비용조정.xlsx"):
        self._data = data
        self.name = name
        self.size = len(data)

    def getvalue(self) -> bytes:
        return self._data


def _adjustment_xlsx(*rows) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "조정"
    ws.append(ca.TEMPLATE_COLS)
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _patch_adjustment_upload(monkeypatch, data: bytes | None):
    import streamlit

    original = streamlit.file_uploader

    def fake_file_uploader(label, *args, **kwargs):
        if kwargs.get("key") == "settle_ecount_adj_uploader":
            return None if data is None else _FakeUpload(data)
        return original(label, *args, **kwargs)

    monkeypatch.setattr(streamlit, "file_uploader", fake_file_uploader)


def test_ui_adjustment_upload_preview_and_generate(ecount_seller_ui_app, monkeypatch):
    at = ecount_seller_ui_app
    at.multiselect(key="settle_ecount_seller_multiselect").set_value(["셀러B"]).run()
    _patch_adjustment_upload(monkeypatch, _adjustment_xlsx(
        _row(일자="2026-10-03", 조정유형="반품완료", 특이사항="셀러B", 품목="상품B",
             수량=-1, 상품금액=-7000, 배송비=3000, 구분="변심반품"),
        _row(조정유형="판매수수료", 특이사항="셀러B", 품목="판매수수료", 수량=1, 상품금액=-500),
        _row(일자="2026-10-03", 조정유형="반품완료", 특이사항="다른셀러", 배송비=3000),
    ))
    at.run()
    _assert_ecount_seller_ui_clean(at)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["반영 건수"] == "2건"
    assert metrics["순 조정액"] == "-4,500원"
    # 양식 링크는 요청 전에는 만들지 않는다 (생성 전 다운로드 파일 없음 원칙)
    assert not at.get("link_button")

    at.button(key="settle_ecount_preview_btn").click().run()
    _assert_ecount_seller_ui_clean(at)
    plan = at.session_state["settle_ecount_plan"]
    sheet = plan["seller_sheets"]["셀러B"]
    assert int(sheet["합계"].sum()) == 31000 - 4500
    assert set(sheet[ss.ADJ_TYPE_COL]) == {"", "반품완료", "판매수수료"}
    assert ss.ADJ_SHEET_NAME in [tab.label for tab in at.tabs]
    assert len(plan["adjustments_df"]) == 2

    at.button(key="settle_ecount_generate_btn").click().run()
    _assert_ecount_seller_ui_clean(at)
    wb = openpyxl.load_workbook(at.session_state["settle_ecount_output_path"])
    try:
        assert wb.sheetnames[-1] == ss.ADJ_SHEET_NAME
        ws = wb["셀러B"]
        assert ws["G3"].value in (None, "")
        assert "반품완료" in [ws.cell(r, 7).value for r in range(4, ws.max_row)]
    finally:
        wb.close()
    history = at.session_state["settle_ecount_history"][-1]
    assert history["비용조정"] == "2건"


def test_ui_adjustment_errors_stop_before_preview(ecount_seller_ui_app, monkeypatch):
    at = ecount_seller_ui_app
    at.multiselect(key="settle_ecount_seller_multiselect").set_value(["셀러B"]).run()
    _patch_adjustment_upload(monkeypatch, _adjustment_xlsx(
        _row(일자="2026-10-03", 조정유형="반품완료", 특이사항="셀러B", 품목="상품B",
             상품금액=-7000),
    ))
    at.run()
    assert not at.exception
    assert any("입력 오류 1건" in e.value for e in at.error)
    keys = [b.key for b in at.button]
    assert "settle_ecount_preview_btn" not in keys


def test_ui_adjustment_removed_restores_ecount_only(ecount_seller_ui_app, monkeypatch):
    at = ecount_seller_ui_app
    at.multiselect(key="settle_ecount_seller_multiselect").set_value(["셀러B"]).run()
    _patch_adjustment_upload(monkeypatch, _adjustment_xlsx(
        _row(일자="2026-10-03", 조정유형="판매수수료", 특이사항="셀러B", 품목="판매수수료",
             수량=1, 상품금액=-500),
    ))
    at.run()
    at.button(key="settle_ecount_preview_btn").click().run()
    signature = at.session_state["settle_ecount_plan_signature"]
    assert at.session_state["settle_ecount_plan"].get("adjustments_df") is not None

    _patch_adjustment_upload(monkeypatch, None)  # 파일 삭제
    at.run()
    _assert_ecount_seller_ui_clean(at)
    assert at.session_state["settle_ecount_plan"] is None  # 이전 미리보기 폐기
    assert at.session_state["settle_ecount_plan_signature"] != signature
    at.button(key="settle_ecount_preview_btn").click().run()
    plan = at.session_state["settle_ecount_plan"]
    assert plan.get("adjustments_df") is None
    assert list(plan["seller_sheets"]["셀러B"].columns) == list(st_mod.OUTPUT_COLS)


def test_ui_template_link_only_after_request(ecount_seller_ui_app):
    at = ecount_seller_ui_app
    at.multiselect(key="settle_ecount_seller_multiselect").set_value(["셀러B"]).run()
    assert not at.get("link_button")
    at.button(key="settle_ecount_adj_template_req").click().run()
    _assert_ecount_seller_ui_clean(at)
    assert len(at.get("link_button")) == 1


# 2026-11-20 hoyeon.han: 화면 표에서 빈 수량·금액이 'None'으로 보이지 않게 한다.
def test_blank_na_display_shows_blank_cells_without_changing_data():
    """배송비만 있는 조정 행의 수량·상품매출은 화면에서 빈칸, 데이터는 그대로."""
    import ui_components

    df = pd.DataFrame({
        "제품": ["배송비", None],
        "수량": [float("nan"), -1.0],
        "상품매출": [float("nan"), -89000.0],
        "판매배송비": [6600, 0],
    })
    original = df.copy()
    shown = ui_components.blank_na_display(df)
    pd.testing.assert_frame_equal(df, original)  # 합계 계산·엑셀 작성에 쓰는 원본은 그대로
    assert not shown.isna().to_numpy().any()  # st.dataframe 은 빈 값을 'None'으로 그린다
    assert shown["수량"].tolist() == ["", "-1"]
    assert shown["상품매출"].tolist() == ["", "-89000"]
    assert shown["제품"].tolist() == ["배송비", ""]
    assert shown["판매배송비"].tolist() == [6600, 0]  # 빈 값 없는 열은 숫자 그대로
    # 빈 값이 없으면 기존처럼 원본 그대로 표시
    plain = pd.DataFrame({"수량": [1], "상품매출": [1000]})
    assert ui_components.blank_na_display(plain) is plain
