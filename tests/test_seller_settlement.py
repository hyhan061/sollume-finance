# 2026-07-06 hoyeon.han 셀러 정산서 참고파일 대조 테스트 신규 작성
"""seller_settlement 모듈 검증.

참고 정산서(tests/리버후드정산내역서_2026-04_드엘리사 4차.xls)와
발주내역(tests/솔루미랩_발주내역_20260703 (4).xlsm)의 대조가 핵심:
  - 상세내역: 3146행, 상품매출 727,585,000 / 판매배송비 112,200 / 도선료 147,000
  - 셀러 시트: 집계 38행 행 단위 일치 + 합계 727,844,200
"""

from datetime import date

import pandas as pd
import pytest
import xlrd
from openpyxl import load_workbook

import seller_settlement as ss
# from conftest import REFERENCE_XLS
# 2026-11-05 hoyeon.han: pytest fixture는 자동 주입받고 참고파일 경로는 이 테스트 기준으로 정한다.
from pathlib import Path
REFERENCE_XLS = Path(__file__).resolve().parent / "리버후드정산내역서_2026-04_드엘리사 4차.xls"

SELLER = "드엘리사 4차"

# 참고 정산서의 품목명 정리 매핑 (원본 제품명 → 정산서 표기명)
ITEM_MAPPING = {
    "사파이어쿨링 X2(A10) 변경": "사파이어쿨링 X2(A10)",
    "유라이크 사파이어 쿨링 팬시 제모 의료기기(~2월)": "유라이크 사파이어 쿨링 팬시 제모 의료기기",
}


# ===== 참고파일 대조 =====


def test_detail_matches_reference(filtered_april):
    """상세내역 = 참고 정산서 상세내역과 행수/금액 일치."""
    detail = ss.build_detail_df(filtered_april, [SELLER])

    assert len(detail) == 3146
    assert int(detail["상품매출"].sum()) == 727_585_000
    assert int(detail["판매배송비"].sum()) == 112_200
    assert int(detail["도선료"].sum()) == 147_000
    total = int(
        detail["상품매출"].sum() + detail["판매배송비"].sum() + detail["도선료"].sum()
    )
    assert total == 727_844_200

    # 컬럼 순서 = 참고 정산서 상세내역과 동일
    assert detail.columns.tolist() == [
        "출고일", "업체명", "구분", "수하인명", "수하인주소", "제품",
        "연락처1", "연락처2", "특이사항", "수량", "상품매출", "판매배송비", "도선료",
    ]
    # item_mapping 없이 호출하면 제품명은 원본 그대로 (참고파일 상세내역과 동일)
    assert "사파이어쿨링 X2(A10) 변경" in set(detail["제품"])


def test_detail_applies_item_mapping(filtered_april):
    """2026-07-06: 상세내역 제품명에도 품목명 매핑이 적용된다 (사용자 요청)."""
    detail = ss.build_detail_df(filtered_april, [SELLER], item_mapping=ITEM_MAPPING)
    products = set(detail["제품"])
    # 매핑 원본 명칭은 사라지고 매핑 결과가 들어간다
    assert "사파이어쿨링 X2(A10) 변경" not in products
    assert "사파이어쿨링 X2(A10)" in products
    assert "유라이크 사파이어 쿨링 팬시 제모 의료기기" in products
    # 행수/금액은 매핑과 무관하게 동일
    assert len(detail) == 3146
    assert int(detail["상품매출"].sum()) == 727_585_000

    # build_sheet_plan 을 통한 detail_df 도 매핑이 반영되어야 함
    plan = ss.build_sheet_plan(filtered_april, [SELLER], item_mapping=ITEM_MAPPING)
    assert "사파이어쿨링 X2(A10) 변경" not in set(plan["detail_df"]["제품"])


def _read_reference_seller_rows():
    """참고 정산서 '드엘리사4차' 시트의 데이터 행/합계행 읽기."""
    wb = xlrd.open_workbook(str(REFERENCE_XLS))
    sh = wb.sheet_by_name("드엘리사4차")
    data_rows = []
    for r in range(3, sh.nrows - 1):  # row3~: 데이터, 마지막 행: 합계
        vals = [sh.cell_value(r, c) for c in range(6)]
        data_rows.append(
            {
                "작성일자": str(vals[0]),
                "품목": str(vals[1]),
                "수량": int(vals[2]),
                "단가": int(vals[3]),
                "합계": int(vals[4]),
                "비고": str(vals[5]),
            }
        )
    total_row = [sh.cell_value(sh.nrows - 1, c) for c in range(6)]
    return data_rows, total_row


