# 2026-10-14 hoyeon.han: 기존 자원 정책 보존 및 실행 없는 격리 Docker 설정 검증.
import hashlib
# 2026-11-05 hoyeon.han: 개인 baseline을 명시적으로 검증하고 정식 소스·결과 경로를 사용한다.
import argparse
import json
import os
# 2026-11-05 hoyeon.han: 정식 검증 경로와 개인 입력·결과 경로를 분리한다.
import sys
from pathlib import Path
import secrets
import subprocess
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]

# 2026-11-05 hoyeon.han: 정식 검증 경로와 개인 입력·결과 경로를 분리한다.
sys.path.insert(0, str(ROOT))
from scripts.verification.verification_common import DEFAULT_OUTPUT_DIR, add_baseline_argument, load_baseline
# OUTPUT = ROOT / '.Codex/user-management/resource-limits-validation-20261014.json'
# 2026-11-05 hoyeon.han: 정식 검증 경로와 개인 입력·결과 경로를 분리한다.
OUTPUT = DEFAULT_OUTPUT_DIR / 'resource-limits-validation-20261014.json'


def command(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True, **kwargs)


def main():
    # 2026-11-05 hoyeon.han: 개인 baseline을 명시적으로 검증하고 정식 소스·결과 경로를 사용한다.
    parser = argparse.ArgumentParser(description='격리 Docker 자원 정책과 업무파일 보존 기준을 확인합니다.')
    parser.add_argument('--output', default=str(OUTPUT))
    add_baseline_argument(parser)
    args = parser.parse_args()
    try:
        baseline = load_baseline(args.baseline)
    except ValueError as exc:
        parser.error(str(exc))
    # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
    # env = dict(os.environ, AUTH_PUBLIC_ORIGIN='https://sollumeesthe.com',
    env = dict(os.environ, AUTH_PUBLIC_ORIGIN='https://office1.sollumeesthe.com',
               AUTH_ENCRYPTION_KEY=Fernet.generate_key().decode(), ORDER_API_KEY='test-only-resource-policy')
    source = command(['git', 'show', 'main:docker-compose.cloud.yml']).stdout
    previous = json.loads(command(['docker', 'compose', '--env-file', os.devnull, '-f', '-',
                                  'config', '--format', 'json'], input=source, env=env).stdout)['services']
    current = json.loads(command(['docker', 'compose', '--env-file', os.devnull, '-f', 'docker-compose.cloud.yml',
                                 'config', '--format', 'json'], env=env).stdout)['services']
    names = ('sollume-app', 'sollume-api')
    policies = {name: current[name]['deploy']['resources'] for name in names}
    assert policies == {name: previous[name]['deploy']['resources'] for name in names}
    # baseline = json.loads((ROOT / '.Codex/user-management/data-baseline.json').read_text())
    # 2026-11-05 hoyeon.han: 개인 baseline을 명시적으로 검증하고 정식 소스·결과 경로를 사용한다.
    # baseline은 명령 실행 전에 선택한 개인 입력에서 검증했다.
    assert all(hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == h for n, h in baseline.items())
    checks = [{'name': 'restored_policy_matches_main', 'passed': True}]
    engine = {}
    # 2026-10-14 hoyeon.han: 실행 없는 HostConfig 검증에는 설치된 공식 Nginx 이미지만 사용한다.
    # image = 'sollume-finance-security:test'
    image = 'nginx:alpine'
    image_id = command(['docker', 'image', 'inspect', image, '--format', '{{.Id}}']).stdout.strip()
    project = 'sollume-resources-qa-' + secrets.token_hex(6)
    with tempfile.TemporaryDirectory(prefix=project + '-', dir='/private/tmp') as temporary:
        probe = Path(temporary) / 'compose.json'
        # 자원 정책만 옮긴다. 운영 경로·환경 키·포트·네트워크·서비스 시작 명령은 사용하지 않는다.
        probe.write_text(json.dumps({'services': {
            name: {'image': image_id, 'command': ['/bin/true'], 'network_mode': 'none',
                   'labels': {'sollume.resource.qa': project},
                   'deploy': {'resources': policies[name]}}
            for name in names
        }}))
        base = ['docker', 'compose', '--project-name', project, '--file', str(probe)]
        try:
            command(base + ['create', '--pull', 'never'])
            ids = command(base + ['ps', '-a', '-q']).stdout.split()
            assert len(ids) == 2
            containers = json.loads(command(['docker', 'inspect', *ids]).stdout)
            for container in containers:
                name = container['Config']['Labels']['com.docker.compose.service']
                host = container['HostConfig']
                state = container['State']
                limit = policies[name]['limits']
                reservation = policies[name].get('reservations', {})
                actual = {field: host[field] for field in ('NanoCpus', 'Memory', 'MemoryReservation', 'NetworkMode', 'PortBindings')}
                actual.update(status=state['Status'], running=state['Running'], started_at=state['StartedAt'], mounts=container['Mounts'])
                assert actual['NanoCpus'] == int(float(limit['cpus']) * 1_000_000_000)
                assert actual['Memory'] == int(limit['memory'])
                assert actual['MemoryReservation'] == int(reservation.get('memory', 0))
                assert actual['status'] == 'created' and not actual['running']
                assert actual['started_at'].startswith('0001-01-01')
                assert actual['NetworkMode'] == 'none' and not actual['PortBindings'] and not actual['mounts']
                engine[name] = actual
                checks.append({'name': name + '_docker_host_config_and_not_started', 'passed': True})
        finally:
            command(base + ['down', '--remove-orphans'])
    remaining = command(['docker', 'ps', '-aq', '--filter', 'label=sollume.resource.qa=' + project]).stdout.strip()
    assert not remaining
    unchanged = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == h for n, h in baseline.items()}
    assert all(unchanged.values())
    checks.extend([{'name': 'temporary_containers_removed', 'passed': True},
                   {'name': 'existing_database_and_order_files_unchanged', 'passed': True}])
    report = {'checked_at': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
              'branch': command(['git', 'branch', '--show-current']).stdout.strip(),
              'baseline_main': command(['git', 'rev-parse', 'main']).stdout.strip(),
              'passed': True, 'checks': checks, 'compose_resources': policies, 'docker_host_config': engine,
              'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                # for name in ('docker-compose.cloud.yml', '.codex/tests/test_security_config.py')},
                                # 2026-11-05 hoyeon.han: 개인 baseline을 명시적으로 검증하고 정식 소스·결과 경로를 사용한다.
                                for name in ('docker-compose.cloud.yml', 'tests/security/test_security_config.py')},
              'existing_data_unchanged': unchanged, 'cleanup_complete': True, 'production_deployed': False,
              'scope': '로컬 Docker Desktop에서 create/inspect만 수행',
              'limitations': ['컨테이너는 기동하지 않았다. 운영 서버 및 운영 DB에는 연결하지 않았다.',
                              'CPU 예약은 Compose 선언 보존을 검증했다. 실제 CPU 최소 할당이나 운영 부하 성능을 검증하지 않았다.']}
    # OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    # 2026-11-05 hoyeon.han: 개인 baseline을 명시적으로 검증하고 정식 소스·결과 경로를 사용한다.
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': len(checks), 'created_but_never_started': len(engine),
                      'cleanup_complete': True, 'existing_files_unchanged': len(unchanged), 'production_deployed': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
