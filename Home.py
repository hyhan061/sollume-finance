# Home.py
# 2025-12-16 hoyeon.han
# 솔루미랩 회계 시스템 - Multi-Page App 홈 화면
# 2025-12-17 hoyeon.han: 로그인 인증 기능 추가

# Streamlit page configuration
# title: 🏠 홈
# icon: 🏠

import streamlit as st
import os
import sys
from pathlib import Path

# 2025-12-17 hoyeon.han: 인증 모듈 직접 import (Src/__init__.py 우회)
import importlib.util
spec = importlib.util.spec_from_file_location("auth", Path(__file__).parent / "Src" / "auth.py")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)

init_session_state = auth.init_session_state
is_session_valid = auth.is_session_valid
show_login_page = auth.show_login_page
show_user_info_sidebar = auth.show_user_info_sidebar

# 디렉토리 생성
os.makedirs("logs", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("processed", exist_ok=True)
os.makedirs("database", exist_ok=True)
os.makedirs("database/backups", exist_ok=True)

# 페이지 설정
st.set_page_config(
    page_title="SollumeLab 회계 시스템",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2025-12-17 hoyeon.han: 세션 상태 초기화
init_session_state()

# CSS 커스터마이징 (로그인 전에도 필요)
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
        text-align: center;
    }
    .section-box {
        padding: 1.5rem;
        background-color: #f8f9fa;
        border-radius: 10px;
        border-left: 4px solid #3498db;
        margin: 1rem 0;
    }
    .section-title {
        font-size: 1.3rem;
        font-weight: bold;
        color: #2c3e50;
        margin-bottom: 0.5rem;
    }
    .section-desc {
        color: #555;
        font-size: 0.95rem;
        line-height: 1.6;
    }
    .feature-list {
        margin-left: 1.5rem;
        color: #555;
    }
</style>
""", unsafe_allow_html=True)

# 메인 타이틀 (로그인 전에도 표시)
st.markdown('<div class="main-header">📊 SollumeLab 회계 시스템</div>', unsafe_allow_html=True)

# 2025-12-17 hoyeon.han: 인증 체크 - 미인증 시 로그인 페이지 표시
if not is_session_valid():
    show_login_page()
    st.stop()

# 2025-12-17 hoyeon.han: 사이드바에 사용자 정보 표시
show_user_info_sidebar()

# 홈 화면 (로그인 후)
st.markdown("### 환영합니다! 👋")
st.markdown("왼쪽 사이드바에서 원하는 기능을 선택하세요.")

st.divider()

# 기능 소개
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
    <div class="section-box">
        <div class="section-title">📝 전표 생성</div>
        <div class="section-desc">
            발주내역 엑셀 파일을 업로드하여 경리나라 전표를 생성합니다.
            <div class="feature-list">
                <ul>
                    <li>매출 전표 생성</li>
                    <li>매입 전표 생성</li>
                    <li>날짜별 일괄 처리</li>
                    <li>자동 사업자번호 매칭</li>
                </ul>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class="section-box">
        <div class="section-title">📊 발주내역 요약</div>
        <div class="section-desc">
            기간별 발주내역을 요약하여 엑셀 파일로 다운로드합니다.
            <div class="feature-list">
                <ul>
                    <li>기간 선택 (시작일~종료일)</li>
                    <li>일자별 매출/매입 내역</li>
                    <li>엑셀 파일 다운로드</li>
                    <li>자동 집계 및 정렬</li>
                </ul>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("""
    <div class="section-box">
        <div class="section-title">🏢 거래처 관리</div>
        <div class="section-desc">
            거래처 정보를 조회, 등록, 수정, 삭제할 수 있습니다.
            <div class="feature-list">
                <ul>
                    <li>거래처 검색</li>
                    <li>신규 거래처 등록</li>
                    <li>정보 수정/삭제</li>
                    <li>Excel 가져오기/내보내기</li>
                </ul>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# 사용 안내
st.markdown("### 📖 사용 방법")
st.info("""
👈 **왼쪽 사이드바**에서 메뉴를 선택하세요.

1️⃣ **전표 생성**: 발주내역 엑셀 업로드 → 날짜 선택 → 전표 생성 → 다운로드

2️⃣ **발주내역 요약**: 발주내역 엑셀 업로드 → 기간 선택 → 요약 처리 → 다운로드

3️⃣ **거래처 관리**: 거래처 검색 → 조회/등록/수정/삭제 → DB 관리
""")

# 시스템 정보
st.divider()

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("### 📁 시스템 정보")

    # 디렉토리 상태 확인
    dirs_status = {
        "로그": Path("logs").exists(),
        "업로드": Path("uploads").exists(),
        "처리완료": Path("processed").exists(),
        "데이터베이스": Path("database").exists()
    }

    for dir_name, exists in dirs_status.items():
        status_icon = "✅" if exists else "❌"
        st.write(f"{status_icon} {dir_name} 디렉토리")

with col_right:
    st.markdown("### 🔍 DB 상태")

    db_path = Path("database/customer_master.db")
    if db_path.exists():
        st.success(f"✅ 거래처 DB 연결됨")
        st.caption(f"DB 크기: {db_path.stat().st_size / 1024:.2f} KB")
    else:
        st.warning("⚠️ 거래처 DB가 없습니다. 마이그레이션이 필요합니다.")
        st.caption("scripts/migrate_excel_to_db.py를 실행하세요.")

# Footer
st.divider()
st.caption("© 2025 솔루미랩 | v3.0.0 | Multi-Page App")
st.caption("작성자: hoyeon.han | 작성일: 2025-12-16")
