"""정산서 생성 [셀러] 페이지 / 2026-07-06 hoyeon.han"""

# 2026-07-06 hoyeon.han: 셀러(비고)별 정산서 생성 페이지 신규 생성
# - 원본: 서버에 저장된 발주내역(order_data/current.xlsm) — 업로드 UI 없음
# - 흐름: 일자(기간/개별 날짜) → 거래처 → 셀러(단일) → 품목명 정리 → 시트명
#         → 미리보기 → 생성/다운로드
# - 출력: 셀러 시트(품목별판매현황, 기본 13pt + 합계행 색상 강조) + 상세내역 시트

import importlib.util
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정 (Streamlit 명령 중 가장 먼저 실행되어야 함)
st.set_page_config(page_title="정산서 생성(셀러)", page_icon="🧾", layout="wide")

# 인증 체크 (Src/__init__.py 우회 — 기존 페이지 패턴 동일)
spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent.parent / "Src" / "auth.py"
)
if spec is None or spec.loader is None:
    raise ImportError("auth 모듈을 불러올 수 없습니다.")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
auth.require_auth()

# 커스텀 사이드바
from ui_components import render_custom_sidebar  # noqa: E402

# 2026-07-09 hoyeon.han: 디자인 개선 - 공통 테마 CSS/헤더 모듈
from ui_theme import inject_global_css, render_page_header  # noqa: E402

render_custom_sidebar()
# 2026-07-09 hoyeon.han: 사이드바(화면 폭 설정) 렌더 이후 전역 CSS 주입
inject_global_css()

# 셀러 정산서 비즈니스 로직 / 발주내역 저장소
import seller_settlement as ss  # noqa: E402
from order_file_store import OrderFileStore  # noqa: E402

# 디렉토리 생성
os.makedirs("processed", exist_ok=True)


# ===== 세션 상태 초기화 =====

MODE_RANGE = "기간 선택"
MODE_DATES = "개별 날짜 선택"

