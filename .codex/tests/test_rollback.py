"""2026-10-15 hoyeon.han: 롤백 안전 경계·실제 격리 복구 리허설 검증.

실제 Docker 리허설은 SOLLUME_ROLLBACK_INTEGRATION=1을 명시할 때만 수행한다.
일반 테스트는 가짜 명령만 사용하여 운영 자원을 실행하지 않는다.
"""
from __future__ import annotations

import hashlib
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_deployment_capture_failure_stops_before_any_pull_or_up(tmp_path):
    """실제 배포 셸을 가짜 외부 명령으로 실행해 캡처 실패 차단 순서를 검증한다."""
    app = tmp_path / 'app'
    app.mkdir()
    (app / 'scripts').mkdir()
    (app / 'database').mkdir()
    # 2026-10-19 hoyeon.han: 운영에서 준비한 쓰기 가능한 releases를 재현해 capture 실패 자체를 검증한다.
    (app / 'database/backups/releases').mkdir(parents=True, mode=0o700)
    for name in ('users.db', 'customer_master.db'):
        (app / 'database' / name).write_bytes(b'synthetic untouched database fixture')
    source_key=base64.urlsafe_b64encode(b'0'*32).decode()
    # 2026-10-19 hoyeon.han: 승인한 office1 공개 주소로 배포 중단 경계를 검증합니다.
    # (app / '.env').write_text('AUTH_PUBLIC_ORIGIN=https://sollumeesthe.com\nAUTH_ENCRYPTION_KEY='+source_key+'\nORDER_API_KEY=synthetic-api-key\n')
    (app / '.env').write_text('AUTH_PUBLIC_ORIGIN=https://office1.sollumeesthe.com\nAUTH_ENCRYPTION_KEY='+source_key+'\nORDER_API_KEY=synthetic-api-key\n')
    (app / 'docker-compose.cloud.yml').write_text('{"unchanged":"running compose fixture"}')
    source_nginx = ROOT / 'nginx-host-api.conf.example'
    nginx = tmp_path / 'nginx.site'
    nginx.write_text(source_nginx.read_text())
    commands = tmp_path / 'commands.jsonl'
    helper = app / 'scripts/release_snapshot.py'
    helper.write_text('import json,os,pathlib,sys\n'
                      'with pathlib.Path(os.environ["ROLLBACK_QA_COMMANDS"]).open("a") as log:\n'
                      ' log.write(json.dumps(["capture-helper",*sys.argv[1:],{"inherited_auth_exports":any(k in os.environ for k in ("AUTH_ENCRYPTION_KEY","AUTH_SIGNING_KEY","AUTH_PUBLIC_ORIGIN","ORDER_API_KEY"))}])+"\\n")\n'
                      'raise SystemExit(17)\n')
    # 2026-10-20 hoyeon.han: 공통 검사를 통과시켜 기존 capture 실패 경계 자체를 계속 검사한다.
    (app / 'scripts/deployment_preflight.py').write_text(
        'import json,os,pathlib,sys\n'
        'with pathlib.Path(os.environ["ROLLBACK_QA_COMMANDS"]).open("a") as log:\n'
        ' log.write(json.dumps(["preflight-helper",*sys.argv[1:]])+"\\n")\n'
        'print(json.dumps({"runtime_transition_required":False}))\n')
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    required = {'sollume-app': 8501, 'sollume-auth': 8503, 'sollume-api': 8502}
    config = {'services': {name: {
        'ports': [{'host_ip': '127.0.0.1', 'target': port}],
        # 2026-10-19 hoyeon.han: 렌더링된 운영 Compose도 office1과 일치시킵니다.
        # 'environment': {'AUTH_ENV': 'production', 'AUTH_PUBLIC_ORIGIN': 'https://sollumeesthe.com',
        'environment': {'AUTH_ENV': 'production', 'AUTH_PUBLIC_ORIGIN': 'https://office1.sollumeesthe.com',
                        'AUTH_ENCRYPTION_KEY': 'synthetic-not-real-key'},
    } for name, port in required.items()}}
    rendered = tmp_path / 'rendered.json'
    rendered.write_text(json.dumps(config))
    tool = '''#!PYTHON
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name
with pathlib.Path(os.environ['ROLLBACK_QA_COMMANDS']).open('a') as log:
 log.write(json.dumps([name,*sys.argv[1:],{'inherited_auth_exports':any(k in os.environ for k in ('AUTH_ENCRYPTION_KEY','AUTH_SIGNING_KEY','AUTH_PUBLIC_ORIGIN','ORDER_API_KEY'))}])+'\\n')
if name=='docker':
 if 'config' in sys.argv:
  print(pathlib.Path(os.environ['ROLLBACK_QA_RENDERED']).read_text())
 else:
  raise SystemExit(91)
elif name=='curl':
 if '-o' in sys.argv:
  shutil.copyfile(os.environ['ROLLBACK_QA_RENDERED'],sys.argv[sys.argv.index('-o')+1])
 else:
  raise SystemExit(92)
elif name=='sudo':
 # 2026-10-19 hoyeon.han: 비대화식 sudo 인자도 실제 셸과 동일하게 검사한다.
 # if sys.argv[1:]!=['nginx','-t']:
 if sys.argv[1:]!=['-n','nginx','-t']:
  raise SystemExit(93)
'''.replace('PYTHON', sys.executable)
    for name in ('docker', 'curl', 'sudo'):
        path = fake_bin / name
        path.write_text(tool)
        path.chmod(0o700)
    tracked = [app / '.env', app / 'docker-compose.cloud.yml',
               app / 'database/users.db', app / 'database/customer_master.db', nginx]
    before = {str(path): sha(path) for path in tracked}
    env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ.get('PATH', ''),
               SOLLUME_APP_DIR=str(app), SOLLUME_NGINX_SITE_CONFIG=str(nginx),
               SOLLUME_OPS_PYTHON=sys.executable, ROLLBACK_QA_COMMANDS=str(commands),
               ROLLBACK_QA_RENDERED=str(rendered),AUTH_ENCRYPTION_KEY=base64.urlsafe_b64encode(b'1'*32).decode(),
               AUTH_SIGNING_KEY='synthetic-polluted-signing-key-value',AUTH_PUBLIC_ORIGIN='https://polluted.invalid',
               ORDER_API_KEY='synthetic-polluted-api-key')
    run = subprocess.run(['bash', str(ROOT / 'deploy-oracle.sh')], env=env,
                         capture_output=True, text=True, timeout=30)
    observed = [json.loads(line) for line in commands.read_text().splitlines()]
    assert run.returncode != 0
    assert sum(command[0] == 'capture-helper' for command in observed) == 1
    assert not any(command[-1].get('inherited_auth_exports') for command in observed if command[0] in ('docker','capture-helper'))
    assert not any(command[0] == 'docker' and any(word in command for word in ('pull', 'up', 'down', 'stop', 'run'))
                   for command in observed)
    assert '복구 지점 생성에 실패' in run.stderr
    assert {str(path): sha(path) for path in tracked} == before


