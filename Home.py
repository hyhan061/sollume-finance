# Home.py
# 2025-12-16 hoyeon.han
# 솔루미랩 회계 시스템 - Multi-Page App 홈 화면
# 2025-12-17 hoyeon.han: 로그인 인증 기능 추가
# 2026-07-10 hoyeon.han: st.navigation 라우터로 전면 개편.
#   - 진입점(라우터): set_page_config / 인증 / 전역 CSS / 사이드바(로고+사용자) / 네비게이션을 여기서 1회 처리.
#   - 로그인 화면: st.navigation(position="hidden") 으로 메뉴 완전 숨김(로고+폼만).
#   - 인증 후: 기능 성격별 그룹(계층) 네비. 각 pages/*.py 는 콘텐츠만 담당(보일러플레이트 제거).
#   - 기존 랜딩(환영/기능카드/시스템정보)은 아래 _home_page() 로 보존.

import importlib.util
import os
import sys
from pathlib import Path

import streamlit as st

# Src 경로 추가 후 공통 UI 모듈 import
sys.path.insert(0, str(Path(__file__).parent / "Src"))
from ui_components import render_sidebar_logo, render_sidebar_user_simple  # noqa: E402
from ui_theme import inject_global_css, render_page_header  # noqa: E402

# 인증 모듈 직접 import (Src/__init__.py 우회)
_spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent / "Src" / "auth.py"
)
if _spec is None or _spec.loader is None:
    raise ImportError("인증 모듈(auth.py)을 로드할 수 없습니다. 파일 경로를 확인해주세요.")
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)

# 디렉토리 생성
for _d in ("logs", "uploads", "processed", "database", "database/backups"):
    os.makedirs(_d, exist_ok=True)

