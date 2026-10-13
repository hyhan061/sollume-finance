"""이카운트 정산서 생성 페이지 / 2026-09-01 hoyeon.han"""

# 2026-09-01 hoyeon.han: 이카운트(ECOUNT) 판매현황내역 기반 정산서 생성 페이지 신규 생성.
# 절차는 기존 '정산서 생성'(pages/settlement.py) 업로드 흐름과 동일하게 맞추고,
# 원본 파일 형식만 이카운트 .xlsx 로 바꾼다. 파싱 이후 단계는 Src/settlement.py 의
# 기존 함수를 한 줄도 고치지 않고 그대로 재사용한다.
# 2026-10-13 hoyeon.han: 출력 연결만 발주내역 기반 집계·상세 작성기로 전환.
# 2026-10-13 hoyeon.han: 기존 발주내역 화면처럼 셀러를 선택하고 주문유형은 전체 포함.

import importlib.util
import io
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정은 st.navigation 라우터(Home.py)가 진입점에서 처리한다
# st.set_page_config(page_title="정산서 생성(이카운트)", page_icon="🧮", layout="wide")

# 인증 체크 (Src/__init__.py 우회 — 기존 페이지 패턴 동일)
spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent.parent / "Src" / "auth.py"
)
if spec is None or spec.loader is None:
    raise ImportError("auth 모듈을 불러올 수 없습니다.")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
# auth.require_auth()

# 커스텀 사이드바 / 전역 CSS 는 Home.py 라우터가 처리
from ui_components import render_custom_sidebar  # noqa: E402,F401
from ui_theme import inject_global_css, render_page_header  # noqa: E402,F401

# render_custom_sidebar()
# inject_global_css()

# 정산서 비즈니스 로직 (기존 파이프라인 재사용)
import ecount_settlement as es  # noqa: E402
import settlement as st_mod  # noqa: E402
# 2026-10-13 hoyeon.han: 발주내역 기반 정산서 작성기를 재사용한다.
import seller_settlement as ss  # noqa: E402

os.makedirs("processed", exist_ok=True)


# ===== 세션 상태 초기화 =====
# 세션키 접두사는 반드시 'settle_ecount_'. 기존 화면(settlement_ / settle_order_ /
# sseller_)과 겹치면 화면을 오갈 때 서로의 리셋 함수가 남의 상태를 지운다.

_DEFAULTS: dict[str, Any] = {
    "settle_ecount_parsed": None,
    "settle_ecount_uploaded_sig": None,  # (파일명, 크기)
    "settle_ecount_start_date": None,
    "settle_ecount_end_date": None,
    # "settle_ecount_order_types": None,  # 기존 주문유형 필터 상태 보존
    "settle_ecount_vendor": None,
    # 2026-10-13 hoyeon.han: 기존 화면과 동일하게 최초 셀러 선택은 비워 둔다.
    "settle_ecount_sellers": [],
    "settle_ecount_item_mapping": None,
    "settle_ecount_remark_sheet_map": None,
    # "settle_ecount_sheets": None,  # 기존 원본 행 분할 미리보기
    # 2026-10-13 hoyeon.han: 집계·상세내역 계획과 출력 옵션을 함께 관리.
    "settle_ecount_plan": None,
    "settle_ecount_plan_signature": None,
    "settle_ecount_include_overall": True,
    "settle_ecount_detail_mode": ss.DETAIL_MODE_SINGLE,
    "settle_ecount_output_path": None,
    "settle_ecount_output_filename": None,
    "settle_ecount_history": [],
}

for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# 상위 단계가 바뀌면 제거해야 하는 위젯 상태
# _TYPE_WIDGET_KEYS = ("settle_ecount_types_multiselect",)
# 2026-10-13 hoyeon.han: 상위 조건이 바뀌면 셀러 위젯도 초기화한다.
_SELLER_WIDGET_KEYS = ("settle_ecount_seller_multiselect",)
_EDITOR_WIDGET_KEYS = ("settle_ecount_item_editor", "settle_ecount_sheet_editor")
_OPTION_WIDGET_KEYS = (
    # "settle_ecount_exclude_general",
    # "settle_ecount_highlight_total",
    # "settle_ecount_total_font_size",
    # "settle_ecount_total_font_color",
    # "settle_ecount_total_fill_color",
    # 2026-10-13 hoyeon.han: 기존 발주내역 화면과 같은 옵션을 초기화한다.
    "settle_ecount_include_overall_cb",
    "settle_ecount_detail_mode_radio",
    "settle_ecount_seller_font_size",
    "settle_ecount_font_color",
    "settle_ecount_fill_color",
)
# 2026-10-13 hoyeon.han: 상세내역 기본은 선택 조건 전체 하나로 생성.
_DETAIL_LABELS = {
    "생성 안 함": ss.DETAIL_MODE_NONE,
    "전체 하나로 생성": ss.DETAIL_MODE_SINGLE,
    "셀러별 생성": ss.DETAIL_MODE_PER_SELLER,
}

# 구분(주문유형)이 비어 있는 행을 고를 수 있게 하는 라벨.
# extract_order_types() 가 빈 값을 제외하므로, 이 라벨이 없으면 구분 없는 행이
# 필터에서 통째로 누락된다.
# _NO_TYPE_LABEL = "(미지정)"
# 2026-10-13 hoyeon.han: 특이사항이 없는 주문도 '일반' 셀러로 선택할 수 있다.
_NO_SELLER_LABEL = ss.SHEET_GENERAL


def _reset_option_widgets() -> None:
    """생성 옵션/편집기 위젯 상태 제거 (다음 렌더에서 기본값 재초기화)."""
    for wk in _OPTION_WIDGET_KEYS + _EDITOR_WIDGET_KEYS:
        st.session_state.pop(wk, None)