def release_api():
    spec=importlib.util.spec_from_file_location('rollback_policy_tests',ROOT/'scripts/release_snapshot.py')
    loaded=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=loaded
    spec.loader.exec_module(loaded)
    return loaded


def test_approved_nginx_policy_keeps_equivalent_whitespace_and_comment_meaning():
    api=release_api()
    source=(ROOT/'nginx-host-api.conf.example').read_text()
    api._approved_nginx(source.replace('server {','server    {').replace('    listen','\tlisten')+'\n# 합성 주석\n')


@pytest.mark.parametrize('addition',[
    '\ninclude /tmp/other-site.conf;\n',
    '\nserver { listen 443 ssl; location / { return 200; } }\n',
    '\nlocation /unsafe { auth_request off; }\n',
])
def test_nginx_policy_rejects_additional_include_server_or_auth_bypass(addition):
    api=release_api()
    with pytest.raises(api.SafetyError):
        api._approved_nginx((ROOT/'nginx-host-api.conf.example').read_text()+addition)


def test_quoted_hash_in_certificate_filename_is_not_a_comment(tmp_path):
    api=release_api()
    cert=tmp_path/'test#certificate.pem'
    key=tmp_path/'test#key.pem'
    source=(ROOT/'nginx-host-api.conf.example').read_text()
    # 2026-10-19 hoyeon.han: office1 인증서 경로 치환에서도 # 문자를 주석으로 오인하지 않습니다.
    # source=source.replace('/etc/letsencrypt/live/sollumeesthe.com/fullchain.pem',json.dumps(str(cert)))
    # source=source.replace('/etc/letsencrypt/live/sollumeesthe.com/privkey.pem',json.dumps(str(key)))
    source=source.replace('/etc/letsencrypt/live/office1.sollumeesthe.com/fullchain.pem',json.dumps(str(cert)))
    source=source.replace('/etc/letsencrypt/live/office1.sollumeesthe.com/privkey.pem',json.dumps(str(key)))
    api._approved_nginx(source)
    assert api._certificates(source)=={'cert':str(cert),'key':str(key)}


def test_secure_maintenance_keeps_office1_acme_without_default_server_or_other_hosts():
    """2026-10-19 hoyeon.han: 공개 업무는 차단하고 고정 office1 HTTP 갱신 경로만 허용합니다."""
    api=release_api()
    content=api.ReleaseManager._maintenance({'cert':'/office1/fullchain.pem','key':'/office1/privkey.pem'})
    assert content.count('server_name office1.sollumeesthe.com;')==2
    assert 'default_server' not in content and 'server_name _' not in content
    assert 'root /var/www/letsencrypt;' in content and 'try_files $uri =404;' in content
    assert 'location ^~ /.well-known/acme-challenge/' in content
    assert 'location / { add_header Cache-Control no-store always; return 503;' in content
    assert content.count('return 503;')==2
    assert 'server_name sollumeesthe.com;' not in content


