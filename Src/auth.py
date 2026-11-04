# 2026-10-14 hoyeon.han: 공개 운영용 DB 세션 인증. 이전 구현은 아래 주석으로 보존.
import hashlib
import logging
from functools import lru_cache
from urllib.parse import urlsplit
import streamlit as st
from auth_gateway import load_security_settings, session_cookie_name
from security_service import SecurityService, SecurityError

logger = logging.getLogger(__name__)


def get_settings():
    return load_security_settings()


@lru_cache(maxsize=4)
def _service(db_path, encryption_key, download_dir):
    return SecurityService(db_path=db_path, encryption_key=encryption_key, download_dir=download_dir)


def get_service():
    settings = get_settings()
    return _service(settings.get('AUTH_DB_PATH'), settings['AUTH_ENCRYPTION_KEY'], settings.get('AUTH_DOWNLOAD_DIR'))


def get_session_token():
    try:
        return st.context.cookies.get(session_cookie_name(get_settings()), '')
    except (RuntimeError, ValueError, KeyError):
        return ''


def init_session_state():
    # 계정/세션이 바뀌면 전표, 거래처 선택, 이전 다운로드 결과까지 모두 정리.
    token = get_session_token()
    marker = hashlib.sha256(token.encode()).hexdigest() if token else ''
    if st.session_state.get('_security_marker') != marker:
        st.session_state.clear()
        st.session_state['_security_marker'] = marker


def get_current_user():
    init_session_state()
    token = get_session_token()
    if not token:
        return None
    try:
        user = get_service().get_session(token, touch=False)
        if user:
            st.session_state['user_info'] = user
            return user
    except (SecurityError, ValueError):
        pass
    except Exception:
        logger.exception('사용자 세션 확인 실패')
    # 인증 DB 장애나 폐기된 세션에서는 업무 자료를 남기지 않음.
    st.session_state.clear()
    st.session_state['_security_marker'] = hashlib.sha256(token.encode()).hexdigest()
    return None


def is_session_valid():
    return bool(get_current_user())


def require_auth(redirect=True):
    if get_current_user():
        return True
    if redirect:
        st.error('로그인이 만료되었거나 접근이 차단되었습니다. 다시 로그인해 주세요.')
        st.stop()
    return False


def require_permission(page_id, redirect=True):
    if not require_auth(redirect):
        return False
    try:
        user = get_service().require_permission(get_session_token(), page_id)
        get_service().get_session(get_session_token(), touch=True)
        st.session_state['user_info'] = user
        return True
    except SecurityError:
        if redirect:
            st.error('이 화면 또는 작업에 대한 접근 권한이 없습니다. 관리자에게 문의하세요.')
            st.stop()
        return False
    except Exception:
        logger.exception('화면 권한 확인 실패')
        if redirect:
            st.error('접근 권한을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.')
            st.stop()
        return False


def require_admin(redirect=True):
    return require_permission('users', redirect)


def can_access(page_id):
    user = get_current_user()
    return bool(user and (user.get('is_admin') or page_id in user.get('permissions', [])))


def get_username():
    user = get_current_user()
    return user.get('username') if user else None


def is_admin():
    user = get_current_user()
    return bool(user and user.get('is_admin'))


def authentication_url(path='/auth/login'):
    origin = get_settings()['AUTH_PUBLIC_ORIGIN'].rstrip('/')
    if path not in ('/auth/login', '/auth/logout', '/auth/account'):
        raise ValueError('허용되지 않은 인증 경로입니다.')
    return origin + path


def unique_output_path(filename, page_id):
    """2026-10-14 hoyeon.han: 직원·생성 건별 파일을 분리해 동일 파일명 덮어쓰기를 방지."""
    from pathlib import Path
    import secrets
    import re
    require_permission(page_id)
    user = get_current_user()
    if not user or not re.fullmatch(r'[0-9a-f]{32}', user['session_id']):
        raise SecurityError('파일을 저장할 로그인 정보를 확인할 수 없습니다.')
    name = Path(str(filename)).name
    if name in ('', '.', '..') or '\\' in name or any(ord(c) < 32 for c in name):
        raise SecurityError('출력 파일명을 확인해 주세요.')
    directory = Path(get_settings()['AUTH_DOWNLOAD_DIR']).parent / '_session_outputs' / user['session_id'] / secrets.token_hex(16)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    return str(directory / name)


