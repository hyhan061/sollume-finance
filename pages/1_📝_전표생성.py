"""
솔루미랩 경리나라 전표 생성 페이지
매출/매입 전표 날짜별 일괄등록 파일 생성
2025-12-16 hoyeon.han: app.py.backup의 tab1 내용을 별도 페이지로 분리
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

# 전표 생성 모듈
from processing import get_sales_daily, get_purchase_daily, save_dataframe_to_xls

# 커스텀 예외 및 로거
from Src.exceptions import (
    SollumeBaseException,
    ErrorSeverity,
    MasterFileNotFoundError,
    SheetNotFoundError,
    NoDataForDateError
)
from Src.logger import get_logger

# 디렉토리 생성
os.makedirs("logs", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("processed", exist_ok=True)

# 페이지 설정
st.set_page_config(
    page_title="전표 생성",
    page_icon="📝",
    layout="wide"
)

# =============================================================================
# 2025-12-16 hoyeon.han: Session State 초기화
# =============================================================================

if 'history' not in st.session_state:
    st.session_state.history = []

if 'last_result' not in st.session_state:
    st.session_state.last_result = None

# CSS 스타일
st.markdown("""
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
    .success-box {
        padding: 1rem;
        background-color: #d4edda;
        border-left: 4px solid #28a745;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .error-box {
        padding: 1rem;
        background-color: #f8d7da;
        border-left: 4px solid #dc3545;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .info-box {
        padding: 1rem;
        background-color: #d1ecf1;
        border-left: 4px solid #17a2b8;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .warning-box {
        padding: 1rem;
        background-color: #fff3cd;
        border-left: 4px solid #ffc107;
        border-radius: 4px;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# 페이지 타이틀
# =============================================================================

st.markdown('<div class="main-header">📝 전표 생성</div>', unsafe_allow_html=True)
st.caption("발주내역 파일에서 경리나라 전표 파일을 생성합니다.")

st.divider()

# =============================================================================
# 2025-12-16 hoyeon.han: process_data() 함수 정의
# =============================================================================

def process_data(uploaded_file, selected_date):
    """데이터 처리 함수"""

    # 진행상황 표시
    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        # 1. 임시 파일 저장
        status_text.text("📤 파일 업로드 중...")
        progress_bar.progress(10)

        temp_path = os.path.join("uploads", uploaded_file.name)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.read())

        logging.info(f"파일 업로드: {uploaded_file.name}, 크기: {uploaded_file.size} bytes")

        # 2. 날짜 변환
        date_str = selected_date.strftime('%Y-%m-%d')

        # 3. 매출 데이터 처리
        status_text.text("💰 매출 데이터 처리 중...")
        progress_bar.progress(30)

        df_sales = get_sales_daily(temp_path, date_str, master_file_path="Src/거래처마스터.xlsx")
        logging.info(f"매출 처리 완료: {len(df_sales)}건")

        # 4. 매입 데이터 처리
        status_text.text("🛒 매입 데이터 처리 중...")
        progress_bar.progress(60)

        df_purchase = get_purchase_daily(temp_path, date_str, master_file_path="Src/거래처마스터.xlsx")
        logging.info(f"매입 처리 완료: {len(df_purchase)}건")

        # 5. 파일 저장
        status_text.text("💾 파일 저장 중...")
        progress_bar.progress(80)

        sales_filename = f"매출_{date_str}.xls"
        purchase_filename = f"매입_{date_str}.xls"

        sales_filepath = os.path.join("processed", sales_filename)
        purchase_filepath = os.path.join("processed", purchase_filename)

        save_dataframe_to_xls(df_sales, sales_filepath)
        save_dataframe_to_xls(df_purchase, purchase_filepath)

        # 6. 임시 파일 삭제
        os.remove(temp_path)

        # 7. 완료
        progress_bar.progress(100)
        status_text.text("✅ 처리 완료!")

        # 성공 메시지
        st.balloons()
        st.markdown('<div class="success-box">✅ <b>처리가 완료되었습니다!</b></div>', unsafe_allow_html=True)

        # 2025-12-16 hoyeon.han: 처리 결과를 Session State에 저장
        st.session_state.last_result = {
            'date': date_str,
            'file': uploaded_file.name,
            'sales_count': len(df_sales),
            'purchase_count': len(df_purchase),
            'df_sales': df_sales,
            'df_purchase': df_purchase,
            'sales_filename': sales_filename,
            'purchase_filename': purchase_filename,
            'sales_filepath': sales_filepath,
            'purchase_filepath': purchase_filepath,
            'timestamp': datetime.now()
        }

        # 처리 이력 추가
        st.session_state.history.append({
            'timestamp': datetime.now(),
            'date': date_str,
            'file': uploaded_file.name,
            'sales_count': len(df_sales),
            'purchase_count': len(df_purchase)
        })

        # 페이지 리로드
        st.rerun()

    except SollumeBaseException as e:
        # 커스텀 예외 처리
        progress_bar.empty()
        status_text.empty()

        # 심각도에 따른 아이콘
        severity_icon = {
            ErrorSeverity.INFO: "ℹ️",
            ErrorSeverity.WARNING: "⚠️",
            ErrorSeverity.ERROR: "❌",
            ErrorSeverity.CRITICAL: "🚨"
        }

        # 사용자 메시지 표시
        st.markdown(
            f'<div class="error-box">'
            f'{severity_icon[e.severity]} <b>{e.category.value}</b><br>'
            f'{e.user_message}'
            f'</div>',
            unsafe_allow_html=True
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
            "파일명": uploaded_file.name if uploaded_file else "N/A",
            "선택_날짜": date_str,
        }

        st.download_button(
            label="📥 오류 리포트 다운로드 (개발자 전달용)",
            data=json.dumps(error_report, ensure_ascii=False, indent=2),
            file_name=f"error_report_{e.error_id}.json",
            mime="application/json"
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
        progress_bar.empty()
        status_text.empty()

        st.markdown(
            '<div class="error-box">🚨 <b>예상치 못한 오류가 발생했습니다</b></div>',
            unsafe_allow_html=True
        )

        with st.expander("🔍 에러 상세 정보 (개발자에게 전달)"):
            st.exception(e)

        logging.error(f"처리 실패: {str(e)}", exc_info=True)

# =============================================================================
# Section 1: 파일 업로드 및 처리
# =============================================================================

def upload_and_process_section():
    """파일 업로드 및 처리 섹션"""

    st.markdown('<div class="section-header">1️⃣ 파일 업로드 및 처리</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([3, 2, 1])

    with col1:
        uploaded_file = st.file_uploader(
            "📁 발주내역 파일 선택 (.xlsm)",
            type=['xlsm'],
            help="솔루미랩 발주내역 파일을 선택하세요. (누적)2025년 발주내역 시트가 포함되어야 합니다.",
            key="main_uploader"
        )

    with col2:
        selected_date = st.date_input(
            "📅 처리 날짜",
            value=datetime.today(),
            max_value=datetime.today(),
            help="전표를 생성할 날짜를 선택하세요",
            key="date_selector"
        )

    with col3:
        st.write("")
        st.write("")
        process_button = st.button(
            "▶️ 처리",
            type="primary",
            use_container_width=True,
            key="process_button"
        )

    if uploaded_file:
        st.info(
            f"📎 선택된 파일: **{uploaded_file.name}** "
            f"({uploaded_file.size / 1024 / 1024:.2f} MB)"
        )

    if process_button:
        if not uploaded_file:
            st.error("⚠️ 파일을 먼저 선택해주세요.")
        else:
            process_data(uploaded_file, selected_date)

    st.divider()

# =============================================================================
# Section 2: 처리 결과
# =============================================================================

def result_section():
    """처리 결과 표시 섹션"""

    result = st.session_state.last_result

    st.markdown('<div class="section-header">2️⃣ 처리 결과</div>', unsafe_allow_html=True)

    st.success(
        f"✅ 처리 완료! ({result['date']}) | "
        f"파일: {result['file']} | "
        f"매출 {result['sales_count']}건, 매입 {result['purchase_count']}건"
    )

    # 메트릭 표시
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("처리 날짜", result['date'])
    with col2:
        st.metric("매출 건수", result['sales_count'])
    with col3:
        st.metric("매입 건수", result['purchase_count'])
    with col4:
        st.metric("처리 시각", result['timestamp'].strftime('%H:%M:%S'))

    # 탭으로 데이터 표시
    tab1, tab2 = st.tabs(["💰 매출 데이터", "🛒 매입 데이터"])

    with tab1:
        st.info(f"총 {result['sales_count']}건의 매출 데이터가 처리되었습니다.")
        st.dataframe(
            result['df_sales'].head(20),
            use_container_width=True,
            height=300
        )

        with open(result['sales_filepath'], "rb") as f:
            st.download_button(
                label="📥 매출 파일 다운로드",
                data=f.read(),
                file_name=result['sales_filename'],
                mime="application/vnd.ms-excel",
                type="primary",
                use_container_width=True,
                key="download_sales"
            )

    with tab2:
        st.info(f"총 {result['purchase_count']}건의 매입 데이터가 처리되었습니다.")
        st.dataframe(
            result['df_purchase'].head(20),
            use_container_width=True,
            height=300
        )

        with open(result['purchase_filepath'], "rb") as f:
            st.download_button(
                label="📥 매입 파일 다운로드",
                data=f.read(),
                file_name=result['purchase_filename'],
                mime="application/vnd.ms-excel",
                type="primary",
                use_container_width=True,
                key="download_purchase"
            )

    st.markdown(
        '<div class="info-box">'
        '💡 <b>동일 파일로 다른 날짜를 처리하려면 위로 스크롤하여 날짜를 변경하세요!</b><br>'
        '파일은 자동으로 유지되므로 재업로드가 필요 없습니다.'
        '</div>',
        unsafe_allow_html=True
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

            st.caption(
                f"{item['timestamp'].strftime('%H:%M:%S')} | "
                f"{item['file']}"
            )

            if idx < len(st.session_state.history):
                st.divider()
    else:
        st.info("아직 처리한 내역이 없습니다.")

# =============================================================================
# Section 4: 저장된 파일 목록
# =============================================================================

def file_list_section():
    """저장된 파일 목록 섹션"""

    processed_files = sorted(
        os.listdir("processed"),
        reverse=True
    ) if os.path.exists("processed") else []

    if processed_files:
        files_by_date = {}
        for filename in processed_files:
            try:
                date_part = filename.split('_')[1].replace('.xls', '')
                if date_part not in files_by_date:
                    files_by_date[date_part] = []
                files_by_date[date_part].append(filename)
            except:
                continue

        for date, files in sorted(files_by_date.items(), reverse=True):
            st.markdown(f"### 📅 {date} ({len(files)}개 파일)")

            for filename in files:
                filepath = os.path.join("processed", filename)
                file_size = os.path.getsize(filepath) / 1024
                file_time = datetime.fromtimestamp(os.path.getmtime(filepath))

                col1, col2 = st.columns([4, 1])

                with col1:
                    st.write(f"**{filename}**")
                    st.caption(f"{file_size:.1f} KB | {file_time.strftime('%Y-%m-%d %H:%M:%S')}")

                with col2:
                    with open(filepath, "rb") as f:
                        st.download_button(
                            label="⬇️",
                            data=f.read(),
                            file_name=filename,
                            mime="application/vnd.ms-excel",
                            key=f"dl_{filename}_{date}"
                        )

            st.divider()
    else:
        st.info("저장된 파일이 없습니다.")

# =============================================================================
# Section 5: 로그 뷰어
# =============================================================================

def log_viewer_section():
    """로그 뷰어 섹션"""

    if os.path.exists("logs/app.log"):
        with open("logs/app.log", "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-50:]

        st.text_area(
            "최근 로그 (50줄)",
            value="".join(recent_lines),
            height=300,
            label_visibility="collapsed"
        )

        with open("logs/app.log", "rb") as f:
            st.download_button(
                label="📥 전체 로그 다운로드",
                data=f.read(),
                file_name=f"app_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
                mime="text/plain",
                key="download_log"
            )
    else:
        st.info("아직 로그가 없습니다.")

# =============================================================================
# Section 6: 시스템 설정
# =============================================================================

def settings_section():
    """시스템 설정 및 관리 섹션"""

    st.markdown("#### 📋 거래처마스터 파일")
    master_file = "Src/거래처마스터.xlsx"

    if os.path.exists(master_file):
        file_size = os.path.getsize(master_file) / 1024
        file_time = datetime.fromtimestamp(os.path.getmtime(master_file))

        st.success(f"✓ 파일 존재: {master_file}")
        st.caption(
            f"{file_size:.1f} KB | "
            f"최종 수정: {file_time.strftime('%Y-%m-%d %H:%M')}"
        )
    else:
        st.error(f"✗ 파일이 존재하지 않습니다: {master_file}")

    st.divider()

    st.markdown("#### 💾 디스크 사용량")

    def get_folder_size(folder):
        if not os.path.exists(folder):
            return 0
        total = 0
        for entry in os.scandir(folder):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_folder_size(entry.path)
        return total

    uploads_size = get_folder_size("uploads") / 1024 / 1024
    processed_size = get_folder_size("processed") / 1024 / 1024
    logs_size = get_folder_size("logs") / 1024 / 1024

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("업로드 폴더", f"{uploads_size:.2f} MB")
    with col2:
        st.metric("처리 폴더", f"{processed_size:.2f} MB")
    with col3:
        st.metric("로그 폴더", f"{logs_size:.2f} MB")

    st.divider()

    st.markdown("#### 🧹 데이터 정리")
    st.warning("⚠️ 아래 작업은 되돌릴 수 없습니다. 신중하게 선택하세요.")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🗑️ 업로드 파일 삭제", type="secondary", key="del_uploads"):
            if os.path.exists("uploads"):
                for file in os.listdir("uploads"):
                    os.remove(os.path.join("uploads", file))
                st.success("삭제 완료!")
                st.rerun()

    with col2:
        if st.button("🗑️ 처리된 파일 삭제", type="secondary", key="del_processed"):
            if os.path.exists("processed"):
                for file in os.listdir("processed"):
                    os.remove(os.path.join("processed", file))
                st.success("삭제 완료!")
                st.rerun()

    with col3:
        if st.button("🗑️ 로그 파일 삭제", type="secondary", key="del_logs"):
            if os.path.exists("logs/app.log"):
                os.remove("logs/app.log")
                st.success("삭제 완료!")
                st.rerun()

# =============================================================================
# 메인 실행
# 2025-12-16 hoyeon.han: 단일 페이지에 모든 섹션 렌더링
# =============================================================================

# Section 1: 파일 업로드 및 처리
upload_and_process_section()

# Section 2: 처리 결과 (조건부 표시)
if st.session_state.last_result:
    result_section()

# Section 3-6: Expander로 접을 수 있게 구성
with st.expander("📜 이번 세션 처리 이력", expanded=False):
    session_history_section()

with st.expander("📁 저장된 파일 목록", expanded=False):
    file_list_section()

with st.expander("🔍 최근 로그 (문제 해결용)", expanded=False):
    log_viewer_section()

with st.expander("⚙️ 시스템 설정 및 관리", expanded=False):
    settings_section()

# 푸터
st.divider()
st.caption("© 2025 솔루미랩 | v3.0.0")