def test_seller_sheet_matches_reference(filtered_april):
    """셀러 시트 집계가 참고 정산서 38행과 행 단위(순서 포함)로 일치."""
    if not REFERENCE_XLS.exists():
        pytest.skip("참고 정산서 파일이 없습니다.")

    rows = ss.filter_by_seller(filtered_april, SELLER)
    agg = ss.aggregate_item_sheet(rows, ITEM_MAPPING)

    ref_rows, ref_total = _read_reference_seller_rows()
    assert len(agg) == len(ref_rows) == 38

    for i, ref in enumerate(ref_rows):
        got = agg.iloc[i]
        assert got["작성일자"] == ref["작성일자"], f"row {i} 작성일자"
        assert got["품목"] == ref["품목"], f"row {i} 품목"
        assert int(got["수량"]) == ref["수량"], f"row {i} 수량"
        assert int(round(float(got["단가"]))) == ref["단가"], f"row {i} 단가"
        assert int(got["합계"]) == ref["합계"], f"row {i} 합계"
        assert got["비고"] == ref["비고"] == SELLER, f"row {i} 비고"

    # 합계행: ['', '38건', '3,179', '', '727,844,200', '']
    assert ref_total[1] == f"{len(agg)}건"
    assert int(agg["수량"].sum()) == int(str(ref_total[2]).replace(",", ""))
    assert int(agg["합계"].sum()) == int(str(ref_total[4]).replace(",", "")) == 727_844_200


# ===== 일자 선택 모드 =====


def test_filter_by_individual_dates(orders_df):
    """개별 날짜 모드: 지정한 날짜의 행만 포함."""
    picked = [date(2026, 4, 13), date(2026, 4, 15)]
    out = ss.filter_orders(orders_df, vendor="리버후드", dates=picked)

    assert not out.empty
    got_dates = set(out["출고일"].dt.date)
    assert got_dates == set(picked) & got_dates  # 지정 날짜 외 없음
    assert got_dates.issubset(set(picked))

    # 기간 모드로 같은 두 날짜만 있는 구간과 비교하는 대신, 날짜별 행수 합 검증
    by_range = ss.filter_orders(
        orders_df, vendor="리버후드", start_date=picked[0], end_date=picked[-1]
    )
    per_day = by_range[by_range["출고일"].dt.date.isin(picked)]
    assert len(out) == len(per_day)


def test_filter_requires_date_input(orders_df):
    with pytest.raises(ValueError):
        ss.filter_orders(orders_df, vendor="리버후드")
    with pytest.raises(ValueError):
        ss.filter_orders(orders_df, vendor="리버후드", dates=[])


# ===== 수량 0 포함 규칙 =====


def _make_synthetic_df():
    """수량 0/반품/도선료/택배비가 섞인 합성 발주내역 (정규화 형태)."""
    cols = ss.COLUMN_MAP_SALE
    rows = [
        # date, vendor, category, consignee, addr, product, p1, p2, seller, qty, amount, delivery, ferry
        ("2026-06-01", "테스트업체", "발주", "김철수", "서울", "상품A", "010", "010", "셀러X", 2, 20000, 0, 0),
        ("2026-06-01", "테스트업체", "발주", "이영희", "부산", "상품A", "010", "010", "셀러X", 1, 10000, 0, 3000),
        # 수량 0 이지만 금액이 있는 행 — 반드시 포함되어야 함
        ("2026-06-01", "테스트업체", "마감", "박민수", "대구", "상품A", "010", "010", "셀러X", 0, 5000, 0, 0),
        # 반품 (수량 음수) + 반품 택배비
        ("2026-06-02", "테스트업체", "반품", "최지우", "인천", "상품A", "010", "010", "셀러X", -1, -10000, 6600, 0),
    ]
    df = pd.DataFrame(rows, columns=[cols[k] for k in ss.DETAIL_LOGICAL_COLS])
    df[cols["date"]] = pd.to_datetime(df[cols["date"]])
    return df


def test_zero_qty_row_included():
    """수량 0 & 금액≠0 행이 집계/상세내역/합계에 모두 포함된다."""
    df = _make_synthetic_df()
    agg = ss.aggregate_item_sheet(ss.filter_by_seller(df, "셀러X"))

    # 수량 0 행: 단가 0 그룹으로 존재, 합계에 금액 반영
    zero_qty = agg[(agg["수량"] == 0) & (agg["품목"] == "상품A")]
    assert len(zero_qty) == 1
    assert int(zero_qty.iloc[0]["합계"]) == 5000
    assert int(zero_qty.iloc[0]["단가"]) == 0

    # 전체 합계 = 20000+10000+5000-10000(반품) + 도선료 3000 + 택배비 6600
    assert int(agg["합계"].sum()) == 34_600

    detail = ss.build_detail_df(df, ["셀러X"])
    assert len(detail) == 4  # 수량 0 행 포함


