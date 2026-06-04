"""
솔루미랩 발주내역 파일 비교 페이지
서버에 저장된 기존 발주내역과 새로 올린 발주내역을 일자·업체·비고 그룹 +
제품·과세구분 라인 단위로 비교하여 추가/삭제/변경 항목을 보여준다.
2026-06-04 hoyeon.han: 발주내역 비교 화면 신규 작성
"""

import streamlit as st
import pandas as pd
import io
import sys
from pathlib import Path

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정 (Streamlit 명령 중 가장 먼저 실행되어야 함)
st.set_page_config(page_title="발주내역 비교", page_icon="🔍", layout="wide")

# 2026-06-04 hoyeon.han: 인증 체크 (Src/__init__.py 우회 — 기존 페이지 패턴 동일)
import importlib.util

spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent.parent / "Src" / "auth.py"
)
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
auth.require_auth()

# 커스텀 사이드바 (발주내역 파일 선택 컴포넌트는 사용하지 않음 — 덮어쓰기 방지)
from ui_components import render_custom_sidebar

render_custom_sidebar()

# 비교 로직 (순수 모듈) 및 저장소
from order_compare import (
    read_order_sheet,
    extract_order_dates,
    build_compare_lines,
    compare_orders,
    summarize_by_group,
)
from order_file_store import OrderFileStore

