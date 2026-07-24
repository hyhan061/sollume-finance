"""정산서 생성 페이지 / 2026-05-27 hoyeon.han"""

# 2026-05-27 hoyeon.han: 정산서(매출/매입) 생성 페이지 신규 생성

import importlib.util
import os
import sys
from datetime import date, datetime  # 2026-07-24 hoyeon.han: 발주내역 일자 모드용 date 추가
from pathlib import Path

import pandas as pd
import streamlit as st

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정 (Streamlit 명령 중 가장 먼저 실행되어야 함)
# 2026-07-10 hoyeon.han: st.navigation 라우터(Home.py)로 이전 - 진입점에서 처리
# st.set_page_config(
#     page_title="정산서 생성", page_icon="📋", layout="wide"
# )

# 인증 체크 (Src/__init__.py 우회 — 기존 페이지 패턴 동일)
spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent.parent / "Src" / "auth.py"
)
if spec is None or spec.loader is None:
    raise ImportError("auth 모듈을 불러올 수 없습니다.")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
# auth.require_auth()

# 커스텀 사이드바
from ui_components import render_custom_sidebar  # noqa: E402

# 2026-07-09 hoyeon.han: 디자인 개선 - 공통 테마 CSS/헤더 모듈
from ui_theme import inject_global_css, render_page_header  # noqa: E402

# render_custom_sidebar()
# 2026-07-09 hoyeon.han: 사이드바 렌더 이후 전역 CSS 주입
# inject_global_css()

# 정산서 비즈니스 로직
import settlement as st_mod  # noqa: E402

# 2026-07-24 hoyeon.han: 발주내역 기반 생성 — 순수 로직/저장소 재사용
# (settlement_seller.py 는 side-effect 페이지 스크립트라 import 금지, 순수 모듈만 사용)
import seller_settlement as ss  # noqa: E402
from order_file_store import OrderFileStore  # noqa: E402

# 디렉토리 생성
os.makedirs("uploads", exist_ok=True)
os.makedirs("processed", exist_ok=True)


# ===== 세션 상태 초기화 =====

