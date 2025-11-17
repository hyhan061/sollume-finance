"""
솔루미랩 경리나라 전표 생성 Streamlit 앱
매출/매입 전표 날짜별 일괄등록 파일 생성
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
import sys
import logging
from pathlib import Path

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent / "Src"))

from processing import get_sales_daily, get_purchase_daily, save_dataframe_to_xls

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

# 세션 스테이트 초기화
if 'history' not in st.session_state:
    st.session_state.history = []

# CSS 커스터마이징
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
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
</style>
""", unsafe_allow_html=True)

# 사이드바 메뉴
with st.sidebar:
    st.image("https://via.placeholder.com/150x50/1f77b4/ffffff?text=SollumeLab", use_container_width=True)
    st.title("📋 메뉴")

    page = st.radio(
        "페이지 선택",
        ["전표 생성", "처리 이력", "설정"],
        label_visibility="collapsed"
    )

    st.divider()

    # 시스템 정보
    st.subheader("시스템 정보")

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
    today_files = [f for f in os.listdir("processed") if today_str in f]
    st.metric("오늘 처리 건수", len(today_files))

    st.divider()

    # 도움말
    with st.expander("❓ 도움말"):
        st.markdown("""
        **사용 방법:**
        1. 발주내역 파일(.xlsm) 선택
        2. 처리할 날짜 선택
        3. '업로드 및 처리' 버튼 클릭
        4. 매출/매입 파일 다운로드

        **문제 발생 시:**
        - 처리 이력 페이지에서 로그 확인
        - 스크린샷을 찍어 개발자에게 전달
        """)

# 메인 페이지
if page == "전표 생성":
    st.markdown('<div class="main-header">📊 경리나라 매출/매입 전표 날짜별 일괄등록 파일 생성</div>', unsafe_allow_html=True)

    # 안내 메시지
    st.info("💡 발주내역 파일을 업로드하고 처리할 날짜를 선택하세요.")

    # 입력 폼
    col1, col2 = st.columns([2, 1])

    with col1:
        uploaded_file = st.file_uploader(
            "📁 발주내역 파일 선택 (.xlsm)",
            type=['xlsm'],
            help="솔루미랩 발주내역 파일을 선택하세요. (누적)2025년 발주내역 시트가 포함되어야 합니다."
        )

    with col2:
        selected_date = st.date_input(
            "📅 처리 날짜 선택",
            value=datetime.today(),
            max_value=datetime.today(),
            help="전표를 생성할 날짜를 선택하세요"
        )

    # 파일 정보 표시
    if uploaded_file:
        st.success(f"✓ 파일 선택됨: {uploaded_file.name} ({uploaded_file.size / 1024 / 1024:.2f} MB)")

    st.divider()

    # 처리 버튼
    if st.button("▶️ 업로드 및 처리", type="primary", use_container_width=True):
        if uploaded_file is None:
            st.error("⚠️ 파일을 먼저 선택해주세요.")
        else:
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

                # 처리 이력 저장
                st.session_state.history.append({
                    'timestamp': datetime.now(),
                    'date': date_str,
                    'file': uploaded_file.name,
                    'sales_count': len(df_sales),
                    'purchase_count': len(df_purchase)
                })

                # 결과 표시
                st.subheader("📊 처리 결과")

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("처리 날짜", date_str)
                with col2:
                    st.metric("매출 건수", len(df_sales))
                with col3:
                    st.metric("매입 건수", len(df_purchase))

                # 탭으로 데이터 미리보기
                tab1, tab2 = st.tabs(["💰 매출 데이터", "🛒 매입 데이터"])

                with tab1:
                    st.info(f"총 {len(df_sales)}건의 매출 데이터가 처리되었습니다.")
                    st.dataframe(df_sales.head(20), use_container_width=True, height=400)

                    # 다운로드 버튼
                    with open(sales_filepath, "rb") as f:
                        st.download_button(
                            label="📥 매출 파일 다운로드",
                            data=f.read(),
                            file_name=sales_filename,
                            mime="application/vnd.ms-excel",
                            type="primary",
                            use_container_width=True
                        )

                with tab2:
                    st.info(f"총 {len(df_purchase)}건의 매입 데이터가 처리되었습니다.")
                    st.dataframe(df_purchase.head(20), use_container_width=True, height=400)

                    # 다운로드 버튼
                    with open(purchase_filepath, "rb") as f:
                        st.download_button(
                            label="📥 매입 파일 다운로드",
                            data=f.read(),
                            file_name=purchase_filename,
                            mime="application/vnd.ms-excel",
                            type="primary",
                            use_container_width=True
                        )

            except FileNotFoundError as e:
                progress_bar.empty()
                status_text.empty()
                st.markdown(f'<div class="error-box">⚠️ <b>파일을 찾을 수 없습니다</b><br>{str(e)}</div>', unsafe_allow_html=True)
                st.info("💡 Src/거래처마스터.xlsx 파일이 있는지 확인해주세요.")
                logging.error(f"파일 없음: {str(e)}")

            except KeyError as e:
                progress_bar.empty()
                status_text.empty()
                st.markdown(f'<div class="error-box">⚠️ <b>Excel 시트를 찾을 수 없습니다</b><br>{str(e)}</div>', unsafe_allow_html=True)
                st.info("💡 파일에 '(누적)2025년 발주내역' 시트가 있는지 확인해주세요.")
                logging.error(f"시트 없음: {str(e)}")

            except Exception as e:
                progress_bar.empty()
                status_text.empty()
                st.markdown(f'<div class="error-box">❌ <b>처리 중 오류가 발생했습니다</b></div>', unsafe_allow_html=True)

                # 에러 상세 정보 (펼치기)
                with st.expander("🔍 에러 상세 정보 (개발자에게 전달)"):
                    st.exception(e)

                logging.error(f"처리 실패: {str(e)}", exc_info=True)