# def _reset_below_vendor() -> None:
#     """거래처 변경 시 매핑 이하 리셋."""
# 2026-10-13 hoyeon.han: 셀러 변경 때 기존 매핑·미리보기·다운로드를 모두 폐기한다.
def _reset_below_sellers() -> None:
    """셀러 선택 변경 시 품목/시트/옵션/출력 상태 리셋."""
    for k in (
        "settle_ecount_item_mapping",
        "settle_ecount_remark_sheet_map",
        # "settle_ecount_sheets",
        # 2026-10-13 hoyeon.han: 필터 변경 시 이전 집계와 다운로드를 폐기한다.
        "settle_ecount_plan",
        "settle_ecount_plan_signature",
        "settle_ecount_include_overall",
        "settle_ecount_detail_mode",
        "settle_ecount_output_path",
        "settle_ecount_output_filename",
    ):
        st.session_state[k] = _DEFAULTS[k]
    _reset_option_widgets()


# def _reset_below_types() -> None:
#     """구분(주문유형) 필터 변경 시 거래처 이하 리셋.
#
#     기존 화면에는 없던 계층이다. 빠뜨리면 필터를 바꿔도 이전 조건으로 만든
#     품목 매핑/시트 배치/미리보기가 살아남아 조용히 틀린 파일이 생성된다.
#     """
#     st.session_state["settle_ecount_vendor"] = _DEFAULTS["settle_ecount_vendor"]
#     _reset_below_vendor()


# 2026-10-13 hoyeon.han: 거래처 변경 시 셀러 선택부터 초기화한다.
def _reset_below_vendor() -> None:
    """거래처 변경 시 셀러 선택과 하위 상태 리셋."""
    st.session_state["settle_ecount_sellers"] = []
    for wk in _SELLER_WIDGET_KEYS:
        st.session_state.pop(wk, None)
    _reset_below_sellers()


def _reset_below_period() -> None:
    # """기간 변경 시 구분 필터 이하 리셋."""
    # st.session_state["settle_ecount_order_types"] = _DEFAULTS[
    #     "settle_ecount_order_types"
    # ]
    # for wk in _TYPE_WIDGET_KEYS:
    #     st.session_state.pop(wk, None)
    # _reset_below_types()
    # 2026-10-13 hoyeon.han: 주문유형 필터 대신 거래처·셀러 이하를 초기화한다.
    """기간 변경 시 거래처·셀러 선택과 하위 상태 리셋."""
    st.session_state["settle_ecount_vendor"] = _DEFAULTS["settle_ecount_vendor"]
    _reset_below_vendor()


def _reset_below_parse() -> None:
    """파일 변경 시 파싱 결과 이하 모든 상태 리셋."""
    for k in (
        "settle_ecount_parsed",
        "settle_ecount_uploaded_sig",
        "settle_ecount_start_date",
        "settle_ecount_end_date",
    ):
        st.session_state[k] = _DEFAULTS[k]
    _reset_below_period()


@st.cache_data(show_spinner="📖 이카운트 판매현황내역을 읽는 중...", max_entries=3)
def _parse_ecount_cached(
    file_name: str, file_size: int, _file_bytes: bytes
) -> dict[str, Any]:
    """업로드 파일 파싱 (캐시).

    st.cache_data 는 '_' 로 시작하는 인자를 해시에서 제외한다. 5MB 바이트열을
    해시하지 않도록 파일명/크기만 캐시 키로 쓴다. max_entries 로 누적 메모리를 제한.

    주의: 반환 dict 는 캐시된 객체 그대로다. parsed["df"] 를 in-place 수정하면
    캐시가 오염된다 (하위 filter_by_* 는 모두 .copy() 하므로 현재는 안전).
    """
    return es.parse_ecount_xlsx(io.BytesIO(_file_bytes))


# 2026-10-13 hoyeon.han: 사용자가 제공한 화면 원본을 cwd와 무관하게 불러온다.
_MANUAL_IMAGE_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "ecount_sales_download_guide.png"
)


# 2026-10-13 hoyeon.han: 읽기 전용 매뉴얼 팝업. 파일·셀러·정산 세션은 변경하지 않는다.
@st.dialog(
    "이카운트 판매현황내역 다운로드 방법",
    width="large",
    dismissible=True,
    on_dismiss="ignore",
)
def _show_download_manual() -> None:
    st.info(
        # 2026-10-13 hoyeon.han: 핵심 두 설정을 팝업 상단에서 굵게 강조한다.
        "보고서 유형: **정산서**\n\n"
        "다운로드: **검색(F8) 오른쪽 ▼ → Excel(데이터)**"
    )
    st.markdown(
        "### 다운로드 순서\n\n"
        "1. 이카운트에서 **재고Ⅰ → 영업관리 → 판매 → 판매현황**으로 이동합니다.\n"
        "2. **메뉴: 현황 / 구분: 라인별**로 두고, 기준일자에 정산 기간을 지정합니다. "
        "필요한 거래처를 지정하고 **거래구분은 전체**로 두어 반품도 포함합니다.\n"
        "3. 화면 하단의 보고서 유형을 **정산서**로 선택합니다. "
        "이 양식으로 내려받아야 정산서 생성에 필요한 열이 포함됩니다.\n"
        "4. 파란 **검색(F8) 버튼** 오른쪽의 ▼를 누르고, 펼쳐진 메뉴에서 "
        "**Excel(데이터)** 항목을 선택해 다운로드합니다. **Excel(화면)이 아닙니다.**\n"
        "5. 다운로드한 **.xlsx** 파일을 이 화면에 업로드합니다. "
        "시트명·머리글·데이터 행을 임의로 변경하지 마세요."
    )
    if _MANUAL_IMAGE_PATH.is_file():
        st.image(
            str(_MANUAL_IMAGE_PATH),
            caption="하단 '정산서' 보고서 유형과 검색(F8) 오른쪽 ▼ 위치를 확인하세요.",
            width="stretch",
        )
    else:
        st.warning("매뉴얼 이미지를 불러올 수 없습니다. 위 다운로드 순서를 참고하세요.")
    st.markdown(
        "### 업로드 전 확인\n\n"
        "- 원본 파일의 **구분 열은 발주·반품 등 주문유형**, "
        "**특이사항 열은 셀러명**이어야 합니다. "
        "조회 화면의 '구분: 라인별'과 원본의 주문유형 열은 서로 다른 항목입니다.\n"
        "- 필수 열: **일자, 거래처명, 품목명, 구분, 수량, 단가, 합계, 특이사항**.\n"
        "- 상세내역에 필요한 **수하인명, 연락처1, 수하인주소**도 기존 정산서 양식에 "
        "포함되어 있는지 확인하세요.\n"
        "- 업로드 후 **원본 총합계 검산**을 확인하고, 정산할 **셀러를 복수 선택**하세요."
    )
    st.caption("팝업을 닫아도 업로드 파일과 셀러 선택값은 그대로 유지됩니다.")
    if st.button("닫기", key="settle_ecount_manual_close"):
        st.rerun()


