# 2026-11-05 hoyeon.han: 재사용 검증 소스를 tests의 보안·운영 테스트로 분리한다.
"""2026-10-14 hoyeon.han: 실제 운영 Docker CLI 통합 시나리오(명시 실행).

SOLLUME_DOCKER_USER_CLI_INTEGRATION=1 .venv311/bin/python -m pytest
#   .codex/tests/test_docker_user_cli.py -v (이전 실행 경로)
  tests/operations/test_docker_user_cli.py -v
한 모듈 fixture에서 실제 Docker/Compose 검증을 1회 수행한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get('SOLLUME_DOCKER_USER_CLI_INTEGRATION') != '1',
                               reason='Docker CLI 통합검증은 명시 실행 시에만 수행합니다.')


@pytest.fixture(scope='module')
def actual_docker_cli():
    # result_file = ROOT / '.Codex/user-management/docker-user-cli-results.json'
    # command = [sys.executable, str(ROOT / '.Codex/user-management/verify_docker_user_cli.py'),
    # 2026-11-04 hoyeon.han: Linux에서도 실제 검증 스크립트와 결과 파일 경로를 찾는다.
    # result_file = ROOT / '.codex/user-management/docker-user-cli-results.json'
    # command = [sys.executable, str(ROOT / '.codex/user-management/verify_docker_user_cli.py'),
    # 2026-11-05 hoyeon.han: 실행 소스와 ignored 검증 결과 디렉터리를 구분한다.
    result_file = ROOT / '.codex/outputs/verification/docker-user-cli-results.json'
    command = [sys.executable, str(ROOT / 'scripts/verification/verify_docker_user_cli.py'),
               '--image', os.environ.get('SOLLUME_DOCKER_USER_CLI_IMAGE', 'sollume-finance-security:venv-test'),
               '--output', str(result_file)]
    executed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)
    if executed.returncode:
        pytest.fail('실제 Docker CLI 검증 실패. 비밀정보를 표시하지 않고 결과 JSON을 확인합니다.')
    result = json.loads(result_file.read_text())
    assert result['passed'] and all(item['passed'] for item in result['checks'])
    return result


def test_docker_and_compose_execute_identical_virtual_environment(actual_docker_cli):
    observed = actual_docker_cli['observations']
    for name in ('docker_python', 'compose_python'):
        assert observed[name]['prefix'] == '/opt/venv'
        assert observed[name]['base_prefix'] != '/opt/venv'
        assert observed[name]['executable'] == '/opt/venv/bin/python'
    assert all(path.startswith('/opt/venv/bin/') for path in observed['docker_python']['paths'].values())


def test_existing_admin_init_does_not_duplicate_or_change_legacy_accounts(actual_docker_cli):
    observed = actual_docker_cli['observations']
    assert observed['init_returncodes'] == [0, 0]
    assert observed['legacy_user_count_before'] == observed['legacy_user_count_after_init'] == 3
    assert observed['legacy_history_rows_before'] == observed['legacy_history_rows_after_init'] == 2
    assert observed['legacy_identity_hash_grants_preserved_before_mfa']


def test_actual_deployment_import_gate_requires_venv_and_keeps_db_unmodified(actual_docker_cli):
    observed = actual_docker_cli['observations']['deployment_preflight']
    assert observed['venv_returncode'] == observed['existing_db_returncode'] == 0
    assert observed['system_python_returncode'] != 0


def test_cli_issued_code_is_accepted_by_actual_mfa_registration_routes(actual_docker_cli):
    observed = actual_docker_cli['observations']
    assert observed['legacy_admin_http_mfa']['user_id'] == 42
    for name in ('legacy_admin_http_mfa', 'new_admin_http_mfa'):
        for requirement in ('authenticated', 'mfa_enrolled', 'password_changed', 'cookie_secure',
                            'code_consumed', 'secret_encrypted', 'code_reuse_denied'):
            assert observed[name][requirement]


def test_missing_key_and_non_tty_password_input_fail_closed(actual_docker_cli):
    observed = actual_docker_cli['observations']
    assert observed['missing_key_cli_returncode'] != 0
    assert observed['non_tty_new_admin_returncode'] != 0
    assert observed['non_tty_new_admin_account_count'] == 0


def test_real_tty_creates_only_one_admin_with_hidden_password(actual_docker_cli):
    observed = actual_docker_cli['observations']
    assert observed['tty_new_admin_returncode'] == 0
    assert observed['tty_new_admin_account_count'] == 1
    assert next(item['passed'] for item in actual_docker_cli['checks']
                if item['name'] == 'actual_tty_getpass_password_not_echoed')


def test_verification_keeps_original_data_and_cleans_disposable_resources(actual_docker_cli):
    assert actual_docker_cli['original_data_file_count'] == 9
    assert actual_docker_cli['original_nine_files_unchanged']
    assert actual_docker_cli['source_unchanged_during_run']
    assert actual_docker_cli['cleanup_complete']
