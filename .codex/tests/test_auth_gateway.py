"""2026-10-14 hoyeon.han: 임시 DB로 인증 HTTP·쿠키·다운로드 차단을 검증한다."""

from __future__ import annotations

import re
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pyotp
import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Src"))
from auth_gateway import create_app, load_security_settings, session_cookie_name
from security_service import SecurityError, SecurityService


# 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
# ORIGIN = "https://sollumeesthe.com"
ORIGIN = "https://office1.sollumeesthe.com"
INITIAL_PASSWORD = "Initial test phrase 914!"
NEW_PASSWORD = "Changed test phrase 739!"


@pytest.fixture
def env(tmp_path, monkeypatch):
    # 2026-10-14 hoyeon.han: 테스트는 실제 사용자 DB·키·회계 파일을 사용하지 않는다.
    for name in ("AUTH_ENV", "AUTH_PUBLIC_ORIGIN", "AUTH_ENCRYPTION_KEY", "AUTH_SIGNING_KEY", "AUTH_DEV_APP_ORIGIN", "TRUSTED_PROXY_NETWORKS"):
        monkeypatch.delenv(name, raising=False)
    key = Fernet.generate_key().decode("ascii")
    config = {
        "AUTH_ENV": "production", "AUTH_PUBLIC_ORIGIN": ORIGIN,
        "AUTH_ENCRYPTION_KEY": key, "AUTH_DB_PATH": str(tmp_path / "users.db"),
        "AUTH_DOWNLOAD_DIR": str(tmp_path / "downloads"), "TESTING": True,
    }
    service = SecurityService(config["AUTH_DB_PATH"], key, config["AUTH_DOWNLOAD_DIR"])
    clock = [time.time()]
    monkeypatch.setattr(service, "_now", lambda: clock[0])
    user = service.bootstrap_user("staff.one", INITIAL_PASSWORD, full_name="직원 1", is_admin=False, permissions=["daily-voucher"])
    app = create_app(config, service=service)
    return SimpleNamespace(app=app, client=app.test_client(), service=service, config=config, clock=clock, user=user)


def _get(env, path, client=None, **kwargs):
    return (client or env.client).get(path, base_url=ORIGIN, **kwargs)


def _csrf(response):
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
    assert match, response.status_code
    return match.group(1)


def _post(env, path, values, *, get_path=None, client=None, headers=None, **kwargs):
    client = client or env.client
    nonce = _csrf(_get(env, get_path or path, client))
    return client.post(
        path, base_url=ORIGIN, data={"csrf_token": nonce, **values},
        headers=headers or {"Origin": ORIGIN}, **kwargs,
    )


def _cookie(env, name="__Host-sollume_session", client=None):
    # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
    # cookie = (client or env.client).get_cookie(name, domain="sollumeesthe.com")
    cookie = (client or env.client).get_cookie(name, domain="office1.sollumeesthe.com")
    return cookie.value if cookie else None


def _enroll(env, user=None, client=None):
    user = user or env.user
    client = client or env.client
    code = env.service.issue_enrollment_local(user["id"])
    response = _post(env, "/auth/login", {"username": user["username"], "password": INITIAL_PASSWORD}, client=client)
    assert response.status_code == 303 and response.location == "/auth/enroll"
    response = _post(env, "/auth/enroll", {"stage": "prepare", "enrollment_code": code}, client=client)
    assert response.status_code == 303
    token = _cookie(env, "__Host-sollume_challenge", client)
    secret = env.service.get_challenge(token)["pending_secret"]
    response = _post(env, "/auth/enroll", {
        "stage": "complete", "otp": pyotp.TOTP(secret).at(env.clock[0]),
        "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
    }, client=client)
    assert response.status_code == 303 and response.location == ORIGIN + "/"
    return secret, _cookie(env, client=client), response