def test_fee_lines_and_return_ordering():
    """도선료/택배비 라인 생성 + 정렬(양수 먼저 반품 뒤) 규칙."""
    df = _make_synthetic_df()
    agg = ss.aggregate_item_sheet(ss.filter_by_seller(df, "셀러X"))

    ferry = agg[agg["품목"] == ss.ITEM_FERRY]
    assert len(ferry) == 1
    assert (
        ferry.iloc[0]["작성일자"],
        int(ferry.iloc[0]["수량"]),
        int(ferry.iloc[0]["단가"]),
        int(ferry.iloc[0]["합계"]),
    ) == ("2026-06-01", 1, 3000, 3000)

    parcel = agg[agg["품목"] == ss.ITEM_PARCEL]
    assert len(parcel) == 1
    assert (
        parcel.iloc[0]["작성일자"],
        int(parcel.iloc[0]["수량"]),
        int(parcel.iloc[0]["단가"]),
    ) == ("2026-06-02", 1, 6600)

    # 6/1 상품A: 단가 10000 양수 그룹(수량 3)과 수량0 그룹 → 반품 없음
    # 6/2 상품A: 반품 그룹만 존재
    day2 = agg[agg["작성일자"] == "2026-06-02"].reset_index(drop=True)
    assert day2.iloc[0]["품목"] == "상품A" and int(day2.iloc[0]["수량"]) == -1


def test_aggregate_without_fee_lines(recwarn):
    """도선료/택배비가 모두 없는 셀러 — 빈 프레임 concat 로 인한 dtype 강등/경고 없음."""
    cols = ss.COLUMN_MAP_SALE
    rows = [
        ("2026-06-01", "업체", "발주", "김", "서울", "상품A", "010", "010", "셀러Y", 2, 20000, 0, 0),
        ("2026-06-02", "업체", "발주", "이", "부산", "상품B", "010", "010", "셀러Y", 1, 5000, 0, 0),
    ]
    df = pd.DataFrame(rows, columns=[cols[k] for k in ss.DETAIL_LOGICAL_COLS])
    df[cols["date"]] = pd.to_datetime(df[cols["date"]])

    agg = ss.aggregate_item_sheet(ss.filter_by_seller(df, "셀러Y"))

    # 작성일자가 정상 문자열로 나와야 함 (dtype 강등 시 여기서 깨짐)
    assert list(agg["작성일자"]) == ["2026-06-01", "2026-06-02"]
    assert int(agg["합계"].sum()) == 25_000
    # 도선료/택배비 라인은 없음
    assert ss.ITEM_FERRY not in set(agg["품목"])
    assert ss.ITEM_PARCEL not in set(agg["품목"])
    # pandas concat FutureWarning 미발생
    assert not [w for w in recwarn.list if issubclass(w.category, FutureWarning)]


# ===== 시트 계획 / 예약어 / sanitize / 다중 셀러 =====


def _multi_seller_df():
    """셀러 3종(러브지나, 러브지나 2차, 임파)이 섞인 합성 발주내역."""
    cols = ss.COLUMN_MAP_SALE
    rows = [
        ("2026-06-01", "업체", "발주", "김", "서울", "상품A", "010", "010", "러브지나", 2, 20000, 0, 0),
        ("2026-06-01", "업체", "발주", "이", "부산", "상품A", "010", "010", "러브지나 2차", 1, 10000, 0, 0),
        ("2026-06-02", "업체", "발주", "박", "대구", "상품B", "010", "010", "임파", 3, 30000, 0, 0),
    ]
    df = pd.DataFrame(rows, columns=[cols[k] for k in ss.DETAIL_LOGICAL_COLS])
    df[cols["date"]] = pd.to_datetime(df[cols["date"]])
    return df


def test_sheet_plan_reserved_name_rejected():
    df = _make_synthetic_df()
    with pytest.raises(ValueError):
        ss.build_sheet_plan(df, ["셀러X"], seller_to_sheet={"셀러X": ss.DETAIL_SHEET_NAME})


def test_sheet_plan_sanitizes_sheet_name():
    df = _make_synthetic_df()
    df[ss.COLUMN_MAP_SALE["seller"]] = "셀러/X[1]"
    plan = ss.build_sheet_plan(df, ["셀러/X[1]"])
    assert list(plan["seller_sheets"].keys()) == ["셀러_X_1_"]  # 금지문자 → '_'


def test_sheet_plan_empty_seller_rejected():
    df = _make_synthetic_df()
    with pytest.raises(ValueError):
        ss.build_sheet_plan(df, ["없는셀러"])
    with pytest.raises(ValueError):
        ss.build_sheet_plan(df, [])  # 셀러 미선택


def test_multi_seller_separate_sheets():
    """셀러 여러 개 기본 배치 → 셀러명별 별도 시트, 상세내역은 전체 셀러."""
    df = _multi_seller_df()
    sellers = ["러브지나", "러브지나 2차", "임파"]
    plan = ss.build_sheet_plan(df, sellers)
    assert set(plan["seller_sheets"].keys()) == set(sellers)
    # 각 시트는 자기 셀러 데이터만
    assert int(plan["seller_sheets"]["러브지나"]["합계"].sum()) == 20000
    assert int(plan["seller_sheets"]["임파"]["합계"].sum()) == 30000
    # 상세내역은 선택된 모든 셀러 행
    assert len(plan["detail_df"]) == 3


