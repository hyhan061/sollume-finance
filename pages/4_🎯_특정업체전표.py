"""
솔루미랩 특정업체 전표 생성 페이지
특정 기간 + 특정 업체(복수 선택) 기준으로 매출/매입 전표 생성
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date
import os
import sys
import re
from pathlib import Path

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정 (Streamlit 명령 중 가장 먼저 실행되어야 함)
st.set_page_config(page_title="특정업체 전표", page_icon="🎯", layout="wide")

# 2025-12-17 hoyeon.han: 인증 체크 (Src/__init__.py 우회)
import importlib.util

spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent.parent / "Src" / "auth.py"
)
if spec is None or spec.loader is None:
    raise ImportError("auth 모듈을 불러올 수 없습니다.")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
auth.require_auth()

# 2025-12-22 hoyeon.han: Quick Win #4 - 커스텀 사이드바
# 2026-06-03 hoyeon.han: 발주내역 서버 저장/재사용 공통 컴포넌트 추가
from ui_components import render_custom_sidebar, render_order_file_selector

render_custom_sidebar()

from processing import (
    get_sales_by_period_vendor,
    get_purchase_by_period_vendor,
    save_dataframe_to_xls,
)
from customer_master_db import CustomerMasterDB
from exceptions import SollumeBaseException

# 디렉토리 생성
os.makedirs("uploads", exist_ok=True)
os.makedirs("processed", exist_ok=True)
os.makedirs("database", exist_ok=True)

# 2026-04-08 hoyeon.han: 특정기간 + 특정업체 전표 생성 페이지

if "vendor_period_result" not in st.session_state:
    st.session_state.vendor_period_result = None


def sanitize_vendor_name(vendor_name: str) -> str:
    """파일명 안전화를 위해 금지 문자 치환"""
    sanitized = re.sub(r"[\\/:*?\"<>|]", "_", str(vendor_name).strip())
    return sanitized if sanitized else "unknown_vendor"


def get_vendor_options() -> list[str]:
    """DB에서 업체 목록 로드"""
    db = CustomerMasterDB("database/customer_master.db")
    df_customers = db.get_all_customers()

    if len(df_customers) == 0 or "발주내역_거래처명" not in df_customers.columns:
        return []

    vendor_list = (
        df_customers["발주내역_거래처명"].dropna().astype(str).str.strip().tolist()
    )
    vendor_list = sorted(list(set([v for v in vendor_list if v])))
    return vendor_list


def process_vendor_vouchers(
    file_path,
    source_name,
    selected_sheet: str,
    start_date_value: date,
    end_date_value: date,
    selected_vendors: list[str],
):
    """선택 업체별 기간 전표 생성
    2026-06-03 hoyeon.han: 발주내역 서버 저장 적용 - 저장된 file_path 사용, 임시 저장/삭제 제거
    """
    start_date_str = start_date_value.strftime("%Y-%m-%d")
    end_date_str = end_date_value.strftime("%Y-%m-%d")

    result_rows = []
    skipped_vendors = []

    # 2026-06-03 hoyeon.han: 발주내역 파일은 이미 서버에 저장됨 (임시 저장 불필요)
    # --- 기존 코드 (주석 처리) ---
    # temp_filename = f"temp_vendor_period_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}"
    # temp_path = os.path.join("uploads", temp_filename)
    # --- 기존 코드 끝 ---

    with st.status("🎯 특정업체 전표 생성 중...", expanded=True) as status:
        try:
            # 2026-06-03 hoyeon.han: STEP 1(임시 저장) 제거 - 저장된 파일을 직접 사용
            # --- 기존 코드 (주석 처리) ---
            # st.write("📤 **STEP 1/3**: 업로드 파일 임시 저장")
            # with open(temp_path, "wb") as f:
            #     f.write(uploaded_file.getvalue())
            # st.write(f"✅ 임시 저장 완료: `{uploaded_file.name}`")
            # --- 기존 코드 끝 ---
            st.write(f"📂 발주내역 파일: `{source_name}`")

            st.write("⚙️ **STEP 1/1**: 업체별 매출/매입 전표 생성")
            progress = st.progress(0)
            total = len(selected_vendors)

            for idx, vendor_name in enumerate(selected_vendors, start=1):
                st.write(f"- ({idx}/{total}) **{vendor_name}** 처리 중...")

                df_sales = get_sales_by_period_vendor(
                    file_path=temp_path,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    vendor_name=vendor_name,
                    sheet_name=selected_sheet,
                    use_db=True,
                )
                df_purchase = get_purchase_by_period_vendor(
                    file_path=temp_path,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    vendor_name=vendor_name,
                    sheet_name=selected_sheet,
                    use_db=True,
                )

                if len(df_sales) == 0 and len(df_purchase) == 0:
                    skipped_vendors.append(vendor_name)
                    st.write(f"  ↳ ⚠️ 데이터 없음: {vendor_name}")
                    progress.progress(idx / total)
                    continue

                safe_vendor = sanitize_vendor_name(vendor_name)
                sales_filename = (
                    f"{safe_vendor}_매출_{start_date_str}~{end_date_str}.xls"
                )
                purchase_filename = (
                    f"{safe_vendor}_매입_{start_date_str}~{end_date_str}.xls"
                )

                sales_filepath = os.path.join("processed", sales_filename)
                purchase_filepath = os.path.join("processed", purchase_filename)

                save_dataframe_to_xls(df_sales, sales_filepath)
                save_dataframe_to_xls(df_purchase, purchase_filepath)

                result_rows.append(
                    {
                        "vendor_name": vendor_name,
                        "sales_count": len(df_sales),
                        "purchase_count": len(df_purchase),
                        "sales_filename": sales_filename,
                        "purchase_filename": purchase_filename,
                        "sales_filepath": sales_filepath,
                        "purchase_filepath": purchase_filepath,
                    }
                )

                st.write(
                    f"  ↳ ✅ 생성 완료 (매출 {len(df_sales):,}건 / 매입 {len(df_purchase):,}건)"
                )
                progress.progress(idx / total)

            # 2026-06-03 hoyeon.han: 임시 파일을 만들지 않으므로 정리 단계 제거
            # --- 기존 코드 (주석 처리) ---
            # st.write("🧹 **STEP 3/3**: 임시 파일 정리")
            # if os.path.exists(temp_path):
            #     os.remove(temp_path)
            # --- 기존 코드 끝 ---

            status.update(
                label="✅ 특정업체 전표 생성 완료", state="complete", expanded=False
            )

            st.session_state.vendor_period_result = {
                "source_file": source_name,
                "sheet_name": selected_sheet,
                "start_date": start_date_str,
                "end_date": end_date_str,
                "results": result_rows,
                "skipped_vendors": skipped_vendors,
                "timestamp": datetime.now(),
            }

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


st.title("🎯 특정업체 전표")
st.caption("특정 기간 + 특정 업체(복수 선택) 기준으로 매출/매입 전표를 생성합니다.")
st.divider()

# 1) 파일 업로드 + 시트 선택
# 2026-06-03 hoyeon.han: 발주내역 파일 서버 저장/재사용 컴포넌트로 대체
# --- 기존 코드 (주석 처리) ---
# st.markdown("### 📁 1. 발주내역 파일 업로드")
# uploaded_file = st.file_uploader(
#     "발주내역 Excel 파일을 선택하세요 (.xlsm/.xlsx)",
#     type=["xlsm", "xlsx"],
#     key="vendor_period_uploader",
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
#             key="vendor_period_sheet_selector",
#             help='"발주내역" + 현재 연도 포함 시트를 우선 선택합니다.',
#         )
#
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
order_file = render_order_file_selector("vendor_period", sheet_select=True)
selected_sheet = order_file["sheet_name"] if order_file else None
order_file_path = order_file["file_path"] if order_file else None
source_display_name = order_file["display_name"] if order_file else None

# 2) 기간 선택
st.markdown("### 📅 2. 처리 기간 선택")
today = date.today()
month_first_day = date(today.year, today.month, 1)

col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input(
        "시작일",
        value=month_first_day,
        max_value=today,
        key="vendor_period_start_date",
    )
with col2:
    end_date = st.date_input(
        "종료일",
        value=today,
        max_value=today,
        key="vendor_period_end_date",
    )

invalid_date_order = start_date > end_date
date_range_days = (end_date - start_date).days + 1 if not invalid_date_order else 0
too_long_range = date_range_days > 365

if invalid_date_order:
    st.warning("⚠️ 시작일은 종료일보다 이전 또는 같아야 합니다.")
elif too_long_range:
    st.warning(f"⚠️ 처리 기간이 {date_range_days}일입니다. 최대 365일까지만 지원합니다.")
else:
    st.info(f"📌 선택 기간: **{start_date} ~ {end_date}** ({date_range_days}일)")

# 3) 업체 선택
st.markdown("### 🏢 3. 업체 선택")
vendor_options = get_vendor_options()
if len(vendor_options) == 0:
    st.warning(
        "⚠️ 거래처 DB에서 업체 목록을 불러오지 못했습니다. 거래처 관리를 먼저 확인해주세요."
    )

selected_vendors = st.multiselect(
    "전표를 생성할 업체를 선택하세요",
    options=vendor_options,
    default=[],
    key="vendor_period_multiselect",
)

st.caption(f"선택 업체 수: {len(selected_vendors)}개")

# 4) 생성 버튼
st.markdown("### ▶️ 4. 전표 생성")
# 2026-06-03 hoyeon.han: uploaded_file → order_file_path 기준으로 변경
can_process = (
    order_file_path is not None
    and selected_sheet is not None
    and len(selected_vendors) > 0
    and (not invalid_date_order)
    and (not too_long_range)
)

generate_clicked = st.button(
    "🎯 전표 생성",
    type="primary",
    use_container_width=True,
    disabled=not can_process,
    key="vendor_period_generate_button",
)

if generate_clicked:
    if selected_sheet is None:
        st.error("시트를 선택해주세요.")
        st.stop()

    # 2026-06-03 hoyeon.han: 저장된 발주내역 경로와 원본명을 전달
    process_vendor_vouchers(
        file_path=order_file_path,
        source_name=source_display_name,
        selected_sheet=str(selected_sheet),
        start_date_value=start_date,
        end_date_value=end_date,
        selected_vendors=selected_vendors,
    )

st.divider()

# 5) 결과
st.markdown("### 📦 5. 생성 결과")
result = st.session_state.vendor_period_result

if result:
    st.success(
        f"✅ 처리 완료 | 기간: {result['start_date']}~{result['end_date']} | "
        f"생성 업체: {len(result['results'])}개"
    )

    if len(result["skipped_vendors"]) > 0:
        st.warning(
            "다음 업체는 기간 내 데이터가 없어 건너뛰었습니다: "
            + ", ".join(result["skipped_vendors"])
        )

    if len(result["results"]) == 0:
        st.info("생성된 파일이 없습니다.")
    else:
        for row in result["results"]:
            with st.expander(f"🏷️ {row['vendor_name']}", expanded=True):
                col1, col2, col3 = st.columns([1, 1, 1])

                with col1:
                    st.metric("매출 건수", f"{row['sales_count']:,}건")
                with col2:
                    st.metric("매입 건수", f"{row['purchase_count']:,}건")
                with col3:
                    st.caption("파일 다운로드")

                col_down1, col_down2 = st.columns(2)

                with col_down1:
                    with open(row["sales_filepath"], "rb") as f:
                        st.download_button(
                            label="📥 매출 파일 다운로드",
                            data=f.read(),
                            file_name=row["sales_filename"],
                            mime="application/vnd.ms-excel",
                            use_container_width=True,
                            key=f"download_sales_{row['vendor_name']}",
                        )

                with col_down2:
                    with open(row["purchase_filepath"], "rb") as f:
                        st.download_button(
                            label="📥 매입 파일 다운로드",
                            data=f.read(),
                            file_name=row["purchase_filename"],
                            mime="application/vnd.ms-excel",
                            use_container_width=True,
                            key=f"download_purchase_{row['vendor_name']}",
                        )
else:
    st.info("아직 생성된 결과가 없습니다.")
