# 2026-11-05 hoyeon.han: 재사용 검증 소스를 tests의 보안·운영 테스트로 분리한다.
"""2026-10-14 hoyeon.han: 실제 DB와 분리한 인증·권한·자료 보존 회귀 검증."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys

import bcrypt
from cryptography.fernet import Fernet
import pyotp
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Src"))
from security_service import PAGE_PERMISSIONS, SecurityError, SecurityService

INITIAL = "initial-secret-phrase-2026"
CHANGED = "changed-private-phrase-2026"


@pytest.fixture
def service(tmp_path, monkeypatch):
    result = SecurityService(tmp_path / "users.db", Fernet.generate_key(), tmp_path / "downloads")
    clock = [1800000000.0]
    monkeypatch.setattr(result, "_now", lambda: clock[0])
    result.test_clock = clock
    return result


def enroll(service, username="admin", is_admin=True, permissions=None):
    user = service.bootstrap_user(username, INITIAL, is_admin=is_admin, permissions=permissions)
    code = service.issue_enrollment_local(user["id"])
    challenge = service.begin_login(username, INITIAL, ip_address=username)
    secret = service.prepare_enrollment(challenge["token"], code)
    token = service.complete_login(challenge["token"], pyotp.TOTP(secret).at(service._now()), CHANGED)
    return user, token, secret


def next_login(service, username, secret, ip=None):
    service.test_clock[0] += 30
    challenge = service.begin_login(username, CHANGED, ip_address=ip or username)
    return service.complete_login(challenge["token"], pyotp.TOTP(secret).at(service._now()))


def test_migration_preserves_legacy_ids_hashes_and_history_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.db"
    hashed = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt()).decode()
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,full_name TEXT,email TEXT,is_active INTEGER,is_admin INTEGER,created_at TEXT,last_login TEXT,login_count INTEGER)")
        conn.execute("INSERT INTO users VALUES(7,'employee',?,'직원','e@example.test',1,0,'2025-01-01','2026-01-01',42)", (hashed,))
        conn.execute("CREATE TABLE login_history (id INTEGER PRIMARY KEY,user_id INTEGER,login_time TEXT,ip_address TEXT,success INTEGER)")
        conn.execute("INSERT INTO login_history VALUES(11,7,'2026-01-01','127.0.0.1',1)")
    key = Fernet.generate_key()
    first = SecurityService(path, key, tmp_path / "downloads")
    user = first.get_user_local("employee")
    assert user["id"] == 7 and user["login_count"] == 42
    assert set(user["permissions"]) == set(PAGE_PERMISSIONS)
    assert user["must_change_password"] and not user["mfa_enrolled"]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT password_hash FROM users").fetchone()[0] == hashed
        assert conn.execute("SELECT * FROM login_history").fetchone() == (11, 7, "2026-01-01", "127.0.0.1", 1)
    backup = Path(str(path) + ".pre-security.bak")
    snapshot = backup.read_bytes()
    second = SecurityService(path, key, tmp_path / "downloads")
    assert second.get_user_local("employee") == user
    assert backup.read_bytes() == snapshot
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT password_hash FROM users").fetchone()[0] == hashed
        assert "mfa_enrolled" not in {r[1] for r in conn.execute("PRAGMA table_info(users)")}


def test_password_only_cannot_issue_session_and_secret_requires_registration_proof(service):
    user = service.bootstrap_user("employee", INITIAL, is_admin=False)
    challenge = service.begin_login("employee", INITIAL)
    assert "pending_secret" not in service.get_challenge(challenge["token"])
    with pytest.raises(SecurityError):
        service.get_session(challenge["token"])
    with pytest.raises(SecurityError):
        service.complete_login(challenge["token"], "123456", CHANGED)
    code = service.issue_enrollment_local(user["id"])
    challenge = service.begin_login("employee", INITIAL)
    secret = service.prepare_enrollment(challenge["token"], code)
    assert service.get_challenge(challenge["token"])["pending_secret"] == secret
    token = service.complete_login(challenge["token"], pyotp.TOTP(secret).at(service._now()), CHANGED)
    user = service.get_session(token)
    assert user["permissions"] == []
    assert not {"password_hash", "mfa_secret_cipher", "pending_secret", "token_hash"} & set(user)
    with service._connect() as conn:
        assert conn.execute("SELECT consumed_at FROM security_enrollments").fetchone()[0]
        assert conn.execute("SELECT token_hash FROM security_sessions").fetchone()[0] != token
        assert conn.execute("SELECT mfa_secret_cipher FROM users").fetchone()[0] != secret


def test_first_registration_revokes_other_password_challenges(service):
    user = service.bootstrap_user("employee", INITIAL, is_admin=False)
    code = service.issue_enrollment_local(user["id"])
    old = service.begin_login("employee", INITIAL)
    challenge = service.begin_login("employee", INITIAL)
    secret = service.prepare_enrollment(challenge["token"], code)
    service.complete_login(challenge["token"], pyotp.TOTP(secret).at(service._now()), CHANGED)
    with pytest.raises(SecurityError):
        service.get_challenge(old["token"])


def test_enrollment_code_expires_and_cannot_be_reused(service):
    user = service.bootstrap_user("employee", INITIAL)
    code = service.issue_enrollment_local(user["id"])
    service.test_clock[0] += service.ENROLLMENT_SECONDS + 1
    challenge = service.begin_login("employee", INITIAL)
    with pytest.raises(SecurityError):
        service.prepare_enrollment(challenge["token"], code)
    fresh = service.issue_enrollment_local(user["id"])
    challenge = service.begin_login("employee", INITIAL)
    secret = service.prepare_enrollment(challenge["token"], fresh)
    service.complete_login(challenge["token"], pyotp.TOTP(secret).at(service._now()), CHANGED)
    service.issue_enrollment_local(user["id"])
    challenge = service.begin_login("employee", CHANGED)
    with pytest.raises(SecurityError):
        service.prepare_enrollment(challenge["token"], fresh)


def test_five_password_failures_lock_account_across_ips_and_ip_across_unknown_accounts(service):
    service.bootstrap_user("employee", INITIAL)
    for number in range(5):
        with pytest.raises(SecurityError):
            service.begin_login("employee", "wrong", ip_address=f"ip-{number}")
    with pytest.raises(SecurityError, match="제한"):
        service.begin_login("employee", INITIAL, ip_address="different-ip")
    for number in range(5):
        with pytest.raises(SecurityError):
            service.begin_login(f"missing-{number}", "wrong", ip_address="shared-ip")
    with pytest.raises(SecurityError, match="제한"):
        service.begin_login("another-missing", "wrong", ip_address="shared-ip")
    service.test_clock[0] += service.LOCK_SECONDS + 1
    assert service.begin_login("employee", INITIAL, ip_address="different-ip")["token"]


def test_mfa_failures_persist_across_new_password_challenges(service):
    _, _, secret = enroll(service, "employee", is_admin=False)
    service.test_clock[0] += 30
    wrong = "000000" if pyotp.TOTP(secret).at(service._now()) != "000000" else "000001"
    for number in range(5):
        challenge = service.begin_login("employee", CHANGED, ip_address=f"ip-{number}")
        with pytest.raises(SecurityError):
            service.complete_login(challenge["token"], wrong)
    with pytest.raises(SecurityError, match="제한"):
        service.begin_login("employee", CHANGED, ip_address="fresh-ip")


def test_totp_parallel_use_creates_exactly_one_session(service):
    _, _, secret = enroll(service, "employee", is_admin=False)
    service.test_clock[0] += 30
    challenges = [service.begin_login("employee", CHANGED, ip_address=str(i))["token"] for i in range(2)]
    otp = pyotp.TOTP(secret).at(service._now())
    def complete(challenge):
        try:
            return service.complete_login(challenge, otp)
        except SecurityError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(complete, challenges))
    assert sum(bool(result) for result in results) == 1


def test_admin_permissions_revoke_old_session_and_last_admin_is_protected(service):
    _, admin, _ = enroll(service)
    staff, token, secret = enroll(service, "employee", False, ["daily-voucher"])
    assert service.require_permission(token, "daily-voucher")["id"] == staff["id"]
    for page in ("period-voucher", "system", "users"):
        with pytest.raises(SecurityError):
            service.require_permission(token, page)
    with pytest.raises(SecurityError):
        service.admin_create_user(token, "intruder", INITIAL)
    service.admin_update_user(admin, staff["id"], permissions=["period-voucher"])
    with pytest.raises(SecurityError):
        service.get_session(token)
    token = next_login(service, "employee", secret)
    service.require_permission(token, "period-voucher")
    with pytest.raises(SecurityError):
        service.require_permission(token, "daily-voucher")
    for changes in ({"is_active": False}, {"is_admin": False}):
        with pytest.raises(SecurityError, match="마지막"):
            service.admin_update_user(admin, service.get_session(admin)["id"], **changes)
    service.admin_update_user(admin, staff["id"], is_active=False)
    with pytest.raises(SecurityError):
        service.get_session(token)


def test_concurrent_admin_demotion_keeps_one_active_admin(service):
    first, token_a, _ = enroll(service, "firstadmin")
    second, token_b, _ = enroll(service, "secondadmin")
    def demote(arguments):
        token, user_id = arguments
        try:
            service.admin_update_user(token, user_id, is_admin=False)
            return True
        except SecurityError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(demote, [(token_a, first["id"]), (token_b, second["id"])]))
    assert sum(results) == 1
    assert sum(u["is_active"] and u["is_admin"] for u in service.list_users_local()) == 1


def test_logout_idle_absolute_and_admin_recent_auth_limits(service):
    _, token, secret = enroll(service)
    service.test_clock[0] += service.RECENT_AUTH_SECONDS + 1
    with pytest.raises(SecurityError, match="다시 인증"):
        service.admin_create_user(token, "employee", INITIAL)
    service.reauthenticate(token, CHANGED, pyotp.TOTP(secret).at(service._now()))
    service.admin_create_user(token, "employee", INITIAL)
    service.revoke_session(token)
    with pytest.raises(SecurityError):
        service.get_session(token)
    token = next_login(service, "admin", secret)
    service.test_clock[0] += service.IDLE_SECONDS
    with pytest.raises(SecurityError):
        service.get_session(token, touch=True)
    token = next_login(service, "admin", secret)
    with service._connect() as conn:
        conn.execute("UPDATE security_sessions SET auth_time=? WHERE token_hash=?", (service._now() - service.SESSION_SECONDS, service._digest(token)))
    with pytest.raises(SecurityError):
        service.get_session(token, touch=True)


def test_password_and_mfa_reset_revoke_sessions(service):
    _, admin, _ = enroll(service)
    user, token, _ = enroll(service, "employee", False, ["daily-voucher"])
    service.admin_reset_password(admin, user["id"], "replacement-initial-phrase")
    with pytest.raises(SecurityError):
        service.get_session(token)
    assert service.get_user_local("employee")["must_change_password"]
    service.admin_issue_enrollment(admin, user["id"])
    assert not service.get_user_local("employee")["mfa_enrolled"]


def test_download_checks_owner_session_permission_suspension_expiry_and_logout(service):
    _, admin, _ = enroll(service)
    user, token, secret = enroll(service, "employee", False, ["daily-voucher"])
    _, other, _ = enroll(service, "other", False, ["daily-voucher"])
    grant = service.register_download(token, b"original accounting content", "매출.xls", "application/vnd.ms-excel", "daily-voucher")
    assert Path(service.get_download(token, grant)["path"]).read_bytes() == b"original accounting content"
    with pytest.raises(SecurityError):
        service.get_download(other, grant)
    fresh = next_login(service, "employee", secret)
    with pytest.raises(SecurityError):
        service.get_download(fresh, grant)
    with pytest.raises(SecurityError):
        service.get_download(token, "../../database/users.db")
    service.admin_update_user(admin, user["id"], permissions=[])
    with pytest.raises(SecurityError):
        service.get_download(token, grant)
    service.admin_update_user(admin, user["id"], permissions=["daily-voucher"])
    token = next_login(service, "employee", secret)
    grant = service.register_download(token, b"snapshot", "file.xls", "application/vnd.ms-excel", "daily-voucher")
    service.admin_update_user(admin, user["id"], is_active=False)
    with pytest.raises(SecurityError):
        service.get_download(token, grant)
    service.admin_update_user(admin, user["id"], is_active=True)
    token = next_login(service, "employee", secret)
    grant = service.register_download(token, b"snapshot", "file.xls", "application/vnd.ms-excel", "daily-voucher")
    service.test_clock[0] += service.DOWNLOAD_SECONDS
    with pytest.raises(SecurityError, match="만료"):
        service.get_download(token, grant)
    assert not (service.download_dir / grant).exists()
    grant = service.register_download(token, b"snapshot", "file.xls", "application/vnd.ms-excel", "daily-voucher")
    service.revoke_session(token)
    with pytest.raises(SecurityError):
        service.get_download(token, grant)


def test_audit_and_public_records_do_not_expose_credentials(service):
    _, token, secret = enroll(service)
    user = service.admin_create_user(token, "employee", INITIAL)
    code = service.admin_issue_enrollment(token, user["id"])
    records = json.dumps(service.list_users(token) + service.list_audit(token))
    for sensitive in (INITIAL, CHANGED, code, secret, token, "password_hash", "mfa_secret_cipher"):
        assert sensitive not in records


def test_argon2_accepts_long_non_ascii_password_and_default_is_rejected(service):
    password = "긴비밀번호문장" * 12 + "새로운문장"
    user = service.bootstrap_user("employee", password)
    assert user["id"]
    with service._connect() as conn:
        hashed = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert service.verify_password(password, hashed)
    assert not service.verify_password(password + "다름", hashed)
    with pytest.raises(SecurityError):
        service.bootstrap_user("default", "Password1234!")
    with pytest.raises(SecurityError):
        service.bootstrap_user("weak", "short")


def test_security_key_is_required_before_database_creation(tmp_path):
    with pytest.raises(SecurityError):
        SecurityService(tmp_path / "must-not-create.db", encryption_key="invalid")
    assert not (tmp_path / "must-not-create.db").exists()


def test_cleanup_deletes_only_expired_or_revoked_downloads(service):
    _, admin, _ = enroll(service)
    user_a, token_a, _ = enroll(service, "employee_a", False, ["daily-voucher"])
    _, token_b, _ = enroll(service, "employee_b", False, ["daily-voucher"])
    expired = service.register_download(token_a, b"expired", "expired.xls", "application/vnd.ms-excel", "daily-voucher")
    revoked = service.register_download(token_a, b"revoked", "revoked.xls", "application/vnd.ms-excel", "daily-voucher")
    valid = service.register_download(token_b, b"valid", "valid.xls", "application/vnd.ms-excel", "daily-voucher")
    with service._connect() as conn:
        conn.execute("UPDATE security_downloads SET expires_at=? WHERE id=?", (service._now(), expired))
    service.admin_update_user(admin, user_a["id"], is_active=False)
    service.register_download(token_b, b"new", "new.xls", "application/vnd.ms-excel", "daily-voucher")
    assert not (service.download_dir / expired).exists()
    assert not (service.download_dir / revoked).exists()
    assert Path(service.get_download(token_b, valid)["path"]).read_bytes() == b"valid"


def test_failed_administrator_changes_and_downloads_are_audited(service):
    _, admin, _ = enroll(service)
    _, employee, _ = enroll(service, "employee", False, ["daily-voucher"])
    with pytest.raises(SecurityError):
        service.admin_create_user(admin, "employee", INITIAL)
    with pytest.raises(SecurityError):
        service.admin_reset_password(admin, service.get_session(employee)["id"], "short")
    with pytest.raises(SecurityError):
        service.get_download(employee, "0" * 48)
    denied = {r["action"] for r in service.list_audit(admin) if r["outcome"] == "denied"}
    assert {"create_user", "reset_password", "download"} <= denied


def test_own_password_change_rejects_replay_and_revokes_all_sessions(service):
    _, token_a, secret = enroll(service, "employee", False, ["daily-voucher"])
    token_b = next_login(service, "employee", secret)
    otp = pyotp.TOTP(secret).at(service._now())
    with pytest.raises(SecurityError):
        service.change_own_password(token_a, CHANGED, "second-changed-phrase-2026", otp)
    service.test_clock[0] += 30
    otp = pyotp.TOTP(secret).at(service._now())
    service.change_own_password(token_b, CHANGED, "second-changed-phrase-2026", otp)
    for token in (token_a, token_b):
        with pytest.raises(SecurityError):
            service.get_session(token)
    with pytest.raises(SecurityError):
        service.begin_login("employee", CHANGED, "fresh-ip")
    assert not service.get_user_local("employee")["must_change_password"]


def test_download_rejects_admin_only_registration_for_employee_and_sanitizes_names(service):
    _, token, _ = enroll(service, "employee", False, ["daily-voucher"])
    with pytest.raises(SecurityError):
        service.register_download(token, b"file", "file.xls", "application/vnd.ms-excel", "daily-voucher", admin_only=True)
    grant = service.register_download(token, b"file", "../../secret\r\nHeader:bad.xls", "application/vnd.ms-excel", "daily-voucher")
    result = service.get_download(token, grant)
    assert "/" not in result["filename"] and "\r" not in result["filename"] and "\n" not in result["filename"]
    assert Path(result["path"]).parent == service.download_dir
