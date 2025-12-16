"""
솔루미랩 발주내역 요약 페이지
특정 기간 동안의 발주내역을 일자별/업체별로 요약
2025-12-16 hoyeon.han: app.py.backup의 tab2 내용을 별도 페이지로 분리
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
import sys
from pathlib import Path

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 발주내역 기간별 요약 모듈
from Src.period_summary import process_period_summary

# 디렉토리 생성
os.makedirs("uploads", exist_ok=True)
os.makedirs("processed", exist_ok=True)

# 페이지 설정
st.set_page_config(
    page_title="발주내역 요약",
    page_icon="📊",
    layout="wide"
)

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

st.markdown('<div class="main-header">📊 발주내역 요약</div>', unsafe_allow_html=True)
st.caption("특정 기간 동안의 발주내역을 일자별/업체별로 요약하여 Excel 파일로 제공합니다.")

st.divider()

# =============================================================================
# Section 1: 파일 업로드 및 시트 선택
# 2025-12-16 hoyeon.han: tab2 내용을 페이지 레벨로 변경
# =============================================================================

st.markdown("### 📁 1. 발주내역 파일 업로드")

# 파일 업로드 위젯
uploaded_file_summary = st.file_uploader(
    "발주내역 Excel 파일을 선택하세요 (.xlsm)",
    type=['xlsm', 'xlsx'],
    help="발주내역 데이터가 포함된 Excel 파일을 업로드하세요",
    key="summary_uploader"
)

# 시트 선택 UI 변수 초기화
selected_sheet = None

# 파일이 업로드되면 시트 선택 UI 표시
if uploaded_file_summary is not None:
    st.success(f"✅ 파일 선택됨: {uploaded_file_summary.name} ({uploaded_file_summary.size / 1024 / 1024:.2f} MB)")

    with st.spinner("시트 목록 확인 중..."):
        try:
            # Excel 파일 객체 생성
            excel_file = pd.ExcelFile(uploaded_file_summary)
            sheet_names = excel_file.sheet_names

            # 스마트 기본값 찾기
            default_index = 0
            current_year = datetime.now().year

            for i, sheet in enumerate(sheet_names):
                if "발주내역" in sheet and str(current_year) in sheet:
                    default_index = i
                    break

            # 시트 선택 드롭다운
            selected_sheet = st.selectbox(
                "📋 처리할 시트 선택",
                options=sheet_names,
                index=default_index,
                help="발주내역 데이터가 포함된 시트를 선택하세요",
                key="sheet_selector"
            )

            st.info(f"📌 선택된 시트: **{selected_sheet}**")

            # 시트 미리보기
            with st.expander("🔍 시트 미리보기 (상위 5행)"):
                try:
                    preview_df = pd.read_excel(
                        uploaded_file_summary,
                        sheet_name=selected_sheet,
                        header=3,
                        nrows=5
                    )
                    st.dataframe(preview_df, use_container_width=True)

                except Exception as e:
                    st.warning(f"미리보기를 불러올 수 없습니다: {str(e)}")

        except Exception as e:
            st.error(f"❌ 시트 목록을 읽을 수 없습니다: {str(e)}")
            st.info("💡 시트명을 직접 입력해주세요")

            # Fallback: 직접 입력
            selected_sheet = st.text_input(
                "시트명 입력",
                value="(누적)2025년 발주내역",
                help="Excel 파일 내 시트 이름을 정확히 입력하세요",
                key="sheet_name_input"
            )

# =============================================================================
# Section 2: 처리 기간 선택
# =============================================================================

st.markdown("### 📅 2. 처리 기간 선택")

col1, col2 = st.columns(2)

with col1:
    start_date = st.date_input(
        "시작일",
        value=datetime.today() - timedelta(days=30),
        max_value=datetime.today(),
        help="요약 처리를 시작할 날짜",
        key="start_date_selector"
    )

with col2:
    end_date = st.date_input(
        "종료일",
        value=datetime.today(),
        max_value=datetime.today(),
        help="요약 처리를 종료할 날짜",
        key="end_date_selector"
    )

# 기간 유효성 검증 및 정보 표시
if start_date and end_date:
    days_diff = (end_date - start_date).days + 1

    if start_date > end_date:
        st.warning("⚠️ 시작일은 종료일보다 이전이어야 합니다.")
    elif days_diff > 365:
        st.warning(f"⚠️ 처리 기간이 {days_diff}일입니다. 처리 시간이 오래 걸릴 수 있습니다.")
    else:
        st.info(f"📌 처리 기간: {start_date} ~ {end_date} ({days_diff:,}일)")

# =============================================================================
# Section 3: 실행 버튼
# =============================================================================

st.markdown("### 🚀 3. 실행")

process_summary_button = st.button(
    "📊 요약 파일 생성",
    type="primary",
    use_container_width=True,
    disabled=(
        uploaded_file_summary is None or
        selected_sheet is None or
        start_date > end_date
    ),
    key="process_summary_button"
)

# =============================================================================
# Section 4: 처리 로직 및 결과 표시
# 2025-12-16 hoyeon.han: 진행상황 표시 및 에러 처리 포함
# =============================================================================

if process_summary_button:
    progress_bar = st.progress(0)
    status_text = st.empty()
    log_container = st.expander("📋 처리 로그", expanded=True)
    log_messages = []

    def progress_callback(current, total, msg):
        """
        진행률 콜백 함수

        Args:
            current (int): 현재 처리된 일수
            total (int): 전체 처리할 일수
            msg (str): 상태 메시지
        """
        progress = current / total
        progress_bar.progress(progress)
        status_text.text(f"⏳ 처리 중... ({current}/{total}일) {progress * 100:.1f}% - {msg}")

        log_messages.append(msg)

        with log_container:
            for log_msg in log_messages[-10:]:
                st.caption(f"✓ {log_msg}")

    try:
        # 임시 파일 저장
        temp_file_path = os.path.join("uploads", uploaded_file_summary.name)

        with open(temp_file_path, 'wb') as f:
            f.write(uploaded_file_summary.getvalue())

        # 요약 처리 실행
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        result = process_period_summary(
            file_path=temp_file_path,
            sheet_name=selected_sheet,
            start_date=start_date_str,
            end_date=end_date_str,
            progress_callback=progress_callback
        )

        # 처리 완료
        progress_bar.progress(1.0)
        status_text.text("✅ 처리 완료!")

        st.success("✅ 처리가 완료되었습니다!")

        # 요약 통계 표시
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "💰 총 누적 매출",
                f"{result['total_sales']:,.0f}원"
            )

        with col2:
            st.metric(
                "💳 총 누적 매입",
                f"{result['total_buy']:,.0f}원"
            )

        with col3:
            profit_pct = (result['profit'] / result['total_sales'] * 100) if result['total_sales'] > 0 else 0
            st.metric(
                "📈 손익",
                f"{result['profit']:,.0f}원",
                delta=f"{profit_pct:.1f}%"
            )

        st.divider()

        # 다운로드 버튼
        st.markdown("### ⬇️ 결과 파일 다운로드")

        with open(result['output_file'], 'rb') as f:
            st.download_button(
                label="📥 요약 파일 다운로드",
                data=f,
                file_name=os.path.basename(result['output_file']),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        st.caption(f"📁 파일명: {os.path.basename(result['output_file'])}")
        st.caption(f"📊 생성된 시트: {len(result['sheets_created'])}개")

        # 상세 내역 미리보기
        st.divider()
        st.markdown("### 📊 상세 내역 미리보기")

        if result['daily_summary']:
            with st.expander("📅 일자별 요약", expanded=False):
                daily_df = pd.DataFrame(result['daily_summary'])

                daily_df = daily_df.rename(columns={
                    'date': '날짜',
                    'sales': '매출',
                    'buy': '매입'
                })

                daily_df['손익'] = daily_df['매출'] - daily_df['매입']

                st.dataframe(daily_df, use_container_width=True)

        # 임시 파일 정리
        try:
            os.remove(temp_file_path)
        except:
            pass

    except Exception as e:
        # 에러 처리
        progress_bar.empty()
        status_text.empty()

        st.error(f"❌ 처리 중 오류가 발생했습니다: {str(e)}")

        with st.expander("🔍 에러 상세 정보"):
            import traceback
            st.code(traceback.format_exc())

        # 임시 파일 정리
        try:
            if 'temp_file_path' in locals():
                os.remove(temp_file_path)
        except:
            pass

# 푸터
st.divider()
st.caption("© 2025 솔루미랩 | v3.0.0")