def test_multi_seller_merged_sheet():
    """여러 셀러를 같은 시트명으로 묶으면 통합 — 비고 값은 각 셀러명 보존."""
    df = _multi_seller_df()
    sellers = ["러브지나", "러브지나 2차", "임파"]
    seller_to_sheet = {"러브지나": "러브지나", "러브지나 2차": "러브지나", "임파": "임파"}
    plan = ss.build_sheet_plan(df, sellers, seller_to_sheet=seller_to_sheet)
    assert list(plan["seller_sheets"].keys()) == ["러브지나", "임파"]
    merged = plan["seller_sheets"]["러브지나"]
    # 통합 시트에 두 셀러 데이터 모두 포함, 비고 열에 각 원본 셀러명 유지
    assert set(merged["비고"]) == {"러브지나", "러브지나 2차"}
    assert int(merged["합계"].sum()) == 30000


def test_resolve_sheet_map():
    sm = ss.resolve_sheet_map(
        ["A", "B", "C"], {"A": "묶음", "B": "묶음", "C": ""}
    )
    assert sm == {"묶음": ["A", "B"], "C": ["C"]}
    with pytest.raises(ValueError):
        ss.resolve_sheet_map(["A"], {"A": ss.DETAIL_SHEET_NAME})


# 2026-08-10 hoyeon.han: '배치할 시트'를 비웠을 때 '일반' 시트로 가도록 수정하며 추가
def test_normalize_sheet_choice():
    """None/NaN/공백은 fallback 으로, 그 외는 공백 제거한 값으로."""
    assert ss.normalize_sheet_choice(None, "일반") == "일반"
    assert ss.normalize_sheet_choice("", "일반") == "일반"
    assert ss.normalize_sheet_choice("   ", "일반") == "일반"
    assert ss.normalize_sheet_choice(float("nan"), "일반") == "일반"
    assert ss.normalize_sheet_choice(pd.NA, "일반") == "일반"
    assert ss.normalize_sheet_choice(" 묶음 ", "일반") == "묶음"
    # fallback 은 호출부가 정한다 — 셀러명 폴백도 여전히 가능해야 한다
    assert ss.normalize_sheet_choice(None, "쏘피") == "쏘피"


def test_resolve_sheet_map_none_does_not_create_none_sheet():
    """data_editor 가 None 을 돌려줘도 'None' 이라는 이름의 시트가 생기지 않는다."""
    sm = ss.resolve_sheet_map(["A", "B"], {"A": None, "B": "묶음"})
    assert "None" not in sm
    assert sm == {"A": ["A"], "묶음": ["B"]}


def test_resolve_sheet_map_general_merges():
    """화면이 '일반'으로 확정해 넘기면 여러 셀러가 '일반' 시트로 통합된다."""
    sm = ss.resolve_sheet_map(
        ["A", "B", "C"], {"A": "일반", "B": "일반", "C": "쏘피"}
    )
    assert sm == {"일반": ["A", "B"], "쏘피": ["C"]}


def test_split_into_sheets_none_value_goes_to_general():
    """파일업로드 방식도 None/빈 값이 '일반' 시트로 간다 ('None' 시트 생성 금지)."""
    import settlement as st_mod

    df = pd.DataFrame(
        {
            "작성일자": ["2026-08-01", "2026-08-02", "2026-08-03"],
            "품목": ["A", "B", "C"],
            "수량": [1, 2, 3],
            "단가": [100, 200, 300],
            "합계": [100, 400, 900],
            "비고": ["쏘피", "민들레", "임파"],
        }
    )
    sheets = st_mod.split_into_sheets(
        df, {"쏘피": None, "민들레": "", "임파": "임파"}
    )
    assert "None" not in sheets
    assert len(sheets[st_mod.SHEET_GENERAL]) == 2
    assert list(sheets.keys()) == [
        st_mod.SHEET_OVERALL,
        st_mod.SHEET_GENERAL,
        "임파",
    ]


# ===== 헤더 텍스트 / 파일명 =====


def test_period_line_and_filename():
    line = ss.build_period_line(
        "리버후드", start_date=date(2026, 4, 1), end_date=date(2026, 4, 30)
    )
    assert "2026-04-01" in line and "2026-04-30" in line and "리버후드" in line

    picked = [date(2026, 4, 15), date(2026, 4, 13)]
    line2 = ss.build_period_line("리버후드", dates=picked)
    assert "2026-04-13, 2026-04-15" in line2  # 정렬 + 3개 이하 나열

    many = [date(2026, 4, d) for d in range(1, 8)]
    line3 = ss.build_period_line("리버후드", dates=many)
    assert "2026-04-01 외 6일" in line3

    # 2026-07-06: 시트 1개면 '정산서_매출_{업체명}_{시트명}', 여러개면 '{업체명}'만
    fn = ss.build_output_filename("리버후드", ["드엘리사 4차"])
    assert fn == "정산서_매출_리버후드_드엘리사 4차.xlsx"

    fn_multi = ss.build_output_filename("리버후드", ["드엘리사 4차", "바글이"])
    assert fn_multi == "정산서_매출_리버후드.xlsx"

    # 파일명 금지문자는 '_' 로 치환
    fn2 = ss.build_output_filename("리버/후드", ["드엘리사:4차"])
    assert fn2 == "정산서_매출_리버_후드_드엘리사_4차.xlsx"


