# 2026-11-04 hoyeon.han: 구매 정산·유형 보호·최신 원본 저장·화면 통합 회귀 검증.
# 테스트 원본 제외 규칙(tests/)과 분리해 합성 회귀 검증 코드를 보관한다.
# 2026-11-05 hoyeon.han: 프로젝트 테스트는 .codex 대신 tests 경로에서 관리한다.
import hashlib
import io
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

# ROOT = Path(__file__).resolve().parents[2]
# 2026-11-05 hoyeon.han: tests 바로 아래로 이동한 위치에서 프로젝트 루트를 찾는다.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Src"))
sys.path.insert(0, str(ROOT / "tests"))

import ecount_settlement as es
import ecount_file_store as store_module
import seller_settlement as ss
from ecount_file_store import EcountFileStore
from settlement import TYPE_PURCHASE, TYPE_SALE
from test_ecount_settlement import ecount_ui_authenticated_session  # noqa: F401


def workbook_bytes(doc_type=TYPE_PURCHASE, *, native_total=True, amount=200, dates=None):
    """개인정보 없는 합성 원본: 일반 판매·반품·배송비·금액공란을 함께 검증한다."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "구매현황내역" if doc_type == TYPE_PURCHASE else "판매현황내역"
    ws.append(["회사명 : 합성회사 / 2026/10/01 ~ 2026/10/31"])
    if doc_type == TYPE_PURCHASE:
        headers = ["일자", "거래처명", "품목명", "수량", "특이사항", "공급가액", "부가세", "단가(vat포함)"]
        if native_total:
            headers += ["구분", "합계"]
        ws.append(headers)
        gross = amount + amount // 10
        rows = [
            ["2026/10/01", "합성매입처", "제품", 2, "셀러A", amount, amount // 10, gross],
            ["2026-10-02", "합성매입처", "제품", -1, "셀러A", -100, -10, -110],
            ["20261003", "합성매입처", "배송비", 1, "셀러A", 10, 1, 11],
            ["2026/10/04", "합성매입처", "제품", 1, None, None, None, None],
        ]
        if dates is not None:
            for row, source_date in zip(rows, dates):
                row[0] = source_date
        if native_total:
            for row, category, total in zip(rows, ["발주", "변심반품", "발주", None], [gross, -110, 11, None]):
                row += [category, total]
        for row in rows:
            ws.append(row)
        footer = ["총합계", None, None, 3, None, amount - 90, amount // 10 - 9, None]
        if native_total:
            footer += [None, gross - 99]
        ws.append(footer)
    else:
        ws.append(["일자", "거래처명", "품목명", "구분", "수량", "단가", "합계", "특이사항"])
        ws.append(["20261001", "합성매출처", "제품", "발주", 2, 100, amount, "셀러A"])
        ws.append(["총합계", None, None, None, 2, None, amount, None])
    stream = io.BytesIO()
    wb.save(stream)
    # 압축비 변화와 무관하게 같은 이름·같은 크기의 수정본을 만든다.
    stable = io.BytesIO()
    with zipfile.ZipFile(stream) as source, zipfile.ZipFile(stable, "w", compression=zipfile.ZIP_STORED) as target:
        for name in source.namelist():
            target.writestr(name, source.read(name))
    return stable.getvalue()


def edit_cell(payload, coordinate, value):
    wb = openpyxl.load_workbook(io.BytesIO(payload))
    wb.active[coordinate] = value
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.mark.parametrize("native_total", [False, True])
def test_purchase_contract_totals_and_no_detail(tmp_path, native_total):
    payload = workbook_bytes(native_total=native_total)
    parsed = es.parse_ecount_xlsx(io.BytesIO(payload), expected_doc_type=TYPE_PURCHASE)
    df = parsed["df"]
    assert parsed["doc_type"] == TYPE_PURCHASE
    assert parsed["blank_amount_rows"] == 1
    assert parsed["blank_amount_source_rows"] == [6]
    assert parsed["source_has_total"] is native_total
    assert list(df["작성일자"]) == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    assert df["합계"].sum() == 121
    assert es.verify_totals(df, parsed["footer_total"], parsed["footer_qty"])["matches"]
    plan = es.build_ecount_sheet_plan(df, detail_mode=ss.DETAIL_MODE_PER_SELLER, doc_type=TYPE_PURCHASE)
    assert plan["detail_mode"] == ss.DETAIL_MODE_NONE
    assert plan["detail_df"] is None and plan["detail_sheets"] is None
    assert set(plan["seller_sheets"]) == {"셀러A", "일반"}
    assert plan["overall_df"]["합계"].sum() == 121
    assert plan["overall_df"]["수량"].sum() == 3
    # 단가(vat포함)는 행 금액이다. 수량을 다시 곱하지 않아야 한다.
    item = plan["seller_sheets"]["셀러A"]
    assert item.loc[(item["품목"] == "제품") & (item["수량"] == 2), "단가"].iloc[0] == 110
    assert item.loc[item["수량"] < 0, "합계"].sum() == -110
    out = tmp_path / "정산서_매입.xlsx"
    ss.write_seller_settlement_xlsx(str(out), ss.TITLE_PURCHASE, "조회기간", plan, column_map=ss.COLUMN_MAP_PURCHASE)
    wb = openpyxl.load_workbook(out)
    assert not any("상세" in name for name in wb.sheetnames)
    assert all(wb[name]["A1"].value == ss.TITLE_PURCHASE for name in wb.sheetnames)


@pytest.mark.parametrize("doc_type,wrong", [(TYPE_SALE, TYPE_PURCHASE), (TYPE_PURCHASE, TYPE_SALE)])
def test_wrong_type_and_unknown_sheet_are_rejected(doc_type, wrong):
    payload = workbook_bytes(doc_type)
    with pytest.raises(ValueError, match="시트"):
        es.parse_ecount_xlsx(io.BytesIO(payload), expected_doc_type=wrong)
    wb = openpyxl.load_workbook(io.BytesIO(payload))
    wb.active.title = "이름을변경한시트"
    out = io.BytesIO()
    wb.save(out)
    with pytest.raises(ValueError, match="시트"):
        es.parse_ecount_xlsx(io.BytesIO(out.getvalue()), expected_doc_type=doc_type)


def test_both_known_sheets_select_expected_type():
    purchase = openpyxl.load_workbook(io.BytesIO(workbook_bytes()))
    sales = openpyxl.load_workbook(io.BytesIO(workbook_bytes(TYPE_SALE)))
    ws = purchase.create_sheet("판매현황내역", 0)
    for row in sales.active.values:
        ws.append(row)
    out = io.BytesIO()
    purchase.save(out)
    for doc_type in (TYPE_SALE, TYPE_PURCHASE):
        assert es.parse_ecount_xlsx(io.BytesIO(out.getvalue()), expected_doc_type=doc_type)["doc_type"] == doc_type


@pytest.mark.parametrize("coordinate,value", [("F3", "잘못된금액"), ("F3", "inf"), ("J3", 221), ("J7", 122)])
def test_invalid_purchase_amount_is_rejected(coordinate, value):
    with pytest.raises(ValueError):
        es.parse_ecount_xlsx(io.BytesIO(edit_cell(workbook_bytes(), coordinate, value)), expected_doc_type=TYPE_PURCHASE)


def test_store_independent_latest_and_failed_validation(tmp_path):
    store = EcountFileStore(tmp_path / "ecount")
    assert store.load(TYPE_SALE) is None and not store.store_dir.exists()
    sale = store.save(workbook_bytes(TYPE_SALE), "../판매.xlsx", TYPE_SALE)
    purchase = store.save(workbook_bytes(), "구매.xlsx", TYPE_PURCHASE)
    assert sale["original_name"] == "판매.xlsx"
    for payload in (workbook_bytes(TYPE_SALE), b"bad xlsx", edit_cell(workbook_bytes(), "F3", "오류")):
        with pytest.raises(ValueError):
            store.save(payload, "교체실패.xlsx", TYPE_PURCHASE)
        assert store.load(TYPE_PURCHASE) == purchase
    replacement = store.save(workbook_bytes(amount=300), "구매수정.xlsx", TYPE_PURCHASE)
    assert store.load(TYPE_PURCHASE) == replacement
    assert store.load(TYPE_SALE) == sale
    assert len(list(store.store_dir.rglob("*.zip"))) == 2
    assert not list(store.store_dir.rglob("*.tmp"))


def test_store_atomic_write_failure_and_concurrent_reads(tmp_path, monkeypatch):
    store = EcountFileStore(tmp_path / "ecount")
    old = store.save(workbook_bytes(), "구매.xlsx", TYPE_PURCHASE)
    def fail_replace(*args):
        raise OSError("합성 저장 실패")
    with monkeypatch.context() as patch:
        patch.setattr(store_module.os, "replace", fail_replace)
        with pytest.raises(OSError):
            store.save(workbook_bytes(amount=300), "구매수정.xlsx", TYPE_PURCHASE)
    assert store.load(TYPE_PURCHASE) == old
    assert not list(store.store_dir.rglob("*.tmp"))
    def task(i):
        record = store.save(workbook_bytes(amount=200 + i * 10), f"구매{i}.xlsx", TYPE_PURCHASE) if i % 2 else store.load(TYPE_PURCHASE)
        assert record["sha256"] == hashlib.sha256(record["file_bytes"]).hexdigest()
        return record
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(list(pool.map(task, range(12)))) == 12
    assert len(list(store.store_dir.rglob("*.zip"))) == 1


def test_real_purchase_original_anchor():
    source = ROOT / "tests" / "GC5IPNOYZGCPI73.xlsx"
    if not source.exists():
        pytest.skip("개인정보 원본은 저장소에 포함하지 않음")
    parsed = es.parse_ecount_xlsx(source, expected_doc_type=TYPE_PURCHASE)
    assert len(parsed["df"]) == 10979
    assert parsed["df"]["수량"].sum() == 11078
    assert parsed["df"]["합계"].sum() == 2138043907
    assert parsed["blank_amount_rows"] == 14
    assert es.verify_totals(parsed["df"], parsed["footer_total"], parsed["footer_qty"])["matches"]


def purchase_app(tmp_path, monkeypatch, marker):
    from streamlit.testing.v1 import AppTest
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(ROOT / "pages" / "settlement_ecount.py"), default_timeout=30)
    at.session_state["_security_marker"] = marker
    at.session_state["settle_ecount_doc_type"] = TYPE_PURCHASE
    return at.run()


def assert_clean(at):
    assert not at.exception, [error.value for error in at.exception]
    assert not at.error, [error.value for error in at.error]


def test_purchase_ui_stored_reuse_output_and_type_switch(tmp_path, monkeypatch, ecount_ui_authenticated_session):
    store = EcountFileStore(tmp_path / "order_data" / "ecount")
    stored = store.save(workbook_bytes(), "구매.xlsx", TYPE_PURCHASE)
    store.save(workbook_bytes(TYPE_SALE), "판매.xlsx", TYPE_SALE)
    at = purchase_app(tmp_path, monkeypatch, ecount_ui_authenticated_session)
    assert_clean(at)
    assert at.session_state["settle_ecount_uploaded_sig"] == (TYPE_PURCHASE, stored["sha256"])
    at.button(key="settle_ecount_select_all").click().run()
    at.button(key="settle_ecount_preview_btn").click().run()
    assert_clean(at)
    assert not any(radio.key == "settle_ecount_detail_mode_radio" for radio in at.radio)
    assert at.session_state["settle_ecount_plan"]["detail_df"] is None
    assert not any("상세" in tab.label for tab in at.tabs)
    at.button(key="settle_ecount_generate_btn").click().run()
    assert_clean(at)
    assert len(at.get("link_button")) == 1
    output = Path(at.session_state["settle_ecount_output_path"])
    wb = openpyxl.load_workbook(output)
    assert wb.active["A1"].value == ss.TITLE_PURCHASE
    assert not any("상세" in name for name in wb.sheetnames)
    assert "매입" in at.session_state["settle_ecount_output_filename"]
    at.radio(key="settle_ecount_doc_type").set_value(TYPE_SALE).run()
    assert_clean(at)
    assert at.session_state["settle_ecount_sellers"] == []
    assert at.session_state["settle_ecount_plan"] is None
    assert at.session_state["settle_ecount_output_path"] is None
    assert at.session_state["settle_ecount_parsed"]["doc_type"] == TYPE_SALE
    at.button(key="settle_ecount_select_all").click().run()
    assert at.radio(key="settle_ecount_detail_mode_radio").value == "전체 하나로 생성"
    at.radio(key="settle_ecount_doc_type").set_value(TYPE_PURCHASE).run()
    assert_clean(at)
    assert at.session_state["settle_ecount_sellers"] == []


def test_source_replacement_same_name_size_invalidates_cache_and_widgets(tmp_path, monkeypatch, ecount_ui_authenticated_session):
    store = EcountFileStore(tmp_path / "order_data" / "ecount")
    first = workbook_bytes(amount=200)
    second = workbook_bytes(amount=300)
    assert len(first) == len(second)
    store.save(first, "구매.xlsx", TYPE_PURCHASE)
    at = purchase_app(tmp_path, monkeypatch, ecount_ui_authenticated_session)
    at.button(key="settle_ecount_select_all").click().run()
    at.button(key="settle_ecount_preview_btn").click().run()
    at.button(key="settle_ecount_generate_btn").click().run()
    assert_clean(at)
    replacement = store.save(second, "구매.xlsx", TYPE_PURCHASE)
    at.run()
    assert_clean(at)
    assert at.session_state["settle_ecount_uploaded_sig"] == (TYPE_PURCHASE, replacement["sha256"])
    assert at.session_state["settle_ecount_parsed"]["df"]["합계"].sum() == 231
    assert at.session_state["settle_ecount_plan"] is None
    assert at.session_state["settle_ecount_output_path"] is None
    assert at.session_state["settle_ecount_sellers"] == []


def test_wrong_upload_ui_keeps_server_original_and_hides_output(tmp_path, monkeypatch, ecount_ui_authenticated_session):
    import streamlit as st
    store = EcountFileStore(tmp_path / "order_data" / "ecount")
    original = store.save(workbook_bytes(), "구매.xlsx", TYPE_PURCHASE)
    at = purchase_app(tmp_path, monkeypatch, ecount_ui_authenticated_session)
    at.button(key="settle_ecount_select_all").click().run()
    at.button(key="settle_ecount_preview_btn").click().run()
    at.button(key="settle_ecount_generate_btn").click().run()
    sale_bytes = workbook_bytes(TYPE_SALE)
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: SimpleNamespace(name="판매.xlsx", getvalue=lambda: sale_bytes))
    at.radio(key="settle_ecount_source_mode").set_value("새 파일 업로드").run()
    assert not at.exception
    assert at.error and "기존 서버 저장본은 유지" in at.error[0].value
    assert at.session_state["settle_ecount_parsed"] is None
    assert at.session_state["settle_ecount_output_path"] is None
    assert not at.get("link_button")
    assert store.load(TYPE_PURCHASE) == original


def test_valid_upload_saved_and_restored_new_session(tmp_path, monkeypatch, ecount_ui_authenticated_session):
    import streamlit as st
    payload = workbook_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(st, "file_uploader", lambda *args, **kwargs: SimpleNamespace(name="구매.xlsx", getvalue=lambda: payload))
        at = purchase_app(tmp_path, monkeypatch, ecount_ui_authenticated_session)
        assert_clean(at)
        assert at.radio(key="settle_ecount_source_mode").value == "서버에 저장된 최신 파일"
    at = purchase_app(tmp_path, monkeypatch, ecount_ui_authenticated_session)
    assert_clean(at)
    assert at.session_state["settle_ecount_parsed"]["df"]["합계"].sum() == 121
    assert at.session_state["settle_ecount_uploaded_sig"] == (TYPE_PURCHASE, hashlib.sha256(payload).hexdigest())
