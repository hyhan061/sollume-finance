"""정산서 생성 페이지 / 2026-05-27 hoyeon.han"""

# 2026-05-27 hoyeon.han: 정산서(매출/매입) 생성 페이지 신규 생성

import importlib.util
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정 (Streamlit 명령 중 가장 먼저 실행되어야 함)
st.set_page_config(
    page_title="정산서 생성", page_icon="📋", layout="wide"
)

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
# 2026-07-09 hoyeon.han: 사이드바 렌더 이후 전역 CSS 주입
inject_global_css()

# 정산서 비즈니스 로직
import settlement as st_mod  # noqa: E402

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


# ===== 헤더 =====

# 2026-07-09 hoyeon.han: 디자인 개선 - 통일 페이지 헤더로 교체
# st.title("📋 정산서 생성")
# st.caption("기간 내 거래처별 매출/매입 정산서를 생성합니다.")
# st.divider()
render_page_header(
    "정산서 생성",
    "원본 정산서(.xls)를 업로드해 비고별 시트로 정리·발행합니다.",
    icon="📋",
)


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