# ===== writer 스모크 =====


def test_write_xlsx_structure(tmp_path):
    """생성 파일 구조: [셀러시트, 상세내역], 13pt, 합계 셀만 강조, 상세 합계/총합계."""
    df = _make_synthetic_df()
    plan = ss.build_sheet_plan(df, ["셀러X"])
    out = str(tmp_path / "out.xlsx")
    ss.write_seller_settlement_xlsx(
        out,
        title=ss.TITLE_SALE,
        period_line=ss.build_period_line(
            "테스트업체", start_date=date(2026, 6, 1), end_date=date(2026, 6, 2)
        ),
        plan=plan,
    )

    wb = load_workbook(out)
    assert wb.sheetnames == ["셀러X", ss.DETAIL_SHEET_NAME]

    ws = wb["셀러X"]
    assert ws.cell(row=1, column=1).value == ss.TITLE_SALE
    assert [ws.cell(row=3, column=c).value for c in range(1, 7)] == list(ss.OUTPUT_COLS)

    n = len(plan["seller_sheets"]["셀러X"])
    # 데이터 셀 폰트 13pt
    assert ws.cell(row=4, column=2).font.size == 13
    # 합계행: N건 / 수량합 / 금액합. 행 전체 굵게 13pt, 색상 강조는 합계 셀만.
    total_row = 4 + n
    assert ws.cell(row=total_row, column=2).value == f"{n}건"
    assert ws.cell(row=total_row, column=5).value == 34_600
    tcell = ws.cell(row=total_row, column=5)  # 합계(금액) 셀
    assert tcell.font.bold and tcell.font.size == 13
    assert tcell.font.color.rgb == "FFFF0000"
    assert tcell.fill.start_color.rgb == "FFFFFF00"
    # 2026-07-06: 색상 강조는 합계 셀만 — 다른 합계행 셀(예: 'N건')은 채우기 없음
    other_cell = ws.cell(row=total_row, column=2)
    assert other_cell.font.bold and other_cell.font.size == 13  # 굵게 13pt는 유지
    assert other_cell.fill.patternType is None  # 채우기 색상 없음

    ws2 = wb[ss.DETAIL_SHEET_NAME]
    assert ws2.cell(row=1, column=1).value == "출고일"
    assert ws2.freeze_panes == "A2"
    n_detail = len(plan["detail_df"])
    amount_idx = plan["detail_df"].columns.tolist().index("상품매출") + 1
    # 열별 합계행
    assert ws2.cell(row=2 + n_detail, column=amount_idx).value == 25_000
    # 빈 2행 뒤 총합계행 = 상품매출+판매배송비+도선료
    assert ws2.cell(row=2 + n_detail + 3, column=amount_idx).value == 34_600
    # 셀러시트 예약어 방어 (writer 단)
    bad_plan = {
        "seller_sheets": {ss.DETAIL_SHEET_NAME: plan["seller_sheets"]["셀러X"]},
        "detail_df": plan["detail_df"],
    }
    with pytest.raises(ValueError):
        ss.write_seller_settlement_xlsx(
            str(tmp_path / "bad.xlsx"), ss.TITLE_SALE, "x", bad_plan
        )


def test_write_xlsx_multiple_sheets(tmp_path):
    """셀러 다중 → 여러 셀러 시트 + 상세내역, 시트 순서 = 배치 순서."""
    df = _multi_seller_df()
    sellers = ["러브지나", "러브지나 2차", "임파"]
    # 러브지나·러브지나 2차 → '러브지나' 시트로 통합, 임파는 별도
    seller_to_sheet = {"러브지나": "러브지나", "러브지나 2차": "러브지나", "임파": "임파"}
    plan = ss.build_sheet_plan(df, sellers, seller_to_sheet=seller_to_sheet)
    out = str(tmp_path / "multi.xlsx")
    ss.write_seller_settlement_xlsx(
        out,
        title=ss.TITLE_SALE,
        period_line=ss.build_period_line("업체", dates=[date(2026, 6, 1), date(2026, 6, 2)]),
        plan=plan,
    )
    wb = load_workbook(out)
    assert wb.sheetnames == ["러브지나", "임파", ss.DETAIL_SHEET_NAME]


# ===== 매입 정산서 (2026-07-23 hoyeon.han 신규) =====
# 매입 참고 정산서 파일이 없으므로 자체 정합성/구조 테스트로 검증한다.

PURCHASE_VENDOR = "시온프로젝트"
# 테스트 발주내역 고정본 기준 앵커: 2026 전체·시온프로젝트의
# (상품매입 + 매입배송비>0 + 매입도선료>0) 합계
PURCHASE_TOTAL = 348_517_620


