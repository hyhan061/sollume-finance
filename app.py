"""
솔루미랩 경리나라 전표 생성 Streamlit 앱
매출/매입 전표 날짜별 일괄등록 파일 생성
2025-12-09 hoyeon.han: 단일 페이지 레이아웃으로 재설계 (페이지 전환 없이 모든 기능 통합)
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
sys.path.insert(0, str(Path(__file__).parent / "Src"))

# 2025-12-10 hoyeon.han: 기존 전표 생성 모듈
from processing import get_sales_daily, get_purchase_daily, save_dataframe_to_xls

# 2025-12-10 hoyeon.han: 발주내역 기간별 요약 모듈 추가
from Src.period_summary import process_period_summary

# 2025-11-29 hoyeon.han: Phase 2 - 커스텀 예외 및 로거 import
from Src.exceptions import (
    SollumeBaseException,
    ErrorSeverity,
    MasterFileNotFoundError,
    SheetNotFoundError,
    NoDataForDateError
)
from Src.logger import get_logger

# 로깅 설정
logging.basicConfig(
    filename='logs/app.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# 디렉토리 생성
os.makedirs("logs", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("processed", exist_ok=True)

# 페이지 설정
st.set_page_config(
    page_title="경리나라 전표 생성",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =============================================================================
# 2025-12-09 hoyeon.han: Session State 초기화
# Session State란? Streamlit에서 페이지 새로고침 후에도 데이터를 유지하는 메커니즘
# 일반 변수는 페이지가 다시 실행되면 초기화되지만, session_state는 유지됨
# =============================================================================

# 처리 이력을 저장할 리스트 초기화
# 'history'라는 키가 session_state에 없으면 빈 리스트 생성
# 이미 있으면 기존 값 유지 (페이지 새로고침해도 이력 유지)
if 'history' not in st.session_state:
    st.session_state.history = []  # 빈 리스트로 시작

# 마지막 처리 결과를 저장할 변수 초기화
# 처리가 완료되면 이 변수에 결과 딕셔너리가 저장됨
# None이면 아직 처리한 결과가 없다는 의미
if 'last_result' not in st.session_state:
    st.session_state.last_result = None  # 초기값은 None (비어있음)

# CSS 커스터마이징
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

# 사이드바 - 시스템 정보만 표시
with st.sidebar:
    st.markdown("### 📊 SollumeLab")
    st.title("시스템 정보")

    # 마스터 파일 체크
    master_file = "Src/거래처마스터.xlsx"
    if os.path.exists(master_file):
        st.success("✓ 거래처마스터 파일 존재")
        file_time = datetime.fromtimestamp(os.path.getmtime(master_file))
        st.caption(f"최종 수정: {file_time.strftime('%Y-%m-%d %H:%M')}")
    else:
        st.error("✗ 거래처마스터 파일 없음")

    # 오늘 처리 건수
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_files = [f for f in os.listdir("processed") if today_str in f] if os.path.exists("processed") else []
    st.metric("오늘 처리 건수", len(today_files))

    st.divider()

    # 도움말
    with st.expander("❓ 도움말"):
        st.markdown("""
        **사용 방법:**
        1. 발주내역 파일(.xlsm) 선택
        2. 처리할 날짜 선택
        3. '처리 실행' 버튼 클릭
        4. 결과 확인 및 파일 다운로드

        **장점:**
        - 페이지 이동 없이 모든 작업 완료
        - 동일 파일로 여러 날짜 처리 가능
        - 스크롤만으로 모든 정보 확인

        **문제 발생 시:**
        - 아래 '최근 로그' 섹션에서 확인
        - 스크린샷을 찍어 개발자에게 전달
        """)

# =============================================================================
# 메인 페이지: 단일 페이지에 모든 섹션 통합
# =============================================================================

st.markdown('<div class="main-header">📊 경리나라 전표 생성 시스템</div>', unsafe_allow_html=True)
st.caption("💡 탭을 선택하여 원하는 기능을 사용하세요!")

st.divider()

# =============================================================================
# 2025-12-10 hoyeon.han: 탭 구조로 변경
# st.tabs(): 여러 탭을 생성하는 Streamlit 함수
# 반환값은 탭 객체들의 리스트 (각 탭에 컨텐츠를 추가할 수 있음)
# =============================================================================

# 탭 생성
# 탭 제목 리스트를 전달하면, 각 탭 객체가 반환됩니다
tab1, tab2 = st.tabs([
    "📝 전표 생성",           # 첫 번째 탭: 기존 기능 (일자별 전표 생성)
    "📊 발주내역 요약"  # 두 번째 탭: 신규 기능 (기간별 요약)
])

# =============================================================================
# 탭 1: 전표 생성 (기존 기능)
# =============================================================================

# with 문: 컨텍스트 관리자
# with tab1: 블록 안의 모든 코드는 tab1 탭에 표시됩니다
with tab1:
    # 원래 메인 페이지 내용을 함수로 래핑

    def upload_and_process_section():
        """
        2025-12-09 hoyeon.han: Section 1 - 파일 업로드 및 처리

        기능 설명:
    - 사용자가 발주내역 .xlsm 파일을 선택합니다
    - 처리할 날짜를 선택합니다
    - '처리' 버튼을 클릭하면 매출/매입 전표를 생성합니다

    기술 설명:
    - st.file_uploader(): Streamlit의 파일 업로드 위젯
    - st.date_input(): 날짜 선택 위젯
    - st.button(): 클릭 가능한 버튼 위젯
    - st.columns(): 화면을 여러 열로 나누는 레이아웃 함수
    """

    st.markdown('<div class="section-header">1️⃣ 파일 업로드 및 처리</div>', unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 화면을 3개의 열로 나눔 (비율 3:2:1)
    # col1 (가장 넓음): 파일 업로드
    # col2 (중간): 날짜 선택
    # col3 (가장 좁음): 처리 버튼
    # -------------------------------------------------------------------------
    col1, col2, col3 = st.columns([3, 2, 1])

    # 첫 번째 열: 파일 업로드 위젯
    with col1:
        # st.file_uploader(): 파일 선택 위젯
        # 반환값은 업로드된 파일 객체 (선택 안하면 None)
        uploaded_file = st.file_uploader(
            "📁 발주내역 파일 선택 (.xlsm)",  # 위젯 제목
            type=['xlsm'],  # 허용할 파일 확장자 (xlsm만 가능)
            help="솔루미랩 발주내역 파일을 선택하세요. (누적)2025년 발주내역 시트가 포함되어야 합니다.",  # 물음표 아이콘에 마우스 올리면 표시
            key="main_uploader"  # Streamlit 내부에서 이 위젯을 식별하는 고유 키
        )

    # 두 번째 열: 날짜 선택 위젯
    with col2:
        # st.date_input(): 달력 형태의 날짜 선택 위젯
        # 반환값은 선택된 날짜 객체 (datetime.date)
        selected_date = st.date_input(
            "📅 처리 날짜",  # 위젯 제목
            value=datetime.today(),  # 기본값: 오늘 날짜
            max_value=datetime.today(),  # 최대값: 오늘까지만 선택 가능 (미래 날짜 선택 방지)
            help="전표를 생성할 날짜를 선택하세요",  # 도움말
            key="date_selector"  # 고유 키
        )

    # 세 번째 열: 처리 버튼
    with col3:
        # 위젯 높이를 맞추기 위한 공백 추가
        st.write("")  # 빈 줄 추가 (버튼이 다른 위젯과 수직으로 정렬되도록)
        st.write("")  # 빈 줄 하나 더 추가

        # st.button(): 클릭 가능한 버튼
        # 반환값: 버튼이 클릭되면 True, 아니면 False
        process_button = st.button(
            "▶️ 처리",  # 버튼 텍스트
            type="primary",  # 버튼 스타일 (파란색 강조 버튼)
            use_container_width=True,  # 열의 전체 너비 사용
            key="process_button"  # 고유 키
        )

    # 파일 정보 표시
    if uploaded_file:
        st.info(
            f"📎 선택된 파일: **{uploaded_file.name}** "
            f"({uploaded_file.size / 1024 / 1024:.2f} MB)"
        )

    # 처리 로직
    if process_button:
        if not uploaded_file:
            st.error("⚠️ 파일을 먼저 선택해주세요.")
        else:
            process_data(uploaded_file, selected_date)

    st.divider()

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

        # =================================================================
        # 2025-12-09 hoyeon.han: 처리 결과를 Session State에 저장
        # 왜 저장하나? 페이지가 다시 실행되어도 결과를 표시하기 위해
        # 딕셔너리(dictionary) 형태로 여러 정보를 하나로 묶어서 저장
        # =================================================================

        st.session_state.last_result = {
            # 처리한 날짜 (예: "2025-12-09")
            'date': date_str,

            # 업로드한 파일 이름 (예: "발주내역_2025.xlsm")
            'file': uploaded_file.name,

            # 처리된 매출 데이터 건수 (예: 42건)
            'sales_count': len(df_sales),

            # 처리된 매입 데이터 건수 (예: 38건)
            'purchase_count': len(df_purchase),

            # 실제 매출 데이터 전체 (pandas DataFrame 객체)
            # DataFrame은 엑셀처럼 행과 열로 구성된 표 형태의 데이터
            'df_sales': df_sales,

            # 실제 매입 데이터 전체 (pandas DataFrame 객체)
            'df_purchase': df_purchase,

            # 저장된 매출 파일 이름 (예: "매출_2025-12-09.xls")
            'sales_filename': sales_filename,

            # 저장된 매입 파일 이름 (예: "매입_2025-12-09.xls")
            'purchase_filename': purchase_filename,

            # 매출 파일의 전체 경로 (예: "processed/매출_2025-12-09.xls")
            'sales_filepath': sales_filepath,

            # 매입 파일의 전체 경로 (예: "processed/매입_2025-12-09.xls")
            'purchase_filepath': purchase_filepath,

            # 처리가 완료된 시각 (datetime 객체, 예: 2025-12-09 14:35:22)
            'timestamp': datetime.now()
        }

        # =================================================================
        # 처리 이력을 history 리스트에 추가
        # append()는 리스트의 끝에 새 항목을 추가하는 함수
        # 이력 목록에 표시할 요약 정보만 저장 (전체 데이터는 last_result에만)
        # =================================================================

        st.session_state.history.append({
            # 처리 시각 (나중에 역순 정렬하여 최신 항목이 위에 표시됨)
            'timestamp': datetime.now(),

            # 처리 날짜
            'date': date_str,

            # 파일 이름
            'file': uploaded_file.name,

            # 매출 건수
            'sales_count': len(df_sales),

            # 매입 건수
            'purchase_count': len(df_purchase)
        })

        # 페이지 리로드하여 결과 섹션 표시
        st.rerun()

    # 2025-11-29 hoyeon.han: Phase 2 - 개선된 예외 처리
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

        # 개발자용 정보 (접을 수 있음)
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

        # 오류 ID 강조
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
# Section 2: 처리 결과 (조건부 표시)
# =============================================================================

def result_section():
    """
    2025-12-09 hoyeon.han: Section 2 - 처리 결과 표시

    기능 설명:
    - 처리가 완료된 후 결과를 화면에 표시합니다
    - 매출/매입 데이터를 테이블 형태로 보여줍니다
    - 생성된 .xls 파일을 다운로드할 수 있습니다

    기술 설명:
    - st.session_state.last_result에서 저장된 결과 딕셔너리를 읽어옵니다
    - st.dataframe()으로 pandas DataFrame을 테이블 형태로 표시
    - st.download_button()으로 파일 다운로드 기능 제공
    - st.tabs()로 매출/매입 데이터를 탭으로 구분하여 표시
    """

    # Session State에서 저장된 처리 결과를 가져옴
    # 이 result는 딕셔너리 형태로, 'date', 'file', 'sales_count' 등의 키를 포함
    result = st.session_state.last_result

    st.markdown('<div class="section-header">2️⃣ 처리 결과</div>', unsafe_allow_html=True)

    # 성공 메시지
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

        # 다운로드 버튼
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

        # 다운로드 버튼
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

    # 안내 메시지
    st.markdown(
        '<div class="info-box">'
        '💡 <b>동일 파일로 다른 날짜를 처리하려면 위로 스크롤하여 날짜를 변경하세요!</b><br>'
        '파일은 자동으로 유지되므로 재업로드가 필요 없습니다.'
        '</div>',
        unsafe_allow_html=True
    )

    st.divider()

# =============================================================================
# Section 3: 이번 세션 처리 이력 (Expander)
# =============================================================================

def session_history_section():
    """
    2025-12-09 hoyeon.han: Section 3 - 이번 세션 처리 이력

    기능 설명:
    - 현재 브라우저 세션에서 처리한 모든 내역을 보여줍니다
    - 최신 항목이 위에 표시됩니다 (역순 정렬)
    - 브라우저를 닫으면 이력이 초기화됩니다

    기술 설명:
    - st.session_state.history 리스트를 역순(reversed)으로 순회
    - enumerate()로 순번을 자동으로 부여
    - st.columns()로 정보를 여러 열에 나누어 표시
    """

    # history 리스트에 항목이 있는지 확인
    # 리스트가 비어있으면 False, 하나라도 있으면 True
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
# Section 4: 저장된 파일 목록 (Expander)
# =============================================================================

def file_list_section():
    """
    2025-12-09 hoyeon.han: Section 4 - 저장된 파일 목록

    기능 설명:
    - processed/ 폴더에 저장된 모든 .xls 파일을 보여줍니다
    - 날짜별로 그룹화하여 Expander로 표시합니다
    - 각 파일의 크기와 생성 시각을 보여줍니다
    - 다운로드 버튼을 제공합니다

    기술 설명:
    - os.listdir()로 폴더의 파일 목록 가져오기
    - sorted()로 파일명 정렬
    - 파일명에서 날짜 추출하여 그룹화 (딕셔너리 사용)
    - 중첩 Expander로 날짜별로 접을 수 있게 구성
    """

    # processed 폴더의 파일 목록 가져오기
    # os.path.exists()로 폴더 존재 여부 확인 후 파일 목록 가져옴
    # 폴더가 없으면 빈 리스트 반환
    processed_files = sorted(
        os.listdir("processed"),  # 폴더의 모든 파일/폴더 이름 목록
        reverse=True  # 역순 정렬 (최신 파일이 위에)
    ) if os.path.exists("processed") else []  # 삼항 연산자

    if processed_files:
        # =================================================================
        # 2025-12-09 hoyeon.han: 중첩 Expander 제거
        # Streamlit에서는 Expander 안에 또 다른 Expander를 넣을 수 없음
        # 대신 날짜를 섹션 헤더로 표시하고, divider로 구분
        # =================================================================

        # 날짜별 그룹화
        files_by_date = {}
        for filename in processed_files:
            try:
                # 파일명에서 날짜 부분 추출 (예: "매출_2025-12-09.xls" -> "2025-12-09")
                date_part = filename.split('_')[1].replace('.xls', '')
                if date_part not in files_by_date:
                    files_by_date[date_part] = []
                files_by_date[date_part].append(filename)
            except:
                # 파일명 형식이 다른 경우 건너뛰기
                continue

        # 날짜별로 표시 (중첩 Expander 대신 섹션 헤더 사용)
        for date, files in sorted(files_by_date.items(), reverse=True):
            # 날짜를 큰 제목으로 표시
            st.markdown(f"### 📅 {date} ({len(files)}개 파일)")

            # 해당 날짜의 파일들을 순회
            for filename in files:
                filepath = os.path.join("processed", filename)
                file_size = os.path.getsize(filepath) / 1024
                file_time = datetime.fromtimestamp(os.path.getmtime(filepath))

                # 두 개의 열로 나누기: 파일 정보 / 다운로드 버튼
                col1, col2 = st.columns([4, 1])

                with col1:
                    st.write(f"**{filename}**")
                    st.caption(f"{file_size:.1f} KB | {file_time.strftime('%Y-%m-%d %H:%M:%S')}")

                with col2:
                    # 파일을 바이너리 모드로 읽어서 다운로드 버튼 제공
                    with open(filepath, "rb") as f:
                        st.download_button(
                            label="⬇️",
                            data=f.read(),
                            file_name=filename,
                            mime="application/vnd.ms-excel",
                            key=f"dl_{filename}_{date}"
                        )

            # 날짜 그룹 사이에 구분선 추가
            st.divider()
    else:
        st.info("저장된 파일이 없습니다.")

# =============================================================================
# Section 5: 로그 뷰어 (Expander)
# =============================================================================

def log_viewer_section():
    """
    2025-12-09 hoyeon.han: Section 5 - 로그 뷰어

    기능 설명:
    - logs/app.log 파일의 최근 50줄을 보여줍니다
    - 에러 발생 시 문제를 파악하는 데 사용합니다
    - 전체 로그 파일을 다운로드할 수 있습니다

    기술 설명:
    - open()으로 파일 읽기
    - readlines()로 모든 줄을 리스트로 가져오기
    - 슬라이싱 [-50:]으로 마지막 50줄만 추출
    - st.text_area()로 텍스트 박스에 표시
    """

    # 로그 파일이 존재하는지 확인
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

        # 전체 로그 다운로드
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
# Section 6: 시스템 설정 (Expander)
# =============================================================================

def settings_section():
    """
    2025-12-09 hoyeon.han: Section 6 - 시스템 설정 및 관리

    기능 설명:
    - 거래처마스터 파일 상태 확인
    - 디스크 사용량 모니터링 (uploads, processed, logs 폴더)
    - 데이터 정리 기능 (파일 삭제)

    기술 설명:
    - os.path.getsize()로 파일 크기 확인
    - os.path.getmtime()로 파일 수정 시각 확인
    - os.scandir()로 폴더 크기 재귀적으로 계산
    - st.button()으로 삭제 기능 제공 (위험한 작업이므로 경고 표시)
    """

    # 거래처마스터 파일 정보 표시
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

    # 디스크 사용량
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

    # 정리 기능
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
# 2025-12-09 hoyeon.han: 메인 실행 - 단일 페이지 레이아웃으로 모든 섹션 렌더링
#
# 이전 버전 (v2.0.1)의 문제점:
# - 3개 페이지로 분리 (전표 생성, 처리 이력, 설정)
# - 페이지 이동 시 업로드한 파일이 사라짐
# - 결과를 보려면 페이지를 왔다갔다 해야 함
#
# 신규 버전 (v2.1.0)의 개선 사항:
# - 모든 기능을 한 페이지에 통합
# - 페이지 이동 없이 스크롤만으로 모든 작업 수행
# - 파일이 자동으로 유지됨 (재업로드 불필요)
# - 처리 후 바로 결과 확인 가능
# =============================================================================

# -----------------------------------------------------------------------------
# Section 1: 파일 업로드 및 처리 (항상 맨 위에 표시)
# -----------------------------------------------------------------------------
# 이 섹션은 항상 표시됩니다.
# 사용자가 파일을 선택하고 날짜를 선택한 후 처리 버튼을 클릭하는 곳입니다.
upload_and_process_section()

# -----------------------------------------------------------------------------
# Section 2: 처리 결과 (조건부 표시)
# -----------------------------------------------------------------------------
# 이 섹션은 처리가 완료된 경우에만 표시됩니다.
# st.session_state.last_result가 None이 아니면 (처리 결과가 있으면) 표시
# 처리 결과가 없으면 이 섹션은 건너뜁니다.
if st.session_state.last_result:
    result_section()

# -----------------------------------------------------------------------------
# Section 3-6: Expander로 접을 수 있게 구성
# -----------------------------------------------------------------------------
# Expander는 클릭하면 펼쳐지고 다시 클릭하면 접히는 UI 컴포넌트입니다.
# expanded=False는 처음에 접힌 상태로 시작한다는 의미입니다.
# 필요할 때만 펼쳐서 보면 되므로 화면이 깔끔합니다.

# Section 3: 이번 세션 처리 이력
# 현재 브라우저 세션에서 처리한 모든 내역을 시간 역순으로 표시
with st.expander("📜 이번 세션 처리 이력", expanded=False):
    session_history_section()

# Section 4: 저장된 파일 목록
# processed/ 폴더에 저장된 모든 .xls 파일을 날짜별로 그룹화하여 표시
with st.expander("📁 저장된 파일 목록", expanded=False):
    file_list_section()

# Section 5: 최근 로그 (문제 해결용)
# logs/app.log 파일의 최근 50줄을 표시 (에러 발생 시 확인용)
with st.expander("🔍 최근 로그 (문제 해결용)", expanded=False):
    log_viewer_section()

    # Section 6: 시스템 설정 및 관리
    # 거래처마스터 파일 정보, 디스크 사용량, 데이터 정리 기능 제공
    with st.expander("⚙️ 시스템 설정 및 관리", expanded=False):
        settings_section()

# =============================================================================
# 탭 2: 발주내역 요약 (신규 기능)
# 2025-12-10 hoyeon.han: 기간별 발주내역 요약 생성 기능 추가
# =============================================================================

with tab2:
    st.markdown('<div class="section-header">📊 발주내역 요약 생성</div>', unsafe_allow_html=True)
    st.caption("특정 기간 동안의 발주내역을 일자별/업체별로 요약하여 Excel 파일로 제공합니다.")

    # =========================================================================
    # Section 1: 파일 업로드 및 시트 선택
    # =========================================================================
    st.markdown("### 📁 1. 발주내역 파일 업로드")

    # 파일 업로드 위젯
    # key를 다르게 설정하여 tab1의 uploader와 구분
    uploaded_file_summary = st.file_uploader(
        "발주내역 Excel 파일을 선택하세요 (.xlsm)",
        type=['xlsm', 'xlsx'],  # .xlsm과 .xlsx 모두 허용
        help="발주내역 데이터가 포함된 Excel 파일을 업로드하세요",
        key="summary_uploader"  # tab1의 "main_uploader"와 다른 고유 키
    )

    # 시트 선택 UI 변수 초기화
    selected_sheet = None

    # 파일이 업로드되면 시트 선택 UI 표시
    if uploaded_file_summary is not None:
        # 파일 선택 성공 메시지
        # .name: 파일명 속성
        # .size: 파일 크기(바이트) 속성
        # / 1024 / 1024: 바이트를 메가바이트로 변환
        # :.2f: 소수점 2자리까지 표시
        st.success(f"✅ 파일 선택됨: {uploaded_file_summary.name} ({uploaded_file_summary.size / 1024 / 1024:.2f} MB)")

        # st.spinner(): 처리 중 표시 (로딩 애니메이션)
        # with 블록이 실행되는 동안 "시트 목록 확인 중..." 메시지와 스피너 표시
        with st.spinner("시트 목록 확인 중..."):
            try:
                # pd.ExcelFile(): Excel 파일 객체 생성
                # 이 객체를 사용하면 시트 목록만 빠르게 가져올 수 있음 (전체 데이터 읽지 않음)
                excel_file = pd.ExcelFile(uploaded_file_summary)

                # .sheet_names: Excel 파일 내 모든 시트 이름 리스트
                sheet_names = excel_file.sheet_names

                # =========================================================
                # 스마트 기본값 찾기
                # "발주내역" 포함 + 현재 연도 포함 시트를 우선 선택
                # =========================================================
                default_index = 0  # 기본값: 첫 번째 시트
                current_year = datetime.now().year  # 현재 연도 (예: 2025)

                # enumerate(): 리스트의 인덱스와 값을 함께 반환
                # 예: enumerate(["A", "B", "C"]) → (0, "A"), (1, "B"), (2, "C")
                for i, sheet in enumerate(sheet_names):
                    # "발주내역"과 현재 연도가 모두 포함된 시트 찾기
                    # in 연산자: 문자열에 특정 문자열이 포함되어 있는지 확인
                    # str(current_year): 숫자를 문자열로 변환 (2025 → "2025")
                    if "발주내역" in sheet and str(current_year) in sheet:
                        default_index = i  # 해당 시트의 인덱스를 기본값으로 설정
                        break  # 찾았으므로 반복문 종료

                # =========================================================
                # 시트 선택 드롭다운
                # =========================================================
                # st.selectbox(): 드롭다운 선택 위젯
                selected_sheet = st.selectbox(
                    "📋 처리할 시트 선택",
                    options=sheet_names,  # 선택 가능한 옵션 리스트
                    index=default_index,  # 기본 선택 인덱스
                    help="발주내역 데이터가 포함된 시트를 선택하세요",
                    key="sheet_selector"  # 고유 키
                )

                # 선택된 시트 정보 표시
                # **텍스트**: Markdown 문법으로 굵게 표시
                st.info(f"📌 선택된 시트: **{selected_sheet}**")

                # =========================================================
                # 시트 미리보기 (접을 수 있는 영역)
                # =========================================================
                # st.expander(): 클릭하면 펼쳐지는 영역
                # expanded=False: 처음에는 접힌 상태
                with st.expander("🔍 시트 미리보기 (상위 5행)"):
                    try:
                        # pd.read_excel()로 실제 데이터 읽기
                        # nrows=5: 상위 5행만 읽기 (전체 데이터를 읽지 않아 빠름)
                        preview_df = pd.read_excel(
                            uploaded_file_summary,
                            sheet_name=selected_sheet,  # 선택된 시트
                            header=3,  # 4번째 줄을 컬럼명으로 사용
                            nrows=5  # 5행만 읽기
                        )

                        # st.dataframe(): DataFrame을 표 형태로 표시
                        # use_container_width=True: 화면 너비에 맞춤
                        st.dataframe(preview_df, use_container_width=True)

                    except Exception as e:
                        # 미리보기 실패 시 경고 메시지 표시
                        # str(e): 예외 객체를 문자열로 변환
                        st.warning(f"미리보기를 불러올 수 없습니다: {str(e)}")

            except Exception as e:
                # 시트 목록 읽기 실패 시
                st.error(f"❌ 시트 목록을 읽을 수 없습니다: {str(e)}")
                st.info("💡 시트명을 직접 입력해주세요")

                # Fallback: 직접 입력
                # st.text_input(): 텍스트 입력 위젯
                selected_sheet = st.text_input(
                    "시트명 입력",
                    value="(누적)2025년 발주내역",  # 기본값
                    help="Excel 파일 내 시트 이름을 정확히 입력하세요",
                    key="sheet_name_input"
                )

    # =========================================================================
    # Section 2: 처리 기간 선택
    # =========================================================================
    st.markdown("### 📅 2. 처리 기간 선택")

    # 화면을 2개의 열로 나누기 (시작일, 종료일)
    col1, col2 = st.columns(2)

    # 첫 번째 열: 시작일
    with col1:
        # 기본값: 30일 전
        # timedelta(days=30): 30일을 나타내는 객체
        # datetime.today() - timedelta(days=30): 오늘로부터 30일 전
        start_date = st.date_input(
            "시작일",
            value=datetime.today() - timedelta(days=30),  # 기본값: 30일 전
            max_value=datetime.today(),  # 최대값: 오늘 (미래 날짜 선택 불가)
            help="요약 처리를 시작할 날짜",
            key="start_date_selector"
        )

    # 두 번째 열: 종료일
    with col2:
        end_date = st.date_input(
            "종료일",
            value=datetime.today(),  # 기본값: 오늘
            max_value=datetime.today(),  # 최대값: 오늘
            help="요약 처리를 종료할 날짜",
            key="end_date_selector"
        )

    # 기간 유효성 검증 및 정보 표시
    if start_date and end_date:
        # 날짜 차이 계산
        # .days: timedelta 객체에서 일수만 추출
        days_diff = (end_date - start_date).days + 1  # +1: 시작일과 종료일 포함

        if start_date > end_date:
            # 시작일이 종료일보다 늦으면 경고
            st.warning("⚠️ 시작일은 종료일보다 이전이어야 합니다.")
        elif days_diff > 365:
            # 1년 초과 시 경고 (처리 가능하지만 시간이 오래 걸림)
            st.warning(f"⚠️ 처리 기간이 {days_diff}일입니다. 처리 시간이 오래 걸릴 수 있습니다.")
        else:
            # 정상 범위일 때 정보 표시
            # :,: 천 단위 콤마 추가 (30 → 30, 1000 → 1,000)
            st.info(f"📌 처리 기간: {start_date} ~ {end_date} ({days_diff:,}일)")

    # =========================================================================
    # Section 3: 실행 버튼
    # =========================================================================
    st.markdown("### 🚀 3. 실행")

    # 실행 버튼
    # disabled: 비활성화 조건 (파일 없음 or 시트 없음 or 날짜 역순)
    process_summary_button = st.button(
        "📊 요약 파일 생성",
        type="primary",  # 파란색 강조 버튼
        use_container_width=True,
        disabled=(
            uploaded_file_summary is None or  # 파일이 업로드되지 않았거나
            selected_sheet is None or  # 시트가 선택되지 않았거나
            start_date > end_date  # 시작일이 종료일보다 늦으면
        ),
        key="process_summary_button"
    )

    # =========================================================================
    # Section 4: 처리 로직 및 결과 표시
    # =========================================================================
    if process_summary_button:
        # 진행 상황 표시 위젯들
        # st.progress(): 진행률 바 (0.0 ~ 1.0)
        progress_bar = st.progress(0)

        # st.empty(): 나중에 내용을 동적으로 업데이트할 수 있는 빈 컨테이너
        # .text(), .markdown() 등으로 내용을 계속 갱신할 수 있음
        status_text = st.empty()

        # st.expander()를 사용하여 로그를 접을 수 있게 함
        # expanded=True: 처음에 펼쳐진 상태
        log_container = st.expander("📋 처리 로그", expanded=True)

        # 로그 메시지를 저장할 리스트
        # 각 일자별 처리 결과를 이 리스트에 추가하고, 화면에 표시
        log_messages = []

        # =====================================================================
        # 콜백 함수: 진행률 업데이트
        # =====================================================================
        # def: 함수 정의
        # current, total, msg: 매개변수 (파라미터)
        def progress_callback(current, total, msg):
            """
            진행률 콜백 함수

            이 함수는 period_summary.process_period_summary()에서 호출됩니다.
            일자별 처리가 완료될 때마다 이 함수가 실행되어 화면을 업데이트합니다.

            Args:
                current (int): 현재 처리된 일수
                total (int): 전체 처리할 일수
                msg (str): 상태 메시지
            """
            # 진행률 계산 (0.0 ~ 1.0)
            # / 연산자: 나눗셈 (정수를 나누면 실수 결과)
            progress = current / total

            # 진행률 바 업데이트
            progress_bar.progress(progress)

            # 상태 텍스트 업데이트
            # :.1f%: 소수점 1자리 퍼센트 (0.5 → 50.0%)
            status_text.text(f"⏳ 처리 중... ({current}/{total}일) {progress * 100:.1f}% - {msg}")

            # 로그 메시지 추가
            log_messages.append(msg)

            # 로그 컨테이너에 표시
            # with 문: 이 블록 안의 코드는 log_container 안에 표시됨
            with log_container:
                # 최근 10개 메시지만 표시 (너무 길어지지 않도록)
                # [-10:]: 리스트의 마지막 10개 항목
                for log_msg in log_messages[-10:]:
                    st.caption(f"✓ {log_msg}")

        try:
            # =================================================================
            # 임시 파일 저장
            # =================================================================
            # 업로드된 파일을 디스크에 임시로 저장
            # Streamlit의 UploadedFile 객체는 메모리에만 있으므로,
            # pandas가 읽을 수 있도록 파일로 저장해야 함

            # 임시 파일 경로 생성
            temp_file_path = os.path.join("uploads", uploaded_file_summary.name)

            # with open(): 파일 열기 (with 블록이 끝나면 자동으로 닫힘)
            # 'wb': write binary (바이너리 쓰기 모드)
            with open(temp_file_path, 'wb') as f:
                # .write(): 파일에 데이터 쓰기
                # .getvalue(): UploadedFile 객체에서 바이너리 데이터 가져오기
                f.write(uploaded_file_summary.getvalue())

            # =================================================================
            # 요약 처리 실행
            # =================================================================
            # 날짜 객체를 문자열로 변환
            # .strftime(): datetime을 문자열로 포맷팅
            start_date_str = start_date.strftime('%Y-%m-%d')
            end_date_str = end_date.strftime('%Y-%m-%d')

            # process_period_summary() 호출
            # 이 함수는 Src/period_summary.py에 정의되어 있음
            result = process_period_summary(
                file_path=temp_file_path,  # 임시 파일 경로
                sheet_name=selected_sheet,  # 선택된 시트명
                start_date=start_date_str,  # 시작일 (문자열)
                end_date=end_date_str,  # 종료일 (문자열)
                progress_callback=progress_callback  # 진행률 콜백 함수
            )

            # =================================================================
            # 처리 완료 - 결과 표시
            # =================================================================
            # 진행률 바를 100%로 설정
            progress_bar.progress(1.0)
            status_text.text("✅ 처리 완료!")

            # 성공 메시지
            st.success("✅ 처리가 완료되었습니다!")

            # 요약 통계 표시
            # st.columns([비율]): 화면을 열로 나누기
            col1, col2, col3 = st.columns(3)

            # st.metric(): 지표 카드 (제목, 값, 변화량)
            with col1:
                st.metric(
                    "💰 총 누적 매출",
                    f"{result['total_sales']:,.0f}원"  # :,.0f: 천 단위 콤마, 소수점 없음
                )

            with col2:
                st.metric(
                    "💳 총 누적 매입",
                    f"{result['total_buy']:,.0f}원"
                )

            with col3:
                # delta: 변화량 (양수면 녹색 화살표, 음수면 빨간 화살표)
                profit_pct = (result['profit'] / result['total_sales'] * 100) if result['total_sales'] > 0 else 0
                st.metric(
                    "📈 손익",
                    f"{result['profit']:,.0f}원",
                    delta=f"{profit_pct:.1f}%"  # 손익률
                )

            st.divider()

            # =================================================================
            # 다운로드 버튼
            # =================================================================
            st.markdown("### ⬇️ 결과 파일 다운로드")

            # 생성된 파일 읽기
            # 'rb': read binary (바이너리 읽기 모드)
            with open(result['output_file'], 'rb') as f:
                # st.download_button(): 파일 다운로드 버튼
                st.download_button(
                    label="📥 요약 파일 다운로드",
                    data=f,  # 파일 데이터
                    file_name=os.path.basename(result['output_file']),  # 파일명 (경로 제외)
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # Excel 파일 MIME 타입
                    use_container_width=True
                )

            # 파일 정보 표시
            st.caption(f"📁 파일명: {os.path.basename(result['output_file'])}")
            st.caption(f"📊 생성된 시트: {len(result['sheets_created'])}개")

            # =================================================================
            # 상세 내역 미리보기 (선택사항)
            # =================================================================
            st.divider()
            st.markdown("### 📊 상세 내역 미리보기")

            # 일자별 요약 표시
            # 리스트를 DataFrame으로 변환하여 표로 표시
            if result['daily_summary']:
                with st.expander("📅 일자별 요약", expanded=False):
                    # pd.DataFrame(): 리스트나 딕셔너리를 DataFrame으로 변환
                    daily_df = pd.DataFrame(result['daily_summary'])

                    # 컬럼명 변경 (영어 → 한글)
                    # .rename(): 컬럼명 변경
                    # columns={기존명: 새이름}
                    daily_df = daily_df.rename(columns={
                        'date': '날짜',
                        'sales': '매출',
                        'buy': '매입'
                    })

                    # 손익 컬럼 추가
                    daily_df['손익'] = daily_df['매출'] - daily_df['매입']

                    # 표 표시
                    st.dataframe(daily_df, use_container_width=True)

            # =================================================================
            # 임시 파일 정리
            # =================================================================
            # 처리가 완료되었으므로 임시 파일 삭제
            try:
                # os.remove(): 파일 삭제
                os.remove(temp_file_path)
            except:
                # 삭제 실패해도 무시 (중요하지 않음)
                pass

        except Exception as e:
            # =================================================================
            # 에러 처리
            # =================================================================
            # 진행률 바 숨기기 (에러 발생 시)
            progress_bar.empty()
            status_text.empty()

            # 에러 메시지 표시
            st.error(f"❌ 처리 중 오류가 발생했습니다: {str(e)}")

            # 상세 에러 정보 (개발자용)
            with st.expander("🔍 에러 상세 정보"):
                # import traceback: 에러의 전체 스택 트레이스 출력
                import traceback

                # st.code(): 코드 블록으로 표시 (고정폭 폰트, 색상 강조)
                st.code(traceback.format_exc())

            # 임시 파일 정리 (에러 발생 시에도 실행)
            try:
                if 'temp_file_path' in locals():  # 변수가 존재하는지 확인
                    os.remove(temp_file_path)
            except:
                pass

# 푸터
st.divider()
st.caption(
    f"© 2024 SollumeLab | Streamlit 탭 버전 | "
    f"마지막 업데이트: 2025-12-10 | "
    f"v2.2.0-with-period-summary"
)
