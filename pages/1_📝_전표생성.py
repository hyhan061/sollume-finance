"""
솔루미랩 경리나라 전표 생성 페이지
매출/매입 전표 날짜별 일괄등록 파일 생성
2025-12-16 hoyeon.han: app.py.backup의 tab1 내용을 별도 페이지로 분리
2025-12-17 hoyeon.han: 로그인 인증 추가
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
import sys
import logging
from pathlib import Path
import json

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정 (Streamlit 명령 중 가장 먼저 실행되어야 함)
# 2026-07-10 hoyeon.han: st.navigation 라우터(Home.py)로 이전 - 진입점에서 처리
# st.set_page_config(page_title="전표 생성", page_icon="📝", layout="wide")

# 2025-12-17 hoyeon.han: 인증 체크 (Src/__init__.py 우회)
import importlib.util

spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent.parent / "Src" / "auth.py"
)
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
# auth.require_auth()

# 2025-12-22 hoyeon.han: Quick Win #4 - 커스텀 사이드바 로고
# 2026-06-03 hoyeon.han: 발주내역 서버 저장/재사용 공통 컴포넌트 추가
from ui_components import render_custom_sidebar, render_order_file_selector

# 2026-07-09 hoyeon.han: 디자인 개선 - 공통 테마 CSS/헤더 모듈
from ui_theme import inject_global_css, render_page_header

# render_custom_sidebar()
# 2026-07-09 hoyeon.han: 사이드바 렌더 이후 전역 CSS 주입
# inject_global_css()

# 전표 생성 모듈
from processing import get_sales_daily, get_purchase_daily, save_dataframe_to_xls

# 커스텀 예외 및 로거
from Src.exceptions import (
    SollumeBaseException,
    ErrorSeverity,
    MasterFileNotFoundError,
    SheetNotFoundError,
    NoDataForDateError,
)
from Src.logger import get_logger

# 디렉토리 생성
os.makedirs("logs", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("processed", exist_ok=True)

# =============================================================================
# 2025-12-16 hoyeon.han: Session State 초기화
# =============================================================================

if "history" not in st.session_state:
    st.session_state.history = []

if "last_result" not in st.session_state:
    st.session_state.last_result = None

# CSS 스타일
# 2026-07-09 hoyeon.han: 디자인 개선 - 페이지 로컬 <style> 제거(.main-header 등 유틸 클래스는 ui_theme.inject_global_css()가 전역 제공)
# st.markdown(
#     """
# <style>
#     .main-header {
#         font-size: 2rem;
#         font-weight: bold;
#         color: #1f77b4;
#         margin-bottom: 1rem;
#     }
#     .section-header {
#         font-size: 1.5rem;
#         font-weight: bold;
#         color: #2c3e50;
#         margin-top: 2rem;
#         margin-bottom: 1rem;
#         border-bottom: 2px solid #3498db;
#         padding-bottom: 0.5rem;
#     }
#     .success-box {
#         padding: 1rem;
#         background-color: #d4edda;
#         border-left: 4px solid #28a745;
#         border-radius: 4px;
#         margin: 1rem 0;
#     }
#     .error-box {
#         padding: 1rem;
#         background-color: #f8d7da;
#         border-left: 4px solid #dc3545;
#         border-radius: 4px;
#         margin: 1rem 0;
#     }
#     .info-box {
#         padding: 1rem;
#         background-color: #d1ecf1;
#         border-left: 4px solid #17a2b8;
#         border-radius: 4px;
#         margin: 1rem 0;
#     }
#     .warning-box {
#         padding: 1rem;
#         background-color: #fff3cd;
#         border-left: 4px solid #ffc107;
#         border-radius: 4px;
#         margin: 1rem 0;
#     }
# </style>
# """,
#     unsafe_allow_html=True,
# )

# =============================================================================
# 페이지 타이틀
# =============================================================================

# 2026-07-09 hoyeon.han: 디자인 개선 - 통일 페이지 헤더로 교체
# st.markdown('<div class="main-header">📝 전표 생성</div>', unsafe_allow_html=True)
# st.caption("발주내역 파일에서 경리나라 전표 파일을 생성합니다.")
# st.divider()
render_page_header(
    "전표 생성",
    "발주내역 엑셀에서 날짜별 매출·매입 전표를 생성합니다.",
    icon="📝",
)