def test_purchase_load_normalizes_columns(orders_df_purchase):
    """매입 로딩: 매입 컬럼 존재 + 원본 '도선료.1' → '매입도선료' 정규화."""
    cols = set(orders_df_purchase.columns)
    for need in ("매입처", "상품매입", "매입배송비", "매입도선료"):
        assert need in cols, f"매입 컬럼 누락: {need}"
    # pandas 가 중복 '도선료' 헤더에 붙인 접미명은 load_orders 에서 정규화됨
    assert "도선료.1" not in cols
    # 매입 맵의 모든 원본 컬럼이 실제 존재해야 한다
    assert set(ss.COLUMN_MAP_PURCHASE.values()) <= cols


def test_purchase_self_consistency(orders_df_purchase):
    """매입: 셀러 시트 합계 총합 == 상세내역 기준 기대 합계 (자체 정합성)."""
    cmap = ss.COLUMN_MAP_PURCHASE
    df_pv = ss.filter_orders(
        orders_df_purchase,
        vendor=PURCHASE_VENDOR,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        column_map=cmap,
    )
    sellers = ss.extract_sellers(df_pv, column_map=cmap)
    assert sellers, f"{PURCHASE_VENDOR} 매입 데이터에 셀러(특이사항)가 있어야 함"

    # 상세내역 기준 기대 합계 = 상품매입 전체합 + 매입배송비(>0)합 + 매입도선료(>0)합
    # (aggregate_item_sheet 가 fee 라인을 값>0 행만 만드는 규칙과 동일)
    detail = ss.build_detail_df(df_pv, sellers, column_map=cmap)
    amt = int(detail[cmap["amount"]].sum())
    deliv = int(detail.loc[detail[cmap["delivery"]] > 0, cmap["delivery"]].sum())
    ferry = int(detail.loc[detail[cmap["ferry"]] > 0, cmap["ferry"]].sum())
    expected_total = amt + deliv + ferry

    plan = ss.build_sheet_plan(df_pv, sellers, column_map=cmap)
    sheet_total = sum(int(sdf["합계"].sum()) for sdf in plan["seller_sheets"].values())

    # 핵심 불변식: 셀러 시트 합계 총합 = 상세내역 기준 기대 합계
    assert sheet_total == expected_total
    # 회귀 앵커 (테스트 발주내역 고정본)
    assert sheet_total == PURCHASE_TOTAL


def test_purchase_output_filename():
    """매입 파일명: doc_type=매입 이 파일명에 반영된다."""
    one = ss.build_output_filename(
        PURCHASE_VENDOR, ["11am"], doc_type=ss.TYPE_PURCHASE
    )
    assert one == "정산서_매입_시온프로젝트_11am.xlsx"
    many = ss.build_output_filename(
        PURCHASE_VENDOR, ["a", "b"], doc_type=ss.TYPE_PURCHASE
    )
    assert many == "정산서_매입_시온프로젝트.xlsx"


def _make_synthetic_purchase_df():
    """매입 매핑 컬럼으로 구성한 합성 발주내역 (파일 없이 집계 검증)."""
    cols = ss.COLUMN_MAP_PURCHASE
    rows = [
        # date, 매입처, 구분, 수하인명, 주소, 제품, p1, p2, 특이사항, 수량, 상품매입, 매입배송비, 매입도선료
        ("2026-06-01", "매입처A", "발주", "김철수", "서울", "상품A", "010", "010", "셀러P", 2, 20000, 0, 0),
        ("2026-06-01", "매입처A", "발주", "이영희", "부산", "상품A", "010", "010", "셀러P", 1, 10000, 0, 3000),
        ("2026-06-02", "매입처A", "발주", "박민수", "대구", "상품B", "010", "010", "셀러P", 3, 30000, 5000, 0),
    ]
    df = pd.DataFrame(rows, columns=[cols[k] for k in ss.DETAIL_LOGICAL_COLS])
    df[cols["date"]] = pd.to_datetime(df[cols["date"]])
    return df


def test_purchase_aggregate_with_purchase_map():
    """매입 맵으로도 집계 동작: 금액=상품매입, 라인=매입도선료/매입배송비."""
    cmap = ss.COLUMN_MAP_PURCHASE
    df = _make_synthetic_purchase_df()
    agg = ss.aggregate_item_sheet(
        ss.filter_by_seller(df, "셀러P", column_map=cmap), column_map=cmap
    )
    # 상품 60000(상품A 30000 + 상품B 30000) + 도선료 3000 + 택배비 5000
    assert int(agg["합계"].sum()) == 68_000
    assert int((agg["품목"] == ss.ITEM_FERRY).sum()) == 1
    assert int((agg["품목"] == ss.ITEM_PARCEL).sum()) == 1
    assert set(agg["비고"]) == {"셀러P"}


# ===== 상세내역 3택 (2026-07-24 hoyeon.han 신규) =====
# 발주내역 기반 정산서생성의 상세내역 옵션: none / single(기본) / per_seller.
# 기본값(single)은 기존 셀러 화면과 하위호환이어야 한다.

_SELLERS3 = ["러브지나", "러브지나 2차", "임파"]


