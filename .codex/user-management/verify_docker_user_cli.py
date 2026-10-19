"""2026-10-14 hoyeon.han: 운영 사용자 CLI를 실제 Docker 가상환경에서 격리 검증.

실행: .venv311/bin/python .Codex/user-management/verify_docker_user_cli.py
Docker 이미지는 먼저 로컬에서 빌드한다. 운영 Compose·계정·자료를 마운트하지
않으며 합성 DB/키/코드만 임시 /fixture에서 사용하고 모두 정리한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import secrets
import select
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

import bcrypt
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == 'user-management' else Path.cwd()
SOURCE_FILES = ['Dockerfile', 'requirements.txt', 'scripts/manage_users.py',
                'scripts/init_users_db.py', 'scripts/run_local.py', 'Src/auth_gateway.py',
                'Src/security_service.py', 'Src/templates/auth.html', 'deploy-oracle.sh']
IMAGE_FILES = [name for name in SOURCE_FILES if name not in ('Dockerfile', 'deploy-oracle.sh')]
USER_FIELDS = ('id', 'username', 'password_hash', 'full_name', 'email', 'is_active',
               'is_admin', 'created_at', 'last_login', 'login_count', 'permissions')


def digest_file(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run_command(args, *, input_text=None, cwd=None, timeout=120):
    return subprocess.run(list(map(str, args)), input=input_text, cwd=cwd,
                          capture_output=True, text=True, timeout=timeout)


def docker(*args, input_text=None, check=True):
    result = run_command(['docker', *args], input_text=input_text)
    if check and result.returncode:
        raise RuntimeError('Docker operation failed: ' + ' '.join(map(str, args[:2])))
    return result


MFA_HTTP_PROBE = r'''
import hashlib, html, json, os, re, sqlite3, sys, time
sys.path.insert(0, '/app/Src')
from auth_gateway import create_app
from security_service import SecurityService
incoming=json.loads(sys.stdin.read())
app=create_app({'TESTING':True})
client=app.test_client()
service=app.extensions['security_service']
# 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
# base='https://sollumeesthe.com'
base='https://office1.sollumeesthe.com'
headers={'Origin':base}
def csrf(path):
    response=client.get(path,base_url=base)
    assert response.status_code==200
    matched=re.search(r'name="csrf_token" value="([^"]+)"',response.get_data(as_text=True))
    assert matched
    return html.unescape(matched.group(1)),response
token,_=csrf('/auth/login')
response=client.post('/auth/login',base_url=base,headers=headers,
    data={'csrf_token':token,'username':incoming['username'],'password':incoming['password']})
assert response.status_code==303 and response.location=='/auth/enroll'
assert client.get('/auth/check',base_url=base).status_code==401
token,_=csrf('/auth/enroll')
response=client.post('/auth/enroll',base_url=base,headers=headers,
    data={'csrf_token':token,'stage':'prepare','enrollment_code':incoming['code']})
assert response.status_code==303
token,page=csrf('/auth/enroll')
secret=re.search(r'<code>([A-Z2-7]+)</code>',page.get_data(as_text=True)).group(1)
assert 'data:image/svg+xml;base64,' in page.get_data(as_text=True)
otp=SecurityService._totp(secret,int(time.time()//30))
response=client.post('/auth/enroll',base_url=base,headers=headers,
    data={'csrf_token':token,'stage':'complete','otp':otp,'new_password':incoming['new_password'],
          'confirm_password':incoming['new_password']})
assert response.status_code==303 and response.location==base+'/'
assert client.get('/auth/check',base_url=base).status_code==200
# 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
# cookie=client.get_cookie('__Host-sollume_session',domain='sollumeesthe.com')
cookie=client.get_cookie('__Host-sollume_session',domain='office1.sollumeesthe.com')
assert cookie and cookie.secure and cookie.http_only and cookie.path=='/'
public=service.get_session(cookie.value)
assert public['mfa_enrolled'] and not public['must_change_password']
with sqlite3.connect(os.environ['AUTH_DB_PATH']) as conn:
    stored=conn.execute('SELECT code_hash,consumed_at FROM security_enrollments WHERE user_id=?',(public['id'],)).fetchone()
    assert stored and stored[0]==hashlib.sha256(incoming['code'].encode()).hexdigest() and stored[1] is not None
    cipher=conn.execute('SELECT mfa_secret_cipher,password_hash FROM users WHERE id=?',(public['id'],)).fetchone()
    assert cipher[0] and secret not in cipher[0] and cipher[1].startswith('$argon2')
# Attempt to reuse the consumed code through a different pending login challenge.
challenge=service.begin_login(incoming['username'],incoming['new_password'],'192.0.2.10')
try:
    service.prepare_enrollment(challenge['token'],incoming['code'])
    replay_denied=False
except ValueError:
    replay_denied=True
print(json.dumps({'authenticated':True,'mfa_enrolled':True,'password_changed':True,
    'cookie_secure':True,'code_consumed':True,'secret_encrypted':True,
    'code_reuse_denied':replay_denied,'user_id':public['id']}))
'''


class DockerCliVerifier:
    def __init__(self, image, output):
        self.image, self.output = image, Path(output)
        self.started = datetime.now(timezone.utc).isoformat()
        self.temp = Path(tempfile.mkdtemp(prefix='sollume-docker-cli-', dir='/private/tmp'))
        self.project = 'sollume-cli-qa-' + secrets.token_hex(6)
        self.compose_path = self.temp / 'compose.yml'
        self.env_path = self.temp / 'runtime.env'
        self.serial = 0
        self.container_names = []
        self.checks = []
        self.observations = {}
        self.sensitive_values = []
        self.source_hashes = {name: digest_file(ROOT / name) for name in SOURCE_FILES}
        original = json.loads((ROOT / '.Codex/user-management/data-baseline.json').read_text())
        self.original_hashes = {name: digest_file(ROOT / name) for name in original}
        self.original_baseline = original
        self.cleanup_complete = False

    def record(self, name, passed, **details):
        self.checks.append({'name': name, 'passed': bool(passed), **details})
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)
        if not passed:
            raise AssertionError(name)

    def compose_command(self, command, *, environment=None, tty=False, entrypoint='python'):
        self.serial += 1
        name = self.project + '-' + str(self.serial)
        self.container_names.append(name)
        args = ['docker', 'compose', '--project-name', self.project, '--env-file', os.devnull,
                '-f', str(self.compose_path), 'run', '--rm', '--no-deps', '--name', name]
        if not tty:
            args += ['-T']
        args += ['--entrypoint', entrypoint]
        for key, value in (environment or {}).items():
            args += ['--env', key + '=' + value]
        return args + ['sollume-auth', *command]

    def compose_run(self, command, *, input_text=None, environment=None, entrypoint='python'):
        result = run_command(self.compose_command(command, environment=environment, entrypoint=entrypoint),
                             input_text=input_text, cwd=self.temp)
        return result

    def users(self, filename='legacy-users.db'):
        with sqlite3.connect(self.temp / filename) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute('SELECT * FROM users ORDER BY id')]

    def stable_legacy_rows(self):
        return [{key: row[key] for key in USER_FIELDS} for row in self.users()]

    def history(self):
        with sqlite3.connect(self.temp / 'legacy-users.db') as conn:
            return conn.execute('SELECT id,user_id,login_time,ip_address,success FROM login_history ORDER BY id').fetchall()

    def setup(self):
        self.record('host_verifier_runs_inside_python_venv', sys.prefix != sys.base_prefix)
        self.record('original_nine_files_match_preserved_baseline',
                    len(self.original_hashes) == 9 and self.original_hashes == self.original_baseline)
        inspected = docker('image', 'inspect', self.image).stdout
        metadata = json.loads(inspected)[0]
        self.image_id = metadata['Id']
        self.observations['image_architecture'] = metadata['Architecture']
        self.observations['image_id'] = self.image_id
        self.key = Fernet.generate_key().decode()
        self.password = 'CLI-old-synthetic-' + secrets.token_urlsafe(20)
        self.new_password = 'CLI-new-synthetic-' + secrets.token_urlsafe(20)
        self.sensitive_values += [self.key, self.password, self.new_password]
        self.env_path.write_text('\n'.join([
            # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
            # 'AUTH_ENV=production', 'AUTH_PUBLIC_ORIGIN=https://sollumeesthe.com',
            'AUTH_ENV=production', 'AUTH_PUBLIC_ORIGIN=https://office1.sollumeesthe.com',
            'AUTH_ENCRYPTION_KEY=' + self.key, 'AUTH_DB_PATH=/fixture/legacy-users.db',
            'AUTH_DOWNLOAD_DIR=/fixture/downloads', 'TRUSTED_PROXY_NETWORKS=127.0.0.1/32',
            'PYTHONDONTWRITEBYTECODE=1', 'PYTHONUNBUFFERED=1',
        ]) + '\n')
        self.env_path.chmod(0o600)
        # Use only a generated manifest, never either operational Compose file.
        manifest = {
            'services': {'sollume-auth': {
                'image': self.image_id, 'working_dir': '/app', 'network_mode': 'none',
                'read_only': True, 'tmpfs': ['/tmp:size=128m'],
                'security_opt': ['no-new-privileges:true'], 'env_file': [str(self.env_path)],
                'labels': {'sollume.cli.qa': self.project},
                'volumes': [{'type': 'bind', 'source': str(self.temp), 'target': '/fixture'}],
            }}
        }
        self.compose_path.write_text(json.dumps(manifest, indent=2))
        self.compose_path.chmod(0o600)
        parsed = run_command(['docker', 'compose', '--project-name', self.project,
                              '--env-file', os.devnull, '-f', self.compose_path,
                              'config', '--format', 'json'], cwd=self.temp)
        self.record('isolated_compose_manifest_parses', parsed.returncode == 0)
        resolved = json.loads(parsed.stdout)['services']['sollume-auth']
        self.record('compose_network_none_no_ports_only_temporary_fixture_mount',
                    resolved['network_mode'] == 'none' and not resolved.get('ports')
                    and len(resolved['volumes']) == 1 and resolved['volumes'][0]['source'] == str(self.temp)
                    and resolved['volumes'][0]['target'] == '/fixture')
        # Legacy schema with existing page grants: migration must preserve all supplied fields.
        db = self.temp / 'legacy-users.db'
        hashed = bcrypt.hashpw(self.password.encode(), bcrypt.gensalt()).decode()
        self.sensitive_values.append(hashed)
        with sqlite3.connect(db) as conn:
            conn.execute('''CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(100),email VARCHAR(100),is_active BOOLEAN DEFAULT 1,
                is_admin BOOLEAN DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,login_count INTEGER DEFAULT 0,permissions TEXT DEFAULT '[]')''')
            conn.execute('''CREATE TABLE login_history (id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address VARCHAR(50),success BOOLEAN DEFAULT 1)''')
            for row in [(42, 'cli_admin', '합성 관리자', 1, 1, '[]'),
                        (77, 'cli_staff', '합성 직원', 1, 0, '["daily-voucher", "order-summary"]'),
                        (99, 'cli_inactive', '합성 정지 직원', 0, 0, '["settlement-seller"]')]:
                conn.execute('''INSERT INTO users(id,username,password_hash,full_name,email,is_active,is_admin,
                    created_at,last_login,login_count,permissions) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (row[0], row[1], hashed, row[2], 'fixture@example.invalid', row[3], row[4],
                     '2026-01-01 00:00:00', '2026-10-01 09:00:00', 5, row[5]))
            conn.executemany('INSERT INTO login_history(id,user_id,login_time,ip_address,success) VALUES(?,?,?,?,?)',
                             [(7, 42, '2026-10-01 09:00:00', '192.0.2.1', 1),
                              (10, 77, '2026-10-02 09:00:00', '192.0.2.2', 0)])
        self.original_fixture_rows = self.stable_legacy_rows()
        self.original_fixture_history = self.history()
        self.observations['legacy_user_count_before'] = len(self.original_fixture_rows)
        self.observations['legacy_history_rows_before'] = len(self.original_fixture_history)

    def python_path_probe(self):
        probe = '''import hashlib,json,os,pathlib,shutil,sys
paths={name:shutil.which(name) for name in ('python','python3','pip','streamlit','gunicorn')}
shebangs={name:pathlib.Path(paths[name]).read_text().splitlines()[0] for name in ('pip','streamlit','gunicorn')}
files=json.loads(sys.stdin.read())
hashes={name:hashlib.sha256(pathlib.Path('/app',name).read_bytes()).hexdigest() for name in files}
print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix,'executable':sys.executable,
'virtual_env':os.environ.get('VIRTUAL_ENV'),'paths':paths,'shebangs':shebangs,'source_sha256':hashes}))
'''
        raw = docker('run', '--rm', '--network', 'none', '--entrypoint', 'python', '-i',
                     self.image_id, '-c', probe, input_text=json.dumps(IMAGE_FILES))
        result = json.loads(raw.stdout)
        self.observations['docker_python'] = result
        self.record('docker_entrypoint_python_uses_opt_venv', result['prefix'] == '/opt/venv'
                    and result['prefix'] != result['base_prefix'] and result['executable'] == '/opt/venv/bin/python'
                    and result['virtual_env'] == '/opt/venv')
        self.record('docker_python_pip_streamlit_gunicorn_paths_share_venv',
                    all(value.startswith('/opt/venv/bin/') for value in result['paths'].values())
                    and all(line.startswith('#!/opt/venv/bin/python') for line in result['shebangs'].values()))
        self.record('built_image_cli_auth_source_matches_current_repository',
                    result['source_sha256'] == {name: self.source_hashes[name] for name in IMAGE_FILES})
        composed = self.compose_run(['-c', 'import json,sys;print(json.dumps({"prefix":sys.prefix,"base_prefix":sys.base_prefix,"executable":sys.executable}))'])
        self.record('compose_entrypoint_python_exit_zero', composed.returncode == 0)
        composed_info = json.loads(composed.stdout)
        self.observations['compose_python'] = composed_info
        self.record('compose_entrypoint_python_uses_same_venv', composed_info['prefix'] == '/opt/venv'
                    and composed_info['prefix'] != composed_info['base_prefix']
                    and composed_info['executable'] == result['executable'])
        module_probe = self.compose_run(['-c', 'import sys;sys.path.insert(0,"/app/scripts");import manage_users,init_users_db;print("imports-ok")'],
                                        environment={'AUTH_DB_PATH': '/fixture/import-only.db'})
        self.record('operational_cli_module_imports_do_not_create_db', module_probe.returncode == 0
                    and 'imports-ok' in module_probe.stdout and not (self.temp / 'import-only.db').exists())

    def deployment_preflight(self):
        # Extract the actual active shell payload; never execute the deployment script.
        lines = [line for line in (ROOT / 'deploy-oracle.sh').read_text().splitlines()
                 if not line.lstrip().startswith('#')]
        active = '\n'.join(lines)
        payloads = re.findall(r"--entrypoint python sollume-auth\s*\\\s*\n\s*-c '([^']+)'", active)
        self.record('active_deployment_preflight_payload_extracted_unambiguously',
                    len(payloads) == 1 and 'sys.prefix != sys.base_prefix' in payloads[0]
                    and 'manage_users, init_users_db' in payloads[0])
        payload = payloads[0]
        absent = self.compose_run(['-c', payload], environment={'AUTH_DB_PATH': '/fixture/preflight-absent.db'})
        self.record('actual_deployment_preflight_in_venv_passes_without_creating_db',
                    absent.returncode == 0 and not (self.temp / 'preflight-absent.db').exists())
        existing_before = digest_file(self.temp / 'legacy-users.db')
        present = self.compose_run(['-c', payload])
        self.record('actual_deployment_preflight_preserves_existing_db_exact_bytes',
                    present.returncode == 0 and digest_file(self.temp / 'legacy-users.db') == existing_before)
        system = self.compose_run(['-c', payload], entrypoint='/usr/local/bin/python')
        self.observations['deployment_preflight'] = {
            'venv_returncode': absent.returncode, 'existing_db_returncode': present.returncode,
            'system_python_returncode': system.returncode,
            'payload_sha256': hashlib.sha256(payload.encode()).hexdigest(),
        }
        self.record('actual_deployment_preflight_rejects_system_python_before_imports',
                    system.returncode != 0 and 'Docker Python 가상환경이 없습니다.' in system.stderr)

    def code_from_output(self, output):
        matched = re.search(r'등록 코드\(24시간, 1회 사용\):\s*([A-Za-z0-9_-]{24,})', output)
        if not matched:
            raise AssertionError('CLI enrollment code missing')
        code = matched.group(1)
        self.sensitive_values.append(code)
        return code

    def mfa_http(self, username, password, code, *, filename='legacy-users.db'):
        incoming = json.dumps({'username': username, 'password': password, 'code': code,
                               'new_password': self.new_password})
        result = self.compose_run(['-c', MFA_HTTP_PROBE], input_text=incoming,
                                  environment={'AUTH_DB_PATH': '/fixture/' + filename})
        self.record(filename + '_actual_http_mfa_probe_exit_zero', result.returncode == 0)
        observed = json.loads(result.stdout)
        self.record(filename + '_issued_cli_code_completes_actual_http_mfa_registration',
                    all(observed[key] for key in ('authenticated', 'mfa_enrolled', 'password_changed',
                                                  'cookie_secure', 'code_consumed', 'secret_encrypted', 'code_reuse_denied')))
        return observed

    def cli_scenarios(self):
        listing = self.compose_run(['scripts/manage_users.py', '--list'])
        self.record('documented_compose_manage_users_list_exit_zero', listing.returncode == 0)
        self.record('list_shows_three_legacy_accounts_roles_status_without_sensitive_values',
                    all(name in listing.stdout for name in ('cli_admin', 'cli_staff', 'cli_inactive', '총 3명'))
                    and '관리자' in listing.stdout and '정지' in listing.stdout
                    and all(value not in listing.stdout + listing.stderr for value in self.sensitive_values))
        self.record('first_cli_migration_preserves_legacy_ids_hashes_history_permissions',
                    self.stable_legacy_rows() == self.original_fixture_rows and self.history() == self.original_fixture_history
                    and (self.temp / 'legacy-users.db.pre-security.bak').exists())
        initial = self.compose_run(['scripts/init_users_db.py'])
        repeated = self.compose_run(['scripts/init_users_db.py'])
        self.observations['init_returncodes'] = [initial.returncode, repeated.returncode]
        self.observations['legacy_user_count_after_init'] = len(self.users())
        self.observations['legacy_history_rows_after_init'] = len(self.history())
        self.record('existing_admin_init_repeated_exit_zero_no_duplicate_accounts',
                    initial.returncode == repeated.returncode == 0 and '기존 활성 관리자' in initial.stdout
                    and '기존 활성 관리자' in repeated.stdout and len(self.users()) == 3)
        self.record('init_repeated_preserves_hashes_ids_history_roles_and_grants',
                    self.stable_legacy_rows() == self.original_fixture_rows and self.history() == self.original_fixture_history)
        before = self.users()
        cancelled = self.compose_run(['scripts/manage_users.py', '--enroll', 'cli_admin'], input_text='n\n')
        self.record('enrollment_confirmation_no_preserves_existing_account', cancelled.returncode == 0
                    and '등록 코드(24시간' not in cancelled.stdout and self.users() == before)
        enrollment = self.compose_run(['scripts/manage_users.py', '--enroll', 'cli_admin'], input_text='y\n')
        self.record('documented_enrollment_confirmation_yes_exit_zero', enrollment.returncode == 0)
        code = self.code_from_output(enrollment.stdout)
        with sqlite3.connect(self.temp / 'legacy-users.db') as conn:
            proof = conn.execute('SELECT user_id,consumed_at FROM security_enrollments WHERE code_hash=?',
                                 (hashlib.sha256(code.encode()).hexdigest(),)).fetchone()
        self.record('cli_enrollment_code_stored_as_hash_not_plaintext', proof == (42, None)
                    and code.encode() not in (self.temp / 'legacy-users.db').read_bytes())
        self.record('enrollment_preserves_legacy_passwords_history_ids_and_permissions',
                    self.stable_legacy_rows() == self.original_fixture_rows and self.history() == self.original_fixture_history)
        self.observations['legacy_identity_hash_grants_preserved_before_mfa'] = True
        missing = self.compose_run(['scripts/manage_users.py', '--list'],
                                  environment={'AUTH_ENCRYPTION_KEY': '', 'AUTH_DB_PATH': '/fixture/missing-key.db'})
        self.observations['missing_key_cli_returncode'] = missing.returncode
        self.record('missing_encryption_key_cli_fails_closed_without_creating_db',
                    missing.returncode != 0 and 'AUTH_ENCRYPTION_KEY' in missing.stderr
                    and not (self.temp / 'missing-key.db').exists())
        missing_init = self.compose_run(['scripts/init_users_db.py'],
                                       environment={'AUTH_ENCRYPTION_KEY': '', 'AUTH_DB_PATH': '/fixture/missing-init-key.db'})
        self.record('missing_encryption_key_init_fails_closed_without_creating_db',
                    missing_init.returncode != 0 and not (self.temp / 'missing-init-key.db').exists())
        no_tty = self.compose_run(['scripts/init_users_db.py'], input_text='pipe_admin\n합성 직원\n\n',
                                 environment={'AUTH_DB_PATH': '/fixture/non-tty.db'})
        with sqlite3.connect(self.temp / 'non-tty.db') as conn:
            no_tty_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        self.observations['non_tty_new_admin_returncode'] = no_tty.returncode
        self.observations['non_tty_new_admin_account_count'] = no_tty_count
        self.record('non_tty_new_admin_rejected_without_reading_or_storing_password',
                    no_tty.returncode != 0 and no_tty_count == 0
                    and '비밀번호를 숨겨 입력할 수 있는 터미널' in no_tty.stderr)
        mfa = self.mfa_http('cli_admin', self.password, code)
        self.observations['legacy_admin_http_mfa'] = mfa
        after = self.users()
        self.record('after_intended_mfa_change_legacy_staff_and_inactive_accounts_unchanged',
                    [{key: row[key] for key in USER_FIELDS} for row in after if row['id'] != 42]
                    == [row for row in self.original_fixture_rows if row['id'] != 42]
                    and self.history()[:2] == self.original_fixture_history)
        renewed_list = self.compose_run(['scripts/manage_users.py', '--list'])
        self.record('list_after_mfa_reports_enrollment_completed', renewed_list.returncode == 0
                    and 'cli_admin | 합성 관리자 | 관리자 | 활성 | 인증 앱: 등록' in renewed_list.stdout)

    def tty_admin_creation(self):
        command = self.compose_command(['scripts/init_users_db.py'], tty=True,
                                       environment={'AUTH_DB_PATH': '/fixture/tty-admin.db'})
        master, slave = pty.openpty()
        process = subprocess.Popen(command, cwd=self.temp, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        transcript = bytearray()

        def collect(timeout=0.25):
            if select.select([master], [], [], timeout)[0]:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    return False
                transcript.extend(data)
                return bool(data)
            return True

        def send_after(marker, value):
            deadline = time.monotonic() + 45
            while marker not in transcript.decode('utf-8', errors='replace'):
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError('Synthetic interactive CLI prompt unavailable')
                collect()
            os.write(master, (value + '\n').encode())

        tty_password = 'TTY-initial-synthetic-' + secrets.token_urlsafe(20)
        self.sensitive_values.append(tty_password)
        try:
            send_after('새 사용자 ID: ', 'cli_tty_admin')
            send_after('이름: ', '합성 TTY 관리자')
            send_after('이메일(선택): ', '')
            send_after('비밀번호(12자 이상): ', tty_password)
            send_after('비밀번호 확인: ', tty_password)
            deadline = time.monotonic() + 45
            while process.poll() is None and time.monotonic() < deadline:
                collect()
            if process.poll() is None:
                raise AssertionError('Synthetic interactive CLI did not terminate')
            while collect(0.1):
                if not select.select([master], [], [], 0)[0]:
                    break
            transcript_text = transcript.decode('utf-8', errors='replace')
            self.observations['tty_new_admin_returncode'] = process.returncode
            self.record('actual_tty_new_admin_creation_exit_zero', process.returncode == 0)
            self.record('actual_tty_getpass_password_not_echoed', tty_password not in transcript_text)
            code = self.code_from_output(transcript_text)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            os.close(master)
        rows = self.users('tty-admin.db')
        self.observations['tty_new_admin_account_count'] = len(rows)
        self.record('actual_tty_created_only_one_admin_with_mandatory_mfa_and_password_change',
                    len(rows) == 1 and rows[0]['is_admin'] == 1 and rows[0]['is_active'] == 1
                    and rows[0]['mfa_enrolled'] == 0 and rows[0]['must_change_password'] == 1)
        self.observations['new_admin_http_mfa'] = self.mfa_http('cli_tty_admin', tty_password, code,
                                                             filename='tty-admin.db')

    def cleanup(self):
        # Only exact, randomly generated names from this verifier are touched.
        for name in self.container_names:
            docker('rm', '-f', name, check=False)
        remaining = docker('ps', '-aq', '--filter', 'label=sollume.cli.qa=' + self.project).stdout.strip()
        down = run_command(['docker', 'compose', '--project-name', self.project,
                            '--env-file', os.devnull, '-f', self.compose_path, 'down', '--remove-orphans'],
                           cwd=self.temp) if self.compose_path.exists() else None
        shutil.rmtree(self.temp, ignore_errors=True)
        self.cleanup_complete = not remaining and not self.temp.exists() and (down is None or down.returncode == 0)

    def report(self, failure=None):
        current_sources = {name: digest_file(ROOT / name) for name in SOURCE_FILES}
        current_originals = {name: digest_file(ROOT / name) for name in self.original_hashes}
        source_unchanged = current_sources == self.source_hashes
        data_unchanged = current_originals == self.original_hashes == self.original_baseline
        result = {
            'started_at': self.started, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'passed': failure is None and self.cleanup_complete and source_unchanged and data_unchanged
                      and all(item['passed'] for item in self.checks),
            'check_count': len(self.checks), 'checks': self.checks, 'observations': self.observations,
            'source_sha256': self.source_hashes, 'source_unchanged_during_run': source_unchanged,
            'original_data_file_count': len(self.original_hashes), 'original_nine_files_unchanged': data_unchanged,
            'cleanup_complete': self.cleanup_complete, 'error_type': type(failure).__name__ if failure else None,
            'scope': 'Local Docker image + generated isolated Compose only; no operational Compose, deployment or real account changes.',
            'mfa_http_transport': 'Actual production-mode auth_gateway routes in Flask test_client inside the container; no listening ports.',
            'commands': ['docker run --rm --network none --entrypoint python IMAGE ...',
                         'docker compose -f TEMP_COMPOSE run --rm --no-deps --entrypoint python sollume-auth scripts/manage_users.py --list',
                         'docker compose -f TEMP_COMPOSE run --rm --no-deps --entrypoint python sollume-auth scripts/init_users_db.py',
                         'docker compose -f TEMP_COMPOSE run --rm --no-deps --entrypoint python sollume-auth scripts/manage_users.py --enroll SYNTHETIC_ADMIN'],
        }
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if any(value and value in serialized for value in self.sensitive_values):
            raise AssertionError('Secret must not be stored in verification evidence')
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(serialized)
        title = '# Docker 사용자 CLI 검증 결과\n\n2026-10-14 hoyeon.han\n\n'
        lines = [f"전체 결과: **{'통과' if result['passed'] else '실패'}**, {len(self.checks)}항목.",
                 f"원본 9파일 불변: {data_unchanged}. 최종 소스 해시 일치: {source_unchanged}. 임시 자원 정리: {self.cleanup_complete}.",
                 '실제 운영 Compose와 원본 DB는 실행·마운트하지 않았으며 network_mode:none, 포트 없음, 합성 fixture만 사용했습니다.',
                 'MFA는 컨테이너 안의 실제 운영 모드 HTTP 핸들러로 확인했으며 외부 TLS/Nginx 검증은 별도 결과를 참고합니다.',
                 '\n| 검증 | 결과 |\n|---|---|']
        lines += [f"| {item['name']} | {'통과' if item['passed'] else '실패'} |" for item in self.checks]
        # 2026-10-14 hoyeon.han: Markdown 표 행을 연속 배치하여 결과 표 렌더링을 유지.
        # self.output.with_suffix('.md').write_text(title + '\n\n'.join(lines) + '\n')
        self.output.with_suffix('.md').write_text(title + '\n\n'.join(lines[:4]) + '\n' + '\n'.join(lines[4:]) + '\n')
        print(json.dumps({'passed': result['passed'], 'checks': len(self.checks),
                          'source_unchanged': source_unchanged, 'original_nine_files_unchanged': data_unchanged,
                          'cleanup_complete': self.cleanup_complete, 'result': str(self.output)}, ensure_ascii=False), flush=True)
        return result


def verify(image='sollume-finance-security:venv-test', output=None):
    output = output or ROOT / '.Codex/user-management/docker-user-cli-results.json'
    verifier = DockerCliVerifier(image, output)
    failure = None
    try:
        verifier.setup()
        verifier.python_path_probe()
        verifier.deployment_preflight()
        verifier.cli_scenarios()
        verifier.tty_admin_creation()
    except BaseException as exc:
        failure = exc
        print('Docker CLI verification failed: ' + type(exc).__name__, flush=True)
    finally:
        verifier.cleanup()
        result = verifier.report(failure)
    if failure:
        raise failure
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='sollume-finance-security:venv-test')
    parser.add_argument('--output', default=str(ROOT / '.Codex/user-management/docker-user-cli-results.json'))
    args = parser.parse_args()
    result = verify(args.image, args.output)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
