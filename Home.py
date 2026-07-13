# Home.py
# 2025-12-16 hoyeon.han
# 솔루미랩 회계 시스템 - Multi-Page App 홈 화면
# 2025-12-17 hoyeon.han: 로그인 인증 기능 추가
# 2026-07-10 hoyeon.han: st.navigation 라우터로 전면 개편.
#   - 진입점(라우터): set_page_config / 인증 / 전역 CSS / 사이드바(로고+사용자) / 네비게이션을 여기서 1회 처리.
#   - 로그인 화면: st.navigation(position="hidden") 으로 메뉴 완전 숨김(로고+폼만).
# 2026-07-13 hoyeon.han: 사이드바 커스텀 네비로 전환.
#   - 자동 네비도 position="hidden"으로 숨기고, 사이드바를 직접 구성:
#     최상단 로고(클릭 시 같은 탭에서 홈으로) → st.page_link 그룹 네비('홈' 항목 없음) → 사용자 블록.
#   - 홈(기본 페이지)은 '로고만 가운데'로 심플화. (기존 랜딩 환영/기능카드/사용법/시스템정보는
#     git 이력 참고 — 심플화로 대체)

import importlib.util
import os
import sys
from pathlib import Path

import streamlit as st

# Src 경로 추가 후 공통 UI 모듈 import
sys.path.insert(0, str(Path(__file__).parent / "Src"))
from ui_components import (  # noqa: E402
    render_sidebar_logo,
    render_sidebar_user_simple,
    render_home_logo,
    render_login_screen,
)
from ui_theme import inject_global_css  # noqa: E402

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

# 2026-07-13 hoyeon.han: 브라우저 탭 아이콘(파비콘)을 브랜드 심볼로. 파일 없으면 이모지 폴백.
#   (브라우저 탭은 보통 밝은 배경이라 dark-ink 심볼 사용)
_favicon = Path(__file__).parent / "assets" / "sollume-symbol-dark-ink.png"
_page_icon = str(_favicon) if _favicon.exists() else "📊"

# 페이지 설정 (st.navigation 앱에서는 진입점에서만 호출)
st.set_page_config(
    page_title="SollumeLab 회계 시스템",
    page_icon=_page_icon,
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
    # 2026-07-13 hoyeon.han: 로그인 화면도 홈처럼 심플하게 (중앙 로고 + 최소 폼)
    render_login_screen(auth)


# ---------------------------------------------------------------------------
# 홈(랜딩) 페이지 (인증 후 기본 페이지) — 2026-07-13: 로고만 가운데로 심플화
# ---------------------------------------------------------------------------
def _home_page():
    render_home_logo()


# ---------------------------------------------------------------------------
# 페이지 정의 + 네비게이션 (라우터)
# ---------------------------------------------------------------------------
if not auth.is_session_valid():
    # 미인증: 네비 숨김, 로그인만
    _pg = st.navigation([st.Page(_login_page, title="로그인")], position="hidden")
else:
    # 인증: 자동 네비를 숨기고(position="hidden") 사이드바를 직접 구성한다.
    _home = st.Page(_home_page, title="홈", icon="📊", default=True)
    _p_daily = st.Page("pages/1_📝_전표생성.py", title="일별 전표", icon="📝")
    _p_period = st.Page("pages/5_📆_전표생성_기간.py", title="기간 전표", icon="📆")
    _p_vendor = st.Page("pages/4_🎯_특정업체전표.py", title="특정업체 전표", icon="🎯")
    _p_settle = st.Page("pages/7_📋_정산서생성.py", title="정산서 생성", icon="📋")
    _p_settle_seller = st.Page(
        "pages/9_🧾_정산서생성_셀러.py", title="정산서 생성(셀러)", icon="🧾"
    )
    _p_summary = st.Page("pages/2_📊_발주내역요약.py", title="요약", icon="📊")
    _p_compare = st.Page("pages/8_🔍_발주내역비교.py", title="비교", icon="🔍")
    _p_customer = st.Page("pages/3_🏢_거래처관리.py", title="거래처 관리", icon="🏢")
    _p_system = st.Page("pages/6_⚙️_시스템관리.py", title="시스템 관리", icon="⚙️")

    # 홈은 기본(default) 페이지로 라우팅만 하고, 아래 커스텀 네비에는 노출하지 않는다
    # (홈 이동은 최상단 로고 클릭으로). 나머지는 그룹별 page_link 로 노출.
    _pg = st.navigation(
        [
            _home,
            _p_daily,
            _p_period,
            _p_vendor,
            _p_settle,
            _p_settle_seller,
            _p_summary,
            _p_compare,
            _p_customer,
            _p_system,
        ],
        position="hidden",
    )

    # 사이드바: 최상단 로고(클릭→홈, 내부 이동으로 세션 유지) → 그룹 네비(page_link) → 사용자 블록(하단)
    render_sidebar_logo(_home)
    with st.sidebar:
        st.markdown("**전표 생성**")
        st.page_link(_p_daily)
        st.page_link(_p_period)
        st.page_link(_p_vendor)
        st.markdown("**정산서**")
        st.page_link(_p_settle)
        st.page_link(_p_settle_seller)
        st.markdown("**발주내역**")
        st.page_link(_p_summary)
        st.page_link(_p_compare)
        st.markdown("**관리**")
        st.page_link(_p_customer)
        st.page_link(_p_system)
    render_sidebar_user_simple()

_pg.run()