def test_detail_mode_default_is_single():
    """detail_mode 미지정 시 기존 동작(single) — 하위호환 앵커."""
    df = _multi_seller_df()
    plan = ss.build_sheet_plan(df, _SELLERS3)
    assert plan["detail_mode"] == ss.DETAIL_MODE_SINGLE
    assert plan["detail_df"] is not None
    assert plan["detail_sheets"] is None
    # 명시 single 과 기본이 동일한 detail_df 를 만든다
    plan_single = ss.build_sheet_plan(df, _SELLERS3, detail_mode=ss.DETAIL_MODE_SINGLE)
    pd.testing.assert_frame_equal(plan["detail_df"], plan_single["detail_df"])


def test_detail_mode_none(tmp_path):
    """none: plan 에 상세 데이터 없음 + 워크북 상세시트 0장."""
    df = _multi_seller_df()
    plan = ss.build_sheet_plan(df, _SELLERS3, detail_mode=ss.DETAIL_MODE_NONE)
    assert plan["detail_mode"] == ss.DETAIL_MODE_NONE
    assert plan["detail_df"] is None
    assert plan["detail_sheets"] is None

    out = str(tmp_path / "none.xlsx")
    ss.write_seller_settlement_xlsx(out, ss.TITLE_SALE, "x", plan)
    wb = load_workbook(out)
    assert wb.sheetnames == _SELLERS3  # 셀러 시트만, 상세시트 없음
    assert ss.DETAIL_SHEET_NAME not in wb.sheetnames


def test_detail_mode_per_seller(tmp_path):
    """per_seller: 셀러별 '상세내역_{셀러}' N장이 셀러 시트 뒤에, 내용 일치."""
    df = _multi_seller_df()
    plan = ss.build_sheet_plan(df, _SELLERS3, detail_mode=ss.DETAIL_MODE_PER_SELLER)
    assert plan["detail_mode"] == ss.DETAIL_MODE_PER_SELLER
    assert plan["detail_df"] is None

    expected_names = [f"{ss.DETAIL_SHEET_NAME}_{s}" for s in _SELLERS3]
    assert list(plan["detail_sheets"].keys()) == expected_names
    # 각 상세 시트 = 해당 셀러 단독 build_detail_df 와 동일
    for seller in _SELLERS3:
        name = f"{ss.DETAIL_SHEET_NAME}_{seller}"
        expected = ss.build_detail_df(df, [seller]).reset_index(drop=True)
        got = plan["detail_sheets"][name].reset_index(drop=True)
        pd.testing.assert_frame_equal(got, expected)

    out = str(tmp_path / "per_seller.xlsx")
    ss.write_seller_settlement_xlsx(out, ss.TITLE_SALE, "x", plan)
    wb = load_workbook(out)
    # 셀러 시트들 뒤에 상세 시트들
    assert wb.sheetnames == _SELLERS3 + expected_names


def test_detail_mode_per_seller_with_merged_summary(tmp_path):
    """요약시트로 여러 셀러를 묶어도 상세는 셀러 단위로 분리된다 (A3 결정)."""
    df = _multi_seller_df()
    # 러브지나 + 러브지나 2차 → '러브지나' 요약시트로 통합, 임파는 별도
    seller_to_sheet = {"러브지나": "러브지나", "러브지나 2차": "러브지나", "임파": "임파"}
    plan = ss.build_sheet_plan(
        df, _SELLERS3, seller_to_sheet=seller_to_sheet,
        detail_mode=ss.DETAIL_MODE_PER_SELLER,
    )
    # 요약 시트는 2장(러브지나 통합, 임파)
    assert list(plan["seller_sheets"].keys()) == ["러브지나", "임파"]
    # 상세는 셀러 단위 3장
    assert list(plan["detail_sheets"].keys()) == [
        "상세내역_러브지나", "상세내역_러브지나 2차", "상세내역_임파"
    ]

    out = str(tmp_path / "merged.xlsx")
    ss.write_seller_settlement_xlsx(out, ss.TITLE_SALE, "x", plan)
    wb = load_workbook(out)
    assert wb.sheetnames == [
        "러브지나", "임파",
        "상세내역_러브지나", "상세내역_러브지나 2차", "상세내역_임파",
    ]


def test_per_seller_detail_name_collision_with_summary():
    """상세 시트명이 셀러 요약 시트명과 겹치면 접미('_2')로 회피한다."""
    df = _multi_seller_df()
    # 임파의 요약 시트명을 '상세내역_러브지나'로 강제 → 러브지나 상세와 충돌 유발
    seller_to_sheet = {"임파": "상세내역_러브지나"}
    plan = ss.build_sheet_plan(
        df, _SELLERS3, seller_to_sheet=seller_to_sheet,
        detail_mode=ss.DETAIL_MODE_PER_SELLER,
    )
    summary_names = list(plan["seller_sheets"].keys())
    assert "상세내역_러브지나" in summary_names  # 임파의 요약 시트

    detail_names = list(plan["detail_sheets"].keys())
    assert "상세내역_러브지나" not in detail_names   # 요약과 충돌 → 회피됨
    assert "상세내역_러브지나_2" in detail_names
    # 요약 + 상세 전체 시트명이 유일
    all_names = summary_names + detail_names
    assert len(all_names) == len(set(all_names))