elif page == "처리 이력":
    st.markdown('<div class="main-header">📜 처리 이력</div>', unsafe_allow_html=True)

    # 이번 세션 처리 이력
    if st.session_state.history:
        st.subheader("이번 세션 처리 내역")
        for idx, item in enumerate(reversed(st.session_state.history), 1):
            with st.container():
                col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
                with col1:
                    st.write(f"**{item['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}**")
                with col2:
                    st.write(f"📅 {item['date']}")
                with col3:
                    st.write(f"💰 {item['sales_count']}건")
                with col4:
                    st.write(f"🛒 {item['purchase_count']}건")
                st.caption(f"파일: {item['file']}")
                st.divider()
    else:
        st.info("아직 처리한 내역이 없습니다.")

    st.divider()

    # 처리된 파일 목록
    st.subheader("📁 저장된 파일 목록")

    processed_files = sorted(os.listdir("processed"), reverse=True) if os.path.exists("processed") else []

    if processed_files:
        # 날짜별로 그룹화
        files_by_date = {}
        for filename in processed_files:
            # 파일명에서 날짜 추출 (매출_2024-11-15.xls)
            try:
                date_part = filename.split('_')[1].replace('.xls', '')
                if date_part not in files_by_date:
                    files_by_date[date_part] = []
                files_by_date[date_part].append(filename)
            except:
                continue

        for date, files in sorted(files_by_date.items(), reverse=True):
            with st.expander(f"📅 {date} ({len(files)}개 파일)"):
                for filename in files:
                    filepath = os.path.join("processed", filename)
                    file_size = os.path.getsize(filepath) / 1024  # KB
                    file_time = datetime.fromtimestamp(os.path.getmtime(filepath))

                    col1, col2 = st.columns([3, 1])
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
                                key=f"download_{filename}"
                            )
    else:
        st.info("저장된 파일이 없습니다.")

    st.divider()

    # 로그 뷰어
    st.subheader("📋 애플리케이션 로그")

    if os.path.exists("logs/app.log"):
        log_lines_count = st.slider("표시할 줄 수", 10, 100, 50)

        with open("logs/app.log", "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-log_lines_count:]

        st.text_area(
            "최근 로그",
            value="".join(recent_lines),
            height=400,
            label_visibility="collapsed"
        )

        # 로그 다운로드
        with open("logs/app.log", "rb") as f:
            st.download_button(
                label="📥 전체 로그 다운로드",
                data=f.read(),
                file_name=f"app_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
                mime="text/plain"
            )
    else:
        st.info("아직 로그가 없습니다.")

elif page == "설정":
    st.markdown('<div class="main-header">⚙️ 설정</div>', unsafe_allow_html=True)

    st.subheader("파일 경로 설정")

    master_file_path = st.text_input(
        "거래처마스터 파일 경로",
        value="Src/거래처마스터.xlsx",
        help="거래처마스터 Excel 파일의 경로를 입력하세요"
    )

    if os.path.exists(master_file_path):
        st.success(f"✓ 파일 존재: {master_file_path}")

        # 파일 정보
        file_size = os.path.getsize(master_file_path) / 1024
        file_time = datetime.fromtimestamp(os.path.getmtime(master_file_path))

        col1, col2 = st.columns(2)
        with col1:
            st.metric("파일 크기", f"{file_size:.1f} KB")
        with col2:
            st.metric("최종 수정", file_time.strftime('%Y-%m-%d %H:%M'))
    else:
        st.error(f"✗ 파일이 존재하지 않습니다: {master_file_path}")

    st.divider()

    # 디스크 사용량
    st.subheader("💾 디스크 사용량")

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

    uploads_size = get_folder_size("uploads") / 1024 / 1024  # MB
    processed_size = get_folder_size("processed") / 1024 / 1024  # MB
    logs_size = get_folder_size("logs") / 1024 / 1024  # MB

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("업로드 폴더", f"{uploads_size:.2f} MB")
    with col2:
        st.metric("처리 폴더", f"{processed_size:.2f} MB")
    with col3:
        st.metric("로그 폴더", f"{logs_size:.2f} MB")

    st.divider()

    # 정리 기능
    st.subheader("🧹 데이터 정리")

    st.warning("⚠️ 아래 작업은 되돌릴 수 없습니다. 신중하게 선택하세요.")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🗑️ 처리된 파일 모두 삭제", type="secondary"):
            if os.path.exists("processed"):
                for file in os.listdir("processed"):
                    os.remove(os.path.join("processed", file))
                st.success("처리된 파일을 모두 삭제했습니다.")
                st.rerun()

    with col2:
        if st.button("🗑️ 로그 파일 삭제", type="secondary"):
            if os.path.exists("logs/app.log"):
                os.remove("logs/app.log")
                st.success("로그 파일을 삭제했습니다.")
                st.rerun()

# 푸터
st.divider()
st.caption(f"© 2024 SollumeLab | Streamlit 버전 | 마지막 업데이트: 2024-11-15")