# =============================================================================
# 2025-12-22 hoyeon.han: validate_uploaded_file() 함수 추가
# Quick Win #5 - 파일 검증
# =============================================================================


def validate_uploaded_file(file_path):
    """
    업로드된 파일을 즉시 검증하여 문제를 미리 발견
    2026-06-03 hoyeon.han: uploaded_file 객체 대신 저장된 파일 경로(file_path)를 사용

    검증 항목:
    1. 파일 크기 (200MB 이하)
    2. 필수 시트 존재 여부
    3. 필수 컬럼 존재 여부
    4. 데이터 샘플 미리보기
    """
    col1, col2, col3, col4 = st.columns(4)

    validation_passed = True

    # 1. 파일 크기 검증
    with col1:
        file_size_mb = os.path.getsize(file_path) / 1024 / 1024
        if file_size_mb < 200:
            st.metric(
                "📦 파일 크기",
                f"{file_size_mb:.2f} MB",
                delta="✅ 정상",
                delta_color="normal",
            )
        else:
            st.metric(
                "📦 파일 크기",
                f"{file_size_mb:.2f} MB",
                delta="⚠️ 너무 큼",
                delta_color="inverse",
            )
            validation_passed = False

    # 2. 시트 확인
    with col2:
        try:
            # 시트 목록만 확인 (데이터 로드 X)
            import openpyxl

            # 2026-06-03 hoyeon.han: 저장된 파일 경로를 직접 사용 (임시 저장 불필요)
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            sheet_names = wb.sheetnames
            wb.close()

            target_sheet = "(누적)2025년 발주내역"
            if target_sheet in sheet_names:
                st.metric(
                    "📋 필수 시트",
                    "✅ 존재",
                    delta=f"{len(sheet_names)}개 시트",
                    delta_color="normal",
                )
            else:
                st.metric(
                    "📋 필수 시트",
                    "❌ 없음",
                    delta="시트명 확인",
                    delta_color="inverse",
                )
                validation_passed = False
                st.error(f"⚠️ '{target_sheet}' 시트가 없습니다.")

        except Exception as e:
            st.metric(
                "📋 필수 시트", "❌ 오류", delta="파일 읽기 실패", delta_color="inverse"
            )
            validation_passed = False
            st.error(f"시트 확인 중 오류: {str(e)[:50]}...")

    # 3. 컬럼 확인 (샘플 데이터 읽기)
    with col3:
        try:
            # 상위 5행만 읽어서 컬럼 확인
            df_sample = pd.read_excel(
                file_path, sheet_name="(누적)2025년 발주내역", header=3, nrows=5
            )

            required_cols = ["출고일", "계산서", "업체명", "제품", "상품매출"]
            missing_cols = [
                col for col in required_cols if col not in df_sample.columns
            ]

            if not missing_cols:
                st.metric(
                    "🔤 필수 컬럼",
                    "✅ 정상",
                    delta=f"{len(df_sample.columns)}개 컬럼",
                    delta_color="normal",
                )
            else:
                st.metric(
                    "🔤 필수 컬럼",
                    "❌ 누락",
                    delta=f"{len(missing_cols)}개 누락",
                    delta_color="inverse",
                )
                validation_passed = False
                st.error(f"⚠️ 누락된 컬럼: {', '.join(missing_cols)}")

        except Exception as e:
            st.metric(
                "🔤 필수 컬럼", "❌ 오류", delta="컬럼 읽기 실패", delta_color="inverse"
            )
            validation_passed = False

    # 4. 데이터 샘플
    with col4:
        try:
            if "df_sample" in locals():
                row_count = len(df_sample)
                st.metric(
                    "📊 데이터 샘플",
                    f"{row_count}행",
                    delta="(상위 5건)",
                    delta_color="normal",
                )
            else:
                st.metric(
                    "📊 데이터 샘플", "N/A", delta="데이터 없음", delta_color="off"
                )
        except:
            pass

    # 검증 결과 요약
    st.markdown("---")

    if validation_passed:
        st.success(
            "✅ **파일 검증 통과!** 처리 버튼을 눌러 전표를 생성하세요.", icon="✅"
        )
    else:
        st.error(
            "❌ **파일 검증 실패!** 위의 오류를 수정한 후 다시 시도하세요.", icon="❌"
        )

    # 데이터 미리보기 (검증 통과 시)
    if validation_passed and "df_sample" in locals():
        st.markdown("#### 📋 데이터 미리보기 (상위 5행)")
        st.dataframe(df_sample.head(5), use_container_width=True, height=200)

        # 주요 통계
        col1, col2, col3 = st.columns(3)

        with col1:
            if "출고일" in df_sample.columns:
                dates = pd.to_datetime(df_sample["출고일"], errors="coerce")
                unique_dates = dates.nunique()
                st.info(f"📅 샘플 날짜 범위: {unique_dates}일")

        with col2:
            if "업체명" in df_sample.columns:
                unique_companies = df_sample["업체명"].nunique()
                st.info(f"🏢 샘플 업체 수: {unique_companies}개")

        with col3:
            if "상품매출" in df_sample.columns:
                total_sales = pd.to_numeric(
                    df_sample["상품매출"], errors="coerce"
                ).sum()
                st.info(f"💰 샘플 매출 합계: ₩{total_sales:,.0f}")


