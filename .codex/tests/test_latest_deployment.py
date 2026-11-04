"""2026-11-04 hoyeon.han: 현재 운영 Compose를 보존하는 무인자 latest 배포 회귀."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_release_image_selection import Fixture, ROOT, IMAGE, digest

LATEST = 'hoyeonhan/sollume-lab:latest'
NEW_IMAGE = 'sha256:' + 'b' * 64


class LatestFixture(Fixture):
    def __init__(self, root):
        super().__init__(root)
        self.config['networks'] = {'sollume-network': {'external': True, 'name': 'existing-finance-network'}}
        for service in self.config['services'].values():
            service.update({'pull_policy': 'never', 'platform': 'linux/arm64', 'read_only': True,
                            'networks': {'sollume-network': None},
                            'volumes': [{'type': 'bind', 'source': str(self.app / 'database'), 'target': '/app/database'}],
                            'labels': {'preserve': '$${unchanged}'},
                            'security_opt': ['no-new-privileges:true']})
            service['environment']['TRUSTED_PROXY_NETWORKS'] = '172.18.0.1/32,127.0.0.1/32'
        self.save()
        (self.app / 'docker-compose.cloud.yml').write_text(json.dumps(self.config))
        self.original_compose = (self.app / 'docker-compose.cloud.yml').read_bytes()
        self.env.update(LATEST_QA_IMAGE=NEW_IMAGE, LATEST_QA_CURRENT=str(self.app / 'docker-compose.cloud.yml'),
                        LATEST_QA_ENV=str(self.app / '.env'), LATEST_QA_COUNTER=str(root / 'inspect-count'))
        backup_helper = '''import json,os,pathlib,sys
with pathlib.Path(os.environ['IMAGE_QA_LOG']).open('a') as log:log.write(json.dumps(['backup',*sys.argv[1:]])+'\\n')
if os.environ.get('LATEST_QA_FAIL')=='backup':raise SystemExit(23)
release=sys.argv[sys.argv.index('--release')+1] if '--release' in sys.argv else sys.argv[sys.argv.index('--backup-dir')+1]
print(json.dumps({'release':release}))
'''
        (self.app / 'scripts/release_snapshot.py').write_text(backup_helper)
        tool = '''#!PYTHON
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with pathlib.Path(os.environ['IMAGE_QA_LOG']).open('a') as log:log.write(json.dumps([name,*args])+'\\n')
failure=os.environ.get('LATEST_QA_FAIL','')
def mutate(stage):
 change=os.environ.get('LATEST_QA_MUTATE','')
 if change==stage+'-compose':
  path=pathlib.Path(os.environ['LATEST_QA_CURRENT']);value=json.loads(path.read_text());value['operator_change']='preserve me';path.write_text(json.dumps(value))
 if change==stage+'-env':
  path=pathlib.Path(os.environ['LATEST_QA_ENV']);path.write_text(path.read_text()+'OPERATOR_CHANGE=preserve-me\\n')
if name=='docker':
 if args[:2]==['image','inspect']:
  fmt=args[args.index('--format')+1]
  if fmt=='{{.Id}}':
   counter=pathlib.Path(os.environ['LATEST_QA_COUNTER']);count=int(counter.read_text())+1 if counter.exists() else 1;counter.write_text(str(count))
   changed=int(os.environ.get('LATEST_QA_TAG_CHANGE_AT','99'))
   print('sha256:'+'c'*64 if count>=changed else os.environ['LATEST_QA_IMAGE'])
  else:print(os.environ.get('LATEST_QA_METADATA',os.environ['LATEST_QA_IMAGE']+' linux arm64'))
 elif args[:1]==['info']:print(os.environ.get('LATEST_QA_DOCKER','linux aarch64'))
 elif args[:1]==['pull']:
  if failure=='pull':raise SystemExit(24)
  mutate('pull')
 elif args[:1]==['compose']:
  if 'config' in args:print(pathlib.Path(args[args.index('-f')+1]).read_text())
  elif 'run' in args:
   mutate('auth')
   if failure=='auth':raise SystemExit(25)
  elif 'up' not in args:raise SystemExit(81)
 else:raise SystemExit(82)
elif name=='curl':
 if any('raw.githubusercontent.com' in arg for arg in args):raise SystemExit(92)
 if '--resolve' in args:print('403' if '/media/' in args[-1] else '401')
 else:print('ok')
elif name=='sudo':
 if args not in (['-n','nginx','-t'],['-n','systemctl','reload','nginx']):raise SystemExit(83)
'''.replace('PYTHON', sys.executable)
        for name in ('docker', 'curl', 'sudo'):
            (self.binary / name).write_text(tool)

    def run_default(self, extra_args=()):
        result = subprocess.run(['bash', str(ROOT / 'deploy-oracle.sh'), *extra_args], env=self.env,
                                text=True, capture_output=True, timeout=30)
        observed = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        for path in self.protected:
            if path.name != '.env':
                assert digest(path) == self.before[str(path)]
        if not self.env.get('LATEST_QA_MUTATE', '').endswith('-env'):
            assert digest(self.app / '.env') == self.before[str(self.app / '.env')]
        assert 'synthetic-never-print' not in result.stdout + result.stderr
        assert not list(self.app.glob('docker-compose.cloud.yml.tmp.*'))
        assert not list(self.app.glob('docker-compose.cloud.yml.validated.*'))
        assert not list(self.app.glob('docker-compose.cloud.yml.preflight.*'))
        return result, observed


@pytest.fixture
def latest_fixture(tmp_path):
    return LatestFixture(tmp_path)


def assert_no_up(observed):
    assert not any(row[0] == 'docker' and 'up' in row for row in observed)
    assert not any(row[0] == 'sudo' and 'reload' in row for row in observed)


def nginx_sites(call):
    return [call[index + 1] for index, token in enumerate(call) if token == '--nginx-config']


def test_no_args_preserves_current_auth_config_and_updates_only_image(latest_fixture):
    value = latest_fixture
    before = deepcopy(value.config)
    result, calls = value.run_default()
    assert result.returncode == 0, result.stderr
    assert NEW_IMAGE in result.stdout
    assert not any(row[0] == 'curl' and any('raw.githubusercontent.com' in arg for arg in row) for row in calls)
    assert [row for row in calls if row[:2] == ['docker', 'pull']] == [['docker', 'pull', LATEST]]
    initial_config = next(row for row in calls if row[0] == 'docker' and '--no-interpolate' in row)
    assert initial_config[initial_config.index('-f') + 1] == 'docker-compose.cloud.yml'
    backup_index = next(i for i, row in enumerate(calls) if row[0] == 'backup')
    pull_index = next(i for i, row in enumerate(calls) if row[:2] == ['docker', 'pull'])
    assert backup_index < pull_index
    assert [row[1] for row in calls if row[0] == 'preflight'] == ['ready', 'ready', 'verify']
    expected_sites = [str(value.site), '/etc/nginx/sites-enabled/sollume-finance', '/etc/nginx/sites-enabled/sol-fin']
    assert all(nginx_sites(row) == expected_sites for row in calls if row[0] == 'preflight')
    # 자동 capture는 기존 단일 인증 사이트 계약, 공통 진입점 검사는 세 사이트 계약이다.
    assert all(nginx_sites(row) == expected_sites[:1] for row in calls if row[0] == 'backup')
    for row in [row for row in calls if row[0] == 'docker' and any(token in row for token in ('run', 'up'))]:
        assert row[row.index('--pull') + 1] == 'never'
        if 'up' in row:
            assert '--no-build' in row
    actual = json.loads((value.app / 'docker-compose.cloud.yml').read_text())
    for name, service in actual['services'].items():
        assert service['image'] == LATEST and service['pull_policy'] == 'never'
        service['image'] = before['services'][name]['image']
    assert actual == before


# 2026-11-04 hoyeon.han: 명시한 목록을 자동 추가하거나 순서를 바꾸지 않는다.
def test_explicit_nginx_config_list_keeps_operator_paths(latest_fixture):
    sites = [str(latest_fixture.site), str(latest_fixture.site.parent / 'explicit-legacy')]
    args = [token for site in sites for token in ('--nginx-config', site)]
    result, calls = latest_fixture.run_default(args)
    assert result.returncode == 0, result.stderr
    assert all(nginx_sites(row) == sites for row in calls if row[0] == 'preflight')
    assert all(nginx_sites(row) == sites[:1] for row in calls if row[0] == 'backup')


# 2026-11-04 hoyeon.han: 셸의 실제 기본 세 경로를 실제 Preflight 보안 계약에 연결한다.
def test_default_site_arguments_satisfy_real_preflight_legacy_contract(tmp_path):
    from test_deployment_preflight import Fixture as RealPreflightFixture

    shell_root = tmp_path / 'shell'
    shell_root.mkdir()
    shell = LatestFixture(shell_root)
    result, calls = shell.run_default()
    assert result.returncode == 0, result.stderr
    supplied = nginx_sites(next(row for row in calls if row[:2] == ['preflight', 'ready']))
    real_root = tmp_path / 'actual-preflight'
    real_root.mkdir()
    real = RealPreflightFixture(real_root)
    real.set_runtime(secure=True)
    mapping = {
        str(shell.site): real.sites[0],
        '/etc/nginx/sites-enabled/sollume-finance': real.sites[2],
        '/etc/nginx/sites-enabled/sol-fin': real.sites[1],
    }
    assert len(supplied) == 3 and set(supplied) == set(mapping)
    sites = [mapping[path] for path in supplied]
    before = real.hashes()
    with pytest.raises(ValueError, match='DuckDNS'):
        real.checker(sites[:1]).ready(real.compose)
    for service in real.compose['services'].values():
        service['image'] = LATEST
        service['pull_policy'] = 'never'
    checker = real.checker(sites)
    baseline = checker.ready(real.compose)
    assert baseline['validated'] and not baseline['runtime_transition_required']
    assert checker.verify(real.compose, baseline=baseline)['validated']
    assert real.hashes() == before


@pytest.mark.parametrize('failure', ['ready', 'backup'])
def test_preflight_or_backup_failure_happens_before_pull(latest_fixture, failure):
    value = latest_fixture
    value.env['IMAGE_QA_FAIL' if failure == 'ready' else 'LATEST_QA_FAIL'] = failure
    result, calls = value.run_default()
    assert result.returncode != 0
    assert_no_up(calls)
    assert not any(row[:2] == ['docker', 'pull'] for row in calls)
    assert (value.app / 'docker-compose.cloud.yml').read_bytes() == value.original_compose


@pytest.mark.parametrize('failure', ['pull', 'auth'])
def test_pull_or_missing_auth_failure_keeps_existing_services(latest_fixture, failure):
    value = latest_fixture
    value.env['LATEST_QA_FAIL'] = failure
    result, calls = value.run_default()
    assert result.returncode != 0
    assert_no_up(calls)
    assert (value.app / 'docker-compose.cloud.yml').read_bytes() == value.original_compose


@pytest.mark.parametrize('metadata', [NEW_IMAGE + ' linux amd64', NEW_IMAGE + ' windows arm64', 'latest linux arm64'])
def test_received_image_architecture_and_id_checked_before_auth_and_up(latest_fixture, metadata):
    value = latest_fixture
    value.env['LATEST_QA_METADATA'] = metadata
    result, calls = value.run_default()
    assert result.returncode != 0
    assert_no_up(calls)
    assert not any(row[0] == 'docker' and 'run' in row for row in calls)


@pytest.mark.parametrize('at', ['1', '2', '3'])
def test_latest_tag_change_before_auth_after_auth_or_up_stops(latest_fixture, at):
    latest_fixture.env['LATEST_QA_TAG_CHANGE_AT'] = at
    result, calls = latest_fixture.run_default()
    assert result.returncode != 0
    assert_no_up(calls)
    assert (latest_fixture.app / 'docker-compose.cloud.yml').read_bytes() == latest_fixture.original_compose


@pytest.mark.parametrize('mutation', ['pull-compose', 'pull-env', 'auth-compose', 'auth-env'])
def test_operator_compose_or_env_changes_are_not_overwritten(latest_fixture, mutation):
    value = latest_fixture
    value.env['LATEST_QA_MUTATE'] = mutation
    result, calls = value.run_default()
    assert result.returncode != 0
    assert_no_up(calls)
    if mutation.endswith('compose'):
        current = json.loads((value.app / 'docker-compose.cloud.yml').read_text())
        assert current['operator_change'] == 'preserve me'
        assert all(service['image'] == IMAGE for service in current['services'].values())
    else:
        assert (value.app / 'docker-compose.cloud.yml').read_bytes() == value.original_compose
        assert 'OPERATOR_CHANGE=preserve-me' in (value.app / '.env').read_text()


def test_missing_current_compose_stops_without_download_seed_or_pull(latest_fixture):
    (latest_fixture.app / 'docker-compose.cloud.yml').unlink()
    result, calls = latest_fixture.run_default()
    assert result.returncode != 0
    assert not (latest_fixture.app / 'docker-compose.cloud.yml').exists()
    assert not any(row[0] == 'curl' or row[:2] == ['docker', 'pull'] for row in calls)
    assert_no_up(calls)


def test_second_preflight_failure_preserves_current_compose(latest_fixture):
    latest_fixture.env['IMAGE_QA_FAIL'] = 'second-ready'
    result, calls = latest_fixture.run_default()
    assert result.returncode != 0
    assert_no_up(calls)
    assert (latest_fixture.app / 'docker-compose.cloud.yml').read_bytes() == latest_fixture.original_compose
