"""2026-10-14 hoyeon.han: 실제 Docker/Nginx/TLS 보안 통합 검증.

.venv311/bin/python .Codex/user-management/verify_runtime.py
운영 이미지(sollume-finance-security:test) 빌드 후 실행한다. 실제 데이터/계정을
마운트하거나 변경하지 않으며 모든 생성 컨테이너·네트워크·fixture를 정리한다.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

import bcrypt
from cryptography.fernet import Fernet
import requests
import urllib3

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == 'user-management' else Path.cwd()
sys.path.insert(0, str(ROOT / 'Src'))
from security_service import SecurityService, SecurityError

SOURCE_PATHS = ['Src/security_service.py', 'Src/auth_gateway.py', 'Src/auth.py',
                'Src/secure_downloads.py', 'Home.py', 'nginx.conf', 'Dockerfile',
                'requirements.txt', 'Src/templates/auth.html', '.streamlit/config.toml'] + [str(p.relative_to(ROOT)) for p in sorted((ROOT / 'pages').glob('*.py'))]


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}


def docker(*args, check=True):
    result = subprocess.run(['docker', *map(str, args)], capture_output=True, text=True, timeout=120)
    if check and result.returncode:
        # Never print runtime ENV, cookies, passwords, enrollment codes or secret keys.
        raise RuntimeError('Docker command failed: ' + ' '.join(map(str, args[:3])))
    return result


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Runtime:
    def __init__(self, image, output):
        self.image, self.output = image, Path(output)
        self.tmp = Path(tempfile.mkdtemp(prefix='sollume-security-runtime-', dir='/private/tmp'))
        self.prefix = 'sollume-security-qa-' + secrets.token_hex(6)
        self.network = self.prefix + '-net'
        self.containers = []
        self.secure_port, self.http_port = free_port(), free_port()
        self.base = f'https://127.0.0.1:{self.secure_port}'
        self.checks = []
        self.limits = ['Self-signed certificate is a disposable test fixture; production certificate/domain/server were not changed.',
                       'Browser UI rendering and Streamlit page action scenarios are verified separately by the parent agent.',
                       'Streamlit HTTP page shells are not used as evidence of per-user page authorization.']
        self.started = datetime.now(timezone.utc).isoformat()
        self.initial_hashes = source_hashes()
        self.deferred_cleanup = []
        self.closed = False
        self.rate_retries = 0
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def record(self, name, passed, **detail):
        item = {'name': name, 'passed': bool(passed), **detail}
        self.checks.append(item)
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)
        if not passed:
            raise AssertionError(name)

    def request(self, method, path, session=None, headers=None, retry_rate=False, **kwargs):
        client = session or requests
        h = {'Host': 'sollumeesthe.com', 'Origin': 'https://sollumeesthe.com'}
        if headers:
            h.update(headers)
        for attempt in range(15):
            response = client.request(method, self.base + path, headers=h,
                                      timeout=15, verify=False, allow_redirects=False, **kwargs)
            if response.status_code != 429 or not retry_rate:
                return response
            self.rate_retries += 1
            time.sleep(6.2)
        raise AssertionError('Positive authentication flow remained rate-limited')

    def csrf(self, path, browser):
        response = self.request('GET', path, browser, retry_rate=True)
        if response.status_code != 200:
            raise AssertionError('Authentication form did not render')
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        if not match:
            raise AssertionError('CSRF input missing')
        return html.unescape(match.group(1)), response

    def setup(self):
        for name in ('database', 'processed', 'logs', 'order_data', 'uploads', 'ssl'):
            (self.tmp / name).mkdir(mode=0o700)
        self.key = Fernet.generate_key().decode()
        self.initial_password = 'Synthetic-initial-' + secrets.token_urlsafe(20)
        self.password = 'Synthetic-final-' + secrets.token_urlsafe(20)
        db = self.tmp / 'database/users.db'
        # Disposable old schema: explicit IDs and login history prove migration preservation.
        with sqlite3.connect(db) as conn:
            conn.execute('''CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(100),email VARCHAR(100),is_active BOOLEAN DEFAULT 1,
                is_admin BOOLEAN DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,login_count INTEGER DEFAULT 0)''')
            conn.execute('''CREATE TABLE login_history (id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address VARCHAR(50),success BOOLEAN DEFAULT 1)''')
            hashed = bcrypt.hashpw(self.initial_password.encode(), bcrypt.gensalt()).decode()
            for uid, username, admin in ((42, 'fixture_admin', 1), (77, 'fixture_staff', 0)):
                conn.execute('INSERT INTO users(id,username,password_hash,full_name,is_admin,login_count) VALUES(?,?,?,?,?,?)',
                             (uid, username, hashed, username, admin, 3))
            conn.execute('INSERT INTO login_history(id,user_id,ip_address) VALUES(9,42,?)', ('192.0.2.1',))
        self.service = SecurityService(db, self.key, self.tmp / 'processed/secure_downloads')
        with sqlite3.connect(db) as conn:
            preserved = conn.execute('SELECT id,username,login_count FROM users ORDER BY id').fetchall()
            historical = conn.execute('SELECT id,user_id,ip_address FROM login_history').fetchall()
        self.record('legacy_fixture_migration_preserves_ids_accounts_counts_history',
                    preserved == [(42, 'fixture_admin', 3), (77, 'fixture_staff', 3)]
                    and historical == [(9, 42, '192.0.2.1')]
                    and Path(str(db) + '.pre-security.bak').exists())
        self.service.update_user_local(77, permissions=['daily-voucher'])
        other = self.service.bootstrap_user('fixture_other', self.initial_password,
                                            is_admin=False, permissions=['daily-voucher'])
        self.users = {'admin': 42, 'staff': 77, 'other': other['id']}
        self.codes = {name: self.service.issue_enrollment_local(uid) for name, uid in self.users.items()}
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=sollumeesthe.com', '-addext',
                        'subjectAltName=DNS:sollumeesthe.com,IP:127.0.0.1',
                        '-keyout', str(self.tmp / 'ssl/privkey.pem'), '-out', str(self.tmp / 'ssl/fullchain.pem')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.chmod(self.tmp / 'ssl/privkey.pem', 0o600)
        subnet = None
        for octet in range(240, 250):
            candidate = f'172.31.{octet}.0/24'
            if docker('network', 'create', '--subnet', candidate, self.network, check=False).returncode == 0:
                subnet = f'172.31.{octet}'
                break
        if subnet is None:
            raise RuntimeError('No disposable subnet available')
        self.proxy_ip = subnet + '.10'
        self.env_path = self.tmp / 'runtime.env'
        self.env_path.write_text('\n'.join([
            'AUTH_ENV=production', 'AUTH_PUBLIC_ORIGIN=https://sollumeesthe.com',
            'AUTH_ENCRYPTION_KEY=' + self.key, 'AUTH_DB_PATH=/app/database/users.db',
            'AUTH_DOWNLOAD_DIR=/app/processed/secure_downloads',
            'TRUSTED_PROXY_NETWORKS=' + self.proxy_ip + '/32,127.0.0.1/32',
            'ORDER_API_KEY=' + secrets.token_urlsafe(32), 'ORDER_DATA_DIR=/app/order_data',
            'PYTHONDONTWRITEBYTECODE=1', 'PYTHONUNBUFFERED=1', 'TZ=Asia/Seoul',
            'STREAMLIT_SERVER_ENABLE_CORS=true', 'STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=true',
            'STREAMLIT_SERVER_RUN_ON_SAVE=false', 'STREAMLIT_SERVER_HEADLESS=true',
            'STREAMLIT_SERVER_FILE_WATCHER_TYPE=none', 'STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=false',
            'STREAMLIT_BROWSER_GATHER_USAGE_STATS=false',
            'STREAMLIT_BROWSER_SERVER_ADDRESS=sollumeesthe.com', 'STREAMLIT_BROWSER_SERVER_PORT=443',
        ]) + '\n')
        os.chmod(self.env_path, 0o600)
        self.image_id = docker('image', 'inspect', self.image, '--format', '{{.Id}}').stdout.strip()
        self.nginx_id = docker('image', 'inspect', 'nginx:alpine', '--format', '{{.Id}}').stdout.strip()
        self.record('production_dependency_image_available', self.image_id.startswith('sha256:'))
        self.run_service('app', 'sollume-app', ['streamlit', 'run', 'Home.py', '--server.address=0.0.0.0', '--server.port=8501'])
        self.run_service('auth', 'sollume-auth', ['gunicorn', '--bind', '0.0.0.0:8503', '--workers', '2', '--timeout', '60',
                                              '--pythonpath', '/app/Src', 'auth_gateway:create_app()'])
        self.run_service('api', 'sollume-api', ['gunicorn', '--bind', '0.0.0.0:8502', '--workers', '2', '--timeout', '120',
                                            '--pythonpath', '/app/Src', 'api_server:app'])
        proxy = self.prefix + '-nginx'
        self.containers.append(proxy)
        docker('run', '-d', '--name', proxy, '--label', 'sollume.security.qa=' + self.prefix,
               '--network', self.network, '--ip', self.proxy_ip,
               '-p', f'127.0.0.1:{self.secure_port}:443', '-p', f'127.0.0.1:{self.http_port}:80',
               '-v', f'{ROOT}/nginx.conf:/etc/nginx/nginx.conf:ro',
               '-v', f'{self.tmp}/ssl:/etc/nginx/ssl:ro', 'nginx:alpine')
        for attempt in range(30):
            try:
                response = self.request('GET', '/auth/login')
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Disposable Nginx/auth runtime not ready')
        self.record('actual_nginx_configuration_valid', docker('exec', proxy, 'nginx', '-t').returncode == 0)
        configured = docker('exec', proxy, 'nginx', '-V').stderr
        self.record('actual_nginx_auth_request_module_available', '--with-http_auth_request_module' in configured)
        inspections = json.loads(docker('inspect', *self.containers).stdout)
        all_internal_closed = all(not x['HostConfig']['PortBindings'] for x in inspections[:-1])
        proxy_loopback_only = all(binding['HostIp'] == '127.0.0.1'
                                  for bindings in inspections[-1]['HostConfig']['PortBindings'].values()
                                  for binding in bindings)
        self.record('application_auth_api_ports_not_published_proxy_loopback_only',
                    all_internal_closed and proxy_loopback_only)
        self.record('actual_runtime_code_mounted_read_only',
                    all(all(not m['RW'] for m in x['Mounts'] if m['Destination'] in ('/app/Src', '/app/Home.py', '/app/pages'))
                        for x in inspections[:-1]))
        self.record('actual_runtime_uses_disposable_db_orders_processed',
                    all(all(m['Source'].startswith(str(self.tmp)) for m in x['Mounts']
                            if m['Destination'] in ('/app/database', '/app/order_data', '/app/processed'))
                        for x in inspections[:-1]))

    def run_service(self, role, alias, command):
        name = self.prefix + '-' + role
        self.containers.append(name)
        args = ['run', '-d', '--name', name, '--label', 'sollume.security.qa=' + self.prefix,
                '--network', self.network, '--network-alias', alias, '--env-file', self.env_path,
                '--read-only', '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:size=256m']
        for path in ('Src', 'pages', 'Home.py', 'assets', 'scripts', '.streamlit'):
            args += ['-v', f'{ROOT}/{path}:/app/{path}:ro']
        for path in ('database', 'processed', 'logs', 'order_data', 'uploads'):
            args += ['-v', f'{self.tmp}/{path}:/app/{path}']
        docker(*args, self.image_id, *command)

    def handshake(self, token='', origin='https://sollumeesthe.com', extra=None):
        headers = {'Host': 'sollumeesthe.com', 'Upgrade': 'websocket', 'Connection': 'Upgrade',
                   'Sec-WebSocket-Version': '13', 'Sec-WebSocket-Key': base64.b64encode(secrets.token_bytes(16)).decode(),
                   'Sec-WebSocket-Protocol': 'streamlit', 'Origin': origin}
        if token:
            headers['Cookie'] = '__Host-sollume_session=' + token
        headers.update(extra or {})
        context = ssl._create_unverified_context()
        with socket.create_connection(('127.0.0.1', self.secure_port), timeout=10) as connection:
            with context.wrap_socket(connection, server_hostname='sollumeesthe.com') as secure:
                secure.sendall(('GET /_stcore/stream HTTP/1.1\r\n' +
                                ''.join(f'{name}: {value}\r\n' for name, value in headers.items()) + '\r\n').encode())
                result = b''
                while b'\r\n\r\n' not in result:
                    chunk = secure.recv(4096)
                    if not chunk:
                        break
                    result += chunk
                return int(result.split(b' ')[1]), secure.version()

    def login(self, name, first=True):
        browser = requests.Session()
        username = 'fixture_' + name
        csrf, response = self.csrf('/auth/login', browser)
        response = self.request('POST', '/auth/login', browser, retry_rate=True,
                                data={'csrf_token': csrf, 'username': username, 'password': self.initial_password if first else self.password})
        self.record(name + '_password_redirects_only_to_mfa_or_enrollment',
                    response.status_code == 303 and response.headers.get('Location') == '/auth/enroll')
        self.record(name + '_password_challenge_cannot_access_app',
                    self.request('GET', '/', browser).status_code == 401)
        self.record(name + '_password_challenge_cannot_open_websocket',
                    self.handshake(extra={'Cookie': '; '.join(c.name + '=' + c.value for c in browser.cookies)})[0] == 401)
        self.record(name + '_password_challenge_cannot_download',
                    self.request('GET', '/downloads/' + 'f' * 48, browser).status_code == 401)
        csrf, response = self.csrf('/auth/enroll', browser)
        response = self.request('POST', '/auth/enroll', browser, retry_rate=True,
                                data={'csrf_token': csrf, 'stage': 'prepare', 'enrollment_code': self.codes[name]})
        self.record(name + '_valid_local_enrollment_code_accepted', response.status_code == 303)
        csrf, response = self.csrf('/auth/enroll', browser)
        match = re.search(r'<code>([A-Z2-7]+)</code>', response.text)
        self.record(name + '_server_generated_qr_and_manual_secret_visible_after_proof',
                    match is not None and 'data:image/svg+xml;base64,' in response.text)
        secret = match.group(1)
        otp = self.service._totp(secret, int(time.time() // 30))
        response = self.request('POST', '/auth/enroll', browser, retry_rate=True,
                                data={'csrf_token': csrf, 'stage': 'complete', 'otp': otp,
                                      'new_password': self.password, 'confirm_password': self.password})
        self.record(name + '_mfa_enrollment_and_forced_password_change_completes_login',
                    response.status_code == 303 and response.headers.get('Location') == 'https://sollumeesthe.com/')
        token = next((c.value for c in browser.cookies if c.name == '__Host-sollume_session'), '')
        self.record(name + '_production_session_cookie_secure_http_only_host_only',
                    bool(token) and any('__Host-sollume_session=' in h and 'Secure' in h and 'HttpOnly' in h
                                        and 'SameSite=Lax' in h and 'Path=/' in h and 'Domain=' not in h
                                        for h in response.raw.headers.getlist('Set-Cookie')))
        # Always put tokens in memory; nothing secret is emitted in JSON evidence.
        self.record(name + '_complete_session_receives_streamlit_shell',
                    self.request('GET', '/', headers={'Cookie': '__Host-sollume_session=' + token}).status_code == 200)
        return browser, token, secret

    def cookie_request(self, token, path, method='GET', **kwargs):
        return self.request(method, path, headers={'Cookie': '__Host-sollume_session=' + token}, **kwargs)

    def test(self):
        response = self.request('GET', '/', headers={'Accept': 'text/html'})
        self.record('anonymous_browser_root_redirects_login', response.status_code == 302
                    and response.headers.get('Location') in ('/auth/login', 'https://sollumeesthe.com/auth/login'),
                    status=response.status_code, location=response.headers.get('Location'))
        for path in ('/', '/daily-voucher', '/users', '/system', '/_stcore/upload_file/fake/fake', '/static/fake.js'):
            self.record('anonymous_http_blocked_' + path.replace('/', '_'), self.request('GET', path).status_code == 401)
        self.record('anonymous_upload_post_blocked_before_streamlit',
                    self.request('POST', '/_stcore/upload_file/fake/fake', data=b'no-file').status_code == 401)
        status, version = self.handshake()
        self.record('anonymous_websocket_denied', status == 401)
        self.record('tls12_or_tls13_in_use', version in ('TLSv1.2', 'TLSv1.3'), tls_version=version)
        for path in ('/media', '/media/fake.xls'):
            self.record('legacy_media_route_denied_' + path.replace('/', '_'), self.request('GET', path).status_code == 403)
        for path in ('/_auth_check', '/auth/check', '/auth/health', '/_stcore/health'):
            self.record('internal_endpoint_not_public_' + path.replace('/', '_'), self.request('GET', path).status_code == 404)
        self.record('spoofed_identity_ip_headers_do_not_bypass_auth',
                    self.request('GET', '/', headers={'X-Auth-User': 'fixture_admin', 'X-Auth-Role': 'admin',
                                                     'X-Real-IP': self.proxy_ip, 'X-Forwarded-For': '127.0.0.1',
                                                     'X-Forwarded-Proto': 'https'}).status_code == 401)
        try:
            self.request('GET', '/', headers={'Host': 'attacker.example'})
            rejected = False
        except requests.ConnectionError:
            rejected = True
        self.record('unexpected_public_host_connection_rejected', rejected)
        http_response = requests.get(f'http://127.0.0.1:{self.http_port}/users', headers={'Host': 'attacker.example'},
                                     allow_redirects=False, timeout=10)
        self.record('http_redirect_fixed_https_domain_no_host_reflection',
                    http_response.status_code == 301 and http_response.headers.get('Location') == 'https://sollumeesthe.com/users')
        browser = requests.Session()
        csrf, login_page = self.csrf('/auth/login', browser)
        self.record('login_form_security_headers_and_no_store',
                    "form-action 'self'" in login_page.headers.get('Content-Security-Policy', '')
                    and 'no-store' in login_page.headers.get('Cache-Control', '')
                    and login_page.headers.get('X-Frame-Options') == 'DENY')
        self.record('csrf_missing_denied', self.request('POST', '/auth/login', browser, retry_rate=True,
                    data={'username': 'fixture_staff', 'password': self.initial_password}).status_code == 400)
        self.record('cross_origin_login_post_denied', self.request('POST', '/auth/login', browser, retry_rate=True,
                    headers={'Origin': 'https://attacker.example'}, data={'csrf_token': csrf,
                    'username': 'fixture_staff', 'password': self.initial_password}).status_code == 400)
        self.admin_browser, self.admin_token, admin_secret = self.login('admin')
        self.staff_browser, self.staff_token, staff_secret = self.login('staff')
        self.other_browser, self.other_token, other_secret = self.login('other')
        status, _ = self.handshake(self.staff_token)
        self.record('authenticated_websocket_upgrade_101', status == 101)
        self.record('authenticated_cross_origin_websocket_denied',
                    self.handshake(self.staff_token, origin='https://attacker.example')[0] == 403)
        # Execute from the API container's actual, nontrusted peer address. Spoofed proxy
        # headers and an otherwise valid admin cookie must not unlock the internal check.
        probe = '''import urllib.request, urllib.error, json
results={}
for path in ('/auth/check','/auth/login'):
    req=urllib.request.Request('http://sollume-auth:8503'+path,headers={
        'Host':'sollumeesthe.com','X-Real-IP':'127.0.0.1','X-Forwarded-For':'127.0.0.1',
        'X-Forwarded-Proto':'https','X-Forwarded-Host':'sollumeesthe.com'})
    try:
        response=urllib.request.urlopen(req,timeout=10)
        results[path]=response.status
    except urllib.error.HTTPError as error:
        results[path]=error.code
print(json.dumps(results))
'''
        direct = json.loads(docker('exec', self.prefix + '-api', 'python', '-c', probe).stdout)
        self.record('untrusted_internal_peer_spoofed_proxy_cannot_use_check_or_https_login',
                    direct == {'/auth/check': 404, '/auth/login': 400})
        self.record('staff_service_allowed_daily_only_and_admin_denied',
                    self.service.require_permission(self.staff_token, 'daily-voucher')['id'] == 77)
        for page in ('period-voucher', 'users', 'system'):
            try:
                self.service.require_permission(self.staff_token, page)
                denied = False
            except SecurityError:
                denied = True
            self.record('staff_permission_denied_' + page, denied)
        # A second actual core MFA login proves files are bound to one session, not only user ID.
        challenge = self.service.begin_login('fixture_staff', self.password, '192.0.2.2')
        second = self.service.complete_login(challenge['token'], self.service._totp(staff_secret, int(time.time() // 30) + 1))
        contents = b'synthetic accounting export first immutable snapshot'
        grant = self.service.register_download(self.staff_token, contents, 'same-name.xls', 'application/vnd.ms-excel', 'daily-voucher')
        second_grant = self.service.register_download(self.staff_token, b'second contents', 'same-name.xls', 'application/vnd.ms-excel', 'daily-voucher')
        response = self.cookie_request(self.staff_token, '/downloads/' + grant)
        self.record('valid_download_exact_original_bytes_immutable_same_filename', response.status_code == 200 and response.content == contents)
        self.record('valid_download_attachment_no_store', 'attachment;' in response.headers.get('Content-Disposition', '') and 'no-store' in response.headers.get('Cache-Control', ''))
        self.record('anonymous_download_denied', self.request('GET', '/downloads/' + grant).status_code == 401)
        self.record('other_user_download_denied', self.cookie_request(self.other_token, '/downloads/' + grant).status_code == 403)
        self.record('same_user_other_session_download_denied', self.cookie_request(second, '/downloads/' + grant).status_code == 403)
        self.record('malformed_download_id_denied', self.cookie_request(self.staff_token, '/downloads/not-a-grant').status_code == 403)
        self.record('legacy_media_denied_even_when_authenticated', self.cookie_request(self.staff_token, '/media/fake.xls').status_code == 403)
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute('UPDATE security_downloads SET expires_at=? WHERE id=?', (time.time() - 1, second_grant))
        self.record('expired_download_denied', self.cookie_request(self.staff_token, '/downloads/' + second_grant).status_code == 403)
        self.service.admin_update_user(self.admin_token, 77, permissions=[])
        self.record('permission_change_revokes_previous_staff_http', self.cookie_request(self.staff_token, '/').status_code == 401)
        self.record('permission_change_revokes_previous_staff_download', self.cookie_request(self.staff_token, '/downloads/' + grant).status_code == 401)
        self.record('permission_change_revokes_previous_staff_websocket', self.handshake(self.staff_token)[0] == 401)
        self.record('permission_change_revokes_all_other_staff_sessions', self.cookie_request(second, '/').status_code == 401)
        self.service.admin_update_user(self.admin_token, self.users['other'], is_active=False)
        self.record('account_suspension_revokes_http_and_websocket', self.cookie_request(self.other_token, '/').status_code == 401 and self.handshake(self.other_token)[0] == 401)
        self.service.admin_update_user(self.admin_token, self.users['other'], is_active=True)
        # Expiry tests use independent valid sessions issued by core MFA flow with a later tolerated step.
        other_challenge = self.service.begin_login('fixture_other', self.password, '192.0.2.3')
        other_expiring = self.service.complete_login(other_challenge['token'], self.service._totp(other_secret, int(time.time() // 30) + 1))
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute('UPDATE security_sessions SET last_seen=? WHERE token_hash=?',
                         (time.time() - self.service.IDLE_SECONDS - 1, self.service._digest(other_expiring)))
        self.record('idle_timeout_denies_http_and_websocket', self.cookie_request(other_expiring, '/').status_code == 401 and self.handshake(other_expiring)[0] == 401)
        auth_name = self.prefix + '-auth'
        docker('stop', '-t', '1', auth_name)
        try:
            self.record('auth_service_unavailable_fails_closed_root', self.cookie_request(self.admin_token, '/').status_code == 500)
            self.record('auth_service_unavailable_fails_closed_download', self.cookie_request(self.admin_token, '/downloads/' + grant).status_code == 500)
            self.record('auth_service_unavailable_fails_closed_websocket', self.handshake(self.admin_token)[0] == 500)
        finally:
            docker('start', auth_name)
        for attempt in range(20):
            if self.cookie_request(self.admin_token, '/').status_code == 200:
                break
            time.sleep(1)
        self.record('auth_service_restored_same_admin_session_operates', self.cookie_request(self.admin_token, '/').status_code == 200)
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute('UPDATE security_sessions SET auth_time=? WHERE token_hash=?',
                         (time.time() - self.service.SESSION_SECONDS - 1, self.service._digest(self.admin_token)))
        self.record('absolute_eight_hour_timeout_denies_http_and_websocket', self.cookie_request(self.admin_token, '/').status_code == 401 and self.handshake(self.admin_token)[0] == 401)
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute('UPDATE security_sessions SET auth_time=? WHERE token_hash=?', (time.time(), self.service._digest(self.admin_token)))
        csrf, response = self.csrf('/auth/logout', self.admin_browser)
        self.record('logout_without_csrf_denied_and_session_retained',
                    self.request('POST', '/auth/logout', self.admin_browser, retry_rate=True).status_code == 400
                    and self.cookie_request(self.admin_token, '/').status_code == 200)
        response = self.request('POST', '/auth/logout', self.admin_browser, retry_rate=True, data={'csrf_token': csrf})
        self.record('csrf_confirmed_logout_revokes_cookie_session', response.status_code == 303 and self.cookie_request(self.admin_token, '/').status_code == 401)

    def close(self):
        if self.closed:
            return
        self.closed = True
        results = [docker('rm', '-f', name, check=False).returncode == 0 for name in reversed(self.containers)]
        network = docker('network', 'rm', self.network, check=False)
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.cleanup_ok = all(results) and network.returncode == 0 and not self.tmp.exists()

    def write_result(self, error=None):
        ending_hashes = source_hashes()
        result = {'generated_at': datetime.now(timezone.utc).isoformat(), 'started_at': self.started,
                  'passed': error is None and self.cleanup_ok and all(c['passed'] for c in self.checks)
                            and ending_hashes == self.initial_hashes,
                  'check_count': len(self.checks), 'checks': self.checks,
                  'image': self.image, 'image_id': getattr(self, 'image_id', None),
                  'nginx_image_id': getattr(self, 'nginx_id', None),
                  'source_sha256': self.initial_hashes,
                  'source_unchanged_during_run': ending_hashes == self.initial_hashes,
                  'cleanup_complete': self.cleanup_ok, 'positive_login_rate_limit_retries': self.rate_retries,
                  'limitations': self.limits, 'error_type': type(error).__name__ if error else None}
        if ending_hashes != self.initial_hashes:
            result['changed_source_paths'] = [p for p in ending_hashes if ending_hashes[p] != self.initial_hashes[p]]
            result['limitations'].append('Source changed during this run; rerun after final source changes before final approval.')
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'passed': result['passed'], 'checks': len(self.checks), 'cleanup': self.cleanup_ok,
                          'source_unchanged': result['source_unchanged_during_run'], 'result': str(self.output)}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='sollume-finance-security:test')
    parser.add_argument('--output', default=str(ROOT / '.Codex/user-management/runtime-results.json'))
    args = parser.parse_args()
    runtime = Runtime(args.image, args.output)
    failure = None
    try:
        runtime.setup()
        runtime.test()
    except BaseException as exc:
        failure = exc
        print('Runtime verification failed: ' + type(exc).__name__, flush=True)
    finally:
        runtime.close()
        runtime.write_result(failure)
    if failure:
        raise failure


if __name__ == '__main__':
    main()
