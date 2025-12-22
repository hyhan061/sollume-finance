# user_db.py
# 2025-12-17 hoyeon.han
# 사용자 데이터베이스 관리 모듈

import sqlite3
import bcrypt
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class UserDB:
    """사용자 데이터베이스 관리 클래스"""

    def __init__(self, db_path: str = "database/users.db"):
        """
        UserDB 초기화

        Args:
            db_path: 데이터베이스 파일 경로
        """
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_db()

    def _ensure_db_directory(self):
        """데이터베이스 디렉토리 생성"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _init_db(self):
        """데이터베이스 초기화 (테이블 생성)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # users 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(100),
                email VARCHAR(100),
                is_active BOOLEAN DEFAULT 1,
                is_admin BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                login_count INTEGER DEFAULT 0
            )
        """)

        # login_history 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address VARCHAR(50),
                success BOOLEAN DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        conn.commit()
        conn.close()
        logger.info(f"Database initialized: {self.db_path}")

    @staticmethod
    def hash_password(password: str) -> str:
        """
        비밀번호를 bcrypt로 해싱

        Args:
            password: 평문 비밀번호

        Returns:
            해싱된 비밀번호 문자열
        """
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """
        비밀번호 검증

        Args:
            password: 입력된 평문 비밀번호
            hashed: 저장된 해시값

        Returns:
            일치 여부 (True/False)
        """
        try:
            return bcrypt.checkpw(
                password.encode('utf-8'),
                hashed.encode('utf-8')
            )
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False

    def create_user(
        self,
        username: str,
        password: str,
        full_name: str = "",
        email: str = "",
        is_admin: bool = False
    ) -> bool:
        """
        새 사용자 생성

        Args:
            username: 사용자 ID (고유값)
            password: 비밀번호 (평문, 자동으로 해싱됨)
            full_name: 이름
            email: 이메일
            is_admin: 관리자 여부

        Returns:
            생성 성공 여부
        """
        try:
            # 비밀번호 길이 검증
            if len(password) < 8:
                logger.warning(f"Password too short for user: {username}")
                return False

            password_hash = self.hash_password(password)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO users (username, password_hash, full_name, email, is_admin)
                VALUES (?, ?, ?, ?, ?)
            """, (username, password_hash, full_name, email, is_admin))

            conn.commit()
            conn.close()

            logger.info(f"User created: {username}")
            return True

        except sqlite3.IntegrityError:
            logger.warning(f"User already exists: {username}")
            return False
        except Exception as e:
            logger.error(f"Error creating user {username}: {e}")
            return False

    def get_user(self, username: str) -> Optional[Dict]:
        """
        사용자 정보 조회

        Args:
            username: 사용자 ID

        Returns:
            사용자 정보 딕셔너리 또는 None
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM users WHERE username = ?
            """, (username,))

            row = cursor.fetchone()
            conn.close()

            if row:
                return dict(row)
            return None

        except Exception as e:
            logger.error(f"Error getting user {username}: {e}")
            return None

    def verify_credentials(self, username: str, password: str) -> Optional[Dict]:
        """
        로그인 인증 (사용자명 + 비밀번호 검증)

        Args:
            username: 사용자 ID
            password: 비밀번호

        Returns:
            인증 성공 시 사용자 정보, 실패 시 None
        """
        user = self.get_user(username)

        if not user:
            logger.warning(f"Login failed: user not found - {username}")
            return None

        if not user['is_active']:
            logger.warning(f"Login failed: user inactive - {username}")
            return None

        if not self.verify_password(password, user['password_hash']):
            logger.warning(f"Login failed: wrong password - {username}")
            self._log_login_attempt(user['id'], success=False)
            return None

        # 로그인 성공
        self._update_last_login(user['id'])
        self._log_login_attempt(user['id'], success=True)
        logger.info(f"Login successful: {username}")

        return user

    def _update_last_login(self, user_id: int):
        """마지막 로그인 시간 업데이트"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE users
                SET last_login = ?,
                    login_count = login_count + 1
                WHERE id = ?
            """, (datetime.now(), user_id))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error updating last login: {e}")

    def _log_login_attempt(self, user_id: int, success: bool = True, ip_address: str = ""):
        """로그인 이력 기록"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO login_history (user_id, success, ip_address)
                VALUES (?, ?, ?)
            """, (user_id, success, ip_address))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error logging login attempt: {e}")

    def update_user(
        self,
        username: str,
        full_name: Optional[str] = None,
        email: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> bool:
        """
        사용자 정보 업데이트

        Args:
            username: 사용자 ID
            full_name: 이름 (선택)
            email: 이메일 (선택)
            is_active: 활성화 여부 (선택)

        Returns:
            업데이트 성공 여부
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            updates = []
            params = []

            if full_name is not None:
                updates.append("full_name = ?")
                params.append(full_name)

            if email is not None:
                updates.append("email = ?")
                params.append(email)

            if is_active is not None:
                updates.append("is_active = ?")
                params.append(is_active)

            if not updates:
                return False

            params.append(username)
            query = f"UPDATE users SET {', '.join(updates)} WHERE username = ?"

            cursor.execute(query, params)
            conn.commit()
            conn.close()

            logger.info(f"User updated: {username}")
            return True

        except Exception as e:
            logger.error(f"Error updating user {username}: {e}")
            return False

    def change_password(self, username: str, new_password: str) -> bool:
        """
        비밀번호 변경

        Args:
            username: 사용자 ID
            new_password: 새 비밀번호

        Returns:
            변경 성공 여부
        """
        try:
            if len(new_password) < 8:
                logger.warning(f"New password too short for user: {username}")
                return False

            password_hash = self.hash_password(new_password)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE users
                SET password_hash = ?
                WHERE username = ?
            """, (password_hash, username))

            conn.commit()
            conn.close()

            logger.info(f"Password changed for user: {username}")
            return True

        except Exception as e:
            logger.error(f"Error changing password for {username}: {e}")
            return False

    def delete_user(self, username: str) -> bool:
        """
        사용자 삭제 (실제로는 비활성화)

        Args:
            username: 사용자 ID

        Returns:
            삭제 성공 여부
        """
        return self.update_user(username, is_active=False)

    def list_users(self) -> List[Dict]:
        """
        모든 사용자 목록 조회

        Returns:
            사용자 정보 리스트
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, username, full_name, email, is_active, is_admin,
                       created_at, last_login, login_count
                FROM users
                ORDER BY created_at DESC
            """)

            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return []

    def count_users(self) -> int:
        """총 사용자 수 조회"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
            count = cursor.fetchone()[0]

            conn.close()
            return count

        except Exception as e:
            logger.error(f"Error counting users: {e}")
            return 0
