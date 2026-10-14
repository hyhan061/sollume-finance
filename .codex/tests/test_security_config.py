"""2026-10-14 hoyeon.han: 공개 포트 우회·키 누락·로컬 프로세스 수명 회귀 검사."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from cryptography.fernet import Fernet
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('sollume_local_runner', ROOT / 'scripts' / 'run_local.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def compose_services(filename):
    if shutil.which('docker') is None:
        pytest.skip('Docker Compose CLI가 없는 환경')
    env = dict(os.environ, AUTH_PUBLIC_ORIGIN='https://sollumeesthe.com',
               AUTH_ENCRYPTION_KEY=Fernet.generate_key().decode(), ORDER_API_KEY='test-only-api-key')
    result = subprocess.run(['docker', 'compose', '--env-file', os.devnull, '-f', filename,
                             'config', '--format', 'json'], cwd=ROOT, env=env,
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)['services']


@pytest.mark.parametrize('filename', ['docker-compose.yml', 'docker-compose.cloud.yml'])
def test_compose_does_not_publish_private_services_to_internet(filename):
    services = compose_services(filename)
    for name, port in [('sollume-app',8501), ('sollume-api',8502), ('sollume-auth',8503)]:
        bindings = services[name].get('ports', [])
        if filename.endswith('.cloud.yml'):
            assert len(bindings) == 1
            assert bindings[0]['host_ip'] == '127.0.0.1'
            assert bindings[0]['target'] == port
            assert bindings[0]['published'] == str(port)
        else:
            assert not bindings
            assert services[name]['expose'] == [str(port)]
    if filename == 'docker-compose.yml':
        assert {binding['target'] for binding in services['nginx']['ports']} == {80,443}


@pytest.mark.parametrize('filename', ['docker-compose.yml', 'docker-compose.cloud.yml'])
def test_app_and_auth_share_required_settings_and_persistent_storage(filename):
    services = compose_services(filename)
    app = services['sollume-app']
    auth = services['sollume-auth']
    for service in [app, auth]:
        env = service['environment']
        assert env['AUTH_ENV'] == 'production'
        Fernet(env['AUTH_ENCRYPTION_KEY'].encode())
        assert env['AUTH_PUBLIC_ORIGIN'] == 'https://sollumeesthe.com'
        assert env['AUTH_DB_PATH'] == '/app/database/users.db'
        mounts = {volume['target']:volume for volume in service['volumes']}
        assert Path(mounts['/app/database']['source']) == ROOT/'database'
        assert Path(mounts['/app/processed']['source']) == ROOT/'processed'
        assert '0.0.0.0/0' not in env['TRUSTED_PROXY_NETWORKS']
    assert app['environment']['AUTH_DOWNLOAD_DIR'] == auth['environment']['AUTH_DOWNLOAD_DIR']
    assert app['environment']['STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION'] == 'true'
    assert app['environment']['STREAMLIT_SERVER_ENABLE_CORS'] == 'true'
    assert app['environment']['STREAMLIT_CLIENT_SHOW_ERROR_DETAILS'] == 'false'


@pytest.mark.skipif(shutil.which('docker') is None, reason='Docker Compose CLI가 없는 환경')
@pytest.mark.parametrize('filename', ['docker-compose.yml', 'docker-compose.cloud.yml'])
def test_compose_missing_encryption_key_fails_before_startup(filename):
    # 실제 Compose 파서로 누락된 필수 키가 .env 자동값에 가려지지 않게 검사한다.
    env = dict(os.environ, AUTH_PUBLIC_ORIGIN='https://sollumeesthe.com', AUTH_ENCRYPTION_KEY='', ORDER_API_KEY='test-only-api-key')
    result = subprocess.run(['docker', 'compose', '--env-file', os.devnull, '-f', filename, 'config', '--quiet'],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'AUTH_ENCRYPTION_KEY' in result.stderr


def test_local_key_is_persistent_private_and_origins_are_loopback(tmp_path):
    env = runner.prepare_development_environment(tmp_path, source={'AUTH_PUBLIC_ORIGIN':'https://attacker.example'})
    repeated = runner.prepare_development_environment(tmp_path, source={})
    assert env['AUTH_ENCRYPTION_KEY'] == repeated['AUTH_ENCRYPTION_KEY']
    Fernet(env['AUTH_ENCRYPTION_KEY'].encode())
    assert env['AUTH_PUBLIC_ORIGIN'] == 'http://localhost:8503'
    assert env['AUTH_DEV_APP_ORIGIN'] == 'http://localhost:8501'
    assert env['FLASK_DEBUG'] == '0'
    if os.name != 'nt':
        assert (tmp_path/'database'/'auth-development.key').stat().st_mode & 0o777 == 0o600


def test_local_start_refuses_production_and_never_replaces_invalid_key(tmp_path):
    with pytest.raises(ValueError):
        runner.prepare_development_environment(tmp_path, source={'AUTH_ENV':'production'})
    key_file = tmp_path/'database'/'auth-development.key'
    key_file.parent.mkdir()
    key_file.write_text('invalid-key-must-not-be-overwritten')
    with pytest.raises(ValueError):
        runner.prepare_development_environment(tmp_path, source={})
    assert key_file.read_text() == 'invalid-key-must-not-be-overwritten'


def test_local_shutdown_terminates_both_child_processes():
    children = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']) for _ in range(2)]
    try:
        runner._stop_children(children)
        assert all(child.poll() is not None for child in children)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


# 2026-10-14 hoyeon.han: 실제 Compose 해석 결과로 기존 운영 자원 정책의 누락을 방지한다.
@pytest.mark.parametrize(('service_name', 'expected'), [
    ('sollume-app', {
        # 'limits': {'cpus': '4.0', 'memory': 20 * 1024 ** 3},
        'limits': {'cpus': 4, 'memory': 20 * 1024 ** 3},
        # 'reservations': {'cpus': '2.0', 'memory': 4 * 1024 ** 3},
        'reservations': {'cpus': 2, 'memory': 4 * 1024 ** 3},
    }),
    ('sollume-api', {
        # 'limits': {'cpus': '1.0', 'memory': 2 * 1024 ** 3},
        'limits': {'cpus': 1, 'memory': 2 * 1024 ** 3},
    }),
])
def test_cloud_compose_preserves_legacy_cpu_memory_policy(service_name, expected):
    services = compose_services('docker-compose.cloud.yml')
    # 2026-10-14 hoyeon.han: Compose 버전별 숫자/문자열 표현 차이를 실제 CPU·바이트 값으로 비교한다.
    # assert services[service_name]['deploy']['resources'] == expected
    resources = services[service_name]['deploy']['resources']
    normalized = {
        mode: {field: float(value) if field == 'cpus' else int(value)
               for field, value in policy.items()}
        for mode, policy in resources.items()
    }
    assert normalized == expected
