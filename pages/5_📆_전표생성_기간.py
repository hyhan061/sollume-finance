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
# 2026-06-03 hoyeon.han: 발주내역 서버 저장/재사용 공통 컴포넌트 추가
from ui_components import render_custom_sidebar, render_order_file_selector

render_custom_sidebar()

# 2026-04-09 hoyeon.han: 기간 통합 전표 처리에 필요한 import
from processing import (
    get_sales_by_period,
    get_purchase_by_period,
    save_dataframe_to_xls,
)
from exceptions import SollumeBaseException
import logging

# 디렉토리 생성
os.makedirs("uploads", exist_ok=True)
os.makedirs("processed", exist_ok=True)

# 2026-04-09 hoyeon.han: session_state 초기화
if "period_voucher_result" not in st.session_state:
    st.session_state.period_voucher_result = None

st.title("📆 전표생성-기간")
st.caption("기간 내 전체 거래의 매출/매입 전표를 통합 생성합니다.")
st.divider()

# 2026-06-03 hoyeon.han: 발주내역 파일 서버 저장/재사용 기능 적용
# 기존 업로드/시트선택 로직을 공통 컴포넌트(render_order_file_selector)로 대체한다.
# --- 기존 코드 (주석 처리) ---
# st.markdown("### 📁 1. 발주내역 파일 업로드")
# uploaded_file = st.file_uploader(
#     "발주내역 Excel 파일을 선택하세요 (.xlsm/.xlsx)",
#     type=["xlsm", "xlsx"],
#     key="period_voucher_uploader",
# )
#
# selected_sheet = None
#
# if uploaded_file is not None:
#     st.success(
#         f"✅ 파일 선택됨: {uploaded_file.name} ({uploaded_file.size / 1024 / 1024:.2f} MB)"
#     )
#
#     try:
#         excel_file = pd.ExcelFile(uploaded_file)
#         sheet_names = excel_file.sheet_names
#
#         # 2026-04-09 hoyeon.han: 기본 선택 - '발주내역' + 현재 연도 포함 시트 우선
#         default_index = 0
#         current_year = datetime.now().year
#         for i, sheet in enumerate(sheet_names):
#             if "발주내역" in sheet and str(current_year) in sheet:
#                 default_index = i
#                 break
#
#         selected_sheet = st.selectbox(
#             "📋 처리할 시트 선택",
#             options=sheet_names,
#             index=default_index,
#             key="period_voucher_sheet_selector",
#             help='"발주내역" + 현재 연도 포함 시트를 우선 선택합니다.',
#         )
#
#         # 2026-04-09 hoyeon.han: 시트 미리보기 (상위 5행)
#         with st.expander("🔍 시트 미리보기 (상위 5행)"):
#             try:
#                 preview_df = pd.read_excel(
#                     uploaded_file,
#                     sheet_name=selected_sheet,
#                     header=3,
#                     nrows=5,
#                 )
#                 st.dataframe(preview_df, use_container_width=True)
#             except Exception as e:
#                 st.warning(f"시트 미리보기를 불러올 수 없습니다: {str(e)}")
#
#     except Exception as e:
#         st.error(f"시트 목록을 읽을 수 없습니다: {str(e)}")
# --- 기존 코드 끝 ---
st.markdown("### 📁 1. 발주내역 파일")
order_file = render_order_file_selector("period", sheet_select=True)
selected_sheet = order_file["sheet_name"] if order_file else None
order_file_path = order_file["file_path"] if order_file else None
source_display_name = order_file["display_name"] if order_file else None

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
# 2026-06-03 hoyeon.han: uploaded_file → order_file_path(저장된 파일 경로) 기준으로 변경
can_process = (
    order_file_path is not None
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


# 2026-04-09 hoyeon.han: 기간 통합 전표 처리 오케스트레이션
# 2026-06-03 hoyeon.han: 발주내역 서버 저장 적용
#   - uploaded_file 대신 서버에 저장된 file_path(order_data/current.xlsm)를 직접 사용
#   - 임시 저장(STEP1)/삭제(STEP5, finally) 단계 제거
def process_period_vouchers(file_path, source_name, selected_sheet, start_date, end_date):
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    # 2026-06-03 hoyeon.han: 발주내역 파일은 render_order_file_selector 가 이미
    # 서버(order_data/current.xlsm)에 저장했으므로 임시 저장/삭제 단계가 불필요하다.
    # --- 기존 코드 (주석 처리) ---
    # temp_filename = (
    #     f"temp_period_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}"
    # )
    # temp_path = os.path.join("uploads", temp_filename)
    # --- 기존 코드 끝 ---

    with st.status("⚙️ 기간 전표 생성 중...", expanded=True) as status:
        try:
            # 2026-06-03 hoyeon.han: STEP 1(임시 저장) 제거 - 저장된 파일을 직접 사용
            # --- 기존 코드 (주석 처리) ---
            # st.write("📤 **STEP 1/5**: 업로드 파일 임시 저장")
            # with open(temp_path, "wb") as f:
            #     f.write(uploaded_file.getvalue())
            # st.write(f"✅ 임시 저장 완료: `{uploaded_file.name}`")
            # --- 기존 코드 끝 ---
            st.write(f"📂 발주내역 파일: `{source_name}`")

            st.write(
                f"💰 **STEP 1/3**: 매출 데이터 처리 중... ({start_date_str} ~ {end_date_str})"
            )
            df_sales = get_sales_by_period(
                file_path=file_path,
                start_date=start_date_str,
                end_date=end_date_str,
                sheet_name=selected_sheet,
                use_db=True,
            )
            logging.info(f"기간 매출 처리 완료: {len(df_sales)}건")
            st.write(f"✅ 매출 데이터 처리 완료: **{len(df_sales):,}건**")

            st.write(
                f"🛒 **STEP 2/3**: 매입 데이터 처리 중... ({start_date_str} ~ {end_date_str})"
            )
            df_purchase = get_purchase_by_period(
                file_path=file_path,
                start_date=start_date_str,
                end_date=end_date_str,
                sheet_name=selected_sheet,
                use_db=True,
            )
            logging.info(f"기간 매입 처리 완료: {len(df_purchase)}건")
            st.write(f"✅ 매입 데이터 처리 완료: **{len(df_purchase):,}건**")

            st.write("💾 **STEP 3/3**: 경리나라 전표 파일 저장 중...")
            sales_filename = f"매출_{start_date_str}~{end_date_str}.xls"
            purchase_filename = f"매입_{start_date_str}~{end_date_str}.xls"
            sales_filepath = os.path.join("processed", sales_filename)
            purchase_filepath = os.path.join("processed", purchase_filename)

            save_dataframe_to_xls(df_sales, sales_filepath)
            save_dataframe_to_xls(df_purchase, purchase_filepath)
            st.write(f"✅ 파일 저장 완료")
            st.write(f"   - 매출: `{sales_filename}`")
            st.write(f"   - 매입: `{purchase_filename}`")

            # 2026-06-03 hoyeon.han: STEP 5(임시 파일 정리) 제거 - 임시 파일을 만들지 않음
            # --- 기존 코드 (주석 처리) ---
            # st.write("🧹 **STEP 5/5**: 임시 파일 정리 중...")
            # if os.path.exists(temp_path):
            #     os.remove(temp_path)
            # st.write("✅ 임시 파일 삭제 완료")
            # --- 기존 코드 끝 ---

            status.update(label="✅ 전표 생성 완료", state="complete", expanded=False)

            st.session_state.period_voucher_result = {
                "source_file": source_name,
                "sheet_name": selected_sheet,
                "start_date": start_date_str,
                "end_date": end_date_str,
                "sales_count": len(df_sales),
                "purchase_count": len(df_purchase),
                "df_sales": df_sales,
                "df_purchase": df_purchase,
                "sales_filename": sales_filename,
                "purchase_filename": purchase_filename,
                "sales_filepath": sales_filepath,
                "purchase_filepath": purchase_filepath,
                "timestamp": datetime.now(),
            }

            st.rerun()

        except SollumeBaseException as e:
            status.update(label="❌ 처리 실패", state="error", expanded=True)
            st.error(e.user_message)
            with st.expander("🔍 에러 상세 정보"):
                st.exception(e)

        except Exception as e:
            status.update(label="❌ 처리 실패", state="error", expanded=True)
            st.error(f"처리 중 오류가 발생했습니다: {str(e)}")
            with st.expander("🔍 에러 상세 정보"):
                st.exception(e)

        # 2026-06-03 hoyeon.han: 임시 파일을 만들지 않으므로 finally 의 임시파일 삭제 제거
        # --- 기존 코드 (주석 처리) ---
        # finally:
        #     if os.path.exists(temp_path):
        #         os.remove(temp_path)
        # --- 기존 코드 끝 ---


if generate_clicked:
    if selected_sheet is None:
        st.error("시트를 선택해주세요.")
        st.stop()

    # 2026-04-09 hoyeon.han: T6에서 처리 함수 호출로 교체 완료
    # st.info("처리 중...")
    # pass
    # 2026-06-03 hoyeon.han: 저장된 발주내역 경로(order_file_path)와 원본명을 전달
    process_period_vouchers(
        order_file_path, source_display_name, selected_sheet, start_date, end_date
    )

st.divider()

st.markdown("### 📦 4. 생성 결과")
result = st.session_state.period_voucher_result

# 2026-04-09 hoyeon.han: 결과 섹션 완성
# --- 기존 코드 (주석 처리) ---
# if result:
#     st.success("✅ 전표 생성이 완료되었습니다.")
# else:
#     st.info("아직 생성된 결과가 없습니다.")
# --- 기존 코드 끝 ---

if result:
    st.success(
        f"✅ 처리 완료 | 기간: {result['start_date']}~{result['end_date']} | "
        f"매출 {result['sales_count']:,}건 / 매입 {result['purchase_count']:,}건"
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📅 처리 기간", f"{result['start_date']}~{result['end_date']}")
    with col2:
        st.metric("💰 매출 건수", f"{result['sales_count']:,}건")
    with col3:
        st.metric("🛒 매입 건수", f"{result['purchase_count']:,}건")
    with col4:
        st.metric("⏰ 처리 시각", result["timestamp"].strftime("%H:%M:%S"))

    tab1, tab2 = st.tabs(["💰 매출 데이터", "🛒 매입 데이터"])

    with tab1:
        if result["sales_count"] > 0:
            st.info(f"총 {result['sales_count']:,}건의 매출 데이터가 처리되었습니다.")
            st.dataframe(
                result["df_sales"].head(20), use_container_width=True, height=300
            )
            with open(result["sales_filepath"], "rb") as f:
                st.download_button(
                    label="📥 매출 파일 다운로드",
                    data=f.read(),
                    file_name=result["sales_filename"],
                    mime="application/vnd.ms-excel",
                    type="primary",
                    use_container_width=True,
                    key="period_download_sales",
                )
        else:
            st.warning("해당 기간에 처리할 매출 데이터가 없습니다.")

    with tab2:
        if result["purchase_count"] > 0:
            st.info(
                f"총 {result['purchase_count']:,}건의 매입 데이터가 처리되었습니다."
            )
            st.dataframe(
                result["df_purchase"].head(20), use_container_width=True, height=300
            )
            with open(result["purchase_filepath"], "rb") as f:
                st.download_button(
                    label="📥 매입 파일 다운로드",
                    data=f.read(),
                    file_name=result["purchase_filename"],
                    mime="application/vnd.ms-excel",
                    type="primary",
                    use_container_width=True,
                    key="period_download_purchase",
                )
        else:
            st.warning("해당 기간에 처리할 매입 데이터가 없습니다.")
else:
    st.info("아직 생성된 결과가 없습니다.")
