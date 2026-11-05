# 2026-11-05 hoyeon.han: 재사용 검증 소스를 tests의 보안·운영 테스트로 분리한다.
"""2026-10-20 hoyeon.han: 실제 배포 셸의 오프라인 이미지 선택·중단 순서를 가짜 외부 명령으로 검증한다."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = 'sha256:' + 'a' * 64


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, root):
        self.app = root / 'app'
        (self.app / 'scripts').mkdir(parents=True)
        (self.app / 'database/backups/releases').mkdir(parents=True, mode=0o700)
        self.backup = self.app / 'database/backups/releases/manual-original'
        self.backup.mkdir(mode=0o700)
        self.calls = root / 'calls.jsonl'
        self.site = root / 'primary.site'
        self.site.write_bytes((ROOT / 'nginx-host-api.conf.example').read_bytes())
        for name in ('users.db', 'customer_master.db'):
            with sqlite3.connect(self.app / 'database' / name) as conn:
                conn.execute('CREATE TABLE sentinel(value TEXT)')
                conn.execute('INSERT INTO sentinel VALUES(?)', ('기존 계정·자료 보존',))
        (self.app / '.env').write_text('AUTH_ENV=production\nAUTH_PUBLIC_ORIGIN=https://office1.sollumeesthe.com\n'
                                     'AUTH_ENCRYPTION_KEY=synthetic-never-print-secret\nORDER_API_KEY=synthetic-never-print-api\n')
        (self.app / 'docker-compose.cloud.yml').write_text('{"original":"running configuration"}')
        self.source = root / 'prepared-compose.json'
        self.config = {'name': 'sollume-finance', 'services': {
            name: {'image': IMAGE, 'ports': [{'host_ip': '127.0.0.1', 'target': port, 'published': str(port), 'protocol': 'tcp'}],
                   'environment': {'AUTH_ENV': 'production', 'AUTH_PUBLIC_ORIGIN': 'https://office1.sollumeesthe.com',
                                   'AUTH_ENCRYPTION_KEY': 'synthetic-never-print-secret'},
                   'deploy': {'resources': {'limits': {'cpus': '4' if port == 8501 else '1', 'memory': '20G' if port == 8501 else '2G'},
                                            'reservations': {'cpus': '2' if port == 8501 else '0.5', 'memory': '4G' if port == 8501 else '512M'}}}}
            for name, port in {'sollume-app': 8501, 'sollume-api': 8502, 'sollume-auth': 8503}.items()}}
        self.save()
        self.protected = [self.app / '.env', self.app / 'database/users.db', self.app / 'database/customer_master.db', self.site]
        self.before = {str(path): digest(path) for path in self.protected}
        self.original_compose = (self.app / 'docker-compose.cloud.yml').read_bytes()
        self.binary = root / 'bin'
        self.binary.mkdir()
        self.env = dict(os.environ, PATH=str(self.binary) + ':/usr/bin:/bin', SOLLUME_APP_DIR=str(self.app),
                        SOLLUME_OPS_PYTHON=sys.executable, SOLLUME_NGINX_SITE_CONFIG=str(self.site),
                        IMAGE_QA_LOG=str(self.calls), IMAGE_QA_SOURCE=str(self.source), IMAGE_QA_ID=IMAGE)
        backup_helper = '''import json,os,pathlib,sys
with pathlib.Path(os.environ['IMAGE_QA_LOG']).open('a') as log:log.write(json.dumps(['backup',*sys.argv[1:]])+'\\n')
print(json.dumps({'release':sys.argv[sys.argv.index('--backup-dir')+1]}))
'''
        (self.app / 'scripts/release_snapshot.py').write_text(backup_helper)
        preflight = '''import json,os,pathlib,sys
path=pathlib.Path(os.environ['IMAGE_QA_LOG'])
previous=[json.loads(line) for line in path.read_text().splitlines()]
with path.open('a') as log:log.write(json.dumps(['preflight',*sys.argv[1:]])+'\\n')
phase=sys.argv[1]
second=phase=='ready' and any(row[:2]==['preflight','ready'] for row in previous)
failure=os.environ.get('IMAGE_QA_FAIL','')
print(json.dumps({'runtime_transition_required':True,'policy_fingerprint':'a'*64}))
raise SystemExit(19 if failure==('second-ready' if second else phase) else 0)
'''
        (self.app / 'scripts/deployment_preflight.py').write_text(preflight)
        tool = '''#!PYTHON
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with pathlib.Path(os.environ['IMAGE_QA_LOG']).open('a') as log:log.write(json.dumps([name,*args])+'\\n')
if name=='docker':
 if args[:2]==['image','inspect']:
  if os.environ.get('IMAGE_QA_MISSING'):raise SystemExit(17)
  print(os.environ.get('IMAGE_QA_METADATA',os.environ['IMAGE_QA_ID']+' linux arm64'))
 elif args[:1]==['info']:
  print(os.environ.get('IMAGE_QA_DOCKER','linux aarch64'))
 elif args[:1]==['compose']:
  if 'config' in args:
   print(pathlib.Path(args[args.index('-f')+1]).read_text())
  elif not any(value in args for value in ('pull','run','up')):raise SystemExit(81)
 else:raise SystemExit(82)
elif name=='curl':
 if '--resolve' in args:
  print('403' if '/media/' in args[-1] else '401')
 elif '-o' in args:
  shutil.copyfile(os.environ['IMAGE_QA_SOURCE'],args[args.index('-o')+1])
 else:print('ok')
elif name=='sudo':
 if args not in (['-n','nginx','-t'],['-n','systemctl','reload','nginx']):raise SystemExit(83)
'''.replace('PYTHON', sys.executable)
        for name in ('docker', 'curl', 'sudo'):
            path = self.binary / name
            path.write_text(tool)
            path.chmod(0o700)

    def save(self):
        self.source.write_text(json.dumps(self.config))

    def run(self, options=None):
        command = ['bash', str(ROOT / 'deploy-oracle.sh'), '--backup-dir', str(self.backup), '--nginx-config', str(self.site)]
        command += ['--compose-file', str(self.source), '--local-image-id', IMAGE] if options is None else options
        result = subprocess.run(command, env=self.env, text=True, capture_output=True, timeout=30)
        observed = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        assert {str(path): digest(path) for path in self.protected} == self.before
        assert 'synthetic-never-print' not in result.stdout + result.stderr
        assert not list(self.app.glob('docker-compose.cloud.yml.tmp.*'))
        assert not list(self.app.glob('docker-compose.cloud.yml.validated.*'))
        assert not list(self.app.glob('docker-compose.cloud.yml.preflight.*'))
        return result, observed


@pytest.fixture
def fixture(tmp_path):
    return Fixture(tmp_path)


def assert_no_transition(fixture, result, observed):
    assert result.returncode != 0
    assert (fixture.app / 'docker-compose.cloud.yml').read_bytes() == fixture.original_compose
    assert not any(row[0] == 'docker' and any(token in row for token in ('pull', 'up', 'stop', 'down', 'rm')) for row in observed)
    assert not any(row[0] == 'sudo' and 'reload' in row for row in observed)
    assert not any(row[0] == 'curl' and any('raw.githubusercontent.com' in token for token in row) for row in observed)


@pytest.mark.parametrize('option', ['compose-only', 'image-only'])
def test_offline_options_must_be_paired_before_any_external_command(fixture, option):
    options = ['--compose-file', str(fixture.source)] if option == 'compose-only' else ['--local-image-id', IMAGE]
    result, observed = fixture.run(options)
    assert_no_transition(fixture, result, observed)
    assert not observed


@pytest.mark.parametrize('image', ['latest', 'sha256:' + 'A' * 64, 'sha256:1234', 'sha256:' + 'a' * 63, 'sha256:' + 'g' * 64])
def test_invalid_image_identifier_stops_before_commands(fixture, image):
    result, observed = fixture.run(['--compose-file', str(fixture.source), '--local-image-id', image])
    assert_no_transition(fixture, result, observed)
    assert not observed


@pytest.mark.parametrize('path', ['relative-compose.yml', '/not/a/prepared-compose.yml'])
def test_prepared_compose_must_be_readable_absolute_file(fixture, path):
    result, observed = fixture.run(['--compose-file', path, '--local-image-id', IMAGE])
    assert_no_transition(fixture, result, observed)
    assert not observed


def test_missing_local_image_never_downloads_or_pulls(fixture):
    fixture.env['IMAGE_QA_MISSING'] = '1'
    result, observed = fixture.run()
    assert_no_transition(fixture, result, observed)
    assert not any(row[0] in ('preflight', 'backup') for row in observed)


@pytest.mark.parametrize('metadata', ['sha256:' + 'b' * 64 + ' linux arm64', IMAGE + ' linux amd64', IMAGE + ' windows arm64', IMAGE + ' linux arm64 extra'])
def test_image_id_and_platform_must_match_exactly(fixture, metadata):
    fixture.env['IMAGE_QA_METADATA'] = metadata
    result, observed = fixture.run()
    assert_no_transition(fixture, result, observed)
    assert not any(row[0] in ('preflight', 'backup') for row in observed)


@pytest.mark.parametrize('platform', ['linux amd64', 'windows arm64', 'linux', 'linux arm64 extra'])
def test_docker_platform_must_match_prepared_arm64_image(fixture, platform):
    fixture.env['IMAGE_QA_DOCKER'] = platform
    result, observed = fixture.run()
    assert_no_transition(fixture, result, observed)


@pytest.mark.parametrize('mutation', ['tag', 'other-id', 'missing-service', 'extra-service'])
def test_compose_must_select_same_image_id_for_exactly_three_services(fixture, mutation):
    if mutation == 'tag':
        fixture.config['services']['sollume-api']['image'] = 'example.invalid/latest'
    elif mutation == 'other-id':
        fixture.config['services']['sollume-api']['image'] = 'sha256:' + 'b' * 64
    elif mutation == 'missing-service':
        fixture.config['services'].pop('sollume-auth')
    else:
        fixture.config['services']['extra'] = fixture.config['services']['sollume-app']
    fixture.save()
    result, observed = fixture.run()
    assert_no_transition(fixture, result, observed)
    assert not any(row[0] in ('preflight', 'backup') for row in observed)


@pytest.mark.parametrize('build', [None, {}, '.'])
def test_offline_compose_rejects_build_key_even_when_empty(fixture, build):
    """2026-10-20 hoyeon.han: 로컬 이미지가 있어도 후보의 빈 build 선언까지 거절한다."""
    fixture.config['services']['sollume-auth']['build'] = build
    fixture.save()
    result, observed = fixture.run()
    assert_no_transition(fixture, result, observed)
    assert not any(row[0] in ('preflight', 'backup') or row[0] == 'docker' and 'run' in row for row in observed)


def test_offline_compose_rejects_build_pull_policy(fixture):
    """2026-10-20 hoyeon.han: pull 금지만으로 빌드 정책이 남지 않도록 교체 전에 차단한다."""
    fixture.config['services']['sollume-auth']['pull_policy'] = 'build'
    fixture.save()
    result, observed = fixture.run()
    assert_no_transition(fixture, result, observed)
    assert not any(row[0] in ('preflight', 'backup') or row[0] == 'docker' and 'run' in row for row in observed)


@pytest.mark.parametrize('failure', ['ready', 'second-ready'])
def test_offline_ready_failure_prevents_service_replacement(fixture, failure):
    fixture.env['IMAGE_QA_FAIL'] = failure
    result, observed = fixture.run()
    assert_no_transition(fixture, result, observed)
    if failure == 'ready':
        assert not any(row[0] == 'backup' or row[0] == 'docker' and 'run' in row for row in observed)


def test_offline_success_uses_only_fixed_image_and_preserves_common_gates_and_resources(fixture):
    source_before = digest(fixture.source)
    result, observed = fixture.run()
    assert result.returncode == 0
    assert digest(fixture.source) == source_before
    assert not any(row[0] == 'docker' and 'pull' in row for row in observed)
    assert not any(row[0] == 'curl' and any('raw.githubusercontent.com' in value for value in row) for row in observed)
    runs = [row for row in observed if row[0] == 'docker' and 'run' in row]
    ups = [row for row in observed if row[0] == 'docker' and 'up' in row]
    assert len(runs) == len(ups) == 1
    assert runs[0][runs[0].index('--pull') + 1] == ups[0][ups[0].index('--pull') + 1] == 'never'
    assert '--no-build' in ups[0]
    gates = [row for row in observed if row[0] == 'preflight']
    assert [row[1] for row in gates] == ['ready', 'ready', 'verify']
    assert '--baseline' not in gates[0] and all('--baseline' in row for row in gates[1:])
    rendered = json.loads((fixture.app / 'docker-compose.cloud.yml').read_text())
    assert rendered == fixture.config
    assert all(service['image'] == IMAGE for service in rendered['services'].values())
    assert all(service['deploy']['resources'] == fixture.config['services'][name]['deploy']['resources'] for name, service in rendered['services'].items())


# def test_default_mode_keeps_existing_download_pull_and_common_validation(fixture):
#     result, observed = fixture.run([])
#     assert result.returncode == 0
#     assert any(row[0] == 'curl' and any('raw.githubusercontent.com' in value for value in row) for row in observed)
#     assert any(row[0] == 'docker' and 'pull' in row for row in observed)
#     assert not any(row[:3] == ['docker', 'image', 'inspect'] for row in observed)
#     assert [row[1] for row in observed if row[0] == 'preflight'] == ['ready', 'ready', 'verify']
# 2026-11-04 hoyeon.han: 기본 배포는 기존 인증 구성이 없으면 다운로드로 대체하지 않는다.
def test_default_mode_rejects_existing_non_auth_configuration(fixture):
    result, observed = fixture.run([])
    assert_no_transition(fixture, result, observed)
    assert '기존 인증 Compose' in result.stderr
    assert not any(row[0] in ('preflight', 'backup') for row in observed)