# ===== 페이지 헤더 =====

render_page_header(
    "정산서 생성(이카운트)",
    "이카운트 판매현황내역(.xlsx)을 셀러별 시트로 정리·발행합니다.",
    icon="🧮",
)


# 2026-10-13 hoyeon.han: 업로드 전 및 셀러 미선택 상태에서도 매뉴얼을 열 수 있다.
if st.button("📖 다운로드 매뉴얼", key="settle_ecount_manual_open"):
    _show_download_manual()


# ===== 1. 파일 업로드 =====

st.markdown("### 📁 1. 이카운트 판매현황내역 업로드")
uploaded_file = st.file_uploader(
    "이카운트에서 내려받은 판매현황내역 파일을 선택하세요 (.xlsx)",
    type=["xlsx"],
    key="settle_ecount_uploader",
    help=(
        "이카운트 > 판매현황내역 조회 후 엑셀로 내려받은 파일입니다. "
        "'구분'에는 발주/반품 등 주문유형이, '특이사항'에는 셀러명이 들어 있어야 합니다."
    ),
)

if uploaded_file is not None:
    file_sig = (uploaded_file.name, uploaded_file.size)
    if st.session_state.settle_ecount_uploaded_sig != file_sig:
        try:
            parsed = _parse_ecount_cached(
                uploaded_file.name, uploaded_file.size, uploaded_file.getvalue()
            )
        except ValueError as e:
            st.error(f"❌ {e}")
            st.stop()
        except Exception as e:  # noqa: BLE001 - 총무 직원 대상 안내 후 상세는 expander
            st.error(f"❌ 파일을 읽지 못했습니다: {e}")
            with st.expander("🔍 에러 상세 정보"):
                st.exception(e)
            st.stop()

        _reset_below_parse()
        st.session_state.settle_ecount_parsed = parsed
        st.session_state.settle_ecount_uploaded_sig = file_sig
        st.session_state.settle_ecount_start_date = parsed["start_date"]
        st.session_state.settle_ecount_end_date = parsed["end_date"]
        st.rerun()

parsed = st.session_state.settle_ecount_parsed


# ===== 2. 파싱 결과 확인 =====