_DEFAULTS = {
    "settlement_doc_type": st_mod.TYPE_SALE,
    "settlement_parsed": None,
    "settlement_uploaded_name": None,
    "settlement_start_date": None,
    "settlement_end_date": None,
    "settlement_vendor": None,
    "settlement_item_mapping": None,
    "settlement_remark_sheet_map": None,
    "settlement_sheets": None,
    "settlement_output_path": None,
    "settlement_output_filename": None,
    "settlement_history": [],
    "settlement_doc_type_user_override": False,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# 2026-05-31 hoyeon.han: 생성 옵션 위젯 키 — 데이터 변경 시 함께 제거해
# 자동 감지 기본값이 다시 계산되도록 한다.
_OPTION_WIDGET_KEYS = (
    "settlement_exclude_general",
    "settlement_highlight_total",
    "settlement_total_font_size",
    "settlement_total_font_color",
    "settlement_total_fill_color",
)

# 2026-05-31 hoyeon.han: data_editor 위젯 키 — 거래처/기간/파일이 바뀌면
# 품목·비고 목록이 달라지므로, 행 인덱스 기준 편집 델타가 다른 데이터에
# 잘못 적용되지 않도록 함께 비운다.
_EDITOR_WIDGET_KEYS = (
    "settlement_item_editor",
    "settlement_remark_editor",
)


def _reset_option_widgets() -> None:
    """생성 옵션/편집기 위젯 상태 제거 (다음 렌더에서 기본값 재초기화)."""
    for wk in _OPTION_WIDGET_KEYS + _EDITOR_WIDGET_KEYS:
        st.session_state.pop(wk, None)


def _reset_below_parse() -> None:
    """파일/유형 변경 시 파싱 결과 이하 모든 상태 리셋."""
    for k in (
        "settlement_parsed",
        "settlement_uploaded_name",
        "settlement_start_date",
        "settlement_end_date",
        "settlement_vendor",
        "settlement_item_mapping",
        "settlement_remark_sheet_map",
        "settlement_sheets",
        "settlement_output_path",
        "settlement_output_filename",
    ):
        st.session_state[k] = _DEFAULTS[k]
    _reset_option_widgets()


def _reset_below_period() -> None:
    """기간 변경 시 거래처 이하 리셋."""
    for k in (
        "settlement_vendor",
        "settlement_item_mapping",
        "settlement_remark_sheet_map",
        "settlement_sheets",
        "settlement_output_path",
        "settlement_output_filename",
    ):
        st.session_state[k] = _DEFAULTS[k]
    _reset_option_widgets()


def _reset_below_vendor() -> None:
    """거래처 변경 시 매핑 이하 리셋."""
    for k in (
        "settlement_item_mapping",
        "settlement_remark_sheet_map",
        "settlement_sheets",
        "settlement_output_path",
        "settlement_output_filename",
    ):
        st.session_state[k] = _DEFAULTS[k]
    _reset_option_widgets()


# ===== 발주내역 기반 생성 (2026-07-24 hoyeon.han 신규) =====
# 정산서생성(셀러) 화면(pages/settlement_seller.py)의 흐름을 미러링하되,
# (1) 상세내역 3택 옵션, (2) 비고 없는 행을 '일반' 셀러로 포함, 을 추가한다.
# 셀러 화면 파일은 건드리지 않고 순수 로직(seller_settlement.py)만 재사용한다.
# 세션 키는 'settle_order_' 접두사로 기존 'settlement_' 흐름과 완전히 분리한다.

_ORDER_MODE_RANGE = "기간 선택"
_ORDER_MODE_DATES = "개별 날짜 선택"

# 상세내역 3택 라벨 → seller_settlement 상수 (index 1 = 전체 하나로 = 기본값)
_DETAIL_LABELS = {
    "생성 안 함": ss.DETAIL_MODE_NONE,
    "전체 하나로 생성": ss.DETAIL_MODE_SINGLE,
    "셀러별 생성": ss.DETAIL_MODE_PER_SELLER,
}
_DETAIL_LABEL_LIST = list(_DETAIL_LABELS.keys())

# 비고(특이사항) 없는 행을 묶을 셀러/시트명 (파일업로드 방식의 '일반' 시트와 통일)
_NO_SELLER_LABEL = st_mod.SHEET_GENERAL  # "일반"

_ORDER_DEFAULTS = {
    "settle_order_doc_type": ss.TYPE_SALE,
    "settle_order_file_sig": None,  # (file_path, sheet, mtime, doc_type)
    "settle_order_date_mode": _ORDER_MODE_RANGE,
    "settle_order_start_date": None,
    "settle_order_end_date": None,
    "settle_order_dates": None,
    "settle_order_vendor": None,
    "settle_order_sellers": [],
    "settle_order_item_mapping": None,
    "settle_order_seller_sheet_map": None,
    "settle_order_detail_mode": ss.DETAIL_MODE_SINGLE,  # 기본: 전체 하나로
    "settle_order_plan": None,
    "settle_order_output_path": None,
    "settle_order_output_filename": None,
    "settle_order_history": [],
}

_ORDER_DATE_WIDGETS = (
    "settle_order_date_mode_radio",
    "settle_order_start_input",
    "settle_order_end_input",
    "settle_order_dates_multiselect",
)
_ORDER_VENDOR_WIDGETS = ("settle_order_vendor_select",)
_ORDER_SELLER_WIDGETS = ("settle_order_seller_multiselect",)
_ORDER_EDITOR_WIDGETS = ("settle_order_item_editor", "settle_order_sheet_editor")
_ORDER_OPTION_WIDGETS = (
    "settle_order_font_size",
    "settle_order_font_color",
    "settle_order_fill_color",
    "settle_order_detail_mode_radio",
)


def _order_init_state() -> None:
    for k, v in _ORDER_DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _order_pop_widgets(*groups) -> None:
    for group in groups:
        for wk in group:
            st.session_state.pop(wk, None)


def _reset_order_below_sellers() -> None:
    """셀러 선택 변경 시 품목/시트/상세옵션/plan 이하 리셋."""
    for k in (
        "settle_order_item_mapping",
        "settle_order_seller_sheet_map",
        "settle_order_detail_mode",
        "settle_order_plan",
        "settle_order_output_path",
        "settle_order_output_filename",
    ):
        st.session_state[k] = _ORDER_DEFAULTS[k]
    _order_pop_widgets(_ORDER_EDITOR_WIDGETS, _ORDER_OPTION_WIDGETS)


def _reset_order_below_vendor() -> None:
    st.session_state["settle_order_sellers"] = list(
        _ORDER_DEFAULTS["settle_order_sellers"]
    )
    _order_pop_widgets(_ORDER_SELLER_WIDGETS)
    _reset_order_below_sellers()


def _reset_order_below_date() -> None:
    st.session_state["settle_order_vendor"] = _ORDER_DEFAULTS["settle_order_vendor"]
    _order_pop_widgets(_ORDER_VENDOR_WIDGETS)
    _reset_order_below_vendor()


def _reset_order_below_file() -> None:
    for k in (
        "settle_order_date_mode",
        "settle_order_start_date",
        "settle_order_end_date",
        "settle_order_dates",
    ):
        st.session_state[k] = _ORDER_DEFAULTS[k]
    _order_pop_widgets(_ORDER_DATE_WIDGETS)
    _reset_order_below_date()


@st.cache_data(show_spinner="📖 발주내역을 읽는 중...")
def _order_load_orders(
    path: str, sheet: str, file_mtime: float, order_doc_type: str
) -> pd.DataFrame:
    """발주내역 로딩 (캐싱). file_mtime/order_doc_type 는 캐시 키 분리용."""
    cmap = (
        ss.COLUMN_MAP_SALE if order_doc_type == ss.TYPE_SALE else ss.COLUMN_MAP_PURCHASE
    )
    return ss.load_orders(path, sheet, cmap)


def _render_order_based_flow() -> None:
    """발주내역(서버 저장본) 기반 정산서 생성 흐름 (매출/매입 · 상세내역 3택)."""
    _order_init_state()

    # ----- 1. 정산서 유형 (매출/매입) -----
    st.markdown("### 🧭 1. 정산서 유형")
    doc_type = st.radio(
        "정산서 유형",
        options=[ss.TYPE_SALE, ss.TYPE_PURCHASE],
        horizontal=True,
        index=0 if st.session_state.settle_order_doc_type == ss.TYPE_SALE else 1,
        key="settle_order_doc_type_radio",
        help="매출 기준(상품매출)과 매입 기준(상품매입) 정산서를 전환합니다.",
    )
    st.session_state.settle_order_doc_type = doc_type
    column_map = ss.COLUMN_MAP_SALE if doc_type == ss.TYPE_SALE else ss.COLUMN_MAP_PURCHASE
    title_const = ss.TITLE_SALE if doc_type == ss.TYPE_SALE else ss.TITLE_PURCHASE

    # ----- 2. 발주내역 파일 (서버 저장본) -----
    st.markdown("### 📂 2. 발주내역 파일 (서버 저장본)")
    store = OrderFileStore()
    if not store.exists():
        st.warning(
            "📂 서버에 저장된 발주내역 파일이 없습니다. "
            "**전표생성** 또는 **발주내역요약** 화면에서 발주내역을 먼저 업로드해주세요."
        )
        st.stop()
    meta = store.get_metadata() or {}
    file_path = store.get_path()
    original_name = meta.get("original_name", "current.xlsm")
    uploaded_at = meta.get("uploaded_at", "")
    st.success(
        f"📎 저장된 발주내역 사용: **{original_name}**"
        + (f"  (업로드: {uploaded_at})" if uploaded_at else "")
    )
    sheet_names = meta.get("sheet_names", [])
    if not sheet_names:
        st.error("❌ 저장된 파일의 시트 목록을 읽을 수 없습니다. 파일을 다시 업로드해주세요.")
        st.stop()
    recommended = meta.get("recommended_sheet")
    prev_sig = st.session_state.settle_order_file_sig
    prev_sheet = prev_sig[1] if (prev_sig and prev_sig[0] == file_path) else None
    if prev_sheet in sheet_names:
        default_index = sheet_names.index(prev_sheet)
    elif recommended in sheet_names:
        default_index = sheet_names.index(recommended)
    else:
        default_index = 0
    sheet_col, sheet_tip = st.columns([2, 3], vertical_alignment="center")
    with sheet_col:
        selected_sheet = st.selectbox(
            "📋 처리할 시트 선택",
            options=sheet_names,
            index=default_index,
            key="settle_order_sheet_selector",
        )
    with sheet_tip:
        st.caption("정산서로 만들 발주내역 시트를 선택하세요. 보통 최신 연도 시트입니다.")

    mtime = os.path.getmtime(file_path)
    file_sig = (file_path, selected_sheet, mtime, doc_type)
    if st.session_state.settle_order_file_sig != file_sig:
        st.session_state.settle_order_file_sig = file_sig
        _reset_order_below_file()

    try:
        df_orders = _order_load_orders(file_path, selected_sheet, mtime, doc_type)
    except ValueError as e:
        st.error(f"❌ {e}")
        st.stop()
    except Exception as e:  # noqa: BLE001
        st.error(f"❌ 발주내역을 읽지 못했습니다: {e}")
        with st.expander("🔍 에러 상세 정보"):
            st.exception(e)
        st.stop()

    date_range = ss.extract_date_range(df_orders, column_map=column_map)
    if date_range:
        st.caption(f"📅 데이터 기간  {date_range[0]} ~ {date_range[1]}")
    mc1, mc2 = st.columns(2)
    mc1.metric("데이터 행 수", f"{len(df_orders):,}")
    mc2.metric("업체 수", len(ss.extract_vendors(df_orders, column_map=column_map)))
    if date_range is None:
        st.error("❌ 발주내역에 유효한 출고일 데이터가 없습니다. 시트를 확인해주세요.")
        st.stop()

    # ----- 3. 일자 선택 (기간/개별 날짜) -----
    st.markdown("### 📅 3. 일자 선택")
    mode = st.radio(
        "일자 선택 방식",
        options=[_ORDER_MODE_RANGE, _ORDER_MODE_DATES],
        horizontal=True,
        index=0 if st.session_state.settle_order_date_mode == _ORDER_MODE_RANGE else 1,
        key="settle_order_date_mode_radio",
    )
    if mode != st.session_state.settle_order_date_mode:
        st.session_state.settle_order_date_mode = mode
        _reset_order_below_date()
        st.rerun()
    min_d, max_d = date_range
    date_kwargs: dict = {}
    if mode == _ORDER_MODE_RANGE:
        _month_first = date(date.today().year, date.today().month, 1)
        default_start = min(max(_month_first, min_d), max_d)
        col1, col2 = st.columns(2)
        start_date = col1.date_input(
            "시작일",
            value=st.session_state.settle_order_start_date or default_start,
            min_value=min_d,
            max_value=max_d,
            key="settle_order_start_input",
        )
        end_date = col2.date_input(
            "종료일",
            value=st.session_state.settle_order_end_date or max_d,
            min_value=min_d,
            max_value=max_d,
            key="settle_order_end_input",
        )
        if start_date > end_date:
            st.error("❌ 시작일이 종료일보다 늦을 수 없습니다.")
            st.stop()
        if (start_date, end_date) != (
            st.session_state.settle_order_start_date,
            st.session_state.settle_order_end_date,
        ):
            st.session_state.settle_order_start_date = start_date
            st.session_state.settle_order_end_date = end_date
            _reset_order_below_date()
            st.rerun()
        st.info(f"📌 선택 기간: **{start_date} ~ {end_date}**")
        date_kwargs = {"start_date": start_date, "end_date": end_date}
    else:
        all_dates = ss.extract_order_dates(df_orders, column_map=column_map)
        all_date_strs = [d.isoformat() for d in all_dates]
        default_dates = [
            d.isoformat()
            for d in (st.session_state.settle_order_dates or [])
            if d.isoformat() in all_date_strs
        ]
        picked_strs = st.multiselect(
            "출고일 선택 (발주내역에 있는 날짜만 표시됩니다)",
            options=all_date_strs,
            default=default_dates,
            key="settle_order_dates_multiselect",
        )
        if not picked_strs:
            st.info("📌 날짜를 1개 이상 선택하세요.")
            st.stop()
        picked_sorted = sorted(date.fromisoformat(s) for s in picked_strs)
        if picked_sorted != (st.session_state.settle_order_dates or []):
            st.session_state.settle_order_dates = picked_sorted
            _reset_order_below_date()
            st.rerun()
        st.info(f"📌 선택 날짜: **{len(picked_sorted)}일**")
        date_kwargs = {"dates": picked_sorted}

    # ----- 4. 거래처 선택 -----
    st.markdown("### 🏢 4. 거래처 선택")
    df_dated = ss.filter_by_dates(df_orders, **date_kwargs, column_map=column_map)
    vendors = ss.extract_vendors(df_dated, column_map=column_map)
    if not vendors:
        st.warning("⚠️ 선택한 일자에 거래처 데이터가 없습니다.")
        st.stop()
    prev_vendor = st.session_state.settle_order_vendor
    vendor_idx = vendors.index(prev_vendor) if prev_vendor in vendors else 0
    vendor_col, vendor_tip = st.columns([2, 3], vertical_alignment="center")
    with vendor_col:
        selected_vendor = st.selectbox(
            f"거래처 선택 (총 {len(vendors)}개)",
            options=vendors,
            index=vendor_idx,
            key="settle_order_vendor_select",
        )
    with vendor_tip:
        st.caption("거래처를 바꾸면 아래 셀러·시트 설정이 초기화됩니다.")
    if selected_vendor != prev_vendor:
        st.session_state.settle_order_vendor = selected_vendor
        _reset_order_below_vendor()
        st.rerun()

    # ----- 5. 셀러(비고) 선택 — 비고 없는 행은 '일반'으로 포함 -----
    st.markdown("### 🧑‍💼 5. 셀러(비고) 선택")
    st.caption(
        "셀러 값은 발주내역의 **특이사항** 컬럼입니다. 비고가 없는 행은 "
        f"**'{_NO_SELLER_LABEL}'** 셀러로 묶여 포함됩니다."
    )
    df_pv = ss.filter_orders(
        df_orders, vendor=selected_vendor, **date_kwargs, column_map=column_map
    )
    seller_col = column_map["seller"]
    # 2026-07-24 hoyeon.han: 비고(특이사항) 없는 행을 '일반' 셀러로 재라벨해 포함한다.
    # (파일업로드 방식의 '일반' 시트 개념. 셀러가 전혀 없어도 '일반'으로 생성 가능)
    blank_mask = df_pv[seller_col].astype(str).str.strip() == ""
    n_blank = int(blank_mask.sum())
    if n_blank > 0:
        df_pv = df_pv.copy()
        df_pv.loc[blank_mask, seller_col] = _NO_SELLER_LABEL
        st.info(
            f"ℹ️ 비고(특이사항)가 없는 {n_blank:,}건은 "
            f"'{_NO_SELLER_LABEL}' 셀러로 포함됩니다."
        )
    sellers = ss.extract_sellers(df_pv, column_map=column_map)
    if not sellers:
        st.warning("⚠️ 선택한 일자/거래처에 데이터가 없습니다.")
        st.stop()
    seller_counts = df_pv[seller_col].value_counts()
    if st.button("전체 선택", key="settle_order_select_all"):
        st.session_state["settle_order_seller_multiselect"] = list(sellers)
        st.rerun()
    default_sellers = [
        s for s in st.session_state.settle_order_sellers if s in sellers
    ]
    selected_sellers = st.multiselect(
        f"셀러 선택 (총 {len(sellers)}개, 복수 선택 가능)",
        options=sellers,
        default=default_sellers,
        format_func=lambda s: f"{s} ({int(seller_counts.get(s, 0)):,}건)",
        key="settle_order_seller_multiselect",
    )
    if not selected_sellers:
        st.warning("⚠️ 셀러(비고)를 1개 이상 선택하세요.")
        st.stop()
    selected_sellers = [s for s in sellers if s in set(selected_sellers)]
    if selected_sellers != st.session_state.settle_order_sellers:
        st.session_state.settle_order_sellers = selected_sellers
        _reset_order_below_sellers()
        st.rerun()
    df_seller_rows = ss.filter_by_sellers(
        df_pv, selected_sellers, column_map=column_map
    )

    # ----- 6. 품목명 정리 -----
    st.markdown("### 📝 6. 품목명 정리")
    st.caption(
        "필요시 품목명을 정제하세요. 같은 값으로 묶으면 통합됩니다. "
        "셀러 시트 집계와 상세내역 시트의 제품명에 모두 적용됩니다."
    )
    items = ss.extract_items(df_seller_rows, column_map=column_map)
    if st.session_state.settle_order_item_mapping is None:
        st.session_state.settle_order_item_mapping = {it: it for it in items}
    with st.expander(f"품목명 매핑 편집 ({len(items)}건)", expanded=True):
        # 위젯 상태가 살아있으면 identity baseline(피드백 루프 방지),
        # 페이지 복귀(위젯 상태 소실)면 저장된 매핑으로 '변경' 열 복원.
        if "settle_order_item_editor" in st.session_state:
            changed_col = items
        else:
            _m = st.session_state.settle_order_item_mapping or {}
            changed_col = [_m.get(it, it) for it in items]
        item_df = pd.DataFrame({"원본": items, "변경": changed_col})
        edited_items = st.data_editor(
            item_df,
            disabled=["원본"],
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            key="settle_order_item_editor",
        )
        st.session_state.settle_order_item_mapping = {
            orig: (str(new).strip() if new is not None and str(new).strip() else orig)
            for orig, new in zip(edited_items["원본"], edited_items["변경"])
        }

    # ----- 7. 시트 배치 설정 -----
    st.markdown("### 🏷️ 7. 시트 배치 설정")
    st.caption(
        "각 셀러(비고)를 **어느 시트에 배치할지** 정합니다. 같은 시트명으로 묶으면 통합됩니다. "
        f"`{ss.DETAIL_SHEET_NAME}`은 예약어라 사용할 수 없습니다."
    )
    if st.session_state.settle_order_seller_sheet_map is None:
        st.session_state.settle_order_seller_sheet_map = {
            s: s for s in selected_sellers
        }
    with st.expander(f"시트 배치 편집 ({len(selected_sellers)}건)", expanded=True):
        if "settle_order_sheet_editor" in st.session_state:
            sheet_col_vals = selected_sellers
        else:
            _sm = st.session_state.settle_order_seller_sheet_map or {}
            sheet_col_vals = [_sm.get(s, s) for s in selected_sellers]
        sheet_df = pd.DataFrame(
            {"셀러(비고)": selected_sellers, "배치할 시트": sheet_col_vals}
        )
        edited_sheets = st.data_editor(
            sheet_df,
            disabled=["셀러(비고)"],
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            key="settle_order_sheet_editor",
        )
        st.session_state.settle_order_seller_sheet_map = {
            seller: (
                str(sheet).strip()
                if sheet is not None and str(sheet).strip()
                else seller
            )
            for seller, sheet in zip(
                edited_sheets["셀러(비고)"], edited_sheets["배치할 시트"]
            )
        }
    seller_to_sheet = st.session_state.settle_order_seller_sheet_map
    try:
        sheet_map_preview = ss.resolve_sheet_map(selected_sellers, seller_to_sheet)
    except ValueError as e:
        st.error(f"❌ {e}")
        st.stop()
    _final_sheets = list(sheet_map_preview.keys())
    st.caption(
        f"생성될 셀러 시트: {len(_final_sheets)}개 — "
        + ", ".join(f"**{n}**" for n in _final_sheets)
    )

    # ----- 8. 상세내역 옵션 (신규 — 생성안함/전체하나로/셀러별) -----
    st.markdown("### 🧾 8. 상세내역 시트")
    st.caption(
        "상세내역(원본 주문 행) 시트를 어떻게 만들지 선택합니다. "
        "'셀러별 생성'은 셀러마다 `상세내역_{셀러}` 시트를 따로 만듭니다."
    )
    prev_detail_mode = st.session_state.settle_order_detail_mode
    prev_label = next(
        (lbl for lbl, val in _DETAIL_LABELS.items() if val == prev_detail_mode),
        _DETAIL_LABEL_LIST[1],  # 전체 하나로 생성
    )
    detail_label = st.radio(
        "상세내역 생성 방식",
        options=_DETAIL_LABEL_LIST,
        index=_DETAIL_LABEL_LIST.index(prev_label),
        horizontal=True,
        key="settle_order_detail_mode_radio",
    )
    detail_mode = _DETAIL_LABELS[detail_label]
    if detail_mode != st.session_state.settle_order_detail_mode:
        st.session_state.settle_order_detail_mode = detail_mode
        st.session_state.settle_order_plan = None  # 재-미리보기 유도
        st.rerun()

    # ----- 9. 미리보기 -----
    st.markdown("### 👁️ 9. 미리보기")
    if st.button("🔍 미리보기 생성", key="settle_order_preview_btn"):
        try:
            st.session_state.settle_order_plan = ss.build_sheet_plan(
                df_pv,
                selected_sellers,
                seller_to_sheet=seller_to_sheet,
                item_mapping=st.session_state.settle_order_item_mapping,
                column_map=column_map,
                detail_mode=detail_mode,
            )
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ 미리보기 생성 실패: {e}")
            st.session_state.settle_order_plan = None
    plan = st.session_state.settle_order_plan
    if plan is not None:
        seller_sheets = plan["seller_sheets"]
        cur_mode = plan.get("detail_mode")
        if cur_mode == ss.DETAIL_MODE_SINGLE:
            detail_tab_names = [ss.DETAIL_SHEET_NAME]
        elif cur_mode == ss.DETAIL_MODE_PER_SELLER:
            detail_tab_names = list((plan.get("detail_sheets") or {}).keys())
        else:
            detail_tab_names = []
        tab_labels = list(seller_sheets.keys()) + detail_tab_names
        tabs = st.tabs(tab_labels)
        n_seller = len(seller_sheets)
        for tab, name in zip(tabs[:n_seller], seller_sheets.keys()):
            with tab:
                sdf = seller_sheets[name]
                pm1, pm2, pm3 = st.columns(3)
                pm1.metric("데이터 행", f"{len(sdf):,}건")
                pm2.metric(
                    "수량 합계",
                    f"{int(sdf['수량'].sum()):,}" if not sdf.empty else "0",
                )
                pm3.metric(
                    "금액 합계",
                    f"{int(sdf['합계'].sum()):,}" if not sdf.empty else "0",
                )
                st.dataframe(sdf, use_container_width=True, hide_index=True)
        if cur_mode == ss.DETAIL_MODE_SINGLE:
            with tabs[-1]:
                ddf = plan["detail_df"]
                st.write(f"**{ss.DETAIL_SHEET_NAME}** — {len(ddf):,}건")
                st.dataframe(ddf, use_container_width=True, hide_index=True, height=440)
        elif cur_mode == ss.DETAIL_MODE_PER_SELLER:
            for tab, name in zip(tabs[n_seller:], detail_tab_names):
                with tab:
                    ddf = plan["detail_sheets"][name]
                    st.write(f"**{name}** — {len(ddf):,}건")
                    st.dataframe(
                        ddf, use_container_width=True, hide_index=True, height=440
                    )

    # ----- 10. 생성 및 다운로드 -----
    if plan is not None:
        st.markdown("### 💾 10. 정산서 생성 및 다운로드")
        st.caption("생성 시점의 최신 편집 상태로 다시 계산해 저장합니다.")
        oc1, oc2, oc3 = st.columns(3)
        font_size = oc1.number_input(
            "셀러 시트 폰트 크기",
            min_value=8,
            max_value=36,
            value=13,
            step=1,
            key="settle_order_font_size",
        )
        font_color = oc2.color_picker(
            "합계행 글씨 색상", value="#FF0000", key="settle_order_font_color"
        )
        fill_color = oc3.color_picker(
            "합계행 채우기 색상", value="#FFFF00", key="settle_order_fill_color"
        )
        if st.button("📥 정산서 생성", key="settle_order_generate_btn", type="primary"):
            try:
                # 미리보기 이후 편집 반영 위해 최신 상태로 재계산
                plan_final = ss.build_sheet_plan(
                    df_pv,
                    selected_sellers,
                    seller_to_sheet=seller_to_sheet,
                    item_mapping=st.session_state.settle_order_item_mapping,
                    column_map=column_map,
                    detail_mode=detail_mode,
                )
                out_filename = ss.build_output_filename(
                    selected_vendor,
                    list(plan_final["seller_sheets"].keys()),
                    doc_type=doc_type,
                )
                out_path = os.path.join("processed", out_filename)
                period_line = ss.build_period_line(selected_vendor, **date_kwargs)
                ss.write_seller_settlement_xlsx(
                    out_path=out_path,
                    title=title_const,
                    period_line=period_line,
                    plan=plan_final,
                    seller_font_size=float(font_size),
                    total_font_color=font_color,
                    total_fill_color=fill_color,
                    column_map=column_map,
                )
                st.session_state.settle_order_plan = plan_final
                st.session_state.settle_order_output_path = out_path
                st.session_state.settle_order_output_filename = out_filename
                if mode == _ORDER_MODE_RANGE:
                    period_text = (
                        f"{date_kwargs['start_date']} ~ {date_kwargs['end_date']}"
                    )
                else:
                    period_text = f"{len(date_kwargs['dates'])}개 날짜"
                st.session_state.settle_order_history.append(
                    {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "유형": doc_type,
                        "vendor": selected_vendor,
                        "seller": ", ".join(selected_sellers),
                        "상세내역": detail_label,
                        "시트수": len(plan_final["seller_sheets"]),
                        "일자": period_text,
                        "filename": out_filename,
                    }
                )
                st.success(f"✅ 생성 완료: `{out_filename}`")
            except Exception as e:  # noqa: BLE001
                st.error(f"❌ 정산서 생성 실패: {e}")
                with st.expander("🔍 에러 상세 정보"):
                    st.exception(e)
        if st.session_state.settle_order_output_path and os.path.exists(
            st.session_state.settle_order_output_path
        ):
            with open(st.session_state.settle_order_output_path, "rb") as f:
                st.download_button(
                    label=f"⬇️ {st.session_state.settle_order_output_filename} 다운로드",
                    data=f.read(),
                    file_name=st.session_state.settle_order_output_filename,
                    mime=(
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                    key="settle_order_download_btn",
                    use_container_width=False,
                )

    # ----- 처리 이력 -----
    if st.session_state.settle_order_history:
        st.divider()
        st.markdown("### 📜 이번 세션 처리 이력")
        st.dataframe(
            pd.DataFrame(st.session_state.settle_order_history),
            use_container_width=True,
            hide_index=True,
        )


# ===== 헤더 =====

# 2026-07-09 hoyeon.han: 디자인 개선 - 통일 페이지 헤더로 교체
# st.title("📋 정산서 생성")
# st.caption("기간 내 거래처별 매출/매입 정산서를 생성합니다.")
# st.divider()
render_page_header(
    "정산서 생성",
    # 2026-07-24 hoyeon.han: 발주내역 기반 생성 추가 → 부제 문구 일반화
    # "원본 정산서(.xls)를 업로드해 비고별 시트로 정리·발행합니다.",
    "정산서 파일(.xls) 업로드 또는 발주내역에서 비고/셀러별 시트로 정리·발행합니다.",
    icon="📋",
)


# ===== 0. 생성 방식 선택 (2026-07-24 hoyeon.han) =====
# 발주내역 방식은 정산서생성(셀러) 흐름을 재사용하되 상세내역 3택 옵션을 추가한다.
# 발주내역 선택 시 신규 흐름을 렌더하고 st.stop() 으로 아래 기존 업로드 흐름 렌더를
# 차단한다 → 기존 업로드 흐름 코드는 한 줄도 수정/재들여쓰기하지 않는다.
_GEN_UPLOAD = "정산서 파일 업로드"
_GEN_ORDER = "발주내역"
st.markdown("### 🧭 생성 방식")
gen_method = st.radio(
    "생성 방식",
    [_GEN_UPLOAD, _GEN_ORDER],
    horizontal=True,
    key="settlement_gen_method_radio",
    label_visibility="collapsed",
)
if gen_method == _GEN_ORDER:
    _render_order_based_flow()
    st.stop()


# ===== 1. 정산서 유형 선택 =====

st.markdown("### 🧭 1. 정산서 유형 선택")

prev_doc_type = st.session_state.settlement_doc_type
doc_type = st.radio(
    "정산서 유형",
    [st_mod.TYPE_SALE, st_mod.TYPE_PURCHASE],
    horizontal=True,
    key="settlement_doc_type_radio",
    index=0 if prev_doc_type == st_mod.TYPE_SALE else 1,
)
if doc_type != prev_doc_type:
    st.session_state.settlement_doc_type = doc_type
    st.session_state.settlement_doc_type_user_override = True
    _reset_below_parse()
    st.rerun()


# ===== 2. 파일 업로드 =====

st.markdown("### 📁 2. 정산서 원본 파일 업로드")
uploaded_file = st.file_uploader(
    "정산서 원본 Excel 파일을 선택하세요 (.xls)",
    type=["xls"],
    key="settlement_uploader",
    help="회계 시스템에서 다운로드한 '품목별 판매/구매 현황' 파일을 업로드합니다.",
)

if uploaded_file is not None:
    # 같은 이름이 아니면 새 파일로 간주, 재파싱
    if st.session_state.settlement_uploaded_name != uploaded_file.name:
        _reset_below_parse()
        try:
            parsed = st_mod.parse_settlement_xls(uploaded_file)
        except Exception as e:
            st.error(f"❌ 파일 파싱 실패: {e}")
            st.stop()
        st.session_state.settlement_parsed = parsed
        st.session_state.settlement_uploaded_name = uploaded_file.name
        st.session_state.settlement_start_date = parsed["start_date"]
        st.session_state.settlement_end_date = parsed["end_date"]

        # 자동 유형 추정 (사용자가 직접 변경한 적 없을 때만)
        if (
            parsed["doc_type"]
            and not st.session_state.settlement_doc_type_user_override
            and parsed["doc_type"] != st.session_state.settlement_doc_type
        ):
            st.session_state.settlement_doc_type = parsed["doc_type"]
            st.rerun()

parsed = st.session_state.settlement_parsed
if parsed is not None:
    # 파일 vs 라디오 유형 불일치 경고
    if (
        parsed["doc_type"]
        and parsed["doc_type"] != st.session_state.settlement_doc_type
    ):
        st.warning(
            f"⚠️ 선택한 유형(`{st.session_state.settlement_doc_type}`)과 "
            f"파일 제목(`{parsed['title']}` → 추정 `{parsed['doc_type']}`)이 일치하지 않습니다. "
            "유형을 다시 확인하세요."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("제목", parsed["title"])
    c2.metric(
        "파일 기간",
        f"{parsed['start_date']} ~ {parsed['end_date']}",
    )
    c3.metric("데이터 행 수", f"{len(parsed['df']):,}건")
    vendors_all = st_mod.extract_vendors(parsed["df"])
    c4.metric("거래처 수", f"{len(vendors_all)}개")


# ===== 3. 기간 지정 =====

if parsed is not None:
    st.markdown("### 📅 3. 정산서 생성 기간 지정")
    st.caption("파일 기간을 기본값으로 두고 좁힐 수 있습니다 (확장 불가).")

    col1, col2 = st.columns(2)
    new_start = col1.date_input(
        "시작일",
        value=st.session_state.settlement_start_date,
        min_value=parsed["start_date"],
        max_value=parsed["end_date"],
        key="settlement_start_input",
    )
    new_end = col2.date_input(
        "종료일",
        value=st.session_state.settlement_end_date,
        min_value=parsed["start_date"],
        max_value=parsed["end_date"],
        key="settlement_end_input",
    )

    if new_start > new_end:
        st.error("❌ 시작일이 종료일보다 늦을 수 없습니다.")
        st.stop()

    if (
        new_start != st.session_state.settlement_start_date
        or new_end != st.session_state.settlement_end_date
    ):
        st.session_state.settlement_start_date = new_start
        st.session_state.settlement_end_date = new_end
        _reset_below_period()
        st.rerun()


# ===== 4. 거래처 선택 =====

if parsed is not None:
    st.markdown("### 🏢 4. 거래처 선택")

    df_period = st_mod.filter_by_period(
        parsed["df"],
        st.session_state.settlement_start_date,
        st.session_state.settlement_end_date,
    )
    vendors_in_period = st_mod.extract_vendors(df_period)

    if not vendors_in_period:
        st.warning("⚠️ 선택한 기간에 거래처 데이터가 없습니다.")
        st.stop()

    prev_vendor = st.session_state.settlement_vendor
    default_idx = (
        vendors_in_period.index(prev_vendor)
        if prev_vendor in vendors_in_period
        else 0
    )
    selected_vendor = st.selectbox(
        f"거래처 선택 (총 {len(vendors_in_period)}개)",
        vendors_in_period,
        index=default_idx,
        key="settlement_vendor_select",
    )
    if selected_vendor != prev_vendor:
        st.session_state.settlement_vendor = selected_vendor
        _reset_below_vendor()
        st.rerun()
    elif st.session_state.settlement_vendor is None:
        st.session_state.settlement_vendor = selected_vendor


# ===== 5. 품목명 정리 =====

if parsed is not None and st.session_state.settlement_vendor is not None:
    df_vendor = st_mod.filter_by_vendor(
        df_period, st.session_state.settlement_vendor
    )
    df_clean = st_mod.drop_unused_columns(df_vendor)

    st.markdown("### 📝 5. 품목명 정리")
    st.caption("필요시 품목명을 정제하세요. 같은 값으로 묶으면 통합됩니다.")

    items = sorted({str(v) for v in df_clean["품목"] if str(v).strip()})
    if st.session_state.settlement_item_mapping is None:
        st.session_state.settlement_item_mapping = {it: it for it in items}

    with st.expander(
        f"품목명 매핑 편집 ({len(items)}건)", expanded=True
    ):
        # 2026-05-31 hoyeon.han: data_editor 피드백 루프 제거.
        # 편집 결과(매핑)로 입력 baseline을 다시 만들어 넘기면 매 런마다
        # baseline이 바뀌어 두 번째 편집이 폐기되는 버그가 발생한다.
        # → baseline은 항상 원본 items로 고정하고 편집 상태는 위젯이 보존.
        # item_df = pd.DataFrame(
        #     {
        #         "원본": items,
        #         "변경": [
        #             st.session_state.settlement_item_mapping.get(it, it)
        #             for it in items
        #         ],
        #     }
        # )
        item_df = pd.DataFrame({"원본": items, "변경": items})
        edited_items = st.data_editor(
            item_df,
            disabled=["원본"],
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            key="settlement_item_editor",
        )
        # 매핑 갱신
        st.session_state.settlement_item_mapping = dict(
            zip(edited_items["원본"], edited_items["변경"])
        )

    df_item_mapped = st_mod.apply_mapping(
        df_clean, "품목", st.session_state.settlement_item_mapping
    )


    # ===== 6. 시트 배치 설정 =====
    # 2026-05-27 hoyeon.han: 비고 값은 원본 그대로 유지하고, 어느 시트에 배치할지만
    # 결정하는 라우팅 매핑으로 변경 (데이터 치환 아님).
    st.markdown("### 🏷️ 6. 시트 배치 설정")
    st.caption(
        "비고 값은 원본 그대로 보존됩니다. 각 비고를 **어느 시트에 배치할지**만 결정합니다. "
        "`배치할 시트`를 비워두거나 `일반`이라고 입력하면 `일반` 시트로 분류됩니다. "
        "같은 시트명으로 여러 비고를 묶으면 한 시트로 통합 배치됩니다."
    )

    remarks = sorted(
        {
            str(v).strip()
            for v in df_item_mapped["비고"]
            if str(v).strip()
        }
    )
    if st.session_state.settlement_remark_sheet_map is None:
        st.session_state.settlement_remark_sheet_map = {r: r for r in remarks}

    with st.expander(
        f"시트 배치 편집 ({len(remarks)}건)", expanded=True
    ):
        if not remarks:
            st.info("비고 값이 없습니다. 모든 데이터가 '일반' 시트로 분류됩니다.")
            remark_df = pd.DataFrame({"비고": [], "배치할 시트": []})
        else:
            # 2026-05-31 hoyeon.han: data_editor 피드백 루프 제거 (5단계와 동일 사유).
            # baseline을 원본 remarks로 고정한다.
            # remark_df = pd.DataFrame(
            #     {
            #         "비고": remarks,
            #         "배치할 시트": [
            #             st.session_state.settlement_remark_sheet_map.get(r, r)
            #             for r in remarks
            #         ],
            #     }
            # )
            remark_df = pd.DataFrame({"비고": remarks, "배치할 시트": remarks})
        edited_remarks = st.data_editor(
            remark_df,
            disabled=["비고"],
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            key="settlement_remark_editor",
        )
        if len(edited_remarks) > 0:
            st.session_state.settlement_remark_sheet_map = dict(
                zip(edited_remarks["비고"], edited_remarks["배치할 시트"])
            )

    # 2026-05-27 hoyeon.han: 비고 컬럼은 절대 치환하지 않음. 시트 라우팅만 적용됨.
    df_final = df_item_mapped


# ===== 7. 시트 분할 미리보기 =====

if parsed is not None and st.session_state.settlement_vendor is not None:
    st.markdown("### 👁️ 7. 시트 분할 미리보기")

    if st.button("🔍 미리보기 생성", key="settlement_preview_btn"):
        try:
            # 2026-05-27 hoyeon.han: 비고 → 시트 라우팅 매핑 전달 (비고 값 보존)
            sheets = st_mod.split_into_sheets(
                df_final,
                remark_to_sheet=st.session_state.settlement_remark_sheet_map,
            )
            st.session_state.settlement_sheets = sheets
        except Exception as e:
            st.error(f"❌ 시트 분할 실패: {e}")
            st.session_state.settlement_sheets = None

    sheets = st.session_state.settlement_sheets
    if sheets is not None:
        sheet_tabs = st.tabs(list(sheets.keys()))
        for tab, (name, sub) in zip(sheet_tabs, sheets.items()):
            with tab:
                st.write(f"**{name}** — {len(sub)}건")
                st.dataframe(sub, use_container_width=True, hide_index=True)


# ===== 8. 생성 및 다운로드 =====

if (
    parsed is not None
    and st.session_state.settlement_vendor is not None
    and st.session_state.settlement_sheets is not None
):
    st.markdown("### 💾 8. 정산서 생성 및 다운로드")

    vendor = st.session_state.settlement_vendor
    doc_type = st.session_state.settlement_doc_type
    start_date = st.session_state.settlement_start_date
    end_date = st.session_state.settlement_end_date
    sheets = st.session_state.settlement_sheets

    out_filename = st_mod.build_output_filename(
        doc_type, vendor, start_date, end_date
    )
    out_path = os.path.join("processed", out_filename)
    period_line = st_mod.build_period_line(start_date, end_date, vendor)

    # 2026-05-31 hoyeon.han: 생성 옵션 (일반 시트 제외 / 전체 시트 금액 합계 강조)
    st.markdown("#### ⚙️ 생성 옵션")
    st.caption(
        "옵션은 최종 생성 파일에만 적용됩니다 (위 미리보기에는 반영되지 않음)."
    )

    # 일반 시트 중복 자동 감지: 비어있거나 전체 시트와 행 수가 같으면 사실상 중복
    general_df = sheets.get(st_mod.SHEET_GENERAL)
    overall_df = sheets.get(st_mod.SHEET_OVERALL)
    general_redundant = general_df is not None and (
        len(general_df) == 0
        or (overall_df is not None and len(general_df) == len(overall_df))
    )
    # 위젯 첫 렌더 기본값 선주입 (키 기반 위젯)
    if "settlement_exclude_general" not in st.session_state:
        st.session_state["settlement_exclude_general"] = general_redundant
    if "settlement_highlight_total" not in st.session_state:
        st.session_state["settlement_highlight_total"] = True

    exclude_general = st.checkbox(
        "일반 시트 제외",
        key="settlement_exclude_general",
        help="일반 시트가 비어있거나 전체 시트와 동일하면 기본 제외됩니다.",
    )
    highlight_total = st.checkbox(
        "전체 시트 금액 합계 강조 (볼드 + 글씨/채우기 색상)",
        key="settlement_highlight_total",
    )

    # 강조 켜짐일 때만 세부 스타일 선택 노출
    total_font_size = 11.0
    total_font_color = "#FF0000"
    total_fill_color = "#FFFF00"
    if highlight_total:
        oc1, oc2, oc3 = st.columns(3)
        total_font_size = oc1.number_input(
            "폰트 크기",
            min_value=8,
            max_value=36,
            value=11,
            step=1,
            key="settlement_total_font_size",
        )
        total_font_color = oc2.color_picker(
            "글씨 색상",
            value="#FF0000",
            key="settlement_total_font_color",
        )
        total_fill_color = oc3.color_picker(
            "채우기 색상",
            value="#FFFF00",
            key="settlement_total_fill_color",
        )

    if st.button(
        "📥 정산서 생성", key="settlement_generate_btn", type="primary"
    ):
        try:
            # 2026-05-31 hoyeon.han: 일반 시트 제외 옵션 적용
            sheets_to_write = dict(sheets)
            if exclude_general and st_mod.SHEET_GENERAL in sheets_to_write:
                del sheets_to_write[st_mod.SHEET_GENERAL]
            # 2026-05-31 hoyeon.han: 기존 호출 → 옵션 인자 전달 호출로 변경
            # st_mod.write_settlement_xlsx(
            #     out_path=out_path,
            #     title=parsed["title"],
            #     period_line=period_line,
            #     sheets=sheets,
            # )
            st_mod.write_settlement_xlsx(
                out_path=out_path,
                title=parsed["title"],
                period_line=period_line,
                sheets=sheets_to_write,
                highlight_total=highlight_total,
                total_font_size=float(total_font_size),
                total_font_color=total_font_color,
                total_fill_color=total_fill_color,
            )
            st.session_state.settlement_output_path = out_path
            st.session_state.settlement_output_filename = out_filename
            st.session_state.settlement_history.append(
                {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "doc_type": doc_type,
                    "vendor": vendor,
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "filename": out_filename,
                }
            )
            st.success(f"✅ 생성 완료: `{out_filename}`")
        except Exception as e:
            st.error(f"❌ 정산서 생성 실패: {e}")

    if st.session_state.settlement_output_path and os.path.exists(
        st.session_state.settlement_output_path
    ):
        with open(st.session_state.settlement_output_path, "rb") as f:
            st.download_button(
                label=f"⬇️ {st.session_state.settlement_output_filename} 다운로드",
                data=f.read(),
                file_name=st.session_state.settlement_output_filename,
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                key="settlement_download_btn",
                use_container_width=True,
            )


# ===== 처리 이력 =====

if st.session_state.settlement_history:
    st.divider()
    st.markdown("### 📜 이번 세션 처리 이력")
    hist_df = pd.DataFrame(st.session_state.settlement_history)
    st.dataframe(hist_df, use_container_width=True, hide_index=True)