_DEFAULTS = {
    "sseller_file_sig": None,  # (file_path, sheet_name, mtime)
    "sseller_date_mode": MODE_RANGE,
    "sseller_start_date": None,
    "sseller_end_date": None,
    "sseller_dates": None,  # 개별 날짜 모드 확정값 (list[date])
    "sseller_vendor": None,
    # 2026-07-06 hoyeon.han: 셀러 다중 선택 — 확정된 셀러 목록(list[str])
    "sseller_sellers": [],
    "sseller_item_mapping": None,
    # 2026-07-06 hoyeon.han: 셀러(비고) → 배치할 시트명 매핑 (기존 정산서생성 방식).
    # 비위젯 세션 키에도 보관 → 페이지 복귀(위젯 상태 소실) 시 복원용
    "sseller_seller_sheet_map": None,
    "sseller_plan": None,
    "sseller_output_path": None,
    "sseller_output_filename": None,
    "sseller_history": [],
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# 일자 선택 위젯 키 — 파일(시트)이 바뀌면 날짜 범위가 달라지므로 함께 비운다.
_DATE_WIDGET_KEYS = (
    "sseller_date_mode_radio",
    "sseller_start_input",
    "sseller_end_input",
    "sseller_dates_multiselect",
)
# 선택 위젯 키 — 상위 조건이 바뀌면 선택지가 달라지므로 함께 비운다.
_VENDOR_WIDGET_KEYS = ("sseller_vendor_select",)
_SELLER_WIDGET_KEYS = ("sseller_seller_multiselect",)
# 편집기/옵션 위젯 키 — 데이터 변경 시 행 인덱스 기준 편집 델타가 다른 데이터에
# 잘못 적용되지 않도록 함께 비운다 (페이지 7의 2026-05-31 수정과 동일 사유).
_EDITOR_WIDGET_KEYS = ("sseller_item_editor", "sseller_sheet_editor")
_OPTION_WIDGET_KEYS = (
    "sseller_font_size",
    "sseller_font_color",
    "sseller_fill_color",
)


def _pop_widgets(*key_groups) -> None:
    for group in key_groups:
        for wk in group:
            st.session_state.pop(wk, None)


def _reset_below_sellers() -> None:
    """셀러 선택 변경 시 품목 매핑/시트 배치 이하 리셋."""
    for k in (
        "sseller_item_mapping",
        "sseller_seller_sheet_map",  # 셀러가 바뀌면 시트 배치 매핑 재설정
        "sseller_plan",
        "sseller_output_path",
        "sseller_output_filename",
    ):
        st.session_state[k] = _DEFAULTS[k]
    _pop_widgets(_EDITOR_WIDGET_KEYS, _OPTION_WIDGET_KEYS)


def _reset_below_vendor() -> None:
    """거래처 변경 시 셀러 이하 리셋."""
    st.session_state["sseller_sellers"] = list(_DEFAULTS["sseller_sellers"])
    _pop_widgets(_SELLER_WIDGET_KEYS)
    _reset_below_sellers()


def _reset_below_date() -> None:
    """일자(모드/값) 변경 시 거래처 이하 리셋."""
    st.session_state["sseller_vendor"] = _DEFAULTS["sseller_vendor"]
    _pop_widgets(_VENDOR_WIDGET_KEYS)
    _reset_below_vendor()


def _reset_below_file() -> None:
    """파일(시트) 변경 시 일자 이하 모든 상태 리셋."""
    for k in (
        "sseller_date_mode",
        "sseller_start_date",
        "sseller_end_date",
        "sseller_dates",
    ):
        st.session_state[k] = _DEFAULTS[k]
    _pop_widgets(_DATE_WIDGET_KEYS)
    _reset_below_date()


# ===== 헤더 =====

# 2026-07-09 hoyeon.han: 디자인 개선 - 통일 페이지 헤더로 교체
# st.title("🧾 정산서 생성 [셀러]")
# st.caption(
#     "서버에 저장된 발주내역 하나로 일자·거래처·셀러(비고)별 정산서를 생성합니다. "
#     "(매출 기준 — 매입 정산서는 추후 지원 예정)"
# )
render_page_header(
    "정산서 생성 [셀러]",
    "서버에 저장된 발주내역 하나로 일자·거래처·셀러(비고)별 정산서를 생성합니다. "
    "(매출 기준 — 매입 정산서는 추후 지원 예정)",
    icon="🧾",
)


# ===== 1. 발주내역 파일 (서버 저장본) =====

st.markdown("### 📂 1. 발주내역 파일 (서버 저장본)")

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
# 2026-07-06 hoyeon.han: 페이지 복귀(위젯 상태 소실) 시 selectbox 가 추천 시트로
# 무단 전환되지 않도록, 직전 확정 시트(file_sig[1])를 index 로 복원한다.
prev_sig = st.session_state.sseller_file_sig
prev_sheet = prev_sig[1] if (prev_sig and prev_sig[0] == file_path) else None
if prev_sheet in sheet_names:
    default_index = sheet_names.index(prev_sheet)
elif recommended in sheet_names:
    default_index = sheet_names.index(recommended)
else:
    default_index = 0
selected_sheet = st.selectbox(
    "📋 처리할 시트 선택",
    options=sheet_names,
    index=default_index,
    key="sseller_sheet_selector",
)

# 파일 시그니처 변경 감지 — mtime 포함 (order_data/current.xlsm 은 고정 경로라
# 재업로드(덮어쓰기) 시 경로만으로는 변경을 감지할 수 없음)
mtime = os.path.getmtime(file_path)
file_sig = (file_path, selected_sheet, mtime)
if st.session_state.sseller_file_sig != file_sig:
    st.session_state.sseller_file_sig = file_sig
    _reset_below_file()


@st.cache_data(show_spinner="📖 발주내역을 읽는 중...")
def _load_orders(path: str, sheet: str, file_mtime: float) -> pd.DataFrame:
    """발주내역 로딩 (캐싱).

    file_mtime 은 캐시 무효화 키로만 사용 — order_data/current.xlsm 은 고정
    경로라 재업로드(덮어쓰기) 시 경로/시트명만으로는 캐시가 갱신되지 않음.
    (주의: st.cache_data 는 '_' 로 시작하는 인자를 해시에서 제외하므로
    밑줄 없는 이름을 써야 캐시 키에 포함된다.)
    """
    return ss.load_orders(path, sheet)


try:
    df_orders = _load_orders(file_path, selected_sheet, mtime)
except ValueError as e:
    st.error(f"❌ {e}")
    st.stop()
except Exception as e:  # noqa: BLE001 — 총무 직원 대상 안내 후 상세는 expander
    st.error(f"❌ 발주내역을 읽지 못했습니다: {e}")
    with st.expander("🔍 에러 상세 정보"):
        st.exception(e)
    st.stop()

date_range = ss.extract_date_range(df_orders)
mc1, mc2, mc3 = st.columns(3)
mc1.metric("데이터 행 수", f"{len(df_orders):,}")
mc2.metric("데이터 기간", f"{date_range[0]} ~ {date_range[1]}" if date_range else "-")
mc3.metric("업체 수", len(ss.extract_vendors(df_orders)))

if date_range is None:
    st.error("❌ 발주내역에 유효한 출고일 데이터가 없습니다. 시트를 확인해주세요.")
    st.stop()


# ===== 2. 일자 선택 (기간 / 개별 날짜) =====

st.markdown("### 📅 2. 일자 선택")

mode = st.radio(
    "일자 선택 방식",
    options=[MODE_RANGE, MODE_DATES],
    horizontal=True,
    # 2026-07-06 hoyeon.han: 페이지 복귀 시 위젯 상태가 소실되면 첫 옵션으로
    # 되돌아가 하위 상태가 전부 리셋되는 문제 → 확정 모드를 index 로 복원
    index=0 if st.session_state.sseller_date_mode == MODE_RANGE else 1,
    key="sseller_date_mode_radio",
)
if mode != st.session_state.sseller_date_mode:
    st.session_state.sseller_date_mode = mode
    _reset_below_date()
    st.rerun()

min_d, max_d = date_range
date_kwargs: dict = {}

if mode == MODE_RANGE:
    # 2026-07-06 hoyeon.han: 시작일 기본값은 현재 달의 1일 (데이터 범위로 clamp)
    _month_first = date(date.today().year, date.today().month, 1)
    default_start = min(max(_month_first, min_d), max_d)
    col1, col2 = st.columns(2)
    start_date = col1.date_input(
        "시작일",
        value=st.session_state.sseller_start_date or default_start,
        min_value=min_d,
        max_value=max_d,
        key="sseller_start_input",
    )
    end_date = col2.date_input(
        "종료일",
        value=st.session_state.sseller_end_date or max_d,
        min_value=min_d,
        max_value=max_d,
        key="sseller_end_input",
    )
    if start_date > end_date:
        st.error("❌ 시작일이 종료일보다 늦을 수 없습니다.")
        st.stop()
    if (start_date, end_date) != (
        st.session_state.sseller_start_date,
        st.session_state.sseller_end_date,
    ):
        st.session_state.sseller_start_date = start_date
        st.session_state.sseller_end_date = end_date
        _reset_below_date()
        st.rerun()
    st.info(f"📌 선택 기간: **{start_date} ~ {end_date}**")
    date_kwargs = {"start_date": start_date, "end_date": end_date}
else:
    all_dates = ss.extract_order_dates(df_orders)
    all_date_strs = [d.isoformat() for d in all_dates]
    # 2026-07-06 hoyeon.han: 페이지 복귀(위젯 상태 소실) 시 확정 날짜를 복원
    default_dates = [
        d.isoformat()
        for d in (st.session_state.sseller_dates or [])
        if d.isoformat() in all_date_strs
    ]
    # 옵션은 ISO 문자열 사용 (date 객체도 동작하지만 문자열이 직렬화에 안전)
    picked_strs = st.multiselect(
        "출고일 선택 (발주내역에 있는 날짜만 표시됩니다)",
        options=all_date_strs,
        default=default_dates,
        key="sseller_dates_multiselect",
    )
    if not picked_strs:
        st.info("📌 날짜를 1개 이상 선택하세요.")
        st.stop()
    picked_sorted = sorted(date.fromisoformat(s) for s in picked_strs)
    if picked_sorted != (st.session_state.sseller_dates or []):
        st.session_state.sseller_dates = picked_sorted
        _reset_below_date()
        st.rerun()
    st.info(f"📌 선택 날짜: **{len(picked_sorted)}일** ({', '.join(d.isoformat() for d in picked_sorted[:5])}{' ...' if len(picked_sorted) > 5 else ''})")
    date_kwargs = {"dates": picked_sorted}


# ===== 3. 거래처 선택 =====

st.markdown("### 🏢 3. 거래처 선택")

df_dated = ss.filter_by_dates(df_orders, **date_kwargs)
vendors = ss.extract_vendors(df_dated)
if not vendors:
    st.warning("⚠️ 선택한 일자에 거래처 데이터가 없습니다.")
    st.stop()

prev_vendor = st.session_state.sseller_vendor
vendor_idx = vendors.index(prev_vendor) if prev_vendor in vendors else 0
selected_vendor = st.selectbox(
    f"거래처 선택 (총 {len(vendors)}개)",
    options=vendors,
    index=vendor_idx,
    key="sseller_vendor_select",
)
if selected_vendor != prev_vendor:
    st.session_state.sseller_vendor = selected_vendor
    _reset_below_vendor()
    st.rerun()


# ===== 4. 셀러(비고) 선택 =====

st.markdown("### 🧑‍💼 4. 셀러(비고) 선택")
st.caption(
    "셀러 값은 발주내역의 **특이사항** 컬럼입니다. 비슷하지만 다른 비고를 함께 넣으려면 "
    "여러 개 선택하세요. (다음 단계에서 시트로 묶거나 나눌 수 있습니다.)"
)

df_pv = ss.filter_orders(df_orders, vendor=selected_vendor, **date_kwargs)
sellers = ss.extract_sellers(df_pv)
if not sellers:
    st.warning("⚠️ 선택한 일자/거래처에 셀러(특이사항) 값이 있는 데이터가 없습니다.")
    st.stop()

seller_col = ss.COLUMN_MAP_SALE["seller"]
seller_counts = df_pv[seller_col].value_counts()
n_no_seller = int((df_pv[seller_col].astype(str).str.strip() == "").sum())
if n_no_seller > 0:
    st.info(f"ℹ️ 비고(특이사항)가 없는 행 {n_no_seller:,}건은 셀러 정산서에 포함되지 않습니다.")

# 전체 선택 버튼 (multiselect 위젯 값에 주입 후 rerun)
if st.button("전체 선택", key="sseller_select_all"):
    st.session_state["sseller_seller_multiselect"] = list(sellers)
    st.rerun()

# 이전 확정값 중 현재 목록에 있는 것만 기본값으로 복원 (일자/거래처 변경 대응)
default_sellers = [s for s in st.session_state.sseller_sellers if s in sellers]
selected_sellers = st.multiselect(
    f"셀러 선택 (총 {len(sellers)}개, 복수 선택 가능)",
    options=sellers,
    default=default_sellers,
    format_func=lambda s: f"{s} ({int(seller_counts.get(s, 0)):,}건)",
    key="sseller_seller_multiselect",
)
if not selected_sellers:
    st.warning("⚠️ 셀러(비고)를 1개 이상 선택하세요.")
    st.stop()

# 선택 순서와 무관하게 목록 순서로 정규화 후 확정값과 비교
selected_sellers = [s for s in sellers if s in set(selected_sellers)]
if selected_sellers != st.session_state.sseller_sellers:
    st.session_state.sseller_sellers = selected_sellers
    _reset_below_sellers()
    st.rerun()

df_seller_rows = ss.filter_by_sellers(df_pv, selected_sellers)


# ===== 5. 품목명 정리 =====

st.markdown("### 📝 5. 품목명 정리")
st.caption(
    "필요시 품목명을 정제하세요. 같은 값으로 묶으면 통합됩니다. "
    "셀러 시트 집계와 **상세내역 시트의 제품명**에 모두 적용됩니다."
)

items = ss.extract_items(df_seller_rows)
if st.session_state.sseller_item_mapping is None:
    st.session_state.sseller_item_mapping = {it: it for it in items}

with st.expander(f"품목명 매핑 편집 ({len(items)}건)", expanded=True):
    # 페이지 7의 2026-05-31 수정과 동일: 편집 위젯 상태가 살아있는 동안에는
    # baseline 을 원본 items 로 고정해 피드백 루프(편집이 폐기되는 버그)를 막는다.
    # 2026-07-06 hoyeon.han: 단, 페이지 이동 후 복귀하면 Streamlit 이 위젯 상태
    # ('sseller_item_editor')를 제거하므로, 그 경우에는 저장된 매핑으로 '변경' 열을
    # 복원해 편집 유실 + stale plan 불일치를 방지한다. (위젯 상태가 있으면 identity)
    if "sseller_item_editor" in st.session_state:
        changed_col = items
    else:
        _m = st.session_state.sseller_item_mapping or {}
        changed_col = [_m.get(it, it) for it in items]
    item_df = pd.DataFrame({"원본": items, "변경": changed_col})
    edited_items = st.data_editor(
        item_df,
        disabled=["원본"],
        num_rows="fixed",
        use_container_width=True,
        hide_index=True,
        key="sseller_item_editor",
    )
    # 2026-07-06 hoyeon.han: '변경' 셀을 비우면 None/공백이 되어 서로 다른 품목이
    # 빈 문자열로 무경고 병합되는 문제 → 비었으면 원본 품목명을 유지한다.
    st.session_state.sseller_item_mapping = {
        orig: (str(new).strip() if new is not None and str(new).strip() else orig)
        for orig, new in zip(edited_items["원본"], edited_items["변경"])
    }


# ===== 6. 시트 배치 설정 =====
# 2026-07-06 hoyeon.han: 셀러 다중 선택 → 기존 정산서생성(pages/7) 방식으로
# 각 셀러(비고)를 어느 시트에 배치할지 지정. 같은 시트명으로 묶으면 통합된다.

st.markdown("### 🏷️ 6. 시트 배치 설정")
st.caption(
    "각 셀러(비고)를 **어느 시트에 배치할지** 정합니다. 기본값은 셀러명 그대로(각각 별도 시트)이며, "
    "여러 셀러에 **같은 시트명**을 적으면 한 시트로 통합됩니다. 비고 데이터 값 자체는 보존됩니다. "
    f"`{ss.DETAIL_SHEET_NAME}`은 예약어라 사용할 수 없습니다."
)

if st.session_state.sseller_seller_sheet_map is None:
    st.session_state.sseller_seller_sheet_map = {s: s for s in selected_sellers}

with st.expander(f"시트 배치 편집 ({len(selected_sellers)}건)", expanded=True):
    # 품목명 편집기와 동일: 위젯 상태가 살아있으면 identity baseline(피드백 루프 방지),
    # 페이지 복귀(위젯 상태 소실)면 저장된 매핑으로 '배치할 시트' 열 복원.
    if "sseller_sheet_editor" in st.session_state:
        sheet_col = selected_sellers
    else:
        _sm = st.session_state.sseller_seller_sheet_map or {}
        sheet_col = [_sm.get(s, s) for s in selected_sellers]
    sheet_df = pd.DataFrame({"셀러(비고)": selected_sellers, "배치할 시트": sheet_col})
    edited_sheets = st.data_editor(
        sheet_df,
        disabled=["셀러(비고)"],
        num_rows="fixed",
        use_container_width=True,
        hide_index=True,
        key="sseller_sheet_editor",
    )
    # 배치 시트명이 비었으면 셀러명을 시트명으로 사용
    st.session_state.sseller_seller_sheet_map = {
        seller: (str(sheet).strip() if sheet is not None and str(sheet).strip() else seller)
        for seller, sheet in zip(edited_sheets["셀러(비고)"], edited_sheets["배치할 시트"])
    }

seller_to_sheet = st.session_state.sseller_seller_sheet_map

# 예약어/미리보기 검증 (resolve_sheet_map 이 최종 판단하지만 사용자에게 즉시 피드백)
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


# ===== 7. 미리보기 =====

st.markdown("### 👁️ 7. 미리보기")

if st.button("🔍 미리보기 생성", key="sseller_preview_btn"):
    try:
        st.session_state.sseller_plan = ss.build_sheet_plan(
            df_pv,
            selected_sellers,
            seller_to_sheet=seller_to_sheet,
            item_mapping=st.session_state.sseller_item_mapping,
        )
    except Exception as e:  # noqa: BLE001
        st.error(f"❌ 미리보기 생성 실패: {e}")
        st.session_state.sseller_plan = None

plan = st.session_state.sseller_plan
if plan is not None:
    seller_sheets = plan["seller_sheets"]
    tab_labels = list(seller_sheets.keys()) + [ss.DETAIL_SHEET_NAME]
    tabs = st.tabs(tab_labels)
    for tab, name in zip(tabs[:-1], seller_sheets.keys()):
        with tab:
            sdf = seller_sheets[name]
            pm1, pm2, pm3 = st.columns(3)
            pm1.metric("데이터 행", f"{len(sdf):,}건")
            pm2.metric("수량 합계", f"{int(sdf['수량'].sum()):,}" if not sdf.empty else "0")
            pm3.metric("금액 합계", f"{int(sdf['합계'].sum()):,}" if not sdf.empty else "0")
            st.dataframe(sdf, use_container_width=True, hide_index=True)
    with tabs[-1]:
        ddf = plan["detail_df"]
        st.write(f"**{ss.DETAIL_SHEET_NAME}** — {len(ddf):,}건")
        st.dataframe(ddf, use_container_width=True, hide_index=True, height=440)


# ===== 8. 생성 및 다운로드 =====

if plan is not None:
    st.markdown("### 💾 8. 정산서 생성 및 다운로드")
    st.caption("생성 시점의 최신 편집 상태(품목명/시트 배치)로 다시 계산해 저장합니다.")

    oc1, oc2, oc3 = st.columns(3)
    font_size = oc1.number_input(
        "셀러 시트 폰트 크기",
        min_value=8,
        max_value=36,
        value=13,  # 요구사항: 기본 13pt
        step=1,
        key="sseller_font_size",
    )
    font_color = oc2.color_picker(
        "합계행 글씨 색상", value="#FF0000", key="sseller_font_color"
    )
    fill_color = oc3.color_picker(
        "합계행 채우기 색상", value="#FFFF00", key="sseller_fill_color"
    )

    # 2026-07-06 hoyeon.han: 파일명은 시트 1개면 '정산서_매출_{업체명}_{시트명}',
    # 여러 시트면 '정산서_매출_{업체명}' (build_output_filename 참고)
    out_filename = ss.build_output_filename(
        selected_vendor, list(plan["seller_sheets"].keys())
    )
    out_path = os.path.join("processed", out_filename)

    if st.button("📥 정산서 생성", key="sseller_generate_btn", type="primary"):
        try:
            # 미리보기 이후 편집이 있었을 수 있으므로 최신 상태로 재계산
            plan_final = ss.build_sheet_plan(
                df_pv,
                selected_sellers,
                seller_to_sheet=seller_to_sheet,
                item_mapping=st.session_state.sseller_item_mapping,
            )
            # 재계산으로 시트 구성이 달라졌을 수 있으므로 파일명 재산정
            out_filename = ss.build_output_filename(
                selected_vendor, list(plan_final["seller_sheets"].keys())
            )
            out_path = os.path.join("processed", out_filename)
            period_line = ss.build_period_line(selected_vendor, **date_kwargs)
            ss.write_seller_settlement_xlsx(
                out_path=out_path,
                title=ss.TITLE_SALE,
                period_line=period_line,
                plan=plan_final,
                seller_font_size=float(font_size),
                total_font_color=font_color,
                total_fill_color=fill_color,
            )
            st.session_state.sseller_plan = plan_final
            st.session_state.sseller_output_path = out_path
            st.session_state.sseller_output_filename = out_filename
            if mode == MODE_RANGE:
                period_text = f"{date_kwargs['start_date']} ~ {date_kwargs['end_date']}"
            else:
                period_text = f"{len(date_kwargs['dates'])}개 날짜"
            st.session_state.sseller_history.append(
                {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "vendor": selected_vendor,
                    "seller": ", ".join(selected_sellers),
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

    if st.session_state.sseller_output_path and os.path.exists(
        st.session_state.sseller_output_path
    ):
        with open(st.session_state.sseller_output_path, "rb") as f:
            st.download_button(
                label=f"⬇️ {st.session_state.sseller_output_filename} 다운로드",
                data=f.read(),
                file_name=st.session_state.sseller_output_filename,
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                key="sseller_download_btn",
                use_container_width=True,
            )


# ===== 처리 이력 =====

if st.session_state.sseller_history:
    st.divider()
    st.markdown("### 📜 이번 세션 처리 이력")
    hist_df = pd.DataFrame(st.session_state.sseller_history)
    st.dataframe(hist_df, use_container_width=True, hide_index=True)
