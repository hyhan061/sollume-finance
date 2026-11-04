"""2026-10-14 hoyeon.han: 전용 인증 서버와 회계앱이 공유하는 인증·권한 로직.

모듈 import 시 DB/계정/키를 생성하지 않는다. 웹 관리 API에는 검증된
관리자 세션이 필요하며, 이름에 local이 있는 API와 bootstrap은 서버 운영자
CLI 전용이다. 기존 데이터는 열 추가 방식으로 보존한다.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import time

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
PAGE_PERMISSIONS = {
    "daily-voucher": "일별 전표",
    "period-voucher": "기간 전표",
    "vendor-voucher": "특정업체 전표",
    "settlement": "정산서 생성",
    "settlement-seller": "정산서 생성(셀러)",
    "settlement-ecount": "정산서 생성(이카운트)",
    "order-summary": "요약",
    "order-compare": "비교",
    "customers": "거래처 관리",
}
ADMIN_PAGES = frozenset({"system", "users"})
PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
_DUMMY_HASH = None


class SecurityError(ValueError):
    """사용자에게 표시할 수 있는 비밀정보 없는 오류."""

    @property
    def message(self):
        return str(self)


class SecurityService:
    CHALLENGE_SECONDS = 300
    SESSION_SECONDS = 8 * 60 * 60
    IDLE_SECONDS = 30 * 60
    RECENT_AUTH_SECONDS = 300
    LOCK_SECONDS = 15 * 60
    ENROLLMENT_SECONDS = 24 * 60 * 60
    DOWNLOAD_SECONDS = 15 * 60
    MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

    def __init__(self, db_path=None, encryption_key=None, download_dir=None):
        global _DUMMY_HASH
        self.db_path = str(db_path or ROOT / "database" / "users.db")
        self.download_dir = Path(download_dir or ROOT / "processed" / "secure_downloads")
        key = encryption_key or os.environ.get("AUTH_ENCRYPTION_KEY", "")
        try:
            self._cipher = Fernet(key.encode("ascii") if isinstance(key, str) else key)
        except (ValueError, TypeError, UnicodeError) as exc:
            raise SecurityError("인증 암호화키 설정이 없거나 올바르지 않습니다. 서버 관리자에게 확인하세요.") from exc
        if _DUMMY_HASH is None:
            _DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @staticmethod
    def _now():
        return time.time()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @contextmanager
    def _transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _migrate(self):
        # 2026-10-14 hoyeon.han: 최초 이전 직전 일관된 SQLite 백업을 1회 보관.
        with self._transaction() as conn:
            legacy = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
            migrated = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='security_meta'").fetchone()
            if legacy and not migrated:
                backup_path = Path(self.db_path + ".pre-security.bak")
                if not backup_path.exists():
                    temporary = str(backup_path) + "." + secrets.token_hex(8) + ".tmp"
                    try:
                        with sqlite3.connect(self.db_path) as source, sqlite3.connect(temporary) as destination:
                            source.backup(destination)
                        os.chmod(temporary, 0o600)
                        os.replace(temporary, backup_path)
                    finally:
                        if Path(temporary).exists():
                            Path(temporary).unlink()
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL, full_name VARCHAR(100), email VARCHAR(100),
                is_active BOOLEAN DEFAULT 1, is_admin BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_login TIMESTAMP,
                login_count INTEGER DEFAULT 0)""")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
            additions = {
                "permissions": "TEXT NOT NULL DEFAULT '[]'",
                "must_change_password": "INTEGER NOT NULL DEFAULT 1",
                "mfa_enrolled": "INTEGER NOT NULL DEFAULT 0",
                "mfa_secret_cipher": "TEXT",
                "last_totp_step": "INTEGER NOT NULL DEFAULT -1",
                "session_version": "INTEGER NOT NULL DEFAULT 1",
            }
            for name, definition in additions.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
                    if name == "permissions" and legacy:
                        conn.execute("UPDATE users SET permissions=? WHERE is_admin=0", (json.dumps(list(PAGE_PERMISSIONS)),))
            conn.execute("""CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ip_address VARCHAR(50),
                success BOOLEAN DEFAULT 1, FOREIGN KEY(user_id) REFERENCES users(id))""")
            conn.execute("CREATE TABLE IF NOT EXISTS security_meta (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO security_meta VALUES (1, ?)", (self._now(),))
            conn.execute("""CREATE TABLE IF NOT EXISTS security_challenges (
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, version INTEGER NOT NULL,
                expires_at REAL NOT NULL, ip_address TEXT NOT NULL,
                enrollment_verified INTEGER NOT NULL DEFAULT 0, pending_secret TEXT,
                enrollment_hash TEXT, FOREIGN KEY(user_id) REFERENCES users(id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS security_sessions (
                id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL,
                version INTEGER NOT NULL, auth_time REAL NOT NULL, last_seen REAL NOT NULL,
                recent_auth REAL NOT NULL, revoked_at REAL, FOREIGN KEY(user_id) REFERENCES users(id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS security_enrollments (
                code_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at REAL NOT NULL,
                consumed_at REAL, FOREIGN KEY(user_id) REFERENCES users(id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS security_attempts (
                bucket TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
                window_started REAL NOT NULL, locked_until REAL NOT NULL DEFAULT 0)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS security_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
                actor_id INTEGER, target_id INTEGER, action TEXT NOT NULL,
                outcome TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}')""")
            conn.execute("""CREATE TABLE IF NOT EXISTS security_downloads (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, session_id TEXT NOT NULL,
                page_id TEXT NOT NULL, admin_only INTEGER NOT NULL, filename TEXT NOT NULL,
                mime TEXT NOT NULL, expires_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id))""")

    @staticmethod
    def _digest(value):
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _username(username, creating=False):
        username = str(username).strip()
        if not username or len(username) > 50 or (creating and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{2,49}", username)):
            raise SecurityError("아이디는 영문·숫자로 시작하는 3~50자이며 . _ @ -를 사용할 수 있습니다.")
        return username

    @staticmethod
    def validate_password(password, username=""):
        if not isinstance(password, str) or len(password) < 12 or len(password.encode("utf-8")) > 1024:
            raise SecurityError("비밀번호는 12자 이상으로 설정하세요. 너무 긴 비밀번호는 사용할 수 없습니다.")
        normalized = password.casefold()
        known = {"password1234", "password1234!", "password123!", "administrator", "admin12345678", "admin123456!",
                 "123456789012", "qwerty123456", "qwerty123456!", "changeme12345", "sollume123456", "sollume1234!"}
        if normalized in known or len(set(normalized)) < 4 or (username and normalized == username.casefold()):
            raise SecurityError("추측하기 쉬운 기본 비밀번호는 사용할 수 없습니다. 긴 문장 형태의 새 비밀번호를 설정하세요.")

    @staticmethod
    def hash_password(password):
        SecurityService.validate_password(password)
        return PASSWORD_HASHER.hash(password)

    @staticmethod
    def verify_password(password, stored_hash):
        if not isinstance(password, str) or len(password.encode("utf-8")) > 1024:
            try:
                PASSWORD_HASHER.verify(_DUMMY_HASH or PASSWORD_HASHER.hash("dummy-no-access-password"), "invalid-input")
            except VerificationError:
                pass
            return False
        try:
            if stored_hash.startswith("$argon2"):
                return PASSWORD_HASHER.verify(stored_hash, password)
            if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
                # 2026-10-14 hoyeon.han: 기존 bcrypt 저장 방식의 72바이트 경계 유지.
                return bcrypt.checkpw(password.encode("utf-8")[:72], stored_hash.encode("ascii"))
        except (VerificationError, InvalidHashError, ValueError, TypeError):
            return False
        return False

    def _public(self, row):
        result = {key: row[key] for key in ("id", "username", "full_name", "email", "created_at", "last_login", "login_count")}
        result.update(is_active=bool(row["is_active"]), is_admin=bool(row["is_admin"]),
                      mfa_enrolled=bool(row["mfa_enrolled"]), must_change_password=bool(row["must_change_password"]),
                      permissions=json.loads(row["permissions"]))
        return result

    def _audit(self, conn, action, actor_id=None, target_id=None, outcome="success", detail=None):
        conn.execute("INSERT INTO security_audit (created_at,actor_id,target_id,action,outcome,detail) VALUES (?,?,?,?,?,?)",
                     (self._now(), actor_id, target_id, action, outcome, json.dumps(detail or {}, ensure_ascii=False)))

    def _buckets(self, username, ip):
        return ["account:" + self._digest(username.casefold()), "ip:" + self._digest(ip or "unknown")]

    def _guard_attempts(self, conn, username, ip):
        now = self._now()
        for bucket in self._buckets(username, ip):
            row = conn.execute("SELECT * FROM security_attempts WHERE bucket=?", (bucket,)).fetchone()
            if row and row["locked_until"] > now:
                raise SecurityError("로그인 시도가 제한되었습니다. 15분 후 다시 시도하거나 관리자에게 확인하세요.")

    def _deny_auth(self, conn, username, ip, user=None, action="login_failed"):
        now = self._now()
        for bucket in self._buckets(username, ip):
            row = conn.execute("SELECT * FROM security_attempts WHERE bucket=?", (bucket,)).fetchone()
            failures = row["failures"] + 1 if row and now - row["window_started"] < self.LOCK_SECONDS else 1
            started = row["window_started"] if row and now - row["window_started"] < self.LOCK_SECONDS else now
            locked = now + self.LOCK_SECONDS if failures >= 5 else 0
            conn.execute("INSERT OR REPLACE INTO security_attempts VALUES (?,?,?,?)", (bucket, failures, started, locked))
        if user is not None:
            conn.execute("INSERT INTO login_history (user_id,ip_address,success) VALUES (?,?,0)", (user["id"], ip[:100]))
        self._audit(conn, action, target_id=user["id"] if user else None, outcome="denied")
        conn.commit()  # 실패 이력과 잠금을 유지한 뒤 사용자 오류를 반환한다.
        raise SecurityError("인증 정보가 올바르지 않거나 계정을 사용할 수 없습니다.")

    def begin_login(self, username, password, ip_address=""):
        username = str(username).strip()[:50]
        ip_address = str(ip_address)[:100]
        with self._transaction() as conn:
            self._guard_attempts(conn, username, ip_address)
            user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            stored = user["password_hash"] if user else _DUMMY_HASH
            valid = self.verify_password(password, stored)
            if not valid or not user or not user["is_active"]:
                self._deny_auth(conn, username, ip_address, user)
            token = secrets.token_urlsafe(32)
            now = self._now()
            conn.execute("DELETE FROM security_challenges WHERE expires_at<=?", (now,))
            conn.execute("INSERT INTO security_challenges (token_hash,user_id,version,expires_at,ip_address) VALUES (?,?,?,?,?)",
                         (self._digest(token), user["id"], user["session_version"], now + self.CHALLENGE_SECONDS, ip_address))
            return {"token": token, "needs_enrollment": not bool(user["mfa_enrolled"]),
                    "must_change_password": bool(user["must_change_password"])}

    def _challenge(self, conn, token):
        challenge = conn.execute("SELECT * FROM security_challenges WHERE token_hash=?", (self._digest(token),)).fetchone()
        if not challenge or challenge["expires_at"] <= self._now():
            raise SecurityError("로그인 절차가 만료되었습니다. 처음부터 다시 로그인하세요.")
        user = conn.execute("SELECT * FROM users WHERE id=?", (challenge["user_id"],)).fetchone()
        if not user or not user["is_active"] or user["session_version"] != challenge["version"]:
            raise SecurityError("로그인 절차가 변경 또는 취소되었습니다. 관리자에게 확인하세요.")
        self._guard_attempts(conn, user["username"], challenge["ip_address"])
        return challenge, user

    def _decrypt(self, encrypted):
        try:
            return self._cipher.decrypt(encrypted.encode("ascii")).decode("ascii")
        except (InvalidToken, ValueError, AttributeError) as exc:
            logger.error("인증 비밀키 복호화 실패: 암호화키 설정을 확인하세요.")
            raise SecurityError("인증 정보를 확인할 수 없습니다. 서버 관리자에게 확인하세요.") from exc

    def get_challenge(self, token):
        with self._transaction() as conn:
            challenge, user = self._challenge(conn, token)
            result = {"username": user["username"], "needs_enrollment": not bool(user["mfa_enrolled"]),
                      "must_change_password": bool(user["must_change_password"])}
            if challenge["enrollment_verified"] and challenge["pending_secret"]:
                result["pending_secret"] = self._decrypt(challenge["pending_secret"])
            return result

    def prepare_enrollment(self, challenge_token, enrollment_code):
        with self._transaction() as conn:
            challenge, user = self._challenge(conn, challenge_token)
            if user["mfa_enrolled"]:
                raise SecurityError("인증 앱이 이미 등록되어 있습니다.")
            code_hash = self._digest(str(enrollment_code).strip())
            proof = conn.execute("SELECT * FROM security_enrollments WHERE code_hash=? AND user_id=?",
                                 (code_hash, user["id"])).fetchone()
            if not proof or proof["consumed_at"] is not None or proof["expires_at"] <= self._now():
                self._deny_auth(conn, user["username"], challenge["ip_address"], user, "enrollment_failed")
            secret = self._decrypt(challenge["pending_secret"]) if challenge["pending_secret"] else base64.b32encode(secrets.token_bytes(20)).decode("ascii")
            encrypted = self._cipher.encrypt(secret.encode("ascii")).decode("ascii")
            conn.execute("UPDATE security_challenges SET enrollment_verified=1,pending_secret=?,enrollment_hash=? WHERE token_hash=?",
                         (encrypted, code_hash, challenge["token_hash"]))
            return secret

    @staticmethod
    def _totp(secret, step):
        digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
        offset = digest[-1] & 15
        number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000
        return f"{number:06d}"

    def _otp_step(self, secret, otp):
        otp = str(otp).strip()
        if not re.fullmatch(r"[0-9]{6}", otp):
            return None
        current = int(self._now() // 30)
        for step in (current, current - 1, current + 1):
            if hmac.compare_digest(self._totp(secret, step), otp):
                return step
        return None

    def complete_login(self, challenge_token, otp, new_password=None, ip_address=""):
        with self._transaction() as conn:
            challenge, user = self._challenge(conn, challenge_token)
            if user["must_change_password"]:
                self.validate_password(new_password, user["username"])
                if self.verify_password(new_password, user["password_hash"]):
                    raise SecurityError("초기 비밀번호와 다른 새 비밀번호를 설정하세요.")
            proof = None
            if not user["mfa_enrolled"]:
                if not challenge["enrollment_verified"] or not challenge["pending_secret"]:
                    self._deny_auth(conn, user["username"], challenge["ip_address"], user, "mfa_failed")
                proof = conn.execute("SELECT * FROM security_enrollments WHERE code_hash=? AND user_id=?",
                                     (challenge["enrollment_hash"], user["id"])).fetchone()
                if not proof or proof["consumed_at"] is not None or proof["expires_at"] <= self._now():
                    self._deny_auth(conn, user["username"], challenge["ip_address"], user, "enrollment_failed")
                secret = self._decrypt(challenge["pending_secret"])
            else:
                secret = self._decrypt(user["mfa_secret_cipher"])
            step = self._otp_step(secret, otp)
            if step is None or step <= user["last_totp_step"]:
                self._deny_auth(conn, user["username"], challenge["ip_address"], user, "mfa_failed")
            now = self._now()
            if user["must_change_password"]:
                conn.execute("UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?",
                             (PASSWORD_HASHER.hash(new_password), user["id"]))
            if proof is not None:
                conn.execute("UPDATE security_enrollments SET consumed_at=? WHERE code_hash=?", (now, challenge["enrollment_hash"]))
                conn.execute("UPDATE users SET mfa_secret_cipher=?,mfa_enrolled=1 WHERE id=?", (challenge["pending_secret"], user["id"]))
            conn.execute("UPDATE users SET last_totp_step=?,last_login=CURRENT_TIMESTAMP,login_count=COALESCE(login_count,0)+1 WHERE id=?",
                         (step, user["id"]))
            version = user["session_version"]
            if user["must_change_password"] or proof is not None:
                # 최초 등록/비밀번호 변경 전 발급된 다른 challenge도 폐기한다.
                self._revoke_all(conn, user["id"])
                version += 1
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO security_sessions (id,token_hash,user_id,version,auth_time,last_seen,recent_auth) VALUES (?,?,?,?,?,?,?)",
                         (secrets.token_hex(16), self._digest(token), user["id"], version, now, now, now))
            conn.execute("DELETE FROM security_challenges WHERE token_hash=?", (challenge["token_hash"],))
            # 2026-10-14 hoyeon.han: 계정 버킷만 초기화. IP의 다른 계정 공격 이력은 유지.
            conn.execute("DELETE FROM security_attempts WHERE bucket=?", (self._buckets(user["username"], challenge["ip_address"])[0],))
            conn.execute("INSERT INTO login_history (user_id,ip_address,success) VALUES (?,?,1)", (user["id"], (ip_address or challenge["ip_address"])[:100]))
            self._audit(conn, "login", actor_id=user["id"], target_id=user["id"])
            return token

    def _session(self, conn, token, touch=False):
        session = conn.execute("SELECT * FROM security_sessions WHERE token_hash=?", (self._digest(token),)).fetchone()
        now = self._now()
        if not session or session["revoked_at"] is not None or now - session["auth_time"] >= self.SESSION_SECONDS or now - session["last_seen"] >= self.IDLE_SECONDS:
            raise SecurityError("로그인이 만료되었거나 해제되었습니다. 다시 로그인하세요.")
        user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not user or not user["is_active"] or not user["mfa_enrolled"] or user["must_change_password"] or user["session_version"] != session["version"]:
            raise SecurityError("계정 또는 권한이 변경되었습니다. 다시 로그인하거나 관리자에게 확인하세요.")
        if touch:
            conn.execute("UPDATE security_sessions SET last_seen=? WHERE id=?", (now, session["id"]))
        result = self._public(user)
        result.update(session_id=session["id"], auth_time=session["auth_time"])
        return result, session

    def get_session(self, token, touch=False):
        with self._transaction() as conn:
            return self._session(conn, token, touch)[0]

    def revoke_session(self, token):
        with self._transaction() as conn:
            session = conn.execute("SELECT * FROM security_sessions WHERE token_hash=?", (self._digest(token),)).fetchone()
            if session:
                conn.execute("UPDATE security_sessions SET revoked_at=? WHERE id=?", (self._now(), session["id"]))
                self._audit(conn, "logout", actor_id=session["user_id"], target_id=session["user_id"])

    def _permission(self, user, page_id):
        if page_id not in PAGE_PERMISSIONS and page_id not in ADMIN_PAGES and page_id not in {"home", "account"}:
            raise SecurityError("등록되지 않은 화면 권한입니다.")
        if page_id in {"home", "account"} or user["is_admin"]:
            return
        if page_id in ADMIN_PAGES or page_id not in user["permissions"]:
            raise SecurityError("이 화면 또는 작업에 접근할 권한이 없습니다. 관리자에게 확인하세요.")

    def require_permission(self, token, page_id):
        with self._transaction() as conn:
            user, _ = self._session(conn, token, touch=True)
            try:
                self._permission(user, page_id)
            except SecurityError:
                self._audit(conn, "access", actor_id=user["id"], target_id=user["id"], outcome="denied", detail={"page": page_id})
                conn.commit()
                raise
            return user

    def _admin(self, conn, token, writing=False):
        actor, session = self._session(conn, token)
        if not actor["is_admin"]:
            self._audit(conn, "admin_access", actor_id=actor["id"], outcome="denied")
            conn.commit()
            raise SecurityError("관리자만 사용할 수 있는 기능입니다.")
        if writing and self._now() - session["recent_auth"] > self.RECENT_AUTH_SECONDS:
            self._audit(conn, "admin_recent_auth", actor_id=actor["id"], outcome="denied")
            conn.commit()
            raise SecurityError("중요한 변경 전에 비밀번호와 인증 앱 번호로 다시 인증하세요.")
        return actor

    @contextmanager
    def _management(self, actor_token, action, target_id=None):
        # 2026-10-14 hoyeon.han: 실패한 관리자 변경도 수행자·대상·결과를 기록.
        with self._transaction() as conn:
            actor = self._admin(conn, actor_token, writing=True)
            try:
                yield conn, actor
            except SecurityError:
                conn.rollback()
                conn.execute("BEGIN IMMEDIATE")
                self._audit(conn, action, actor_id=actor["id"], target_id=target_id, outcome="denied")
                conn.commit()
                raise

    def reauthenticate(self, token, password, otp):
        with self._transaction() as conn:
            public, session = self._session(conn, token)
            user = conn.execute("SELECT * FROM users WHERE id=?", (public["id"],)).fetchone()
            self._guard_attempts(conn, user["username"], "reauth:" + session["id"])
            valid = self.verify_password(password, user["password_hash"])
            step = self._otp_step(self._decrypt(user["mfa_secret_cipher"]), otp)
            if not valid or step is None or step <= user["last_totp_step"]:
                self._deny_auth(conn, user["username"], "reauth:" + session["id"], user, "reauth_failed")
            conn.execute("UPDATE users SET last_totp_step=? WHERE id=?", (step, user["id"]))
            conn.execute("UPDATE security_sessions SET recent_auth=?,last_seen=? WHERE id=?", (self._now(), self._now(), session["id"]))
            self._audit(conn, "reauthenticate", actor_id=user["id"], target_id=user["id"])
            return self._public(user)

    @staticmethod
    def _permissions(permissions):
        if permissions is None:
            return []
        if not isinstance(permissions, (list, tuple, set)) or any(p not in PAGE_PERMISSIONS for p in permissions):
            raise SecurityError("직원에게 부여할 업무 화면 권한을 올바르게 선택하세요.")
        return sorted(set(permissions))

    def _new_user(self, conn, username, password, full_name, email, is_admin, permissions, actor_id):
        username = self._username(username, creating=True)
        self.validate_password(password, username)
        permissions = self._permissions(permissions)
        try:
            cursor = conn.execute("INSERT INTO users (username,password_hash,full_name,email,is_admin,permissions) VALUES (?,?,?,?,?,?)",
                                  (username, PASSWORD_HASHER.hash(password), str(full_name)[:100], str(email)[:100], int(bool(is_admin)), json.dumps(permissions)))
        except sqlite3.IntegrityError as exc:
            raise SecurityError("이미 사용 중인 아이디입니다.") from exc
        self._audit(conn, "create_user", actor_id=actor_id, target_id=cursor.lastrowid)
        return self._public(conn.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())

    def admin_create_user(self, actor_token, username, password, full_name="", email="", is_admin=False, permissions=None):
        with self._management(actor_token, "create_user") as (conn, actor):
            return self._new_user(conn, username, password, full_name, email, is_admin, permissions, actor["id"])

    def bootstrap_user(self, username, password, full_name="", email="", is_admin=True, permissions=None):
        """서버 운영자 CLI 전용. HTTP 경로에 연결하면 안 된다."""
        with self._transaction() as conn:
            return self._new_user(conn, username, password, full_name, email, is_admin, permissions, None)

    def _target(self, conn, user_id):
        user = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
        if not user:
            raise SecurityError("사용자를 찾을 수 없습니다.")
        return user

    def _revoke_all(self, conn, user_id):
        conn.execute("UPDATE users SET session_version=session_version+1 WHERE id=?", (user_id,))
        conn.execute("UPDATE security_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (self._now(), user_id))
        conn.execute("DELETE FROM security_challenges WHERE user_id=?", (user_id,))

    def _update_user(self, conn, user_id, actor_id, full_name=None, email=None, is_active=None, is_admin=None, permissions=None):
        user = self._target(conn, user_id)
        new_active = bool(user["is_active"]) if is_active is None else bool(is_active)
        new_admin = bool(user["is_admin"]) if is_admin is None else bool(is_admin)
        if user["is_admin"] and user["is_active"] and (not new_active or not new_admin):
            count = conn.execute("SELECT COUNT(*) FROM users WHERE is_active=1 AND is_admin=1").fetchone()[0]
            if count <= 1:
                self._audit(conn, "update_user", actor_id=actor_id, target_id=user_id, outcome="denied", detail={"reason": "last_admin"})
                conn.commit()
                raise SecurityError("마지막 활성 관리자는 정지하거나 일반 직원으로 변경할 수 없습니다.")
        allowed = json.loads(user["permissions"]) if permissions is None else self._permissions(permissions)
        conn.execute("UPDATE users SET full_name=?,email=?,is_active=?,is_admin=?,permissions=? WHERE id=?",
                     (user["full_name"] if full_name is None else str(full_name)[:100], user["email"] if email is None else str(email)[:100],
                      int(new_active), int(new_admin), json.dumps(allowed), user_id))
        if new_active != bool(user["is_active"]) or new_admin != bool(user["is_admin"]) or allowed != json.loads(user["permissions"]):
            self._revoke_all(conn, user_id)
        self._audit(conn, "update_user", actor_id=actor_id, target_id=user_id,
                    detail={"is_active": new_active, "is_admin": new_admin, "permissions": allowed})
        return self._public(self._target(conn, user_id))

    def admin_update_user(self, actor_token, user_id, full_name=None, email=None, is_active=None, is_admin=None, permissions=None):
        with self._management(actor_token, "update_user", user_id) as (conn, actor):
            return self._update_user(conn, user_id, actor["id"], full_name, email, is_active, is_admin, permissions)

    def update_user_local(self, user_id, full_name=None, email=None, is_active=None, is_admin=None, permissions=None):
        with self._transaction() as conn:
            return self._update_user(conn, user_id, None, full_name, email, is_active, is_admin, permissions)

    def _issue_enrollment(self, conn, user_id, actor_id):
        self._target(conn, user_id)
        self._revoke_all(conn, user_id)
        conn.execute("UPDATE users SET mfa_enrolled=0,mfa_secret_cipher=NULL,last_totp_step=-1 WHERE id=?", (user_id,))
        conn.execute("DELETE FROM security_enrollments WHERE user_id=?", (user_id,))
        code = secrets.token_urlsafe(24)
        conn.execute("INSERT INTO security_enrollments (code_hash,user_id,expires_at) VALUES (?,?,?)",
                     (self._digest(code), user_id, self._now() + self.ENROLLMENT_SECONDS))
        self._audit(conn, "issue_enrollment", actor_id=actor_id, target_id=user_id)
        return code

    def admin_issue_enrollment(self, actor_token, user_id):
        with self._management(actor_token, "issue_enrollment", user_id) as (conn, actor):
            return self._issue_enrollment(conn, user_id, actor["id"])

    def issue_enrollment_local(self, user_id):
        with self._transaction() as conn:
            return self._issue_enrollment(conn, user_id, None)

    def _reset_password(self, conn, user_id, new_password, actor_id):
        user = self._target(conn, user_id)
        self.validate_password(new_password, user["username"])
        conn.execute("UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?", (PASSWORD_HASHER.hash(new_password), user_id))
        self._revoke_all(conn, user_id)
        self._audit(conn, "reset_password", actor_id=actor_id, target_id=user_id)

    def admin_reset_password(self, actor_token, user_id, new_password):
        with self._management(actor_token, "reset_password", user_id) as (conn, actor):
            self._reset_password(conn, user_id, new_password, actor["id"])

    def reset_password_local(self, user_id, new_password):
        with self._transaction() as conn:
            self._reset_password(conn, user_id, new_password, None)

    def admin_unlock_user(self, actor_token, user_id):
        with self._management(actor_token, "unlock_user", user_id) as (conn, actor):
            user = self._target(conn, user_id)
            conn.execute("DELETE FROM security_attempts WHERE bucket=?", (self._buckets(user["username"], "")[0],))
            self._audit(conn, "unlock_user", actor_id=actor["id"], target_id=user_id)

    def list_users(self, actor_token):
        with self._transaction() as conn:
            self._admin(conn, actor_token)
            return [self._public(r) for r in conn.execute("SELECT * FROM users ORDER BY id")]

    def list_users_local(self):
        with self._transaction() as conn:
            return [self._public(r) for r in conn.execute("SELECT * FROM users ORDER BY id")]

    def get_user_local(self, username):
        with self._transaction() as conn:
            user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return self._public(user) if user else None

    def list_audit(self, actor_token, limit=100):
        with self._transaction() as conn:
            self._admin(conn, actor_token)
            rows = conn.execute("SELECT * FROM security_audit ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
            return [dict(r) for r in rows]

    def change_own_password(self, token, current_password, new_password, otp):
        with self._transaction() as conn:
            public, session = self._session(conn, token)
            user = self._target(conn, public["id"])
            self._guard_attempts(conn, user["username"], "reauth:" + session["id"])
            self.validate_password(new_password, user["username"])
            valid = self.verify_password(current_password, user["password_hash"])
            step = self._otp_step(self._decrypt(user["mfa_secret_cipher"]), otp)
            if not valid or step is None or step <= user["last_totp_step"]:
                self._deny_auth(conn, user["username"], "reauth:" + session["id"], user, "change_password_failed")
            if self.verify_password(new_password, user["password_hash"]):
                raise SecurityError("기존 비밀번호와 다른 새 비밀번호를 설정하세요.")
            conn.execute("UPDATE users SET password_hash=?,last_totp_step=?,must_change_password=0 WHERE id=?",
                         (PASSWORD_HASHER.hash(new_password), step, user["id"]))
            self._revoke_all(conn, user["id"])
            self._audit(conn, "change_password", actor_id=user["id"], target_id=user["id"])

    def _cleanup_downloads(self, conn):
        # 2026-10-14 hoyeon.han: 만료·폐기된 행과 그 행의 무작위 불변 파일만 정리.
        now = self._now()
        expired = conn.execute("""SELECT d.id FROM security_downloads d
            LEFT JOIN security_sessions s ON d.session_id=s.id
            LEFT JOIN users u ON d.user_id=u.id
            WHERE d.expires_at<=? OR s.id IS NULL OR s.revoked_at IS NOT NULL
               OR u.is_active=0 OR s.version!=u.session_version
               OR s.auth_time<=? OR s.last_seen<=? LIMIT 200""",
                               (now, now - self.SESSION_SECONDS, now - self.IDLE_SECONDS)).fetchall()
        for row in expired:
            grant_id = row["id"]
            if re.fullmatch(r"[0-9a-f]{48}", grant_id):
                try:
                    (self.download_dir / grant_id).unlink(missing_ok=True)
                except OSError:
                    logger.warning("만료 다운로드 파일 정리에 실패했습니다. 파일 권한을 확인하세요.")
                    continue
            conn.execute("DELETE FROM security_downloads WHERE id=?", (grant_id,))

    def register_download(self, token, data, filename, mime, page_id, admin_only=False):
        if not isinstance(data, bytes) or len(data) > self.MAX_DOWNLOAD_BYTES:
            raise SecurityError("다운로드 파일 형식 또는 크기가 올바르지 않습니다. 파일은 100MB 이하여야 합니다.")
        filename = re.sub(r'[\x00-\x1f\x7f/\\"\r\n]', "_", str(filename)).strip(" .")[:180] or "다운로드.xlsx"
        mime = str(mime)
        if not re.fullmatch(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+", mime):
            raise SecurityError("다운로드 파일 형식이 올바르지 않습니다.")
        with self._transaction() as conn:
            user, session = self._session(conn, token, touch=True)
            self._permission(user, page_id)
            if admin_only and not user["is_admin"]:
                raise SecurityError("관리자만 내려받을 수 있는 파일입니다.")
            self._cleanup_downloads(conn)
            self.download_dir.mkdir(parents=True, exist_ok=True)
            grant_id = secrets.token_hex(24)
            path = self.download_dir / grant_id
            try:
                with path.open("xb") as output:
                    os.chmod(path, 0o600)
                    output.write(data)
                conn.execute("INSERT INTO security_downloads VALUES (?,?,?,?,?,?,?,?)",
                             (grant_id, user["id"], session["id"], page_id, int(bool(admin_only)), filename, mime, self._now() + self.DOWNLOAD_SECONDS))
            except Exception:
                path.unlink(missing_ok=True)
                raise
            self._audit(conn, "register_download", actor_id=user["id"], detail={"page": page_id})
            return grant_id

    def get_download(self, token, download_id):
        if not re.fullmatch(r"[0-9a-f]{48}", str(download_id)):
            raise SecurityError("다운로드 파일을 찾을 수 없거나 권한이 없습니다.")
        with self._transaction() as conn:
            user, session = self._session(conn, token, touch=True)
            grant = conn.execute("SELECT * FROM security_downloads WHERE id=?", (download_id,)).fetchone()
            if not grant or grant["user_id"] != user["id"] or grant["session_id"] != session["id"]:
                self._reject_download(conn, user, "다운로드 파일을 찾을 수 없거나 권한이 없습니다.")
            if grant["expires_at"] <= self._now():
                conn.execute("DELETE FROM security_downloads WHERE id=? AND user_id=? AND session_id=?", (download_id, user["id"], session["id"]))
                (self.download_dir / download_id).unlink(missing_ok=True)
                self._reject_download(conn, user, "다운로드 시간이 만료되었습니다. 파일을 다시 생성하세요.")
            try:
                self._permission(user, grant["page_id"])
            except SecurityError as exc:
                self._reject_download(conn, user, str(exc))
            if grant["admin_only"] and not user["is_admin"]:
                self._reject_download(conn, user, "관리자만 내려받을 수 있는 파일입니다.")
            path = self.download_dir / download_id
            if not path.is_file():
                raise SecurityError("다운로드 파일을 찾을 수 없습니다. 파일을 다시 생성하세요.")
            self._audit(conn, "download", actor_id=user["id"], detail={"page": grant["page_id"]})
            return {"path": str(path), "filename": grant["filename"], "mime": grant["mime"]}

    def _reject_download(self, conn, user, message):
        self._audit(conn, "download", actor_id=user["id"], target_id=user["id"], outcome="denied")
        conn.commit()
        raise SecurityError(message)