# =============================================================================
# 2025-12-16 hoyeon.han: process_data() 함수 정의
# =============================================================================


def process_data(file_path, source_name, selected_date):
    """
    데이터 처리 함수
    2025-12-22 hoyeon.han: Quick Win #3 - st.status로 진행 상황 개선
    2026-06-03 hoyeon.han: 발주내역 서버 저장 적용
      - uploaded_file 대신 저장된 file_path 사용, 임시 저장/삭제 제거
    """

    # 2025-12-22 hoyeon.han: st.status를 사용한 실시간 진행 상황 표시
    with st.status("⚙️ 전표 생성 중...", expanded=True) as status:
        try:
            # 2026-06-03 hoyeon.han: 발주내역 파일은 이미 서버에 저장됨 (임시 저장 제거)
            # --- 기존 코드 (주석 처리) ---
            # st.write("📤 **STEP 1/5**: 파일 업로드 중...")
            # temp_path = os.path.join("uploads", uploaded_file.name)
            # with open(temp_path, "wb") as f:
            #     f.write(uploaded_file.getvalue())
            # logging.info(
            #     f"파일 업로드: {uploaded_file.name}, 크기: {uploaded_file.size} bytes"
            # )
            # st.write(f"✅ 파일 업로드 완료 ({uploaded_file.size / 1024 / 1024:.2f} MB)")
            # --- 기존 코드 끝 ---
            st.write(f"📂 발주내역 파일: `{source_name}`")
            logging.info(f"발주내역 파일 사용: {source_name} (경로: {file_path})")

            # 2. 날짜 변환
            date_str = selected_date.strftime("%Y-%m-%d")

            # 3. 매출 데이터 처리
            st.write(f"💰 **STEP 1/3**: 매출 데이터 처리 중... (날짜: {date_str})")

            # 2025-12-16 hoyeon.han: use_db=True로 DB 사용 (기본값)
            df_sales = get_sales_daily(file_path, date_str, use_db=True)
            logging.info(f"매출 처리 완료: {len(df_sales)}건")
            st.write(f"✅ 매출 데이터 처리 완료: **{len(df_sales):,}건**")

            # 4. 매입 데이터 처리
            st.write("🛒 **STEP 2/3**: 매입 데이터 처리 중...")

            # 2025-12-16 hoyeon.han: use_db=True로 DB 사용 (기본값)
            df_purchase = get_purchase_daily(file_path, date_str, use_db=True)
            logging.info(f"매입 처리 완료: {len(df_purchase)}건")
            st.write(f"✅ 매입 데이터 처리 완료: **{len(df_purchase):,}건**")

            # 5. 파일 저장
            st.write("💾 **STEP 3/3**: 경리나라 전표 파일 저장 중...")

            sales_filename = f"매출_{date_str}.xls"
            purchase_filename = f"매입_{date_str}.xls"

            sales_filepath = os.path.join("processed", sales_filename)
            purchase_filepath = os.path.join("processed", purchase_filename)

            save_dataframe_to_xls(df_sales, sales_filepath)
            save_dataframe_to_xls(df_purchase, purchase_filepath)
            st.write(f"✅ 파일 저장 완료")
            st.write(f"   - 매출: `{sales_filename}`")
            st.write(f"   - 매입: `{purchase_filename}`")

            # 2026-06-03 hoyeon.han: 임시 파일을 만들지 않으므로 정리 단계 제거
            # --- 기존 코드 (주석 처리) ---
            # st.write("🧹 **STEP 5/5**: 임시 파일 정리 중...")
            # try:
            #     os.remove(temp_path)
            #     st.write("✅ 임시 파일 삭제 완료")
            # except FileNotFoundError:
            #     st.write("⚠️ 임시 파일이 이미 삭제되었습니다")
            # --- 기존 코드 끝 ---

            # 7. 완료
            status.update(label="✅ 전표 생성 완료!", state="complete", expanded=False)

            # 성공 메시지
            st.balloons()
            st.markdown(
                '<div class="success-box">✅ <b>처리가 완료되었습니다!</b></div>',
                unsafe_allow_html=True,
            )

            # 2025-12-16 hoyeon.han: 처리 결과를 Session State에 저장
            st.session_state.last_result = {
                "date": date_str,
                "file": source_name,
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

            # 처리 이력 추가
            st.session_state.history.append(
                {
                    "timestamp": datetime.now(),
                    "date": date_str,
                    "file": source_name,
                    "sales_count": len(df_sales),
                    "purchase_count": len(df_purchase),
                }
            )

            # 페이지 리로드
            st.rerun()

        except SollumeBaseException as e:
            # 커스텀 예외 처리
            status.update(label="❌ 처리 실패", state="error", expanded=True)

            # 심각도에 따른 아이콘
            severity_icon = {
                ErrorSeverity.INFO: "ℹ️",
                ErrorSeverity.WARNING: "⚠️",
                ErrorSeverity.ERROR: "❌",
                ErrorSeverity.CRITICAL: "🚨",
            }

            # 사용자 메시지 표시
            st.markdown(
                f'<div class="error-box">'
                f"{severity_icon[e.severity]} <b>{e.category.value}</b><br>"
                f"{e.user_message}"
                f"</div>",
                unsafe_allow_html=True,
            )

            # 해결 방법 안내
            if e.solution_hints:
                st.info("**💡 해결 방법:**")
                for hint in e.solution_hints:
                    st.write(hint)

            # 개발자용 정보
            with st.expander("🔍 개발자용 상세 정보"):
                st.code(f"오류 ID: {e.error_id}")
                st.code(f"발생 시각: {e.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                st.text(e.technical_details)
                if e.context:
                    st.json(e.context)

            # 오류 리포트 다운로드
            error_report = {
                "오류_ID": e.error_id,
                "발생_시각": e.timestamp.isoformat(),
                "카테고리": e.category.value,
                "심각도": e.severity.value,
                "사용자_메시지": e.user_message,
                "기술_상세": e.technical_details,
                "해결_힌트": e.solution_hints,
                "컨텍스트": e.context,
                "파일명": source_name if source_name else "N/A",
                "선택_날짜": date_str,
            }

            st.download_button(
                label="📥 오류 리포트 다운로드 (개발자 전달용)",
                data=json.dumps(error_report, ensure_ascii=False, indent=2),
                file_name=f"error_report_{e.error_id}.json",
                mime="application/json",
            )

            st.warning(
                f"⚠️ 문제가 계속되면 **오류 ID: `{e.error_id}`** 를 "
                f"개발자에게 알려주세요."
            )

            # 로거에 기록
            logger = get_logger()
            logger.log_custom_exception(e)

        except Exception as e:
            # 예상치 못한 오류
            status.update(label="🚨 예상치 못한 오류", state="error", expanded=True)

            st.markdown(
                '<div class="error-box">🚨 <b>예상치 못한 오류가 발생했습니다</b></div>',
                unsafe_allow_html=True,
            )

            with st.expander("🔍 에러 상세 정보 (개발자에게 전달)"):
                st.exception(e)

            logging.error(f"처리 실패: {str(e)}", exc_info=True)


# =============================================================================
# Section 1: 파일 업로드 및 처리
# =============================================================================


def upload_and_process_section():
    """파일 업로드 및 처리 섹션"""

    st.markdown(
        '<div class="section-header">1️⃣ 파일 업로드 및 처리</div>',
        unsafe_allow_html=True,
    )

    # 2026-06-03 hoyeon.han: 발주내역 파일 서버 저장/재사용 컴포넌트 적용
    # 기존 file_uploader(col1)를 공통 컴포넌트로 대체 (1번은 시트 고정이라 sheet_select=False)
    # --- 기존 코드 (주석 처리) ---
    # col1, col2, col3 = st.columns([3, 2, 1])
    #
    # with col1:
    #     uploaded_file = st.file_uploader(
    #         "📁 발주내역 파일 선택 (.xlsm)",
    #         type=["xlsm"],
    #         help="솔루미랩 발주내역 파일을 선택하세요. (누적)2025년 발주내역 시트가 포함되어야 합니다.",
    #         key="main_uploader",
    #     )
    # --- 기존 코드 끝 ---
    order_file = render_order_file_selector("daily", sheet_select=False)

    col2, col3 = st.columns([2, 1])

    with col2:
        selected_date = st.date_input(
            "📅 처리 날짜",
            value=datetime.today(),
            max_value=datetime.today(),
            help="전표를 생성할 날짜를 선택하세요",
            key="date_selector",
        )

    with col3:
        st.write("")
        st.write("")
        process_button = st.button(
            "▶️ 처리", type="primary", use_container_width=True, key="process_button"
        )

    # 2025-12-22 hoyeon.han: Quick Win #5 - 파일 검증
    # 2026-06-03 hoyeon.han: 저장된 파일 경로 기반으로 검증
    if order_file:
        with st.expander("🔍 파일 검증", expanded=True):
            validate_uploaded_file(order_file["file_path"])

    if process_button:
        if not order_file:
            st.error("⚠️ 파일을 먼저 선택해주세요.")
        else:
            process_data(
                order_file["file_path"], order_file["display_name"], selected_date
            )

    st.divider()


# =============================================================================
# Section 2: 처리 결과
# =============================================================================


def result_section():
    """처리 결과 표시 섹션"""

    result = st.session_state.last_result

    st.markdown('<div class="section-header">2️⃣ 처리 결과</div>', unsafe_allow_html=True)

    # 2025-12-22 hoyeon.han: Quick Win #2 - 개선된 메트릭 카드
    st.success(
        f"✅ 처리 완료! ({result['date']}) | "
        f"파일: {result['file']} | "
        f"매출 {result['sales_count']}건, 매입 {result['purchase_count']}건"
    )

    # 메트릭 표시 - 1행: 기본 정보
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📅 처리 날짜", result["date"])
    with col2:
        st.metric("💰 매출 건수", f"{result['sales_count']:,}건")
    with col3:
        st.metric("🛒 매입 건수", f"{result['purchase_count']:,}건")
    with col4:
        st.metric("⏰ 처리 시각", result["timestamp"].strftime("%H:%M:%S"))

    # 메트릭 표시 - 2행: 금액 및 검증 정보
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        # 매출 총액 계산
        total_sales_amount = (
            result["df_sales"]["공급가액"].sum()
            if "공급가액" in result["df_sales"].columns
            else 0
        )
        st.metric(
            "💵 매출 총액",
            f"₩{total_sales_amount:,.0f}",
            help="부가세 제외 공급가액 합계",
        )

    with col2:
        # 매입 총액 계산
        total_purchase_amount = (
            result["df_purchase"]["공급가액"].sum()
            if "공급가액" in result["df_purchase"].columns
            else 0
        )
        st.metric(
            "💸 매입 총액",
            f"₩{total_purchase_amount:,.0f}",
            help="부가세 제외 공급가액 합계",
        )

    with col3:
        # 사업자번호 누락 건수 (매출+매입)
        missing_sales = (
            result["df_sales"]["사업자번호"].isna().sum()
            if "사업자번호" in result["df_sales"].columns
            else 0
        )
        missing_purchase = (
            result["df_purchase"]["사업자번호"].isna().sum()
            if "사업자번호" in result["df_purchase"].columns
            else 0
        )
        total_missing = missing_sales + missing_purchase

        st.metric(
            "⚠️ 사업자번호 누락",
            f"{total_missing}건",
            delta=f"-{total_missing}건" if total_missing > 0 else "정상",
            delta_color="inverse" if total_missing > 0 else "normal",
            help="경리나라 업로드 시 오류 발생 가능",
        )

    with col4:
        # 데이터 검증 상태
        validation_status = "✅ 정상" if total_missing == 0 else f"⚠️ 확인 필요"
        validation_color = "normal" if total_missing == 0 else "inverse"

        st.metric(
            "🔍 검증 상태",
            validation_status,
            delta=f"{result['sales_count'] + result['purchase_count']:,}건 검증",
            delta_color=validation_color,
            help="모든 필수 항목 검증 완료 여부",
        )

    # 탭으로 데이터 표시
    tab1, tab2 = st.tabs(["💰 매출 데이터", "🛒 매입 데이터"])

    with tab1:
        st.info(f"총 {result['sales_count']}건의 매출 데이터가 처리되었습니다.")
        st.dataframe(result["df_sales"].head(20), use_container_width=True, height=300)

    with tab2:
        st.info(f"총 {result['purchase_count']}건의 매입 데이터가 처리되었습니다.")
        st.dataframe(
            result["df_purchase"].head(20), use_container_width=True, height=300
        )

    st.markdown(
        '<div class="info-box">'
        "💡 <b>동일 파일로 다른 날짜를 처리하려면 위로 스크롤하여 날짜를 변경하세요!</b><br>"
        "파일은 자동으로 유지되므로 재업로드가 필요 없습니다."
        "</div>",
        unsafe_allow_html=True,
    )

    st.divider()


# =============================================================================
# Section 3: 이번 세션 처리 이력
# =============================================================================


def session_history_section():
    """이번 세션 처리 이력 섹션"""

    if st.session_state.history:
        st.markdown(f"**총 {len(st.session_state.history)}건 처리됨**")

        for idx, item in enumerate(reversed(st.session_state.history), 1):
            col1, col2, col3, col4 = st.columns([1, 2, 1, 1])

            with col1:
                st.write(f"**#{idx}**")
            with col2:
                st.write(f"📅 {item['date']}")
            with col3:
                st.write(f"💰 {item['sales_count']}건")
            with col4:
                st.write(f"🛒 {item['purchase_count']}건")

            st.caption(f"{item['timestamp'].strftime('%H:%M:%S')} | {item['file']}")

            if idx < len(st.session_state.history):
                st.divider()
    else:
        st.info("아직 처리한 내역이 없습니다.")


# =============================================================================
# 메인 실행
# 2025-04-13 hoyeon.han: 1:2 레이아웃으로 변경 (제어:결과 = 1:2)
# =============================================================================

# 메인 영역 1:2 분할
control_col, result_col = st.columns([1, 2], gap="medium")

# ========== LEFT: 제어 패널 (1/3) ==========
with control_col:
    # 파일 업로드 및 처리
    upload_and_process_section()

    # 다운로드 버튼 (결과 있을 때만 표시)
    if st.session_state.last_result:
        result = st.session_state.last_result
        st.divider()
        st.markdown("### 📥 다운로드")
        with st.container(border=True):
            with open(result["sales_filepath"], "rb") as f:
                st.download_button(
                    label="💰 매출 파일",
                    data=f.read(),
                    file_name=result["sales_filename"],
                    mime="application/vnd.ms-excel",
                    type="primary",
                    use_container_width=True,
                    key="download_sales_main",
                )
            with open(result["purchase_filepath"], "rb") as f:
                st.download_button(
                    label="🛒 매입 파일",
                    data=f.read(),
                    file_name=result["purchase_filename"],
                    mime="application/vnd.ms-excel",
                    type="primary",
                    use_container_width=True,
                    key="download_purchase_main",
                )

    # 처리 이력
    with st.expander("📜 이번 세션 처리 이력", expanded=False):
        session_history_section()

    # 시스템 관리 페이지 안내
    st.divider()
    st.info("📂 파일 목록, 로그 확인은 **⚙️ 시스템 관리** 페이지에서")
    if st.button("⚙️ 시스템 관리로 이동", use_container_width=True, key="goto_settings"):
        st.switch_page("pages/6_⚙️_시스템관리.py")

# ========== RIGHT: 결과 패널 (2/3) ==========
with result_col:
    # 처리 결과 (조걶� 표시)
    if st.session_state.last_result:
        result_section()
    else:
        # 결과 없을 때 안내 메시지
        st.info(
            "👈 좌측에서 파일을 업로드하고 처리 버튼을 클릭하세요.\n\n"
            "처리 결과가 여기에 표시됩니다."
        )

# 푸터
st.divider()
st.caption("© 2025 솔루미랩 | v3.0.0")
