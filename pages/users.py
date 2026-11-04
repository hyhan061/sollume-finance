# 2026-10-14 hoyeon.han: 관리자 전용 직원 계정·화면 권한·인증 복구 관리.
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))
import auth
from security_service import PAGE_PERMISSIONS, SecurityError
from ui_theme import render_page_header

auth.require_admin()
service = auth.get_service()
token = auth.get_session_token()
current = auth.get_current_user()
render_page_header("사용자관리", "직원 계정과 화면 접근 권한, 인증 복구 및 변경 이력을 관리합니다.", icon="👥")

with st.expander("중요한 변경 전 관리자 재인증"):
    st.caption("로그인 또는 재인증 후 5분 동안 관리 변경을 할 수 있습니다. 이미 사용한 인증 번호는 다음 번호로 바뀐 뒤 입력하세요.")
    with st.form("user_management_reauthenticate", clear_on_submit=True):
        password = st.text_input("관리자 비밀번호", type="password")
        code = st.text_input("인증 앱 번호", max_chars=6)
        if st.form_submit_button("재인증"):
            try:
                service.reauthenticate(token, password, code)
                st.success("관리자 재인증이 완료되었습니다.")
            except SecurityError as error:
                st.error(str(error))

users = service.list_users(token)
display = pd.DataFrame(users)
if not display.empty:
    columns = [name for name in ("username", "full_name", "email", "is_active", "is_admin", "mfa_enrolled", "must_change_password", "last_login") if name in display]
    st.dataframe(display[columns].rename(columns={"username": "아이디", "full_name": "이름", "email": "이메일", "is_active": "활성", "is_admin": "관리자", "mfa_enrolled": "2단계 인증 등록", "must_change_password": "비밀번호 변경 필요", "last_login": "최근 로그인"}), hide_index=True, use_container_width=True)

create_tab, edit_tab, history_tab = st.tabs(["직원 추가", "계정·접근 권한 설정", "변경 이력"])
with create_tab:
    with st.form("create_staff_user", clear_on_submit=True):
        username = st.text_input("직원 아이디", max_chars=50)
        full_name = st.text_input("이름", max_chars=100)
        email = st.text_input("이메일", max_chars=100)
        temporary_password = st.text_input("임시 비밀번호", type="password", help="12자 이상. 직원이 최초 등록할 때 새 비밀번호로 변경합니다.")
        confirmation = st.text_input("임시 비밀번호 확인", type="password")
        administrator = st.checkbox("관리자 권한 부여", value=False)
        permissions = st.multiselect("허용할 업무 화면", options=list(PAGE_PERMISSIONS), format_func=PAGE_PERMISSIONS.get)
        st.caption("관리자는 모든 화면에 접근합니다. 일반 직원은 선택한 화면만 접근하며, 시스템 관리·사용자관리는 항상 차단됩니다.")
        submitted = st.form_submit_button("직원 계정 생성", type="primary")
        if submitted:
            try:
                if temporary_password != confirmation:
                    raise SecurityError("임시 비밀번호와 확인 입력이 일치하지 않습니다.")
                new_user = service.admin_create_user(token, username, temporary_password, full_name, email, administrator, permissions)
                invitation = service.admin_issue_enrollment(token, new_user["id"])
                st.success("계정이 생성되었습니다. 임시 비밀번호와 등록 코드를 해당 직원에게 안전하게 전달하세요.")
                st.code(invitation, language=None)
                st.caption("등록 코드는 24시간 동안 유효하며 한 번만 사용할 수 있습니다. 최초 로그인 후 인증 앱 등록을 완료해야 업무를 이용할 수 있습니다.")
            except SecurityError as error:
                st.error(str(error))

with edit_tab:
    if users:
        selected_id = st.selectbox("설정할 직원", options=[user["id"] for user in users],
                                   format_func=lambda uid: next(f"{user['username']} · {user.get('full_name') or ''}" for user in users if user["id"] == uid))
        selected = next(user for user in users if user["id"] == selected_id)
        with st.form(f"edit_user_{selected_id}"):
            full_name = st.text_input("이름", value=selected.get("full_name") or "", max_chars=100)
            email = st.text_input("이메일", value=selected.get("email") or "", max_chars=100)
            active = st.checkbox("계정 활성", value=bool(selected["is_active"]))
            administrator = st.checkbox("관리자", value=bool(selected["is_admin"]))
            permissions = st.multiselect("직원에게 허용할 화면", options=list(PAGE_PERMISSIONS),
                                          default=selected.get("permissions", []), format_func=PAGE_PERMISSIONS.get)
            st.caption("권한·활성 상태를 변경하면 해당 직원의 기존 로그인과 다운로드 권한이 폐기됩니다. 마지막 활성 관리자는 정지하거나 일반 직원으로 변경할 수 없습니다.")
            if st.form_submit_button("계정과 화면 권한 저장", type="primary"):
                try:
                    service.admin_update_user(token, selected_id, full_name=full_name, email=email,
                                              is_active=active, is_admin=administrator, permissions=permissions)
                    st.rerun()
                except SecurityError as error:
                    st.error(str(error))

        st.divider()
        st.caption("잠금 해제는 반복 입력 실패 제한을 해제합니다. 인증 앱 초기화는 기존 인증과 모든 로그인을 폐기하고 재등록 코드를 발급합니다.")
        if st.button("로그인 잠금 해제", key=f"unlock_{selected_id}"):
            try:
                service.admin_unlock_user(token, selected_id)
                # 2026-10-14 hoyeon.han: 계정 잠금 해제와 공유 IP 제한의 차이를 안내.
                # st.success("계정의 로그인 잠금이 해제되었습니다.")
                st.success("계정의 로그인 잠금이 해제되었습니다. 같은 접속 IP의 반복 실패 제한은 최대 15분 동안 유지될 수 있습니다.")
            except SecurityError as error:
                st.error(str(error))
        reset_confirm = st.checkbox("해당 직원의 본인을 확인했고 인증 앱을 재등록하겠습니다", key=f"reset_mfa_confirm_{selected_id}")
        if selected_id == current["id"]:
            st.info("본인 인증 앱 초기화는 다른 관리자 또는 서버 운영자의 로컬 관리 명령으로 진행하세요.")
        if st.button("인증 앱 초기화·등록 코드 발급", disabled=not reset_confirm or selected_id == current["id"], key=f"reset_mfa_{selected_id}"):
            try:
                invitation = service.admin_issue_enrollment(token, selected_id)
                st.code(invitation, language=None)
                st.caption("24시간 유효한 일회용 등록 코드입니다. 해당 직원에게 안전하게 전달하세요.")
            except SecurityError as error:
                st.error(str(error))
        with st.form(f"reset_password_{selected_id}", clear_on_submit=True):
            new_password = st.text_input("새 임시 비밀번호", type="password")
            confirm_password = st.text_input("새 임시 비밀번호 확인", type="password")
            if st.form_submit_button("비밀번호 초기화", disabled=selected_id == current["id"]):
                try:
                    if new_password != confirm_password:
                        raise SecurityError("비밀번호 확인이 일치하지 않습니다.")
                    service.admin_reset_password(token, selected_id, new_password)
                    st.success("기존 로그인이 해제되었습니다. 직원에게 새 임시 비밀번호를 안전하게 전달하세요.")
                except SecurityError as error:
                    st.error(str(error))

with history_tab:
    audit = service.list_audit(token, limit=100)
    if audit:
        st.dataframe(pd.DataFrame(audit), hide_index=True, use_container_width=True)
    else:
        st.info("변경 이력이 없습니다.")