def login(username, password, db_path=None):
    # 비밀번호만으로 Streamlit 세션을 발급하는 기존 진입점을 허용하지 않음.
    return False


def logout():
    token = get_session_token()
    try:
        if token:
            get_service().revoke_session(token)
    finally:
        st.session_state.clear()


def show_login_page():
    from ui_components import render_login_screen
    import sys
    render_login_screen(sys.modules[__name__])


def show_user_info_sidebar():
    from ui_components import render_sidebar_user_simple
    render_sidebar_user_simple()


def render_session_monitor():
    # 주기 검사는 마지막 활동 시간을 갱신하지 않음.
    @st.fragment(run_every='15s')
    def monitor():
        if not is_session_valid():
            st.rerun(scope='app')
    monitor()


# 2026-10-14 hoyeon.han: 이전 비밀번호 단독/메모리 인증 구현 보존 (실행하지 않음).
# # auth.py
# # 2025-12-17 hoyeon.han
# # Streamlit 인증 모듈
#
# import streamlit as st
# from datetime import datetime, timedelta
# from typing import Optional
# import logging
# from pathlib import Path
# import sys
#
# # 프로젝트 루트
# project_root = Path(__file__).parent.parent
#
# # 2025-12-17 hoyeon.han: user_db.py를 직접 로드 (Src/__init__.py 우회)
# import importlib.util
# spec = importlib.util.spec_from_file_location(
#     "user_db",
#     Path(__file__).parent / "user_db.py"
# )
# user_db_module = importlib.util.module_from_spec(spec)
# spec.loader.exec_module(user_db_module)
# UserDB = user_db_module.UserDB
#
# logger = logging.getLogger(__name__)
#
# # 세션 만료 시간 (12시간)
# SESSION_TIMEOUT = timedelta(hours=12)
#
#
# def init_session_state():
#     """세션 상태 초기화"""
#     if 'authenticated' not in st.session_state:
#         st.session_state.authenticated = False
#     if 'username' not in st.session_state:
#         st.session_state.username = None
#     if 'user_info' not in st.session_state:
#         st.session_state.user_info = None
#     if 'login_time' not in st.session_state:
#         st.session_state.login_time = None
#
#
# def is_session_valid() -> bool:
#     """
#     세션 유효성 검사
#
#     Returns:
#         세션 유효 여부
#     """
#     if not st.session_state.authenticated:
#         return False
#
#     if st.session_state.login_time is None:
#         return False
#
#     # 세션 만료 체크
#     elapsed = datetime.now() - st.session_state.login_time
#     if elapsed > SESSION_TIMEOUT:
#         logger.info(f"Session expired for user: {st.session_state.username}")
#         return False
#
#     return True
#
#
# def login(username: str, password: str, db_path: str = "database/users.db") -> bool:
#     """
#     로그인 처리
#
#     Args:
#         username: 사용자 ID
#         password: 비밀번호
#         db_path: 사용자 DB 경로
#
#     Returns:
#         로그인 성공 여부
#     """
#     try:
#         user_db = UserDB(db_path)
#         user = user_db.verify_credentials(username, password)
#
#         if user:
#             # 세션 설정
#             st.session_state.authenticated = True
#             st.session_state.username = user['username']
#             st.session_state.user_info = user
#             st.session_state.login_time = datetime.now()
#
#             logger.info(f"User logged in: {username}")
#             return True
#         else:
#             logger.warning(f"Login failed for user: {username}")
#             return False
#
#     except Exception as e:
#         logger.error(f"Login error: {e}")
#         return False
#
#
# def logout():
#     """로그아웃 처리"""
#     username = st.session_state.get('username', 'unknown')
#     logger.info(f"User logged out: {username}")
#
#     # 세션 초기화
#     st.session_state.authenticated = False
#     st.session_state.username = None
#     st.session_state.user_info = None
#     st.session_state.login_time = None
#
#
# def require_auth(redirect: bool = True) -> bool:
#     """
#     페이지 접근 권한 체크
#
#     Args:
#         redirect: 미인증 시 Home으로 리다이렉트 여부
#
#     Returns:
#         인증 여부
#     """
#     init_session_state()
#
#     if not is_session_valid():
#         if redirect:
#             st.error("🔒 로그인이 필요합니다.")
#             st.info("메인 페이지에서 로그인해주세요.")
#             st.stop()
#         return False
#
#     return True
#
#
# def require_admin(redirect: bool = True) -> bool:
#     """
#     관리자 권한 체크
#
#     Args:
#         redirect: 권한 없을 시 오류 표시 및 중단 여부
#
#     Returns:
#         관리자 여부
#     """
#     if not require_auth(redirect):
#         return False
#
#     user_info = st.session_state.user_info
#     if not user_info or not user_info.get('is_admin', False):
#         if redirect:
#             st.error("🚫 관리자 권한이 필요합니다.")
#             st.stop()
#         return False
#
#     return True
#
#
# def get_current_user() -> Optional[dict]:
#     """
#     현재 로그인한 사용자 정보 조회
#
#     Returns:
#         사용자 정보 또는 None
#     """
#     if is_session_valid():
#         return st.session_state.user_info
#     return None
#
#
# def get_username() -> Optional[str]:
#     """
#     현재 로그인한 사용자 ID 조회
#
#     Returns:
#         사용자 ID 또는 None
#     """
#     if is_session_valid():
#         return st.session_state.username
#     return None
#
#
# def is_admin() -> bool:
#     """
#     현재 사용자가 관리자인지 확인
#
#     Returns:
#         관리자 여부
#     """
#     user = get_current_user()
#     return user and user.get('is_admin', False)
#
#
# def show_login_page():
#     """
#     로그인 페이지 UI 표시
#     Home.py에서 호출
#     """
#     # 2025-12-17 hoyeon.han: 중앙 정렬을 위한 컬럼 사용
#     col1, col2, col3 = st.columns([1, 2, 1])
#
#     with col2:
#         st.markdown("## 🔒 로그인")
#
#     with st.form("login_form"):
#         username = st.text_input(
#             "사용자 ID",
#             placeholder="아이디를 입력하세요",
#             help="등록된 사용자 ID를 입력하세요"
#         )
#         password = st.text_input(
#             "비밀번호",
#             type="password",
#             placeholder="비밀번호를 입력하세요",
#             help="최소 8자 이상"
#         )
#
#         col1, col2 = st.columns([1, 1])
#         with col1:
#             submit = st.form_submit_button("로그인", use_container_width=True, type="primary")
#         with col2:
#             cancel = st.form_submit_button("취소", use_container_width=True)
#
#         if submit:
#             if not username or not password:
#                 st.error("사용자 ID와 비밀번호를 모두 입력하세요.")
#             else:
#                 if login(username, password):
#                     st.success(f"환영합니다, {username}님!")
#                     # 2025-12-17 hoyeon.han: sleep 추가하여 성공 메시지 표시 후 리로드
#                     import time
#                     time.sleep(0.5)
#                     st.rerun()
#                 else:
#                     st.error("사용자 ID 또는 비밀번호가 올바르지 않습니다.")
#
#         if cancel:
#             st.info("로그인이 취소되었습니다.")
#
#     st.divider()
#
#     st.info("""
#     ⚠️ **접근이 제한된 시스템입니다**
#
#     - 등록된 사용자만 접근 가능합니다
#     - 계정이 필요한 경우 시스템 관리자에게 문의하세요
#     - 문의: admin@sollume.com
#     """)
#
#
# def show_user_info_sidebar():
#     """
#     사이드바에 사용자 정보 표시
#     로그인 후 모든 페이지에서 호출
#     """
#     if is_session_valid():
#         user = get_current_user()
#         if user:
#             st.sidebar.divider()
#             st.sidebar.markdown("### 👤 사용자 정보")
#
#             # 사용자 이름 표시
#             full_name = user.get('full_name', user['username'])
#             st.sidebar.write(f"**{full_name}**")
#
#             if user.get('is_admin'):
#                 st.sidebar.caption("🔑 관리자")
#
#             # 로그인 시간 표시
#             if st.session_state.login_time:
#                 login_time_str = st.session_state.login_time.strftime('%Y-%m-%d %H:%M')
#                 st.sidebar.caption(f"🕐 {login_time_str}")
#
#             # 세션 만료까지 남은 시간
#             elapsed = datetime.now() - st.session_state.login_time
#             remaining = SESSION_TIMEOUT - elapsed
#             hours = int(remaining.total_seconds() // 3600)
#             minutes = int((remaining.total_seconds() % 3600) // 60)
#             st.sidebar.caption(f"⏱️ 세션 만료: {hours}시간 {minutes}분 후")
#
#             st.sidebar.divider()
#
#             # 로그아웃 버튼
#             if st.sidebar.button("🚪 로그아웃", use_container_width=True):
#                 logout()
#                 st.rerun()
