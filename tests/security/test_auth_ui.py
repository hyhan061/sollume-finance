# 2026-11-05 hoyeon.han: 재사용 검증 소스를 tests의 보안·운영 테스트로 분리한다.
"""2026-10-14 hoyeon.han: 실제 Streamlit 화면을 임시 DB와 AppTest로 검증한다.

요청의 쿠키 어댑터만 주입한다. 로그인/MFA는 실제 SecurityService를 사용하며
브라우저 HTTP 쿠키·CSRF는 test_auth_gateway.py에서 별도로 검증한다.
이 테스트가 실제 Nginx 또는 WebSocket 검증을 대신하지 않는다.
"""
from __future__ import annotations

from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import pyotp
import pytest
from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest
import streamlit.runtime.context as request_context

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Src"))
from security_service import SecurityError, SecurityService
import auth

class UIEnvironment(SimpleNamespace):
    # 2026-10-14 hoyeon.han: 테스트 실패 출력에도 임시 인증 비밀값을 노출하지 않는다.
    def __repr__(self):
        return "<임시 사용자관리 UI 검증 환경>"


INITIAL_PASSWORD = "UI initial employee phrase 492!"
NEW_PASSWORD = "UI replacement employee phrase 305!"


def _enroll(service, user, clock):
    code = service.issue_enrollment_local(user["id"])
    challenge = service.begin_login(user["username"], INITIAL_PASSWORD)
    secret = service.prepare_enrollment(challenge["token"], code)
    token = service.complete_login(challenge["token"], pyotp.TOTP(secret).at(clock[0]), new_password=NEW_PASSWORD)
    return token, secret