def _download(env, token):
    return env.service.register_download(token, b"private accounting content", "정산서.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "daily-voucher")


def test_password_only_and_unproved_enrollment_cannot_access_data(env):
    response = _post(env, "/auth/login", {"username": "staff.one", "password": INITIAL_PASSWORD})
    assert response.location == "/auth/enroll"
    assert _cookie(env) is None
    assert _get(env, "/auth/check").status_code == 401
    assert _get(env, "/downloads/" + "a" * 48).status_code == 401
    page = _get(env, "/auth/enroll").get_data(as_text=True)
    assert "일회용 등록 코드" in page
    assert "data:image/svg+xml" not in page
    response = _post(env, "/auth/enroll", {"stage": "complete", "otp": "000000", "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD})
    assert response.status_code == 303
    assert _cookie(env) is None
    assert "pending_secret" not in env.service.get_challenge(_cookie(env, "__Host-sollume_challenge"))


def test_enrollment_and_mfa_login_cookie_security(env):
    secret, token, response = _enroll(env)
    assert env.service.get_session(token)["username"] == "staff.one"
    assert _get(env, "/auth/check").status_code == 200
    assert _cookie(env, "__Host-sollume_challenge") is None
    cookies = response.headers.getlist("Set-Cookie")
    full_cookie = next(cookie for cookie in cookies if cookie.startswith("__Host-sollume_session="))
    assert all(flag in full_cookie for flag in ("Secure", "HttpOnly", "Path=/", "SameSite=Lax", "Max-Age=28800"))
    assert "Domain=" not in full_cookie
    assert secret not in full_cookie and NEW_PASSWORD not in full_cookie
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_real_mfa_required_after_registration_and_otp_replay_rejected(env):
    secret, token, _ = _enroll(env)
    env.service.revoke_session(token)
    # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
    # env.client.delete_cookie("__Host-sollume_session", domain="sollumeesthe.com")
    env.client.delete_cookie("__Host-sollume_session", domain="office1.sollumeesthe.com")
    response = _post(env, "/auth/login", {"username": "staff.one", "password": NEW_PASSWORD})
    assert response.location == "/auth/mfa"
    response = _post(env, "/auth/mfa", {"otp": pyotp.TOTP(secret).at(env.clock[0])})
    assert response.location == "/auth/mfa" and _cookie(env) is None
    env.clock[0] += 30
    response = _post(env, "/auth/mfa", {"otp": pyotp.TOTP(secret).at(env.clock[0])})
    assert response.location == ORIGIN + "/"
    assert _get(env, "/auth/check").status_code == 200


@pytest.mark.parametrize("path", ["/auth/login", "/auth/mfa", "/auth/enroll", "/auth/logout", "/auth/account"])
def test_all_state_changing_routes_require_csrf(env, path):
    response = env.client.post(path, base_url=ORIGIN, data={"username": "staff.one", "password": INITIAL_PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 400
    assert _cookie(env) is None


def test_cross_site_origin_is_blocked_even_with_correct_csrf(env):
    response = _post(env, "/auth/login", {"username": "staff.one", "password": INITIAL_PASSWORD}, headers={"Origin": "https://attacker.example"})
    assert response.status_code == 400
    assert _cookie(env, "__Host-sollume_challenge") is None


def test_signed_csrf_cookie_cannot_be_forged(env):
    nonce = _csrf(_get(env, "/auth/login"))
    # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
    # env.client.set_cookie("__Host-sollume_csrf", "tampered-signature", domain="sollumeesthe.com", secure=True)
    env.client.set_cookie("__Host-sollume_csrf", "tampered-signature", domain="office1.sollumeesthe.com", secure=True)
    response = env.client.post("/auth/login", base_url=ORIGIN, data={"csrf_token": nonce, "username": "staff.one", "password": INITIAL_PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 400


def test_wrong_host_and_external_internal_check_are_rejected(env):
    assert env.client.get("/auth/login", base_url="https://attacker.example").status_code == 400
    assert _get(env, "/auth/check", environ_overrides={"REMOTE_ADDR": "198.51.100.14"}).status_code == 404
    assert _get(env, "/auth/health", environ_overrides={"REMOTE_ADDR": "198.51.100.14"}).status_code == 404
    assert _get(env, "/auth/health").get_data(as_text=True) == "ok"


def test_untrusted_identity_headers_and_return_urls_cannot_authorize(env):
    response = _get(env, "/auth/check", headers={"X-Authenticated-User": "admin", "X-User-ID": "1", "X-Forwarded-User": "staff.one"})
    assert response.status_code == 401 and "Location" not in response.headers
    _enroll(env)
    response = _get(env, "/auth/login?next=https://attacker.example&return_url=https://attacker.example")
    assert response.location == ORIGIN + "/"


def test_forwarded_ip_is_accepted_only_from_known_proxy(env, monkeypatch):
    original = env.service.begin_login
    captured = []

    def record(username, password, ip_address=""):
        captured.append(ip_address)
        return original(username, password, ip_address)

    monkeypatch.setattr(env.service, "begin_login", record)
    nonce = _csrf(_get(env, "/auth/login"))
    for remote in ("198.51.100.7", "127.0.0.1"):
        env.client.post("/auth/login", base_url=ORIGIN, data={"csrf_token": nonce, "username": "staff.one", "password": INITIAL_PASSWORD},
                        headers={"Origin": ORIGIN, "X-Real-IP": "203.0.113.25"}, environ_overrides={"REMOTE_ADDR": remote})
    assert captured == ["198.51.100.7", "203.0.113.25"]


def test_logout_get_does_not_revoke_and_post_requires_confirmation(env):
    _, token, _ = _enroll(env)
    confirmation = _get(env, "/auth/logout")
    assert confirmation.status_code == 200
    assert env.service.get_session(token)["username"] == "staff.one"
    assert env.client.post("/auth/logout", base_url=ORIGIN).status_code == 400
    response = env.client.post("/auth/logout", base_url=ORIGIN, data={"csrf_token": _csrf(confirmation)}, headers={"Origin": ORIGIN})
    assert response.status_code == 303
    assert _cookie(env) is None
    assert _get(env, "/auth/check").status_code == 401
    with pytest.raises(SecurityError):
        env.service.get_session(token)


def test_download_requires_valid_session_and_exact_owner_session(env):
    _, token, _ = _enroll(env)
    grant = _download(env, token)
    response = _get(env, "/downloads/" + grant)
    assert response.status_code == 200 and response.data == b"private accounting content"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert "no-store" in response.headers["Cache-Control"]
    unauthenticated = env.app.test_client()
    assert _get(env, "/downloads/" + grant, unauthenticated).status_code == 401
    user2 = env.service.bootstrap_user("staff.two", INITIAL_PASSWORD, is_admin=False, permissions=["daily-voucher"])
    other_client = env.app.test_client()
    _enroll(env, user2, other_client)
    assert _get(env, "/downloads/" + grant, other_client).status_code == 403
    env.service.revoke_session(token)
    assert _get(env, "/downloads/" + grant).status_code == 401


def test_download_access_is_revoked_with_permission_or_account_change(env):
    _, token, _ = _enroll(env)
    grant = _download(env, token)
    env.service.update_user_local(env.user["id"], permissions=[])
    assert _get(env, "/downloads/" + grant).status_code == 401
    assert _get(env, "/auth/check").status_code == 401


def test_download_grant_and_session_expiry_are_enforced(env):
    _, token, _ = _enroll(env)
    grant = _download(env, token)
    env.clock[0] += env.service.DOWNLOAD_SECONDS + 1
    assert _get(env, "/downloads/" + grant).status_code == 403
    env.clock[0] += env.service.IDLE_SECONDS + 1
    assert _get(env, "/auth/check").status_code == 401
    assert _get(env, "/downloads/" + grant).status_code == 401


def test_password_change_requires_current_password_and_fresh_otp_then_revokes(env):
    secret, token, _ = _enroll(env)
    grant = _download(env, token)
    env.clock[0] += 30
    next_password = "Replacement staff phrase 506!"
    response = _post(env, "/auth/account", {"current_password": "wrong", "new_password": next_password, "confirm_password": next_password, "otp": pyotp.TOTP(secret).at(env.clock[0])})
    assert response.location == "/auth/account"
    assert _get(env, "/auth/check").status_code == 200
    response = _post(env, "/auth/account", {"current_password": NEW_PASSWORD, "new_password": next_password, "confirm_password": next_password, "otp": pyotp.TOTP(secret).at(env.clock[0])})
    assert response.location == "/auth/login" and _cookie(env) is None
    assert _get(env, "/downloads/" + grant).status_code == 401
    with pytest.raises(SecurityError):
        env.service.get_session(token)


def test_challenge_expires_and_does_not_issue_session(env):
    _post(env, "/auth/login", {"username": "staff.one", "password": INITIAL_PASSWORD})
    env.clock[0] += 301
    response = _get(env, "/auth/enroll")
    assert response.location == "/auth/login"
    assert _cookie(env, "__Host-sollume_challenge") is None
    assert _cookie(env) is None


def test_body_size_limit_and_unexpected_errors_do_not_leak_secrets(env, monkeypatch, caplog):
    nonce = _csrf(_get(env, "/auth/login"))
    response = env.client.post("/auth/login", base_url=ORIGIN, data={"csrf_token": nonce, "password": "x" * 18000}, headers={"Origin": ORIGIN})
    assert response.status_code == 413

    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_SECRET_PASSWORD_OTP")

    monkeypatch.setattr(env.service, "begin_login", fail)
    response = _post(env, "/auth/login", {"username": "staff.one", "password": INITIAL_PASSWORD})
    assert response.status_code == 503
    assert "PRIVATE_SECRET_PASSWORD_OTP" not in response.get_data(as_text=True)
    assert "PRIVATE_SECRET_PASSWORD_OTP" not in caplog.text


# 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
# @pytest.mark.parametrize("origin", ["http://sollumeesthe.com", "https://localhost", "https://sollumeesthe.com/path", "https://sollumeesthe.com?next=x", "https://user:password@sollumeesthe.com", "https://sollumeesthe.com#fragment"])
@pytest.mark.parametrize("origin", ["http://office1.sollumeesthe.com", "https://localhost", "https://office1.sollumeesthe.com/path", "https://office1.sollumeesthe.com?next=x", "https://user:password@office1.sollumeesthe.com", "https://office1.sollumeesthe.com#fragment"])
def test_invalid_production_configuration_fails_closed(env, origin):
    with pytest.raises(ValueError):
        load_security_settings({**env.config, "AUTH_PUBLIC_ORIGIN": origin})


def test_development_accepts_only_loopback_and_redirects_to_fixed_local_app(env):
    dev_config = {**env.config, "AUTH_ENV": "development", "AUTH_PUBLIC_ORIGIN": "http://localhost:8503"}
    app = create_app(dev_config, env.service)
    client = app.test_client()
    page = client.get("/auth/login", base_url="http://localhost:8503")
    assert page.status_code == 200
    response = client.post("/auth/login", base_url="http://localhost:8503", data={"csrf_token": _csrf(page), "username": "staff.one", "password": INITIAL_PASSWORD}, headers={"Origin": "http://localhost:8503"})
    challenge = next(cookie for cookie in response.headers.getlist("Set-Cookie") if cookie.startswith("sollume_dev_challenge="))
    assert "Secure" not in challenge and "HttpOnly" in challenge
    # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
    # assert client.get("/auth/login", base_url="http://sollumeesthe.com").status_code == 400
    assert client.get("/auth/login", base_url="http://office1.sollumeesthe.com").status_code == 400
    assert session_cookie_name(load_security_settings(dev_config)) == "sollume_dev_session"
    # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
    # for changes in ({"AUTH_PUBLIC_ORIGIN": "http://sollumeesthe.com"}, {"AUTH_DEV_APP_ORIGIN": "https://attacker.example"}):
    for changes in ({"AUTH_PUBLIC_ORIGIN": "http://office1.sollumeesthe.com"}, {"AUTH_DEV_APP_ORIGIN": "https://attacker.example"}):
        with pytest.raises(ValueError):
            load_security_settings({**dev_config, **changes})


def test_http_requires_trusted_https_termination_and_health_stays_internal(env):
    # 2026-10-14 hoyeon.han: TLS 종료 프록시를 가장한 외부 요청은 거부한다.
    # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
    # plain_origin = "http://sollumeesthe.com"
    plain_origin = "http://office1.sollumeesthe.com"
    assert env.client.get("/auth/login", base_url=plain_origin).status_code == 400
    assert env.client.get("/auth/login", base_url=plain_origin, headers={"X-Forwarded-Proto": "https"}, environ_overrides={"REMOTE_ADDR": "198.51.100.14"}).status_code == 400
    assert env.client.get("/auth/login", base_url=plain_origin, headers={"X-Forwarded-Proto": "https"}, environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).status_code == 200
    assert env.client.get("/auth/health", base_url=plain_origin).get_data(as_text=True) == "ok"


def test_stale_and_non_ascii_csrf_input_are_rejected(env):
    # 2026-10-14 hoyeon.han: 만료 nonce와 임의 한글 입력도 예외 노출 없이 거부한다.
    page = _get(env, "/auth/login")
    nonce = _csrf(page)
    response = env.client.post("/auth/login", base_url=ORIGIN, data={"csrf_token": "잘못된입력"}, headers={"Origin": ORIGIN})
    assert response.status_code == 400
    with env.client.session_transaction(base_url=ORIGIN) as csrf_session:
        csrf_session["csrf_issued"] = time.time() - 1801
    response = env.client.post("/auth/login", base_url=ORIGIN, data={"csrf_token": nonce, "username": "staff.one", "password": INITIAL_PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 400


def test_form_headers_preserve_origin_and_production_redirect_stays_same_origin(env):
    # 2026-10-14 hoyeon.han: no-referrer는 Chrome POST Origin=null을 만들어 로그인 자체를 막았다.
    response = _get(env, '/auth/login')
    assert response.headers['Referrer-Policy'] == 'same-origin'
    policy = response.headers['Content-Security-Policy']
    assert "form-action 'self';" in policy
    assert 'localhost' not in policy
    nonce = _csrf(response)
    blocked = env.client.post('/auth/login', base_url=ORIGIN, data={'csrf_token': nonce, 'username': 'staff.one', 'password': INITIAL_PASSWORD}, headers={'Origin': 'null', 'Sec-Fetch-Site': 'same-origin'})
    assert blocked.status_code == 400


def test_development_form_redirect_allows_only_configured_app_origin(env):
    # 2026-10-14 hoyeon.han: MFA POST의 다른 로컬 포트 이동을 CSP에서 고정 주소로만 허용한다.
    origin = 'http://localhost:18703'
    app_origin = 'http://localhost:18701'
    app = create_app({**env.config, 'AUTH_ENV': 'development', 'AUTH_PUBLIC_ORIGIN': origin, 'AUTH_DEV_APP_ORIGIN': app_origin}, env.service)
    response = app.test_client().get('/auth/login', base_url=origin)
    assert response.headers['Referrer-Policy'] == 'same-origin'
    assert "form-action 'self' http://localhost:18701;" in response.headers['Content-Security-Policy']
    assert '*' not in response.headers['Content-Security-Policy']