if parsed is not None:
    st.markdown("### 🔎 2. 원본 확인")

    df_all = parsed["df"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("회사명", parsed["company"] or "-")
    m2.metric(
        "조회기간", f"{parsed['start_date']} ~ {parsed['end_date']}"
    )
    m3.metric("데이터 행", f"{len(df_all):,}행")
    m4.metric("거래처", f"{len(st_mod.extract_vendors(df_all)):,}곳")

    if parsed["period_from_data"]:
        st.warning(
            f"⚠️ 조회기간을 인식하지 못해 데이터 일자 범위"
            f"({parsed['start_date']} ~ {parsed['end_date']})로 대체했습니다."
        )
    if parsed["invalid_date_rows"]:
        st.warning(
            f"⚠️ 날짜 형식이 올바르지 않은 {parsed['invalid_date_rows']:,}행을 제외했습니다."
        )

    # 검산 — 원본 푸터('총합계')와 대조. 이카운트 양식이 바뀌어 열이 밀리면 즉시 드러난다
    v = es.verify_totals(df_all, parsed["footer_total"], parsed["footer_qty"])
    if not v["checked"]:
        st.info(
            f"ℹ️ 원본에 총합계 행이 없어 검산을 건너뜁니다. "
            f"(읽어들인 합계 {v['calc_total']:,.0f}원)"
        )
    elif v["matches"]:
        st.success(
            f"✅ 검산 일치 — 합계 {v['calc_total']:,.0f}원 / "
            f"수량 {v['calc_qty']:,.0f} (원본 총합계와 동일, "
            f"소계·총합계 {parsed['dropped_rows']}행 제외)"
        )
    else:
        st.warning(
            f"⚠️ 원본 총합계({v['footer_total']:,.0f}원)와 "
            f"읽어들인 합계({v['calc_total']:,.0f}원)가 "
            f"{abs(v['total_diff']):,.0f}원 다릅니다. 원본을 확인하세요."
        )

    # 구분/특이사항 뒤바뀜 경고.
    # 2026-09-01 사용자 결정에 따라 자동 교정은 하지 않는다. 다만 옛 파일을 올리면
    # 시트 이름이 '발주'/'변심반품'으로 만들어진 채 에러 없이 잘못된 정산서가
    # 나가므로, 값 분포를 보고 경고만 띄운다.
    warn = parsed.get("swap_warning")
    if warn:
        st.error(
            "⚠️ **'구분'과 '특이사항'이 서로 뒤바뀐 파일로 보입니다.**\n\n"
            f"- `구분` 열의 값: {', '.join(map(str, warn['sample_order_types'][:3]))} … "
            "→ 셀러명처럼 보입니다\n"
            f"- `특이사항` 열의 값: {', '.join(map(str, warn['sample_remarks'][:3]))} … "
            "→ 주문유형처럼 보입니다\n\n"
            "`구분`에는 발주/반품 등 **주문유형**이, `특이사항`에는 **셀러명**이 "
            "들어가야 합니다. 이카운트에서 다시 내려받아 주세요. "
            "이대로 진행하면 시트가 셀러가 아니라 주문유형으로 나뉩니다."
        )

    with st.expander("원본 데이터 미리보기 (상위 10건)", expanded=bool(warn)):
        st.dataframe(
            df_all.head(10),
            use_container_width=True,
            hide_index=True,
        )


# ===== 3. 기간 지정 =====

if parsed is not None:
    st.markdown("### 📅 3. 정산서 생성 기간 지정")
    st.caption("파일 기간을 기본값으로 두고 좁힐 수 있습니다 (확장 불가).")

    col1, col2 = st.columns(2)
    new_start = col1.date_input(
        "시작일",
        value=st.session_state.settle_ecount_start_date,
        min_value=parsed["start_date"],
        max_value=parsed["end_date"],
        key="settle_ecount_start_input",
    )
    new_end = col2.date_input(
        "종료일",
        value=st.session_state.settle_ecount_end_date,
        min_value=parsed["start_date"],
        max_value=parsed["end_date"],
        key="settle_ecount_end_input",
    )

    if new_start > new_end:
        st.error("❌ 시작일이 종료일보다 늦을 수 없습니다.")
        st.stop()

    if (
        new_start != st.session_state.settle_ecount_start_date
        or new_end != st.session_state.settle_ecount_end_date
    ):
        st.session_state.settle_ecount_start_date = new_start
        st.session_state.settle_ecount_end_date = new_end
        _reset_below_period()
        st.rerun()


# 2026-10-13 hoyeon.han: 주문유형 선택 단계는 주석으로 보존하고 전체 유형을 포함한다.
# # ===== 4. 구분(주문유형) 선택 =====
#
# if parsed is not None:
#     st.markdown("### 🧾 4. 구분(주문유형) 선택")
#     st.caption(
#         "정산서에 포함할 주문유형을 고릅니다. 기본은 전체 선택입니다. "
#         "반품은 수량·금액이 음수로 반영되므로, 실제 정산 금액을 맞추려면 함께 두세요. "
#         # "선택한 유형은 출력 파일의 열로는 나오지 않습니다."
#         # 2026-10-13 hoyeon.han: 주문유형은 요약에서 제외하고 상세내역 구분에 표시.
#         "선택한 유형은 정산 요약에는 나오지 않고 상세내역의 구분에 표시됩니다."
#     )
#
#     df_period = st_mod.filter_by_period(
#         parsed["df"],
#         st.session_state.settle_ecount_start_date,
#         st.session_state.settle_ecount_end_date,
#     )
#
#     type_series = df_period[es.COL_ORDER_TYPE].astype(str).str.strip()
#     type_options = es.extract_order_types(df_period)
#     n_blank = int((type_series == "").sum())
#     if n_blank:
#         type_options = type_options + [_NO_TYPE_LABEL]
#
#     if not type_options:
#         st.warning("⚠️ 선택한 기간에 데이터가 없습니다.")
#         st.stop()
#
#     type_counts = {t: int((type_series == t).sum()) for t in type_options}
#     if n_blank:
#         type_counts[_NO_TYPE_LABEL] = n_blank
#
#     # 첫 렌더 기본값 = 전체 선택
#     if "settle_ecount_types_multiselect" not in st.session_state:
#         st.session_state["settle_ecount_types_multiselect"] = list(type_options)
#
#     selected_types = st.multiselect(
#         f"주문유형 선택 (총 {len(type_options)}종)",
#         options=type_options,
#         format_func=lambda t: f"{t} ({type_counts.get(t, 0):,}건)",
#         key="settle_ecount_types_multiselect",
#     )
#     # 선택 순서가 달라도 불필요한 rerun 이 나지 않도록 원본 순서로 정규화
#     selected_types = [t for t in type_options if t in set(selected_types)]
#
#     if not selected_types:
#         st.warning("⚠️ 주문유형을 1개 이상 선택해야 합니다.")
#         st.stop()
#
#     if selected_types != st.session_state.settle_ecount_order_types:
#         st.session_state.settle_ecount_order_types = selected_types
#         _reset_below_types()
#         st.rerun()
#
#     # '(미지정)' 라벨은 실제 빈 문자열로 되돌려 필터에 넘긴다
#     wanted_types = ["" if t == _NO_TYPE_LABEL else t for t in selected_types]
#     df_typed = es.filter_by_order_types(df_period, wanted_types)
#     st.caption(
#         f"선택 결과: {len(df_typed):,}행 / "
#         f"{int(df_typed['합계'].sum()):,}원 "
#         f"(전체 {len(df_period):,}행 중)"
#     )


# ===== 5. 거래처 선택 =====
# 2026-10-13 hoyeon.han: 주문유형 선택을 없애 거래처 선택을 4단계로 배치한다.

if parsed is not None:
    # st.markdown("### 🏢 5. 거래처 선택")
    st.markdown("### 🏢 4. 거래처 선택")
    # 2026-10-13 hoyeon.han: 발주·반품·빈 구분 등 모든 유형을 그대로 포함한다.
    df_period = st_mod.filter_by_period(
        parsed["df"],
        st.session_state.settle_ecount_start_date,
        st.session_state.settle_ecount_end_date,
    )

    # vendors_in_period = st_mod.extract_vendors(df_typed)
    vendors_in_period = st_mod.extract_vendors(df_period)
    if not vendors_in_period:
        st.warning("⚠️ 선택한 조건에 거래처 데이터가 없습니다.")
        st.stop()

    # vendor_summary = es.summarize_vendors(df_typed).set_index("거래처")
    vendor_summary = es.summarize_vendors(df_period).set_index("거래처")
    prev_vendor = st.session_state.settle_ecount_vendor
    default_idx = (
        vendors_in_period.index(prev_vendor)
        if prev_vendor in vendors_in_period
        else 0
    )
    selected_vendor = st.selectbox(
        f"거래처 선택 (총 {len(vendors_in_period)}개)",
        vendors_in_period,
        index=default_idx,
        key="settle_ecount_vendor_select",
    )
    if selected_vendor != prev_vendor:
        st.session_state.settle_ecount_vendor = selected_vendor
        _reset_below_vendor()
        st.rerun()
    elif st.session_state.settle_ecount_vendor is None:
        st.session_state.settle_ecount_vendor = selected_vendor

    if selected_vendor in vendor_summary.index:
        _row = vendor_summary.loc[selected_vendor]
        st.caption(
            f"**{selected_vendor}** — {int(_row['건수']):,}건 / "
            f"수량 {int(_row['수량']):,} / 금액 {int(_row['금액']):,}원"
        )
        # 금액 0원이면 재고이동(예: '재고(출고)')일 수 있다 — 하드코딩 제외 대신 안내
        if int(_row["금액"]) == 0:
            st.warning(
                f"⚠️ '{selected_vendor}'는 금액이 0원인 행 {int(_row['건수']):,}건뿐입니다. "
                "재고이동 데이터일 수 있으니 정산 대상이 맞는지 확인하세요."
            )


# 2026-10-13 hoyeon.han: 기존 발주내역 화면과 동일한 셀러 복수 선택·전체 선택.
# ===== 5. 셀러(특이사항) 선택 =====

if parsed is not None and st.session_state.settle_ecount_vendor is not None:
    st.markdown("### 🧑‍💼 5. 셀러(특이사항) 선택")
    st.caption(
        "셀러 값은 원본의 특이사항 컬럼입니다. 빈 특이사항은 '일반' 셀러로 묶습니다. "
        "선택한 셀러의 주문만 집계·상세내역에 포함하며, 주문유형은 모두 포함합니다."
    )
    df_vendor = st_mod.filter_by_vendor(
        df_period, st.session_state.settle_ecount_vendor
    )
    seller_values = df_vendor[es.COL_REMARK].fillna("").astype(str).str.strip()
    n_blank = int((seller_values == "").sum())
    df_vendor = df_vendor.copy()
    df_vendor[es.COL_REMARK] = seller_values.mask(seller_values == "", _NO_SELLER_LABEL)
    if n_blank:
        st.info(f"ℹ️ 빈 특이사항 {n_blank:,}건은 '일반' 셀러로 포함됩니다.")
    sellers = sorted(df_vendor[es.COL_REMARK].unique().tolist())
    if not sellers:
        st.warning("⚠️ 선택한 기간·거래처에 데이터가 없습니다.")
        st.stop()
    seller_counts = df_vendor[es.COL_REMARK].value_counts()
    if st.button("전체 선택", key="settle_ecount_select_all"):
        st.session_state["settle_ecount_seller_multiselect"] = list(sellers)
        st.rerun()
    default_sellers = [s for s in st.session_state.settle_ecount_sellers if s in sellers]
    selected_sellers = st.multiselect(
        f"셀러 선택 (총 {len(sellers)}개, 복수 선택 가능)",
        options=sellers,
        default=default_sellers,
        format_func=lambda s: f"{s} ({int(seller_counts.get(s, 0)):,}건)",
        key="settle_ecount_seller_multiselect",
    )
    selected_sellers = [s for s in sellers if s in set(selected_sellers)]
    # 빈 선택도 먼저 하위 상태를 폐기해 이전 정산서가 남지 않도록 한다.
    if selected_sellers != st.session_state.settle_ecount_sellers:
        st.session_state.settle_ecount_sellers = selected_sellers
        _reset_below_sellers()
        st.rerun()
    if not selected_sellers:
        st.warning("⚠️ 셀러(특이사항)를 1개 이상 선택하세요.")
        st.stop()
    df_seller_rows = df_vendor[
        df_vendor[es.COL_REMARK].isin(selected_sellers)
    ].copy()
    st.caption(
        f"선택 결과: {len(df_seller_rows):,}행 / "
        f"수량 {int(df_seller_rows['수량'].sum()):,} / "
        f"금액 {int(df_seller_rows['합계'].sum()):,}원"
    )


# ===== 6. 품목명 정리 =====

if parsed is not None and st.session_state.settle_ecount_vendor is not None:
    # df_vendor = st_mod.filter_by_vendor(
    #     df_typed, st.session_state.settle_ecount_vendor
    # )
    # 구분(주문유형)은 OUTPUT_COLS 에 없으므로 여기서 자동으로 떨어져 나간다
    # df_clean = st_mod.drop_unused_columns(df_vendor)
    # 2026-10-13 hoyeon.han: 상세내역에 필요한 구분·수하인·연락처 열을 유지한다.
    # df_clean = df_vendor.copy()
    # 2026-10-13 hoyeon.han: 품목·시트 배치·미리보기·작성 모두 선택한 셀러만 사용한다.
    df_clean = df_seller_rows.copy()

    st.markdown("### 📝 6. 품목명 정리")
    st.caption("필요시 품목명을 정제하세요. 같은 값으로 묶으면 통합됩니다.")

    items = sorted({str(v) for v in df_clean["품목"] if str(v).strip()})
    if st.session_state.settle_ecount_item_mapping is None:
        st.session_state.settle_ecount_item_mapping = {it: it for it in items}

    with st.expander(f"품목명 매핑 편집 ({len(items)}건)", expanded=True):
        # data_editor 피드백 루프 방지: 위젯 상태가 살아있을 때만 identity baseline,
        # 소실됐으면(페이지 복귀) 저장된 매핑으로 복원한다.
        if "settle_ecount_item_editor" in st.session_state:
            changed_col = items
        else:
            _im = st.session_state.settle_ecount_item_mapping or {}
            changed_col = [_im.get(it, it) for it in items]
        item_df = pd.DataFrame({"원본": items, "변경": changed_col})
        edited_items = st.data_editor(
            item_df,
            disabled=["원본"],
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            key="settle_ecount_item_editor",
        )
        # 비운 셀은 data_editor 가 None 을 돌려준다 → 원본 품목명 유지
        st.session_state.settle_ecount_item_mapping = {
            orig: (str(new).strip() if new is not None and str(new).strip() else orig)
            for orig, new in zip(edited_items["원본"], edited_items["변경"])
        }

    # df_item_mapped = st_mod.apply_mapping(
    #     df_clean, "품목", st.session_state.settle_ecount_item_mapping
    # )
    # 2026-10-13 hoyeon.han: 계획 생성에서 요약과 상세에 매핑을 한 번만 적용.
    df_item_mapped = df_clean


    # ===== 7. 시트 배치 설정 =====

    st.markdown("### 🏷️ 7. 시트 배치 설정")
    st.caption(
        "비고(셀러) 값은 원본 그대로 보존됩니다. 각 셀러를 **어느 시트에 배치할지**만 "
        "결정합니다. `배치할 시트`를 비워두거나 `일반`이라고 입력하면 `일반` 시트로 "
        "분류됩니다. 같은 시트명으로 여러 셀러를 묶으면 한 시트로 통합 배치됩니다 "
        "(예: `러브지나 4차`, `러브지나 5차` → `러브지나`)."
    )

    remarks = sorted({str(v).strip() for v in df_item_mapped["비고"] if str(v).strip()})
    if st.session_state.settle_ecount_remark_sheet_map is None:
        st.session_state.settle_ecount_remark_sheet_map = {r: r for r in remarks}

    with st.expander(f"시트 배치 편집 ({len(remarks)}건)", expanded=True):
        if not remarks:
            st.info("비고(셀러) 값이 없습니다. 모든 데이터가 '일반' 시트로 분류됩니다.")
            remark_df = pd.DataFrame({"비고": [], "배치할 시트": []})
        else:
            if "settle_ecount_sheet_editor" in st.session_state:
                sheet_col_vals = remarks
            else:
                _rm = st.session_state.settle_ecount_remark_sheet_map or {}
                sheet_col_vals = [_rm.get(r, r) for r in remarks]
            remark_df = pd.DataFrame({"비고": remarks, "배치할 시트": sheet_col_vals})
        edited_remarks = st.data_editor(
            remark_df,
            disabled=["비고"],
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            key="settle_ecount_sheet_editor",
        )
        if len(edited_remarks) > 0:
            # 비운 셀(None)을 그대로 저장하면 'None' 이름의 시트가 생긴다 → '일반'으로 확정
            st.session_state.settle_ecount_remark_sheet_map = {
                remark: st_mod.normalize_sheet_choice(sheet, st_mod.SHEET_GENERAL)
                for remark, sheet in zip(
                    edited_remarks["비고"], edited_remarks["배치할 시트"]
                )
            }

    # 비고 컬럼은 절대 치환하지 않음. 시트 라우팅만 적용된다
    df_final = df_item_mapped


# 2026-10-13 hoyeon.han: 이전 원본 행 분할/출력 흐름은 아래 주석으로 보존한다.
# # ===== 8. 시트 분할 미리보기 =====
#
# if parsed is not None and st.session_state.settle_ecount_vendor is not None:
#     st.markdown("### 👁️ 8. 시트 분할 미리보기")
#
#     if st.button("🔍 미리보기 생성", key="settle_ecount_preview_btn"):
#         try:
#             sheets = st_mod.split_into_sheets(
#                 df_final,
#                 remark_to_sheet=st.session_state.settle_ecount_remark_sheet_map,
#             )
#             st.session_state.settle_ecount_sheets = sheets
#         except Exception as e:  # noqa: BLE001
#             st.error(f"❌ 시트 분할 실패: {e}")
#             st.session_state.settle_ecount_sheets = None
#
#     sheets = st.session_state.settle_ecount_sheets
#     if sheets is not None:
#         sheet_tabs = st.tabs(list(sheets.keys()))
#         for tab, (name, sub) in zip(sheet_tabs, sheets.items()):
#             with tab:
#                 c1, c2, c3 = st.columns(3)
#                 c1.metric("데이터 행", f"{len(sub):,}행")
#                 c2.metric("수량 합계", f"{int(pd.to_numeric(sub['수량'], errors='coerce').fillna(0).sum()):,}")
#                 c3.metric("금액 합계", f"{int(pd.to_numeric(sub['합계'], errors='coerce').fillna(0).sum()):,}원")
#                 st.dataframe(sub, use_container_width=True, hide_index=True)
#
#
# # ===== 9. 생성 및 다운로드 =====
#
# if (
#     parsed is not None
#     and st.session_state.settle_ecount_vendor is not None
#     and st.session_state.settle_ecount_sheets is not None
# ):
#     st.markdown("### 💾 9. 정산서 생성 및 다운로드")
#
#     vendor = st.session_state.settle_ecount_vendor
#     doc_type = parsed["doc_type"]  # 판매현황내역 → 항상 '매출'
#     start_date = st.session_state.settle_ecount_start_date
#     end_date = st.session_state.settle_ecount_end_date
#     sheets = st.session_state.settle_ecount_sheets
#
#     out_filename = st_mod.build_output_filename(doc_type, vendor, start_date, end_date)
#     out_path = os.path.join("processed", out_filename)
#     period_line = st_mod.build_period_line(start_date, end_date, vendor)
#
#     st.markdown("#### ⚙️ 생성 옵션")
#     st.caption("옵션은 최종 생성 파일에만 적용됩니다 (위 미리보기에는 반영되지 않음).")
#
#     # 일반 시트 중복 자동 감지: 비어있거나 전체 시트와 행 수가 같으면 사실상 중복
#     general_df = sheets.get(st_mod.SHEET_GENERAL)
#     overall_df = sheets.get(st_mod.SHEET_OVERALL)
#     general_redundant = general_df is not None and (
#         len(general_df) == 0
#         or (overall_df is not None and len(general_df) == len(overall_df))
#     )
#     if "settle_ecount_exclude_general" not in st.session_state:
#         st.session_state["settle_ecount_exclude_general"] = general_redundant
#     if "settle_ecount_highlight_total" not in st.session_state:
#         st.session_state["settle_ecount_highlight_total"] = True
#
#     exclude_general = st.checkbox(
#         "일반 시트 제외",
#         key="settle_ecount_exclude_general",
#         help="일반 시트가 비어있거나 전체 시트와 동일하면 기본 제외됩니다.",
#     )
#     if exclude_general and general_df is not None and len(general_df) > 0:
#         st.warning(
#             f"⚠️ '{st_mod.SHEET_GENERAL}' 시트에 {len(general_df):,}행이 있는데 "
#             "'일반 시트 제외'가 켜져 있습니다. 해당 행은 생성 파일에서 빠집니다. "
#             "포함하려면 체크를 해제하세요."
#         )
#     highlight_total = st.checkbox(
#         "전체 시트 금액 합계 강조 (볼드 + 글씨/채우기 색상)",
#         key="settle_ecount_highlight_total",
#     )
#
#     total_font_size = 11.0
#     total_font_color = "#FF0000"
#     total_fill_color = "#FFFF00"
#     if highlight_total:
#         oc1, oc2, oc3 = st.columns(3)
#         total_font_size = oc1.number_input(
#             "폰트 크기",
#             min_value=8,
#             max_value=36,
#             value=11,
#             step=1,
#             key="settle_ecount_total_font_size",
#         )
#         total_font_color = oc2.color_picker(
#             "글씨 색상", value="#FF0000", key="settle_ecount_total_font_color"
#         )
#         total_fill_color = oc3.color_picker(
#             "채우기 색상", value="#FFFF00", key="settle_ecount_total_fill_color"
#         )
#
#     if st.button("📥 정산서 생성", key="settle_ecount_generate_btn", type="primary"):
#         try:
#             sheets_to_write = dict(sheets)
#             if exclude_general and st_mod.SHEET_GENERAL in sheets_to_write:
#                 del sheets_to_write[st_mod.SHEET_GENERAL]
#             st_mod.write_settlement_xlsx(
#                 out_path=out_path,
#                 title=parsed["title"],
#                 period_line=period_line,
#                 sheets=sheets_to_write,
#                 highlight_total=highlight_total,
#                 total_font_size=float(total_font_size),
#                 total_font_color=total_font_color,
#                 total_fill_color=total_fill_color,
#             )
#             st.session_state.settle_ecount_output_path = out_path
#             st.session_state.settle_ecount_output_filename = out_filename
#             st.session_state.settle_ecount_history.append(
#                 {
#                     "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#                     "vendor": vendor,
#                     "주문유형": ", ".join(
#                         st.session_state.settle_ecount_order_types or []
#                     ),
#                     "시트수": len(sheets_to_write),
#                     "start_date": str(start_date),
#                     "end_date": str(end_date),
#                     "filename": out_filename,
#                 }
#             )
#             st.success(f"✅ 생성 완료: `{out_filename}`")
#         except Exception as e:  # noqa: BLE001
#             st.error(f"❌ 정산서 생성 실패: {e}")
#             with st.expander("🔍 에러 상세 정보"):
#                 st.exception(e)
#
#     if st.session_state.settle_ecount_output_path and os.path.exists(
#         st.session_state.settle_ecount_output_path
#     ):
#         with open(st.session_state.settle_ecount_output_path, "rb") as f:
#             st.download_button(
#                 label=f"⬇️ {st.session_state.settle_ecount_output_filename} 다운로드",
#                 data=f.read(),
#                 file_name=st.session_state.settle_ecount_output_filename,
#                 mime=(
#                     "application/vnd.openxmlformats-officedocument."
#                     "spreadsheetml.sheet"
#                 ),
#                 key="settle_ecount_download_btn",
#                 use_container_width=True,
#             )

# ===== 8. 출력 시트 옵션 =====
# 2026-10-13 hoyeon.han: 기존 발주내역 화면과 동일하게 전체/상세 출력을 선택한다.
if parsed is not None and st.session_state.settle_ecount_vendor is not None:
    st.markdown("### 🧾 8. 출력 시트 옵션")
    include_overall = st.checkbox(
        # "전체 시트 포함 (선택 조건 전체를 한 시트로 집계)",
        # 2026-10-13 hoyeon.han: '전체'는 선택한 셀러 범위임을 명확히 한다.
        "전체 시트 포함 (선택한 셀러 전체를 한 시트로 집계)",
        value=st.session_state.settle_ecount_include_overall,
        key="settle_ecount_include_overall_cb",
    )
    st.session_state.settle_ecount_include_overall = include_overall
    detail_labels = list(_DETAIL_LABELS)
    previous_label = next(
        (label for label, mode in _DETAIL_LABELS.items()
         if mode == st.session_state.settle_ecount_detail_mode),
        "전체 하나로 생성",
    )
    detail_label = st.radio(
        "상세내역 생성 방식",
        options=detail_labels,
        index=detail_labels.index(previous_label),
        horizontal=True,
        key="settle_ecount_detail_mode_radio",
    )
    detail_mode = _DETAIL_LABELS[detail_label]
    st.session_state.settle_ecount_detail_mode = detail_mode
    st.caption(
        "정산 요약은 일자·품목·단가·반품 여부·셀러별로 수량과 금액을 합산합니다. "
        "단가는 기존 정산서와 같이 각 원본 행의 합계 ÷ 수량으로 계산합니다. "
        "상세내역은 합산하지 않은 원본 주문 행입니다."
    )

    # 2026-10-13 hoyeon.han: 매핑/옵션 변경 시 오래된 미리보기·다운로드를 숨긴다.
    plan_signature = (
        st.session_state.settle_ecount_uploaded_sig,
        st.session_state.settle_ecount_start_date,
        st.session_state.settle_ecount_end_date,
        # tuple(st.session_state.settle_ecount_order_types or []),
        # 2026-10-13 hoyeon.han: 셀러 선택 변경을 미리보기·다운로드 조건에 반영한다.
        tuple(st.session_state.settle_ecount_sellers),
        st.session_state.settle_ecount_vendor,
        tuple(sorted((st.session_state.settle_ecount_item_mapping or {}).items())),
        tuple(sorted((st.session_state.settle_ecount_remark_sheet_map or {}).items())),
        include_overall,
        detail_mode,
    )
    if plan_signature != st.session_state.settle_ecount_plan_signature:
        st.session_state.settle_ecount_plan = None
        st.session_state.settle_ecount_output_path = None
        st.session_state.settle_ecount_output_filename = None
        st.session_state.settle_ecount_plan_signature = plan_signature

    # ===== 9. 집계 및 상세내역 미리보기 =====
    st.markdown("### 👁️ 9. 집계 및 상세내역 미리보기")
    if st.button("🔍 미리보기 생성", key="settle_ecount_preview_btn"):
        try:
            st.session_state.settle_ecount_plan = es.build_ecount_sheet_plan(
                df_final,
                remark_to_sheet=st.session_state.settle_ecount_remark_sheet_map,
                item_mapping=st.session_state.settle_ecount_item_mapping,
                detail_mode=detail_mode,
                include_overall=include_overall,
            )
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ 정산서 미리보기 생성 실패: {e}")
            st.session_state.settle_ecount_plan = None

    plan = st.session_state.settle_ecount_plan
    if plan is not None:
        preview_sheets = {}
        if plan.get("overall_df") is not None:
            preview_sheets[ss.SHEET_OVERALL] = plan["overall_df"]
        preview_sheets.update(plan["seller_sheets"])
        if detail_mode == ss.DETAIL_MODE_SINGLE:
            preview_sheets[ss.DETAIL_SHEET_NAME] = plan["detail_df"]
        elif detail_mode == ss.DETAIL_MODE_PER_SELLER:
            preview_sheets.update(plan["detail_sheets"] or {})
        sheet_tabs = st.tabs(list(preview_sheets))
        for tab, (name, sub) in zip(sheet_tabs, preview_sheets.items()):
            with tab:
                is_summary = name in plan["seller_sheets"] or name == ss.SHEET_OVERALL
                amount_col = "합계" if is_summary else ss.COLUMN_MAP_SALE["amount"]
                c1, c2, c3 = st.columns(3)
                c1.metric("집계 행" if is_summary else "원본 주문 행", f"{len(sub):,}행")
                c2.metric("수량 합계", f"{int(sub['수량'].sum()):,}")
                c3.metric("금액 합계", f"{int(sub[amount_col].sum()):,}원")
                st.dataframe(sub, use_container_width=True, hide_index=True)

# ===== 10. 생성 및 다운로드 =====
# 2026-10-13 hoyeon.han: 기존 정산서 작성기로 요약과 상세내역을 같은 파일에 작성.
if (
    parsed is not None
    and st.session_state.settle_ecount_vendor is not None
    and st.session_state.settle_ecount_plan is not None
):
    st.markdown("### 💾 10. 정산서 생성 및 다운로드")
    vendor = st.session_state.settle_ecount_vendor
    doc_type = parsed["doc_type"]
    start_date = st.session_state.settle_ecount_start_date
    end_date = st.session_state.settle_ecount_end_date
    out_filename = st_mod.build_output_filename(doc_type, vendor, start_date, end_date)
    out_path = os.path.join("processed", out_filename)
    period_line = ss.build_period_line(vendor, start_date=start_date, end_date=end_date)

    st.markdown("#### ⚙️ 생성 옵션")
    oc1, oc2, oc3 = st.columns(3)
    seller_font_size = oc1.number_input(
        "셀러 시트 폰트 크기", min_value=8, max_value=36, value=13, step=1,
        key="settle_ecount_seller_font_size",
    )
    total_font_color = oc2.color_picker(
        "합계행 글씨 색상", value="#FF0000", key="settle_ecount_font_color",
    )
    total_fill_color = oc3.color_picker(
        "합계행 채우기 색상", value="#FFFF00", key="settle_ecount_fill_color",
    )

    if st.button("📥 정산서 생성", key="settle_ecount_generate_btn", type="primary"):
        try:
            # 생성 직전 최신 매핑·출력 옵션으로 다시 계산(미리보기 캐시를 쓰지 않음).
            plan_final = es.build_ecount_sheet_plan(
                df_final,
                remark_to_sheet=st.session_state.settle_ecount_remark_sheet_map,
                item_mapping=st.session_state.settle_ecount_item_mapping,
                detail_mode=detail_mode,
                include_overall=include_overall,
            )
            ss.write_seller_settlement_xlsx(
                out_path=out_path,
                title=ss.TITLE_SALE,
                period_line=period_line,
                plan=plan_final,
                seller_font_size=float(seller_font_size),
                total_font_color=total_font_color,
                total_fill_color=total_fill_color,
                column_map=ss.COLUMN_MAP_SALE,
            )
            st.session_state.settle_ecount_plan = plan_final
            st.session_state.settle_ecount_output_path = out_path
            st.session_state.settle_ecount_output_filename = out_filename
            sheet_count = (
                len(plan_final["seller_sheets"])
                + int(plan_final["overall_df"] is not None)
                + (1 if detail_mode == ss.DETAIL_MODE_SINGLE else
                   len(plan_final["detail_sheets"] or {}))
            )
            st.session_state.settle_ecount_history.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "vendor": vendor,
                # "주문유형": ", ".join(st.session_state.settle_ecount_order_types or []),
                # 2026-10-13 hoyeon.han: 선택 셀러와 주문유형 전체 포함을 이력에 기록한다.
                "셀러": ", ".join(st.session_state.settle_ecount_sellers),
                "주문유형": "전체 포함",
                "전체시트": "포함" if include_overall else "제외",
                "상세내역": detail_label,
                "시트수": sheet_count,
                "start_date": str(start_date),
                "end_date": str(end_date),
                "filename": out_filename,
            })
            st.success(f"✅ 생성 완료: `{out_filename}`")
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ 정산서 생성 실패: {e}")
            with st.expander("🔍 에러 상세 정보"):
                st.exception(e)

    if st.session_state.settle_ecount_output_path and os.path.exists(
        st.session_state.settle_ecount_output_path
    ):
        with open(st.session_state.settle_ecount_output_path, "rb") as f:
            st.download_button(
                label=f"⬇️ {st.session_state.settle_ecount_output_filename} 다운로드",
                data=f.read(),
                file_name=st.session_state.settle_ecount_output_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="settle_ecount_download_btn",
                use_container_width=True,
            )


# ===== 처리 이력 =====

if st.session_state.settle_ecount_history:
    st.divider()
    st.markdown("### 📜 이번 세션 처리 이력")
    st.dataframe(
        pd.DataFrame(st.session_state.settle_ecount_history),
        use_container_width=True,
        hide_index=True,
    )