@pytest.fixture
def ui_env(tmp_path, monkeypatch):
    # 2026-10-14 hoyeon.han: 상대 경로의 업무 디렉터리까지 tmp로 분리한다.
    monkeypatch.chdir(tmp_path)
    key = Fernet.generate_key().decode("ascii")
    settings = {
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # "AUTH_ENV": "production", "AUTH_PUBLIC_ORIGIN": "https://sollumeesthe.com",
        "AUTH_ENV": "production", "AUTH_PUBLIC_ORIGIN": "https://office1.sollumeesthe.com",
        "AUTH_ENCRYPTION_KEY": key, "AUTH_DB_PATH": str(tmp_path / "database/users.db"),
        "AUTH_DOWNLOAD_DIR": str(tmp_path / "downloads"), "TRUSTED_PROXY_NETWORKS": "127.0.0.1/32",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    for name in ("AUTH_DEV_APP_ORIGIN", "AUTH_SIGNING_KEY"):
        monkeypatch.delenv(name, raising=False)
    auth._service.cache_clear()
    clock = [time.time()]
    monkeypatch.setattr(SecurityService, "_now", staticmethod(lambda: clock[0]))
    service = SecurityService(settings["AUTH_DB_PATH"], key, settings["AUTH_DOWNLOAD_DIR"])
    administrator = service.bootstrap_user("ui.admin", INITIAL_PASSWORD, full_name="테스트 관리자", is_admin=True)
    admin_token, admin_secret = _enroll(service, administrator, clock)
    staff = service.bootstrap_user("ui.staff", INITIAL_PASSWORD, full_name="테스트 직원", is_admin=False, permissions=["daily-voucher", "order-summary"])
    staff_token, staff_secret = _enroll(service, staff, clock)
    cookie = SimpleCookie()
    current = [admin_token]

    def injected_request():
        cookie.clear()
        if current[0]:
            cookie["__Host-sollume_session"] = current[0]
        return SimpleNamespace(cookies=cookie)

    monkeypatch.setattr(request_context, "_get_request", injected_request)
    yield UIEnvironment(service=service, clock=clock, current=current, admin=administrator,
                          admin_token=admin_token, admin_secret=admin_secret,
                          staff=staff, staff_token=staff_token, staff_secret=staff_secret)
    auth._service.cache_clear()


def _element(elements, label):
    return next(element for element in elements if element.label == label)


def _labels(at):
    return {element.proto.label for element in at.sidebar.get("page_link")}


def _assert_no_exception(at):
    assert not at.exception, [exception.message for exception in at.exception]


def _home(env):
    at = AppTest.from_file(ROOT / "Home.py", default_timeout=10).run()
    _assert_no_exception(at)
    return at


def _users(env):
    at = _home(env)
    at.switch_page("pages/users.py").run()
    _assert_no_exception(at)
    assert "직원 추가" in [tab.label for tab in at.tabs]
    return at


def test_admin_can_open_real_user_management_and_create_staff_permissions(ui_env):
    at = _users(ui_env)
    assert "사용자관리" in _labels(at) and "시스템 관리" in _labels(at)
    _element(at.text_input, "직원 아이디").set_value("new.account")
    _element(at.text_input, "이름").set_value("새로운 직원")
    _element(at.text_input, "이메일").set_value("staff@example.test")
    _element(at.text_input, "임시 비밀번호").set_value(INITIAL_PASSWORD)
    _element(at.text_input, "임시 비밀번호 확인").set_value(INITIAL_PASSWORD)
    _element(at.multiselect, "허용할 업무 화면").set_value(["period-voucher", "settlement-seller"])
    _element(at.button, "직원 계정 생성").click().run()
    _assert_no_exception(at)
    assert any("계정이 생성되었습니다" in result.value for result in at.success)
    created = ui_env.service.get_user_local("new.account")
    assert created["full_name"] == "새로운 직원" and created["email"] == "staff@example.test"
    assert created["permissions"] == ["period-voucher", "settlement-seller"]
    assert not created["is_admin"] and not created["mfa_enrolled"] and created["must_change_password"]
    assert any(len(block.value) > 20 for block in at.code)
    assert ui_env.service.get_user_local("ui.admin")["is_admin"]
    assert ui_env.service.get_user_local("ui.staff")["permissions"] == ["daily-voucher", "order-summary"]


def test_staff_menu_contains_only_assigned_screens_and_direct_admin_pages_stop(ui_env):
    ui_env.current[0] = ui_env.staff_token
    at = _home(ui_env)
    assert _labels(at) == {"일별 전표", "요약"}
    for filename in ("users.py", "system.py", "period_voucher.py"):
        direct = AppTest.from_file(ROOT / "pages" / filename, default_timeout=10).run()
        _assert_no_exception(direct)
        assert any("접근 권한이 없습니다" in error.value for error in direct.error)
        assert not direct.dataframe and not direct.button


def test_all_business_pages_fail_before_exposing_data_when_no_screen_permission(ui_env):
    ui_env.service.update_user_local(ui_env.staff["id"], permissions=[])
    ui_env.clock[0] += 30
    challenge = ui_env.service.begin_login("ui.staff", NEW_PASSWORD)
    ui_env.current[0] = ui_env.service.complete_login(challenge["token"], pyotp.TOTP(ui_env.staff_secret).at(ui_env.clock[0]))
    at = _home(ui_env)
    assert _labels(at) == set()
    for filename in ("daily_voucher.py", "period_voucher.py", "vendor_voucher.py", "settlement.py", "settlement_seller.py", "settlement_ecount.py", "order_summary.py", "order_compare.py", "customers.py", "system.py"):
        direct = AppTest.from_file(ROOT / "pages" / filename, default_timeout=10).run()
        _assert_no_exception(direct)
        assert any("접근 권한이 없습니다" in error.value for error in direct.error), filename
        assert not direct.dataframe and not direct.button, filename


def test_admin_changes_permissions_in_form_and_old_staff_session_is_cleared(ui_env):
    ui_env.current[0] = ui_env.staff_token
    old = _home(ui_env)
    old.session_state["last_result"] = {"sales_file": "private-staff-result.xls"}
    old.session_state["settlement_output_path"] = "private-staff-settlement.xlsx"
    ui_env.current[0] = ui_env.admin_token
    at = _users(ui_env)
    _element(at.selectbox, "설정할 직원").set_value(ui_env.staff["id"]).run()
    _element(at.multiselect, "직원에게 허용할 화면").set_value(["settlement"])
    _element(at.button, "계정과 화면 권한 저장").click().run()
    _assert_no_exception(at)
    assert ui_env.service.get_user_local("ui.staff")["permissions"] == ["settlement"]
    with pytest.raises(SecurityError):
        ui_env.service.get_session(ui_env.staff_token)
    ui_env.current[0] = ui_env.staff_token
    old.run()
    _assert_no_exception(old)
    assert "last_result" not in old.session_state.filtered_state
    assert "settlement_output_path" not in old.session_state.filtered_state
    assert _labels(old) == set()
    assert any("로그인 화면으로 이동" in element.value for element in old.markdown)


def test_admin_suspension_form_revokes_existing_staff_and_clears_data(ui_env):
    ui_env.current[0] = ui_env.staff_token
    old = _home(ui_env)
    old.session_state["search_results"] = ["기밀 거래처"]
    ui_env.current[0] = ui_env.admin_token
    at = _users(ui_env)
    _element(at.selectbox, "설정할 직원").set_value(ui_env.staff["id"]).run()
    _element(at.checkbox, "계정 활성").uncheck()
    _element(at.button, "계정과 화면 권한 저장").click().run()
    _assert_no_exception(at)
    assert not ui_env.service.get_user_local("ui.staff")["is_active"]
    ui_env.current[0] = ui_env.staff_token
    old.run()
    _assert_no_exception(old)
    assert "search_results" not in old.session_state.filtered_state
    assert _labels(old) == set()


def test_account_switch_and_logout_clear_previous_business_state(ui_env):
    at = _home(ui_env)
    for key in ("last_result", "settlement_output_path", "search_results", "_secure_downloads", "uploaded_file"):
        at.session_state[key] = "old administrator private accounting data"
    ui_env.current[0] = ui_env.staff_token
    at.run()
    _assert_no_exception(at)
    assert at.session_state["user_info"]["username"] == "ui.staff"
    assert _labels(at) == {"일별 전표", "요약"}
    for key in ("last_result", "settlement_output_path", "search_results", "_secure_downloads", "uploaded_file"):
        assert key not in at.session_state.filtered_state
    at.session_state["last_result"] = "private staff accounting data"
    ui_env.current[0] = ""
    at.run()
    _assert_no_exception(at)
    assert "last_result" not in at.session_state.filtered_state
    assert "user_info" not in at.session_state.filtered_state
    assert _labels(at) == set()


def test_admin_ui_requires_recent_reauthentication_for_changes(ui_env):
    ui_env.clock[0] += 301
    at = _users(ui_env)
    _element(at.text_input, "직원 아이디").set_value("not.created")
    _element(at.text_input, "임시 비밀번호").set_value(INITIAL_PASSWORD)
    _element(at.text_input, "임시 비밀번호 확인").set_value(INITIAL_PASSWORD)
    _element(at.button, "직원 계정 생성").click().run()
    _assert_no_exception(at)
    assert any("다시 인증하세요" in error.value for error in at.error)
    assert ui_env.service.get_user_local("not.created") is None
    _element(at.text_input, "관리자 비밀번호").set_value(NEW_PASSWORD)
    _element(at.text_input, "인증 앱 번호").set_value(pyotp.TOTP(ui_env.admin_secret).at(ui_env.clock[0]))
    _element(at.button, "재인증").click().run()
    _assert_no_exception(at)
    assert any("재인증이 완료" in success.value for success in at.success)
    _element(at.text_input, "직원 아이디").set_value("now.created")
    _element(at.text_input, "임시 비밀번호").set_value(INITIAL_PASSWORD)
    _element(at.text_input, "임시 비밀번호 확인").set_value(INITIAL_PASSWORD)
    _element(at.button, "직원 계정 생성").click().run()
    _assert_no_exception(at)
    assert ui_env.service.get_user_local("now.created") is not None


def test_staff_can_use_assigned_voucher_page_without_admin_navigation(ui_env):
    # 2026-10-14 hoyeon.han: page_link에는 AppTest 클릭 API가 없어 렌더된 링크의 실제 hash로 이동한다.
    ui_env.current[0] = ui_env.staff_token
    at = _home(ui_env)
    link = next(element for element in at.sidebar.get("page_link") if element.proto.label == "일별 전표")
    at._page_hash = link.proto.page_script_hash
    at.run()
    _assert_no_exception(at)
    assert any(button.label == "▶️ 처리" for button in at.button)
    assert not any("접근 권한이 없습니다" in error.value for error in at.error)
    assert not any(button.label == "⚙️ 시스템 관리로 이동" for button in at.button)



def test_legacy_memory_login_flags_do_not_authorize_without_cookie(ui_env):
    # 2026-10-14 hoyeon.han: 기존 authenticated/user_info 메모리 값만으로 업무 접근할 수 없다.
    ui_env.current[0] = ""
    at = _home(ui_env)
    at.session_state["authenticated"] = True
    at.session_state["username"] = "ui.admin"
    at.session_state["user_info"] = {"username": "ui.admin", "is_admin": True}
    at.run()
    _assert_no_exception(at)
    assert _labels(at) == set()
    assert any("로그인 화면으로 이동" in element.value for element in at.markdown)
    direct = AppTest.from_file(ROOT / "pages/users.py", default_timeout=10).run()
    _assert_no_exception(direct)
    assert any("로그인이 만료되었거나 접근이 차단" in error.value for error in direct.error)
    assert not direct.button and not direct.dataframe


def test_last_active_administrator_cannot_be_disabled_in_real_form(ui_env):
    # 2026-10-14 hoyeon.han: 관리자 화면의 실수로 모든 관리자를 정지하지 못한다.
    at = _users(ui_env)
    _element(at.selectbox, "설정할 직원").set_value(ui_env.admin["id"]).run()
    _element(at.checkbox, "계정 활성").uncheck()
    _element(at.button, "계정과 화면 권한 저장").click().run()
    _assert_no_exception(at)
    assert any("마지막 활성 관리자" in error.value for error in at.error)
    assert ui_env.service.get_user_local("ui.admin")["is_active"]
    assert ui_env.service.get_session(ui_env.admin_token)["is_admin"]


def _output_app(payload):
    # 2026-10-14 hoyeon.han: 실제 출력 경로 helper를 Streamlit 세션 안에서 호출한다.
    return AppTest.from_string(
        "from pathlib import Path\nimport streamlit as st\nimport auth\n"
        "output = auth.unique_output_path('same-accounting.xls', 'daily-voucher')\n"
        f"Path(output).write_bytes({payload!r})\n"
        "st.session_state['written_output'] = output\n"
        "st.text('출력 저장 완료')\n",
        default_timeout=10,
    )


def test_same_filename_outputs_are_separated_by_staff_and_generation(ui_env):
    first = _output_app(b"generic admin output A").run()
    _assert_no_exception(first)
    path_a = Path(first.session_state["written_output"])
    original = path_a.read_bytes()
    ui_env.current[0] = ui_env.staff_token
    second = _output_app(b"generic staff output B").run()
    _assert_no_exception(second)
    path_b = Path(second.session_state["written_output"])
    assert path_a.name == path_b.name == "same-accounting.xls"
    assert path_a != path_b
    assert path_a.read_bytes() == original == b"generic admin output A"
    assert path_b.read_bytes() == b"generic staff output B"
    assert ui_env.service.get_session(ui_env.admin_token)["session_id"] in path_a.parts
    assert ui_env.service.get_session(ui_env.staff_token)["session_id"] in path_b.parts
    ui_env.current[0] = ui_env.admin_token
    first.run()
    _assert_no_exception(first)
    path_a2 = Path(first.session_state["written_output"])
    assert path_a2 != path_a and path_a.read_bytes() == original


@pytest.mark.parametrize("blocked", ["revoked", "no_cookie", "permission_changed"])
def test_output_creation_is_blocked_after_session_or_permission_revocation(ui_env, blocked):
    ui_env.current[0] = ui_env.staff_token
    at = _output_app(b"generic placeholder output").run()
    _assert_no_exception(at)
    root = Path(ui_env.service.download_dir).parent / "_session_outputs"
    previous_paths = set(root.rglob("*"))
    if blocked == "revoked":
        ui_env.service.revoke_session(ui_env.staff_token)
    elif blocked == "no_cookie":
        ui_env.current[0] = ""
    else:
        ui_env.service.update_user_local(ui_env.staff["id"], permissions=[])
    at.run()
    _assert_no_exception(at)
    assert at.error
    assert "written_output" not in at.session_state.filtered_state
    assert set(root.rglob("*")) == previous_paths