# 페이지 설정 (st.navigation 앱에서는 진입점에서만 호출)
st.set_page_config(
    page_title="SollumeLab 회계 시스템",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

auth.init_session_state()
# 전역 테마 CSS 주입 (로그인 화면 포함 적용)
inject_global_css()


# ---------------------------------------------------------------------------
# 로그인 페이지 (미인증 시)
# ---------------------------------------------------------------------------
def _login_page():
    render_page_header(
        "SollumeLab 회계 시스템",
        "발주내역 엑셀을 경리나라 매출·매입 전표로 변환합니다.",
        icon="📊",
    )
    auth.show_login_page()


# ---------------------------------------------------------------------------
# 홈(랜딩) 페이지 (인증 후 기본 페이지) — 기존 Home.py 랜딩 콘텐츠 보존
# ---------------------------------------------------------------------------
def _home_page():
    render_page_header(
        "SollumeLab 회계 시스템",
        "발주내역 엑셀을 경리나라 매출·매입 전표로 변환합니다.",
        icon="📊",
    )
    st.markdown("### 환영합니다! 👋")
    st.markdown("왼쪽 사이드바에서 원하는 기능을 선택하세요.")
    st.divider()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            """
        <div class="section-box">
            <div class="section-title">📝 전표 생성</div>
            <div class="section-desc">
                발주내역 엑셀 파일을 업로드하여 경리나라 전표를 생성합니다.
                <div class="feature-list"><ul>
                    <li>매출 전표 생성</li><li>매입 전표 생성</li>
                    <li>날짜별 일괄 처리</li><li>자동 사업자번호 매칭</li>
                </ul></div>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            """
        <div class="section-box">
            <div class="section-title">📊 발주내역 요약</div>
            <div class="section-desc">
                기간별 발주내역을 요약하여 엑셀 파일로 다운로드합니다.
                <div class="feature-list"><ul>
                    <li>기간 선택 (시작일~종료일)</li><li>일자별 매출/매입 내역</li>
                    <li>엑셀 파일 다운로드</li><li>자동 집계 및 정렬</li>
                </ul></div>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            """
        <div class="section-box">
            <div class="section-title">🏢 거래처 관리</div>
            <div class="section-desc">
                거래처 정보를 조회, 등록, 수정, 삭제할 수 있습니다.
                <div class="feature-list"><ul>
                    <li>거래처 검색</li><li>신규 거래처 등록</li>
                    <li>정보 수정/삭제</li><li>Excel 가져오기/내보내기</li>
                </ul></div>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            """
        <div class="section-box">
            <div class="section-title">🎯 특정업체 전표</div>
            <div class="section-desc">
                특정 기간의 특정 업체 전표를 생성합니다.
                <div class="feature-list"><ul>
                    <li>기간 선택 (시작일~종료일)</li><li>복수 업체 선택</li>
                    <li>업체별 매출/매입 전표</li><li>개별 파일 다운로드</li>
                </ul></div>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("### 📖 사용 방법")
    st.info(
        """
👈 **왼쪽 사이드바**에서 메뉴를 선택하세요.

1️⃣ **전표 생성**: 발주내역 엑셀 업로드 → 날짜 선택 → 전표 생성 → 다운로드

2️⃣ **발주내역 요약**: 발주내역 엑셀 업로드 → 기간 선택 → 요약 처리 → 다운로드

3️⃣ **거래처 관리**: 거래처 검색 → 조회/등록/수정/삭제 → DB 관리

4️⃣ **특정업체 전표**: 발주내역 엑셀 업로드 → 기간/업체 선택 → 업체별 전표 생성 → 다운로드
"""
    )

    st.divider()
    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("### 📁 시스템 정보")
        dirs_status = {
            "로그": Path("logs").exists(),
            "업로드": Path("uploads").exists(),
            "처리완료": Path("processed").exists(),
            "데이터베이스": Path("database").exists(),
        }
        for dir_name, exists in dirs_status.items():
            st.write(f"{'✅' if exists else '❌'} {dir_name} 디렉토리")
    with col_right:
        st.markdown("### 🔍 DB 상태")
        db_path = Path("database/customer_master.db")
        if db_path.exists():
            st.success("✅ 거래처 DB 연결됨")
            st.caption(f"DB 크기: {db_path.stat().st_size / 1024:.2f} KB")
        else:
            st.warning("⚠️ 거래처 DB가 없습니다. 마이그레이션이 필요합니다.")
            st.caption("scripts/migrate_excel_to_db.py를 실행하세요.")

    st.divider()
    st.caption("© 2025 솔루미랩 | v3.0.0 | Multi-Page App")


# ---------------------------------------------------------------------------
# 네비게이션 (라우터)
# ---------------------------------------------------------------------------
if not auth.is_session_valid():
    # 미인증: 메뉴 숨김, 로그인만
    _pg = st.navigation([st.Page(_login_page, title="로그인")], position="hidden")
else:
    # 인증: 로고(최상단) → 그룹 네비 → 사용자 블록(하단)
    render_sidebar_logo()
    _pg = st.navigation(
        {
            "홈": [st.Page(_home_page, title="홈", icon="📊", default=True)],
            "전표 생성": [
                st.Page("pages/1_📝_전표생성.py", title="일별 전표", icon="📝"),
                st.Page("pages/5_📆_전표생성_기간.py", title="기간 전표", icon="📆"),
                st.Page("pages/4_🎯_특정업체전표.py", title="특정업체 전표", icon="🎯"),
            ],
            "정산서": [
                st.Page("pages/7_📋_정산서생성.py", title="정산서 생성", icon="📋"),
                st.Page("pages/9_🧾_정산서생성_셀러.py", title="정산서 생성(셀러)", icon="🧾"),
            ],
            "발주내역": [
                st.Page("pages/2_📊_발주내역요약.py", title="요약", icon="📊"),
                st.Page("pages/8_🔍_발주내역비교.py", title="비교", icon="🔍"),
            ],
            "관리": [
                st.Page("pages/3_🏢_거래처관리.py", title="거래처 관리", icon="🏢"),
                st.Page("pages/6_⚙️_시스템관리.py", title="시스템 관리", icon="⚙️"),
            ],
        }
    )
    render_sidebar_user_simple()

_pg.run()