def test_per_seller_sheet_name_truncation():
    """31자 초과·접두 겹침 셀러명도 상세 시트명이 유일하고 31자 이하."""
    cols = ss.COLUMN_MAP_SALE
    base_name = "가" * 30
    a = base_name                 # 30자
    b = base_name[:28] + "나나"    # 앞 28자 동일, 30자 → 절단 시 충돌
    rows = [
        ("2026-06-01", "업체", "발주", "김", "서울", "상품A", "010", "010", a, 1, 1000, 0, 0),
        ("2026-06-01", "업체", "발주", "이", "부산", "상품A", "010", "010", b, 1, 2000, 0, 0),
    ]
    df = pd.DataFrame(rows, columns=[cols[k] for k in ss.DETAIL_LOGICAL_COLS])
    df[cols["date"]] = pd.to_datetime(df[cols["date"]])

    plan = ss.build_sheet_plan(df, [a, b], detail_mode=ss.DETAIL_MODE_PER_SELLER)
    names = list(plan["detail_sheets"].keys())
    assert len(names) == 2
    assert len(set(names)) == 2                                   # 유일
    assert all(len(n) <= ss.SHEET_MAX_LEN for n in names)         # 31자 이하
    assert all(n.startswith(ss.DETAIL_SHEET_NAME + "_") for n in names)


def test_unknown_detail_mode_rejected():
    df = _multi_seller_df()
    with pytest.raises(ValueError):
        ss.build_sheet_plan(df, _SELLERS3, detail_mode="bogus")


# ===== '전체' 시트 (2026-07-31 hoyeon.han 신규) =====
# 발주내역 방식의 include_overall 옵션: 선택 셀러 전체를 한 시트로 집계해 맨 앞에 둔다.
# 기본값 False 라 셀러 화면(및 기존 테스트)에는 영향이 없어야 한다.


def test_overall_default_off(tmp_path):
    """include_overall 기본 False → overall_df None, '전체' 시트 미생성 (하위호환)."""
    df = _multi_seller_df()
    plan = ss.build_sheet_plan(df, _SELLERS3)
    assert plan["overall_df"] is None

    out = str(tmp_path / "no_overall.xlsx")
    ss.write_seller_settlement_xlsx(out, ss.TITLE_SALE, "x", plan)
    wb = load_workbook(out)
    assert ss.SHEET_OVERALL not in wb.sheetnames
    assert wb.sheetnames == _SELLERS3 + [ss.DETAIL_SHEET_NAME]


def test_overall_included_first_sheet(tmp_path):
    """include_overall=True → '전체' 시트가 맨 앞, 집계 합계는 셀러 시트 합의 합."""
    df = _multi_seller_df()
    plan = ss.build_sheet_plan(df, _SELLERS3, include_overall=True)
    assert plan["overall_df"] is not None

    seller_total = sum(int(s["합계"].sum()) for s in plan["seller_sheets"].values())
    assert int(plan["overall_df"]["합계"].sum()) == seller_total == 60_000

    out = str(tmp_path / "overall.xlsx")
    ss.write_seller_settlement_xlsx(out, ss.TITLE_SALE, "x", plan)
    wb = load_workbook(out)
    # '전체'(맨 앞) → 셀러 시트들 → 상세내역(single 기본)
    assert wb.sheetnames == [ss.SHEET_OVERALL] + _SELLERS3 + [ss.DETAIL_SHEET_NAME]
    assert wb.sheetnames[0] == ss.SHEET_OVERALL


def test_overall_with_per_seller_detail(tmp_path):
    """전체 + 셀러별 상세 조합: [전체, 셀러..., 상세내역_셀러...]."""
    df = _multi_seller_df()
    plan = ss.build_sheet_plan(
        df, _SELLERS3, include_overall=True, detail_mode=ss.DETAIL_MODE_PER_SELLER
    )
    out = str(tmp_path / "overall_ps.xlsx")
    ss.write_seller_settlement_xlsx(out, ss.TITLE_SALE, "x", plan)
    wb = load_workbook(out)
    expected = (
        [ss.SHEET_OVERALL] + _SELLERS3 + [f"상세내역_{s}" for s in _SELLERS3]
    )
    assert wb.sheetnames == expected


def test_overall_name_collision_rejected():
    """셀러 시트명이 '전체'인데 include_overall=True 면 충돌로 ValueError."""
    df = _multi_seller_df()
    seller_to_sheet = {"임파": ss.SHEET_OVERALL}  # 임파를 '전체' 시트로 배치
    with pytest.raises(ValueError):
        ss.build_sheet_plan(
            df, _SELLERS3, seller_to_sheet=seller_to_sheet, include_overall=True
        )
    # include_overall=False 면 '전체' 시트명도 일반 셀러 시트로 허용
    plan = ss.build_sheet_plan(
        df, _SELLERS3, seller_to_sheet=seller_to_sheet, include_overall=False
    )
    assert ss.SHEET_OVERALL in plan["seller_sheets"]
