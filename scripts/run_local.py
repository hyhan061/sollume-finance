#!/usr/bin/env python3
"""2026-10-14 hoyeon.han: 가상환경에서 로컬 인증 서버와 회계앱을 함께 실행한다."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def prepare_development_environment(root: Path = PROJECT_ROOT, source=None) -> dict:
    """개발용 키는 로컬 비공개 파일로 보존하고 공개 주소·디버거는 허용하지 않는다."""
    from cryptography.fernet import Fernet

    env = dict(os.environ if source is None else source)
    if env.get('AUTH_ENV') == 'production':
        raise ValueError('운영 환경에서는 start.sh를 사용하지 않습니다. 운영 Compose를 사용하세요.')
    env['AUTH_ENV'] = 'development'
    env['AUTH_PUBLIC_ORIGIN'] = 'http://localhost:8503'
    env['AUTH_DEV_APP_ORIGIN'] = 'http://localhost:8501'
    env['TRUSTED_PROXY_NETWORKS'] = '127.0.0.1/32,::1/128'
    env['FLASK_DEBUG'] = '0'
    env['FLASK_ENV'] = 'production'
    env['PYTHONPATH'] = str(root / 'Src') + os.pathsep + env.get('PYTHONPATH', '')
    env.setdefault('AUTH_DB_PATH', str(root / 'database' / 'users.db'))
    env.setdefault('AUTH_DOWNLOAD_DIR', str(root / 'processed' / 'secure_downloads'))
    if not env.get('AUTH_ENCRYPTION_KEY'):
        key_path = root / 'database' / 'auth-development.key'
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if key_path.is_symlink():
                raise ValueError('개발 인증키 파일에 심볼릭 링크를 사용할 수 없습니다.')
        else:
            with os.fdopen(descriptor, 'wb') as key_file:
                key_file.write(Fernet.generate_key())
        if os.name != 'nt':
            key_path.chmod(0o600)
        env['AUTH_ENCRYPTION_KEY'] = key_path.read_text().strip()
    # 잘못된 기존 키를 조용히 교체하면 MFA가 유실되므로 오류로 중단한다.
    Fernet(env['AUTH_ENCRYPTION_KEY'].encode('ascii'))
    return env


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def _stop_children(children: list[subprocess.Popen]) -> None:
    for process in reversed(children):
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5
    for process in reversed(children):
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> int:
    if sys.prefix == sys.base_prefix:
        print('가상환경을 활성화한 뒤 다시 실행하세요.', file=sys.stderr)
        return 1
    if any(not _port_is_free(port) for port in (8501, 8503)):
        print('8501 또는 8503 포트가 사용 중입니다. 기존 프로그램을 종료하세요.', file=sys.stderr)
        return 1
    try:
        env = prepare_development_environment()
    except (ValueError, OSError, UnicodeError) as exc:
        print(f'로컬 인증 설정을 확인하세요: {exc}', file=sys.stderr)
        return 1
    children = []
    try:
        children.append(subprocess.Popen([
            sys.executable, '-m', 'flask', '--app', 'auth_gateway:create_app', 'run',
            '--host', '127.0.0.1', '--port', '8503', '--no-reload', '--no-debugger',
        ], cwd=PROJECT_ROOT, env=env))
        ready = False
        for _ in range(150):
            if children[0].poll() is not None:
                raise RuntimeError('인증 서버가 시작되지 않았습니다. 설정과 의존성을 확인하세요.')
            try:
                with urllib.request.urlopen('http://localhost:8503/auth/health', timeout=0.5) as response:
                    ready = response.status == 200
            except (OSError, urllib.error.URLError):
                pass
            if ready:
                break
            time.sleep(0.2)
        if not ready:
            raise RuntimeError('인증 서버 준비 시간이 초과되었습니다.')
        children.append(subprocess.Popen([
            sys.executable, '-m', 'streamlit', 'run', 'Home.py',
            '--server.port=8501', '--server.address=127.0.0.1',
            '--server.enableCORS=true', '--server.enableXsrfProtection=true',
            '--server.runOnSave=false', '--browser.gatherUsageStats=false',
            '--browser.serverAddress=localhost', '--browser.serverPort=8501',
        ], cwd=PROJECT_ROOT, env=env))
        print('로컬 접속: http://localhost:8501 (인증 서버: http://localhost:8503/auth/login)')
        print('외부 공개에는 운영 HTTPS Compose/Nginx를 사용하세요. 종료: Ctrl+C')
        while all(process.poll() is None for process in children):
            time.sleep(0.2)
        return next((process.returncode for process in children if process.returncode), 1)
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError) as exc:
        print(f'시작 실패: {exc}', file=sys.stderr)
        return 1
    finally:
        _stop_children(children)


if __name__ == '__main__':
    raise SystemExit(main())
