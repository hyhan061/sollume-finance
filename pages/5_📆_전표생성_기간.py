"""전표생성-기간 페이지 / 2026-04-09 hoyeon.han"""

# 2026-04-09 hoyeon.han: 기간 통합 전표 생성 페이지 신규 생성

import streamlit as st
import pandas as pd
from datetime import datetime, date
import os
import sys
from pathlib import Path

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정 (Streamlit 명령 중 가장 먼저 실행되어야 함)
st.set_page_config(page_title="전표생성-기간", page_icon="📆", layout="wide")

# 2026-04-09 hoyeon.han: 인증 체크 (Src/__init__.py 우회)
import importlib.util

spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent.parent / "Src" / "auth.py"
)
if spec is None or spec.loader is None:
    raise ImportError("auth 모듈을 불러올 수 없습니다.")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
auth.require_auth()

# 2026-04-09 hoyeon.han: 커스텀 사이드바
from ui_components import render_custom_sidebar

render_custom_sidebar()

# 디렉토리 생성
os.makedirs("uploads", exist_ok=True)
os.makedirs("processed", exist_ok=True)

# 2026-04-09 hoyeon.han: session_state 초기화
if "period_voucher_result" not in st.session_state:
    st.session_state.period_voucher_result = None

st.title("📆 전표생성-기간")
st.caption("기간 내 전체 거래의 매출/매입 전표를 통합 생성합니다.")
st.divider()

st.markdown("### 📁 1. 발주내역 파일 업로드")
uploaded_file = st.file_uploader(
    "발주내역 Excel 파일을 선택하세요 (.xlsm/.xlsx)",
    type=["xlsm", "xlsx"],
    key="period_voucher_uploader",
)

selected_sheet = None

if uploaded_file is not None:
    st.success(
        f"✅ 파일 선택됨: {uploaded_file.name} ({uploaded_file.size / 1024 / 1024:.2f} MB)"
    )

    try:
        excel_file = pd.ExcelFile(uploaded_file)
        sheet_names = excel_file.sheet_names

        # 2026-04-09 hoyeon.han: 기본 선택 - '발주내역' + 현재 연도 포함 시트 우선
        default_index = 0
        current_year = datetime.now().year
        for i, sheet in enumerate(sheet_names):
            if "발주내역" in sheet and str(current_year) in sheet:
                default_index = i
                break

        selected_sheet = st.selectbox(
            "📋 처리할 시트 선택",
            options=sheet_names,
            index=default_index,
            key="period_voucher_sheet_selector",
            help='"발주내역" + 현재 연도 포함 시트를 우선 선택합니다.',
        )

        # 2026-04-09 hoyeon.han: 시트 미리보기 (상위 5행)
        with st.expander("🔍 시트 미리보기 (상위 5행)"):
            try:
                preview_df = pd.read_excel(
                    uploaded_file,
                    sheet_name=selected_sheet,
                    header=3,
                    nrows=5,
                )
                st.dataframe(preview_df, use_container_width=True)
            except Exception as e:
                st.warning(f"시트 미리보기를 불러올 수 없습니다: {str(e)}")

    except Exception as e:
        st.error(f"시트 목록을 읽을 수 없습니다: {str(e)}")

st.markdown("### 📅 2. 처리 기간 선택")
today = date.today()
month_first_day = date(today.year, today.month, 1)

col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input(
        "시작일",
        value=month_first_day,
        max_value=today,
        key="period_voucher_start_date",
    )
with col2:
    end_date = st.date_input(
        "종료일",
        value=today,
        max_value=today,
        key="period_voucher_end_date",
    )

# 2026-04-09 hoyeon.han: 기간 유효성 검사
invalid_date_order = start_date > end_date
date_range_days = (end_date - start_date).days + 1 if not invalid_date_order else 0
too_long_range = date_range_days > 365

if invalid_date_order:
    st.warning("⚠️ 시작일은 종료일보다 이전 또는 같아야 합니다.")
elif too_long_range:
    st.warning(f"⚠️ 처리 기간이 {date_range_days}일입니다. 최대 365일까지만 지원합니다.")
else:
    st.info(f"📌 선택 기간: **{start_date} ~ {end_date}** ({date_range_days}일)")

st.markdown("### ▶️ 3. 전표 생성")

# 2026-04-09 hoyeon.han: 버튼 활성화 조건 - 업로드/시트/기간 모두 충족
can_process = (
    uploaded_file is not None
    and selected_sheet is not None
    and (not invalid_date_order)
    and (not too_long_range)
)

generate_clicked = st.button(
    "📆 전표 생성",
    type="primary",
    use_container_width=True,
    disabled=not can_process,
    key="period_voucher_generate_button",
)

if generate_clicked:
    if selected_sheet is None:
        st.error("시트를 선택해주세요.")
        st.stop()

    # 2026-04-09 hoyeon.han: T6에서 처리 함수 호출로 교체 예정
    st.info("처리 중...")
    pass

st.divider()

st.markdown("### 📦 4. 생성 결과")
result = st.session_state.period_voucher_result

# 2026-04-09 hoyeon.han: T7에서 결과 표시 로직 완성 예정
if result:
    st.success("✅ 전표 생성이 완료되었습니다.")
else:
    st.info("아직 생성된 결과가 없습니다.")