@pytest.mark.parametrize('old_setting',[
    ('office1.sollumeesthe.com','sollumeesthe.com'),
    ('listen 443 ssl;','listen 443 ssl default_server;'),
    ('root /var/www/letsencrypt;','root /private/accounting-data;'),
    ('root /var/www/letsencrypt;','alias /private/accounting-data;'),
])
def test_office1_policy_rejects_old_domain_default_server_and_nonapproved_acme_root(old_setting):
    """2026-10-19 hoyeon.han: ACME 추가가 광범위한 파일 공개나 기존 루트 정책 허용으로 이어지지 않습니다."""
    api=release_api();source=(ROOT/'nginx-host-api.conf.example').read_text()
    assert old_setting[0] in source
    with pytest.raises(api.SafetyError):api._approved_nginx(source.replace(*old_setting))


@pytest.fixture(scope='module')
def actual_rollback():
    if os.environ.get('SOLLUME_ROLLBACK_INTEGRATION') != '1':
        pytest.skip('실제 Docker 롤백 리허설은 명시 실행 시에만 수행합니다.')
    output = ROOT / '.codex/user-management/rollback-results.json'
    command = [sys.executable, str(ROOT / '.codex/user-management/verify_rollback.py'), '--output', str(output)]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=900)
    if run.returncode:
        pytest.fail('격리 롤백 리허설 실패. 비밀정보를 출력하지 않고 결과 JSON을 확인하세요.')
    result = json.loads(output.read_text())
    assert result['passed']
    return result


def test_actual_secure_rollback_preserves_current_accounts_and_business_data(actual_rollback):
    assert actual_rollback['scenarios']['secure_restore']['passed']


def test_actual_legacy_restore_keeps_https_closed_and_does_not_revive_revoked_accounts(actual_rollback):
    assert actual_rollback['scenarios']['legacy_restore']['passed']


def test_actual_failure_paths_remain_https_503_after_current_state_backup(actual_rollback):
    assert all(item['passed'] for item in actual_rollback['scenarios']['failure_paths'].values())


def test_rollback_validation_rejects_tampered_or_unsafe_inputs(actual_rollback):
    assert actual_rollback['scenarios']['preflight_guards']['passed']


def test_actual_rollback_cleans_resources_without_touching_original_nine_files(actual_rollback):
    assert actual_rollback['cleanup_complete']
    assert actual_rollback['original_nine_files_unchanged']
    assert actual_rollback['source_unchanged_during_run']


@pytest.mark.parametrize('kind',['atomic','sqlite'])
def test_root_replacement_preserves_existing_owner_before_replace(tmp_path,monkeypatch,kind):
    """2026-10-15 hoyeon.han: root 복구를 모의해 기존 운영자 소유권 유지를 검증한다."""
    import sqlite3
    import stat
    api=release_api()
    destination=tmp_path/('active-compose.json' if kind=='atomic' else 'users.db')
    source=tmp_path/'source.db'
    if kind=='sqlite':
        for path,value in ((source,'합성 새 계정'),(destination,'합성 기존 계정')):
            conn=sqlite3.connect(path)
            try:
                conn.execute('CREATE TABLE users(value TEXT)')
                conn.execute('INSERT INTO users VALUES(?)',(value,));conn.commit()
            finally:
                conn.close()
    else:
        destination.write_text('합성 기존 구성')
    real_stat=Path.stat
    target_uid,target_gid=12345,23456
    def mock_owner(path,*args,**kwargs):
        value=real_stat(path,*args,**kwargs)
        if path==destination:
            fields=list(value);fields[4]=target_uid;fields[5]=target_gid
            return os.stat_result(fields)
        return value
    events=[]
    monkeypatch.setattr(Path,'stat',mock_owner)
    monkeypatch.setattr(api.os,'geteuid',lambda:0)
    monkeypatch.setattr(api.os,'fchown',lambda descriptor,uid,gid:events.append(('owner',uid,gid)))
    real_replace=api.os.replace
    def replace(source,target):
        if Path(target)==destination:
            assert ('owner',target_uid,target_gid) in events
            events.append(('replace',))
        return real_replace(source,target)
    monkeypatch.setattr(api.os,'replace',replace)
    if kind=='atomic':
        api._atomic(destination,'합성 새 구성')
        assert destination.read_text()=='합성 새 구성'
    else:
        api._sqlite_backup(source,destination)
        conn=sqlite3.connect(destination)
        try:
            assert conn.execute('SELECT value FROM users').fetchone()==('합성 새 계정',)
            assert conn.execute('PRAGMA integrity_check').fetchone()==('ok',)
        finally:
            conn.close()
    assert events.index(('owner',target_uid,target_gid))<events.index(('replace',))
    assert stat.S_IMODE(real_stat(destination).st_mode)==0o600