# CSS 스타일 (기존 페이지와 동일 톤)
st.markdown(
    """
<style>
    .main-header {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .section-header {
        font-size: 1.5rem;
        font-weight: bold;
        color: #2c3e50;
        margin-top: 2rem;
        margin-bottom: 1rem;
        border-bottom: 2px solid #3498db;
        padding-bottom: 0.5rem;
    }
    .info-box {
        padding: 1rem;
        background-color: #d1ecf1;
        border-left: 4px solid #17a2b8;
        border-radius: 4px;
        margin: 1rem 0;
    }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<div class="main-header">🔍 발주내역 비교</div>', unsafe_allow_html=True)
st.caption(
    "서버에 저장된 기존 발주내역과 새로 올린 발주내역을 비교해 "
    "추가·삭제·변경된 항목을 찾습니다. (전표는 기존 전표생성 페이지에서 만드세요)"
)
st.divider()


# =============================================================================
# 시트 읽기 캐싱 (큰 파일 두 번 읽기 방지)
# =============================================================================

@st.cache_data(show_spinner=False)
def _read_base(path: str, sheet: str) -> pd.DataFrame:
    """서버 저장본(base) 시트 읽기 — 경로+시트명으로 캐싱."""
    return read_order_sheet(path, sheet)


@st.cache_data(show_spinner=False)
def _read_new(file_bytes: bytes, sheet: str) -> pd.DataFrame:
    """업로드본(new) 시트 읽기 — 파일 bytes+시트명으로 캐싱(저장하지 않음)."""
    return read_order_sheet(io.BytesIO(file_bytes), sheet)


# =============================================================================
# 월 → 일자 트리 체크박스
# =============================================================================

def _on_toggle_month(month_key: str):
    """월 체크박스 토글 → 해당 월의 모든 일자 선택/해제 동기화."""
    days = st.session_state["cmp_month_to_days"][month_key]
    checked = st.session_state[f"cmp_month_{month_key}"]
    sel = st.session_state["cmp_selected_dates"]
    if checked:
        sel.update(days)
    else:
        sel.difference_update(days)
    for d in days:
        st.session_state[f"cmp_day_{d.date().isoformat()}"] = checked


def _on_toggle_day(day_iso: str):
    """일자 체크박스 토글 → 선택집합 갱신 + 상위 월 체크박스 동기화."""
    checked = st.session_state[f"cmp_day_{day_iso}"]
    sel = st.session_state["cmp_selected_dates"]
    ts = pd.Timestamp(day_iso)
    if checked:
        sel.add(ts)
    else:
        sel.discard(ts)
    # 상위 월 체크박스 동기화 (모두 선택 시 체크, 일부 해제 시 해제)
    month_key = day_iso[:7]
    days = st.session_state["cmp_month_to_days"].get(month_key, [])
    if days:
        st.session_state[f"cmp_month_{month_key}"] = all(d in sel for d in days)


def _render_date_tree(available_dates):
    """월→일자 트리 체크박스를 그리고 선택된 날짜(정렬 리스트)를 반환.

    - 선택 상태는 session_state['cmp_selected_dates'] (set) 단일 출처로 관리.
    - 변경은 on_change 콜백에서만 수행(수동 rerun 없음).
    """
    avail_set = set(available_dates)

    # 최초 진입: 전체 선택 기본값
    if "cmp_selected_dates" not in st.session_state:
        st.session_state["cmp_selected_dates"] = set(available_dates)
    # 파일 교체 등으로 사라진 날짜 정리
    st.session_state["cmp_selected_dates"] &= avail_set

    # 월별 그룹핑 (정렬 유지)
    month_to_days = {}
    for d in available_dates:
        month_to_days.setdefault(d.strftime("%Y-%m"), []).append(d)
    st.session_state["cmp_month_to_days"] = month_to_days

    sel = st.session_state["cmp_selected_dates"]

    # 전체 선택/해제 빠른 버튼
    qcol1, qcol2, _ = st.columns([1, 1, 4])
    with qcol1:
        if st.button("전체 선택", use_container_width=True, key="cmp_select_all"):
            sel.update(available_dates)
            for d in available_dates:
                st.session_state[f"cmp_day_{d.date().isoformat()}"] = True
            for mk in month_to_days:
                st.session_state[f"cmp_month_{mk}"] = True
            st.rerun()
    with qcol2:
        if st.button("전체 해제", use_container_width=True, key="cmp_clear_all"):
            sel.clear()
            for d in available_dates:
                st.session_state[f"cmp_day_{d.date().isoformat()}"] = False
            for mk in month_to_days:
                st.session_state[f"cmp_month_{mk}"] = False
            st.rerun()

    for month_key, days in month_to_days.items():
        n_sel = sum(1 for d in days if d in sel)
        all_checked = n_sel == len(days)

        mkey = f"cmp_month_{month_key}"
        if mkey not in st.session_state:
            st.session_state[mkey] = all_checked

        label = f"📅 {month_key}  ({n_sel}/{len(days)}일)"
        if 0 < n_sel < len(days):
            label += "  · 부분선택"
        st.checkbox(label, key=mkey, on_change=_on_toggle_month, args=(month_key,))

        with st.expander(f"{month_key} 일자 선택", expanded=False):
            cols = st.columns(7)
            for i, d in enumerate(days):
                day_iso = d.date().isoformat()
                dkey = f"cmp_day_{day_iso}"
                if dkey not in st.session_state:
                    st.session_state[dkey] = d in sel
                with cols[i % 7]:
                    st.checkbox(
                        d.strftime("%m/%d"),
                        key=dkey,
                        on_change=_on_toggle_day,
                        args=(day_iso,),
                    )

    return sorted(st.session_state["cmp_selected_dates"])


# =============================================================================
# 결과 표시 유틸
# =============================================================================

_DISPLAY_COLUMNS = [
    "거래일자", "거래처", "비고", "품목명", "과세구분", "반품유무", "라인종류",
    "수량_기존", "수량_신규", "수량차",
    "금액_기존", "금액_신규", "금액차",
    "변경유형",
]

_ROW_COLORS = {
    "추가": "#d4edda",
    "삭제": "#f8d7da",
    "변경": "#fff3cd",
    "동일": "#ffffff",
}


def _style_diff(view: pd.DataFrame):
    """변경유형별 행 배경색 + 숫자 천단위 포맷."""
    def _row_style(row):
        color = _ROW_COLORS.get(row["변경유형"], "#ffffff")
        return [f"background-color: {color}"] * len(row)

    fmt = {}
    for c in ["수량_기존", "수량_신규", "금액_기존", "금액_신규"]:
        if c in view.columns:
            fmt[c] = "{:,.0f}"
    for c in ["수량차", "금액차"]:
        if c in view.columns:
            fmt[c] = "{:+,.0f}"

    return view.style.apply(_row_style, axis=1).format(fmt)


def _to_excel_bytes(diff_sales: pd.DataFrame, diff_purchase: pd.DataFrame) -> bytes:
    """매출/매입 비교표를 색상 강조된 엑셀(xlsx) bytes로 변환."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        wb = writer.book
        fmts = {
            "추가": wb.add_format({"bg_color": "#d4edda"}),
            "삭제": wb.add_format({"bg_color": "#f8d7da"}),
            "변경": wb.add_format({"bg_color": "#fff3cd"}),
        }
        for sheet_name, df in [("매출비교", diff_sales), ("매입비교", diff_purchase)]:
            out = df[_DISPLAY_COLUMNS] if not df.empty else df
            out.to_excel(writer, sheet_name=sheet_name, index=False)
            ws = writer.sheets[sheet_name]
            ws.freeze_panes(1, 0)
            if not out.empty:
                ws.autofilter(0, 0, len(out), len(out.columns) - 1)
                # 변경유형별 행 배경색
                for r, t in enumerate(out["변경유형"].tolist(), start=1):
                    if t in fmts:
                        ws.set_row(r, None, fmts[t])
    return buf.getvalue()


def _render_diff_tab(diff_df: pd.DataFrame, label: str):
    """매출/매입 비교 탭 본문."""
    if diff_df.empty:
        st.info(f"{label} 비교 대상 데이터가 없습니다. (선택한 날짜에 데이터가 없을 수 있습니다)")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("➕ 추가", int((diff_df["변경유형"] == "추가").sum()))
    c2.metric("➖ 삭제", int((diff_df["변경유형"] == "삭제").sum()))
    c3.metric("✏️ 변경", int((diff_df["변경유형"] == "변경").sum()))
    c4.metric("💰 금액차 합계", f"{diff_df['금액차'].sum():+,.0f}")

    types = st.multiselect(
        "변경유형 필터",
        options=["추가", "삭제", "변경", "동일"],
        default=["추가", "삭제", "변경"],
        key=f"cmp_filter_{label}",
        help="기본값은 동일 항목을 숨깁니다.",
    )
    view = diff_df[diff_df["변경유형"].isin(types)] if types else diff_df.iloc[0:0]
    view = view[_DISPLAY_COLUMNS]

    st.caption(f"표시 {len(view):,}건 / 전체 {len(diff_df):,}건")
    if view.empty:
        st.info("선택한 변경유형에 해당하는 항목이 없습니다.")
    else:
        st.dataframe(_style_diff(view), use_container_width=True, height=440)

    with st.expander("📋 일자·업체·비고 그룹 요약"):
        summary = summarize_by_group(diff_df)
        st.dataframe(summary, use_container_width=True, hide_index=True)


# =============================================================================
# 1) 파일 소스 준비
# =============================================================================

st.markdown('<div class="section-header">1️⃣ 비교할 파일</div>', unsafe_allow_html=True)

store = OrderFileStore()
if not store.exists():
    st.error(
        "❌ 서버에 저장된 발주내역 파일이 없습니다.\n\n"
        "먼저 '전표 생성' 또는 '시스템 관리' 페이지에서 발주내역 파일을 한 번 업로드해 주세요."
    )
    st.stop()

base_meta = store.get_metadata() or {}
base_path = store.get_path()

col_base, col_new = st.columns(2)

with col_base:
    st.markdown("**📁 기존 (서버 저장본)**")
    st.success(
        f"{base_meta.get('original_name', 'current.xlsm')}"
        + (f"  · 업로드 {base_meta.get('uploaded_at', '')}" if base_meta.get("uploaded_at") else "")
    )
    base_sheets = base_meta.get("sheet_names", [])
    base_recommended = base_meta.get("recommended_sheet")
    if base_sheets:
        base_idx = base_sheets.index(base_recommended) if base_recommended in base_sheets else 0
        base_sheet = st.selectbox(
            "기존 파일 시트", options=base_sheets, index=base_idx, key="cmp_base_sheet"
        )
    else:
        st.warning("저장본의 시트 목록을 읽을 수 없습니다.")
        base_sheet = None

with col_new:
    st.markdown("**🆕 신규 (새로 올릴 파일)**")
    uploaded = st.file_uploader(
        "새 발주내역 파일 (.xlsm/.xlsx) — 비교용으로만 읽으며 서버에 저장하지 않습니다",
        type=["xlsm", "xlsx"],
        key="cmp_new_uploader",
    )

    new_sheet = None
    if uploaded is not None:
        new_bytes = uploaded.getvalue()
        new_sig = (uploaded.name, uploaded.size)
        # 새 파일로 바뀌면 이전 결과/날짜선택 무효화
        if st.session_state.get("cmp_new_sig") != new_sig:
            st.session_state["cmp_new_sig"] = new_sig
            st.session_state["cmp_new_bytes"] = new_bytes
            st.session_state["cmp_new_name"] = uploaded.name
            st.session_state["cmp_ran"] = False
            for k in [k for k in st.session_state.keys()
                      if k.startswith("cmp_month_") or k.startswith("cmp_day_")]:
                del st.session_state[k]
            st.session_state.pop("cmp_selected_dates", None)
        st.success(f"{uploaded.name}  ({uploaded.size / 1024 / 1024:.2f} MB)")
        try:
            new_sheets = pd.ExcelFile(io.BytesIO(new_bytes)).sheet_names
            new_idx = new_sheets.index(base_sheet) if base_sheet in new_sheets else 0
            new_sheet = st.selectbox(
                "신규 파일 시트", options=new_sheets, index=new_idx, key="cmp_new_sheet"
            )
        except Exception as e:
            st.error(f"신규 파일의 시트 목록을 읽을 수 없습니다: {e}")
            st.stop()

if uploaded is None:
    st.info("👆 비교할 새 발주내역 파일을 업로드하세요.")
    st.stop()

if base_sheet and new_sheet and base_sheet != new_sheet:
    st.warning(
        f"⚠️ 선택한 시트명이 다릅니다 (기존: '{base_sheet}' / 신규: '{new_sheet}'). "
        "의도한 것이 맞는지 확인하세요. 비교는 계속 진행됩니다."
    )

# =============================================================================
# 2) 두 파일 읽기 + 비교 날짜 선택
# =============================================================================

st.markdown('<div class="section-header">2️⃣ 비교할 날짜 선택</div>', unsafe_allow_html=True)

try:
    base_df = _read_base(base_path, base_sheet)
    new_df = _read_new(st.session_state["cmp_new_bytes"], new_sheet)
except Exception as e:
    st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")
    st.stop()

available_dates = sorted(set(extract_order_dates(base_df)) | set(extract_order_dates(new_df)))

if not available_dates:
    st.error("두 파일 모두에서 유효한 출고일을 찾을 수 없습니다. '출고일' 컬럼을 확인하세요.")
    st.stop()

st.markdown(
    f'<div class="info-box">📆 비교 가능한 날짜: <b>{len(available_dates)}일</b> '
    f"({available_dates[0].strftime('%Y-%m-%d')} ~ {available_dates[-1].strftime('%Y-%m-%d')})</div>",
    unsafe_allow_html=True,
)

selected_dates = _render_date_tree(available_dates)
st.caption(f"✅ 선택된 날짜: {len(selected_dates)}일")

# =============================================================================
# 3) 비교 실행
# =============================================================================

st.markdown('<div class="section-header">3️⃣ 비교 실행</div>', unsafe_allow_html=True)

run = st.button(
    "🔍 비교 실행",
    type="primary",
    use_container_width=True,
    disabled=(len(selected_dates) == 0),
)
if len(selected_dates) == 0:
    st.warning("최소 한 개 이상의 날짜를 선택하세요.")

if run:
    with st.status("⚙️ 비교 중...", expanded=True) as status:
        try:
            st.write(f"📅 선택 날짜 {len(selected_dates)}일 · 매출/매입 비교 라인 생성 중...")
            base_sales = build_compare_lines(base_df, "sales", selected_dates)
            new_sales = build_compare_lines(new_df, "sales", selected_dates)
            base_buy = build_compare_lines(base_df, "purchase", selected_dates)
            new_buy = build_compare_lines(new_df, "purchase", selected_dates)

            st.write("🔗 차이 계산 중...")
            st.session_state["cmp_result_sales"] = compare_orders(base_sales, new_sales)
            st.session_state["cmp_result_purchase"] = compare_orders(base_buy, new_buy)
            st.session_state["cmp_ran"] = True

            status.update(label="✅ 비교 완료!", state="complete", expanded=False)
        except Exception as e:
            st.session_state["cmp_ran"] = False
            status.update(label="❌ 비교 실패", state="error", expanded=True)
            st.error(f"비교 중 오류가 발생했습니다: {e}")

# =============================================================================
# 4) 결과 표시
# =============================================================================

if st.session_state.get("cmp_ran"):
    diff_sales = st.session_state["cmp_result_sales"]
    diff_purchase = st.session_state["cmp_result_purchase"]

    st.markdown('<div class="section-header">4️⃣ 비교 결과</div>', unsafe_allow_html=True)
    st.caption("🟩 추가  ·  🟥 삭제  ·  🟨 변경")

    tab_sales, tab_purchase = st.tabs(["💰 매출 비교", "🛒 매입 비교"])
    with tab_sales:
        _render_diff_tab(diff_sales, "매출")
    with tab_purchase:
        _render_diff_tab(diff_purchase, "매입")

    # 엑셀 다운로드
    try:
        excel_bytes = _to_excel_bytes(diff_sales, diff_purchase)
        st.download_button(
            "📥 비교 결과 엑셀 다운로드 (매출·매입)",
            data=excel_bytes,
            file_name="발주내역_비교결과.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
            key="cmp_download",
        )
    except Exception as e:
        st.warning(f"엑셀 생성 중 오류가 발생했습니다: {e}")

    # 신규 파일을 서버 저장본으로 교체
    st.divider()
    with st.expander("♻️ 이 신규 파일을 서버 저장본으로 교체"):
        st.warning(
            "교체하면 기존 서버 저장본을 덮어씁니다. 비교가 끝나고 새 파일을 "
            "정식 기준으로 삼을 때만 사용하세요."
        )
        confirm = st.checkbox("위 내용을 이해했으며 교체합니다.", key="cmp_replace_confirm")
        if st.button("서버 저장본 교체", disabled=not confirm, key="cmp_replace_btn"):
            ok, msg = store.save(
                st.session_state["cmp_new_bytes"], st.session_state["cmp_new_name"]
            )
            if ok:
                # 경로는 같지만 내용이 바뀌었으므로 base 읽기 캐시 무효화
                _read_base.clear()
                st.session_state["cmp_ran"] = False
                st.success(msg + " 다음 비교부터 새 저장본이 기존(base)으로 사용됩니다.")
                st.rerun()
            else:
                st.error(msg)
