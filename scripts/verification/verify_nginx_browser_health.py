"""2026-10-21 hoyeon.han: 실제 HTTPS Nginx와 Chrome의 로그인 연결 회귀 검증.

운영 호스트용 Nginx 정책을 격리 Docker 주소/고포트/임시 인증서에만 맞춘다.
실제 Home.py·인증 서버를 production 모드로 실행하고 합성 계정·임시 DB만
사용한다. 기존 업무 폴더는 마운트하지 않고 기존 컨테이너를 조작하지 않는다.
비밀번호, MFA secret, 등록 코드, 쿠키, 다운로드 ID는 결과에 기록하지 않는다.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback

from cryptography.fernet import Fernet
import pyotp
import requests
import urllib3
# from playwright.sync_api import sync_playwright
# 2026-11-05 hoyeon.han: 개인 baseline을 명시적으로 검증하고 정식 소스·결과 경로를 사용한다.
# from playwright.sync_api import sync_playwright  # 실제 실행 함수에서 지연 import한다.

ROOT = Path(__file__).resolve().parents[2]

# 2026-11-05 hoyeon.han: 정식 검증 경로와 개인 입력·결과 경로를 분리한다.
sys.path.insert(0, str(ROOT))
from scripts.verification.verification_common import DEFAULT_OUTPUT_DIR, add_baseline_argument, load_baseline
sys.path.insert(0, str(ROOT / 'Src'))
from security_service import SecurityError, SecurityService

HOST = 'office1.sollumeesthe.com'
COOKIE = '__Host-sollume_session'
CHALLENGE = '__Host-sollume_challenge'


def docker(*args, check=True):
    result = subprocess.run(['docker', *map(str, args)], capture_output=True,
                            text=True, timeout=120)
    if check and result.returncode:
        # 2026-10-21 hoyeon.han: env/쿠키/요청 주소가 섞일 수 있는 원시 출력을 노출하지 않는다.
        raise RuntimeError('격리 Docker 명령 실패: ' + str(args[0]))
    return result


def free_port():
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
        return connection.getsockname()[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def business_hashes():
    result = {}
    for directory in ('database', 'order_data', 'uploads', 'processed'):
        for path in sorted((ROOT / directory).rglob('*')):
            if path.is_file() and not path.is_symlink():
                result[str(path.relative_to(ROOT))] = digest(path)
    return result


def container_snapshot():
    ids = docker('ps', '-aq').stdout.split()
    if not ids:
        return {}
    records = json.loads(docker('inspect', *ids).stdout)
    # 2026-10-21 hoyeon.han: 설정 환경 변수나 비밀값을 전후 증적에 포함하지 않는다.
    # Docker inspect의 Mounts 배열 순서는 고정되지 않아 목적지/원본으로 정렬한다.
    # Health.Log 등의 시간별 진단 기록은 제외하고 실행·시작·종료 상태를 비교한다.
    return {item['Id']: {'image': item['Image'], 'state': {key: item['State'].get(key) for key in (
                            'Status', 'Running', 'Paused', 'Restarting', 'OOMKilled', 'Dead',
                            'Pid', 'ExitCode', 'Error', 'StartedAt', 'FinishedAt')},
                        'restart_count': item['RestartCount'],
                        'mounts': sorted(item['Mounts'], key=lambda mount: (mount['Destination'], mount['Source'])),
                        'port_bindings': item['HostConfig']['PortBindings'],
                        'nano_cpus': item['HostConfig']['NanoCpus'],
                        'memory': item['HostConfig']['Memory']}
            for item in records}


class BrowserRuntime:
    def __init__(self, image, output):
        self.image, self.output = image, Path(output)
        self.temp = Path(tempfile.mkdtemp(prefix='sollume-health-browser-', dir='/private/tmp'))
        os.chmod(self.temp, 0o700)
        self.prefix = 'sollume-health-browser-' + secrets.token_hex(5)
        self.network = self.prefix + '-net'
        self.names = []
        self.port, self.http_port = free_port(), free_port()
        self.origin = f'https://{HOST}:{self.port}'
        self.direct = f'https://127.0.0.1:{self.port}'
        self.checks = []
        self.started = datetime.now(timezone.utc).isoformat()
        self.containers_before = container_snapshot()
        self.images_before = set(docker('image', 'ls', '-aq', '--no-trunc').stdout.split())
        self.data_before = business_hashes()
        self.source_before = {name: digest(ROOT / name) for name in (
            'nginx-host-api.conf.example', 'Src/auth_gateway.py', 'Src/auth.py',
            'Src/security_service.py', 'Home.py', 'pages/users.py')}
        self.enrollment_secrets = {}
        self.otp_steps = {}
        self.contexts = []
        self.health_responses = []
        self.websocket_connections = []
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def record(self, name, passed, **details):
        self.checks.append({'name': name, 'passed': bool(passed), **details})
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)
        if not passed:
            raise AssertionError(name)

    def request(self, path, token=None, accept='application/json', **kwargs):
        headers = {'Host': f'{HOST}:{self.port}', 'Accept': accept}
        if token:
            headers['Cookie'] = COOKIE + '=' + token
        session = requests.Session()
        session.trust_env = False
        return session.get(self.direct + path, headers=headers, timeout=15,
                           verify=False, allow_redirects=False, **kwargs)

    def run_service(self, role, alias, command):
        name = self.prefix + '-' + role
        self.names.append(name)
        args = ['run', '-d', '--pull', 'never', '--name', name, '--network', self.network,
                '--network-alias', alias, '--env-file', str(self.temp / 'runtime.env'),
                '--read-only', '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:size=256m']
        for source in ('Src', 'pages', 'Home.py', 'assets', 'scripts', '.streamlit'):
            args += ['-v', f'{ROOT / source}:/app/{source}:ro']
        for folder in ('database', 'processed', 'logs', 'order_data', 'uploads'):
            args += ['-v', f'{self.temp / folder}:/app/{folder}']
        docker(*args, self.image_id, *command)

    def setup(self):
        for directory in ('database', 'processed', 'logs', 'order_data', 'uploads', 'ssl'):
            (self.temp / directory).mkdir(mode=0o700)
        self.key = Fernet.generate_key().decode()
        self.service = SecurityService(self.temp / 'database/users.db', self.key,
                                       self.temp / 'processed/secure_downloads')
        self.initial_password = 'Initial-' + secrets.token_urlsafe(24)
        self.passwords = {role: 'Changed-' + secrets.token_urlsafe(24)
                          for role in ('admin', 'staff', 'other')}
        self.users = {role: self.service.bootstrap_user(
            'health_qa_' + role, self.initial_password, is_admin=role == 'admin',
            permissions=['order-summary'] if role != 'admin' else [])
            for role in ('admin', 'staff', 'other')}
        self.invitations = {role: self.service.issue_enrollment_local(user['id'])
                            for role, user in self.users.items()}
        for octet in range(225, 240):
            if docker('network', 'create', '--subnet', f'172.31.{octet}.0/24',
                      self.network, check=False).returncode == 0:
                self.proxy_ip = f'172.31.{octet}.10'
                break
        else:
            raise RuntimeError('격리 Docker 네트워크 생성 실패')
        self.image_id = docker('image', 'inspect', self.image, '--format', '{{.Id}}').stdout.strip()
        self.nginx_image_id = docker('image', 'inspect', 'nginx:alpine', '--format', '{{.Id}}').stdout.strip()
        values = {'AUTH_ENV': 'production', 'AUTH_PUBLIC_ORIGIN': self.origin,
                  'AUTH_ENCRYPTION_KEY': self.key, 'AUTH_DB_PATH': '/app/database/users.db',
                  'AUTH_DOWNLOAD_DIR': '/app/processed/secure_downloads',
                  'TRUSTED_PROXY_NETWORKS': self.proxy_ip + '/32,127.0.0.1/32',
                  'ORDER_API_KEY': secrets.token_urlsafe(32), 'ORDER_DATA_DIR': '/app/order_data',
                  'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
                  'STREAMLIT_SERVER_ENABLE_CORS': 'true',
                  'STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION': 'true',
                  'STREAMLIT_SERVER_HEADLESS': 'true', 'STREAMLIT_SERVER_RUN_ON_SAVE': 'false',
                  'STREAMLIT_SERVER_FILE_WATCHER_TYPE': 'none',
                  'STREAMLIT_CLIENT_SHOW_ERROR_DETAILS': 'false',
                  'STREAMLIT_BROWSER_GATHER_USAGE_STATS': 'false',
                  'STREAMLIT_BROWSER_SERVER_ADDRESS': HOST,
                  'STREAMLIT_BROWSER_SERVER_PORT': str(self.port)}
        self.env_path = self.temp / 'runtime.env'
        self.env_path.write_text('\n'.join(key + '=' + value for key, value in values.items()) + '\n')
        os.chmod(self.env_path, 0o600)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=' + HOST, '-addext', 'subjectAltName=DNS:' + HOST + ',IP:127.0.0.1',
                        '-keyout', str(self.temp / 'ssl/privkey.pem'),
                        '-out', str(self.temp / 'ssl/fullchain.pem')], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.chmod(self.temp / 'ssl/privkey.pem', 0o600)
        self.run_service('app', 'sollume-app', ['streamlit', 'run', 'Home.py',
                         '--server.address=0.0.0.0', '--server.port=8501'])
        self.run_service('auth', 'sollume-auth', ['gunicorn', '--bind', '0.0.0.0:8503',
                         '--workers', '2', '--timeout', '60', '--pythonpath', '/app/Src',
                         'auth_gateway:create_app()'])
        self.run_service('api', 'sollume-api', ['gunicorn', '--bind', '0.0.0.0:8502',
                         '--workers', '1', '--pythonpath', '/app/Src', 'api_server:app'])
        source = (ROOT / 'nginx-host-api.conf.example').read_text()
        # 2026-10-21 hoyeon.han: 인증 정책은 유지하고 격리 실행 주소·인증서·포트만 치환한다.
        rendered = source.replace('http://127.0.0.1:8501', 'http://sollume-app:8501')
        rendered = rendered.replace('http://127.0.0.1:8502', 'http://sollume-api:8502')
        rendered = rendered.replace('http://127.0.0.1:8503', 'http://sollume-auth:8503')
        rendered = rendered.replace('/etc/letsencrypt/live/' + HOST + '/', '/etc/nginx/ssl/')
        rendered = rendered.replace('proxy_set_header Host ' + HOST + ';',
                                    f'proxy_set_header Host {HOST}:{self.port};')
        rendered = rendered.replace('proxy_set_header X-Forwarded-Host ' + HOST + ';',
                                    f'proxy_set_header X-Forwarded-Host {HOST}:{self.port};')
        config = 'worker_processes 1;\nevents { worker_connections 512; }\nhttp {\naccess_log off;\n' + rendered + '\n}\n'
        self.config_path = self.temp / 'nginx.conf'
        self.config_path.write_text(config)
        self.proxy = self.prefix + '-nginx'
        self.names.append(self.proxy)
        docker('run', '-d', '--pull', 'never', '--name', self.proxy, '--network', self.network,
               '--ip', self.proxy_ip, '-p', f'127.0.0.1:{self.port}:443',
               '-p', f'127.0.0.1:{self.http_port}:80', '--read-only',
               '--tmpfs', '/var/cache/nginx', '--tmpfs', '/var/run', '--tmpfs', '/tmp',
               '-v', str(self.config_path) + ':/etc/nginx/nginx.conf:ro',
               '-v', str(self.temp / 'ssl') + ':/etc/nginx/ssl:ro', self.nginx_image_id)
        for _ in range(80):
            try:
                if self.request('/auth/login').status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError('격리 HTTPS 인증 서버 준비 실패')
        self.record('actual_host_nginx_template_syntax_valid',
                    docker('exec', self.proxy, 'nginx', '-t').returncode == 0)
        records = json.loads(docker('inspect', *self.names).stdout)
        self.record('all_business_storage_mounts_are_disposable', all(
            mount['Source'].startswith(str(self.temp)) for item in records
            for mount in item['Mounts'] if mount['Destination'] in (
                '/app/database', '/app/processed', '/app/order_data', '/app/uploads', '/app/logs')))
        self.record('application_code_mounts_are_read_only', all(
            not mount['RW'] for item in records for mount in item['Mounts']
            if mount['Destination'] in ('/app/Src', '/app/pages', '/app/Home.py')))
        self.record('backend_ports_are_not_published', all(not item['HostConfig']['PortBindings']
                                                          for item in records[:-1]))

    def new_context(self, browser):
        context = browser.new_context(ignore_https_errors=True)
        self.contexts.append(context)
        # 2026-10-21 hoyeon.han: 실제 데이터나 로그인 값이 담길 수 있는 HAR/trace는 저장하지 않는다.
        context.route('**/*', lambda route: route.continue_()
                      if route.request.url.startswith(self.origin + '/')
                      or route.request.url.startswith('data:') else route.abort())
        return context

    def observe(self, page):
        page.on('response', lambda response: self.health_responses.append(response.status)
                if response.url.split('?', 1)[0] == self.origin + '/_stcore/health' else None)
        page.on('websocket', lambda ws: self.websocket_connections.append(True)
                if ws.url.split('?', 1)[0].endswith('/_stcore/stream') else None)

    @staticmethod
    def token(context):
        return next(cookie['value'] for cookie in context.cookies() if cookie['name'] == COOKIE)

    def next_otp(self, role):
        current = int(time.time() // 30)
        previous = self.otp_steps.get(role, -1)
        if current <= previous:
            time.sleep((previous + 1) * 30 - time.time() + .3)
        step = int(time.time() // 30)
        self.otp_steps[role] = step
        return pyotp.TOTP(self.enrollment_secrets[role]).at(step * 30)

    def enroll(self, browser, role):
        context = self.new_context(browser)
        page = context.new_page()
        self.observe(page)
        page.goto(self.origin + '/auth/login')
        page.get_by_label('사용자 ID').fill(self.users[role]['username'])
        page.get_by_label('비밀번호', exact=True).fill(self.initial_password)
        page.get_by_role('button', name='다음: 2단계 인증').click()
        page.locator('#enrollment_code').wait_for(timeout=15000)
        self.record(role + '_password_only_cannot_access_health',
                    self.request('/_stcore/health', cookies={cookie['name']: cookie['value']
                                 for cookie in context.cookies()}).status_code == 401)
        page.get_by_label('일회용 등록 코드').fill(self.invitations[role])
        page.get_by_role('button', name='등록 코드 확인').click()
        page.get_by_label('연결한 인증 앱의 6자리 번호').wait_for(timeout=15000)
        challenge = next(cookie['value'] for cookie in context.cookies() if cookie['name'] == CHALLENGE)
        self.enrollment_secrets[role] = self.service.get_challenge(challenge)['pending_secret']
        page.get_by_label('새 비밀번호 — 12자 이상', exact=True).fill(self.passwords[role])
        page.get_by_label('새 비밀번호 확인', exact=True).fill(self.passwords[role])
        page.get_by_label('연결한 인증 앱의 6자리 번호').fill(self.next_otp(role))
        page.get_by_role('button', name='등록 완료하고 로그인').click()
        page.wait_for_url(self.origin + '/', timeout=20000)
        page.get_by_text(self.users[role]['username'], exact=True).wait_for(timeout=30000)
        self.record(role + '_production_https_mfa_enrollment_reaches_real_home',
                    not page.locator('[data-testid="stException"]').count())
        self.record(role + '_authenticated_health_is_real_streamlit_200',
                    self.request('/_stcore/health', self.token(context)).status_code == 200)
        return context, page

    def login(self, browser, role):
        # 2026-10-21 hoyeon.han: 운영 rate-limit을 완화하지 않고 합성 연속 로그인 간격을 둔다.
        time.sleep(24.5)
        context = self.new_context(browser)
        page = context.new_page()
        self.observe(page)
        page.goto(self.origin + '/auth/login')
        page.get_by_label('사용자 ID').fill(self.users[role]['username'])
        page.get_by_label('비밀번호', exact=True).fill(self.passwords[role])
        page.get_by_role('button', name='다음: 2단계 인증').click()
        page.get_by_label('인증 앱 번호', exact=True).wait_for(timeout=15000)
        page.get_by_label('인증 앱 번호', exact=True).fill(self.next_otp(role))
        page.get_by_role('button', name='인증하고 로그인', exact=True).click()
        page.wait_for_url(self.origin + '/', timeout=20000)
        page.get_by_text(self.users[role]['username'], exact=True).wait_for(timeout=30000)
        return context, page

    def exercise(self):
        # 2026-11-05 hoyeon.han: 개인 baseline을 명시적으로 검증하고 정식 소스·결과 경로를 사용한다.
        from playwright.sync_api import sync_playwright
        self.record('anonymous_health_json_401', self.request('/_stcore/health').status_code == 401)
        self.record('anonymous_health_html_login_redirect',
                    self.request('/_stcore/health', accept='text/html').status_code == 302)
        self.record('internal_auth_endpoints_remain_hidden', all(
            self.request(path).status_code == 404 for path in ('/auth/check', '/auth/health', '/_auth_check')))
        self.record('legacy_media_remains_forbidden', self.request('/media/synthetic.xls').status_code == 403)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                headless=True, args=['--no-proxy-server',
                    '--host-resolver-rules=MAP ' + HOST + ' 127.0.0.1'])
            try:
                admin_context, admin_page = self.enroll(browser, 'admin')
                admin_page.get_by_role('link', name='사용자관리', exact=True).click()
                admin_page.get_by_role('button', name='직원 계정 생성', exact=True).wait_for(timeout=20000)
                self.record('admin_opens_real_user_management_page',
                            not admin_page.locator('[data-testid="stException"]').count())
                staff_context, staff_page = self.enroll(browser, 'staff')
                self.record('staff_navigation_contains_only_allowed_business_page',
                            staff_page.get_by_role('link', name='요약', exact=True).count() == 1
                            and staff_page.get_by_role('link', name='일별 전표', exact=True).count() == 0
                            and staff_page.get_by_role('link', name='사용자관리', exact=True).count() == 0
                            and staff_page.get_by_role('link', name='시스템 관리', exact=True).count() == 0)
                staff_page.get_by_role('link', name='요약', exact=True).click()
                staff_page.locator('.sl-ph-title').filter(has_text='발주내역 요약').wait_for(timeout=20000)
                self.record('staff_allowed_page_renders_via_real_websocket',
                            not staff_page.locator('[data-testid="stException"]').count())
                staff_page.goto(self.origin + '/users')
                staff_page.get_by_text(self.users['staff']['username'], exact=True).wait_for(timeout=20000)
                self.record('staff_direct_admin_url_does_not_render_management_controls',
                            staff_page.get_by_role('button', name='직원 계정 생성', exact=True).count() == 0
                            and staff_page.get_by_role('tab', name='계정·접근 권한 설정', exact=True).count() == 0)
                try:
                    self.service.require_permission(self.token(staff_context), 'users')
                except SecurityError:
                    denied = True
                else:
                    denied = False
                self.record('staff_direct_admin_action_permission_is_denied', denied)
                other_context, _ = self.enroll(browser, 'other')
                staff_token = self.token(staff_context)
                contents = b'Synthetic health fix download fixture\n'
                grant = self.service.register_download(staff_token, contents, 'synthetic.xls',
                                                        'application/vnd.ms-excel', 'order-summary')
                path = '/downloads/' + grant
                response = self.request(path, staff_token)
                self.record('download_owner_receives_exact_fixture_bytes',
                            response.status_code == 200 and response.content == contents)
                # 2026-10-21 hoyeon.han: 같은 fixture 링크를 실제 Chrome 쿠키로도 내려받는다.
                with staff_page.expect_download() as download_event:
                    staff_page.evaluate('''url => {
                        const link = document.createElement('a'); link.href = url;
                        document.body.appendChild(link); link.click(); link.remove();
                    }''', self.origin + path)
                download = download_event.value
                self.record('real_browser_download_receives_exact_fixture_bytes',
                            download.suggested_filename == 'synthetic.xls'
                            and Path(download.path()).read_bytes() == contents)
                self.record('download_attachment_is_not_cached',
                            'attachment;' in response.headers.get('Content-Disposition', '')
                            and 'no-store' in response.headers.get('Cache-Control', ''))
                self.record('anonymous_download_denied', self.request(path).status_code == 401)
                self.record('other_employee_download_denied',
                            self.request(path, self.token(other_context)).status_code == 403)
                second_context, _ = self.login(browser, 'staff')
                self.record('same_employee_other_login_session_download_denied',
                            self.request(path, self.token(second_context)).status_code == 403)
                expired = self.service.register_download(staff_token, contents, 'expired.xls',
                                                        'application/vnd.ms-excel', 'order-summary')
                with sqlite3.connect(self.service.db_path) as connection:
                    connection.execute('UPDATE security_downloads SET expires_at=? WHERE id=?',
                                       (time.time() - 1, expired))
                self.record('expired_download_denied',
                            self.request('/downloads/' + expired, staff_token).status_code == 403)
                # 2026-10-21 hoyeon.han: 직원의 권한 변경은 실제 관리자 화면의 폼으로 실행한다.
                admin_page.get_by_role('tab', name='계정·접근 권한 설정', exact=True).click()
                admin_page.get_by_test_id('stSelectbox').filter(has_text='설정할 직원').get_by_role('combobox').click()
                admin_page.get_by_role('option', name=self.users['staff']['username'] + ' ·', exact=False).click()
                permission = admin_page.get_by_test_id('stMultiSelect').filter(
                    has_text='직원에게 허용할 화면').get_by_role('combobox')
                permission.click()
                permission.press('Backspace')
                permission.fill('일별 전표')
                admin_page.get_by_role('option', name='일별 전표', exact=True).click()
                permission.press('Escape')
                admin_page.get_by_role('button', name='계정과 화면 권한 저장', exact=True).click()
                for _ in range(100):
                    if self.service.get_user_local(self.users['staff']['username'])['permissions'] == ['daily-voucher']:
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError('관리자 화면 권한 저장 확인 실패')
                self.record('admin_form_persists_staff_specific_page_permissions', True)
                staff_page.get_by_role('link', name='🔒 로그인 화면으로 이동').wait_for(timeout=25000)
                self.record('already_open_staff_websocket_is_revoked',
                            staff_page.get_by_role('link', name='요약', exact=True).count() == 0)
                self.record('permission_change_revokes_health_and_download',
                            self.request('/_stcore/health', staff_token).status_code == 401
                            and self.request(path, staff_token).status_code == 401)
                changed_context, changed_page = self.login(browser, 'staff')
                self.record('mfa_relogin_applies_changed_page_permissions',
                            changed_page.get_by_role('link', name='일별 전표', exact=True).count() == 1
                            and changed_page.get_by_role('link', name='요약', exact=True).count() == 0
                            and changed_page.get_by_role('link', name='사용자관리', exact=True).count() == 0)
                self.record('new_staff_session_cannot_reuse_old_download',
                            self.request(path, self.token(changed_context)).status_code == 403)
                self.record('browser_observed_successful_health_and_websocket',
                            bool(self.health_responses) and all(status == 200 for status in self.health_responses)
                            and len(self.websocket_connections) >= 5,
                            health_response_count=len(self.health_responses),
                            websocket_connection_count=len(self.websocket_connections))
                admin_page.get_by_role('link', name='로그아웃', exact=True).click()
                admin_page.get_by_role('button', name='로그아웃', exact=True).click()
                admin_page.wait_for_url('**/auth/login')
                self.record('production_logout_removes_secure_session_cookie',
                            not any(cookie['name'] == COOKIE for cookie in admin_context.cookies()))
            finally:
                browser.close()

    def close(self):
        cleanup = [docker('rm', '-f', name, check=False).returncode == 0 for name in reversed(self.names)]
        network = docker('network', 'rm', self.network, check=False)
        shutil.rmtree(self.temp, ignore_errors=True)
        self.cleanup_complete = all(cleanup) and network.returncode == 0 and not self.temp.exists()

    def finish(self, error=None):
        after = container_snapshot()
        preserved = all(after.get(identity) == state for identity, state in self.containers_before.items())
        differences = {identity[:12]: [key for key in state if after.get(identity, {}).get(key) != state[key]]
                       for identity, state in self.containers_before.items()
                       if after.get(identity) != state}
        images_after = set(docker('image', 'ls', '-aq', '--no-trunc').stdout.split())
        source_after = {name: digest(ROOT / name) for name in self.source_before}
        self.checks += [
            {'name': 'preexisting_containers_unchanged', 'passed': preserved,
             'container_count': len(self.containers_before), 'changed_fields': differences},
            {'name': 'preexisting_images_preserved', 'passed': self.images_before <= images_after},
            {'name': 'existing_business_files_unchanged', 'passed': self.data_before == business_hashes(),
             'file_count': len(self.data_before)},
            {'name': 'source_unchanged_during_verification', 'passed': self.source_before == source_after},
            {'name': 'owned_containers_network_and_secret_fixtures_removed', 'passed': self.cleanup_complete}]
        passed = error is None and all(check['passed'] for check in self.checks)
        report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'started_at': self.started,
                  'passed': passed, 'check_count': len(self.checks), 'checks': self.checks,
                  'source_sha256': self.source_before, 'image_id': getattr(self, 'image_id', None),
                  'nginx_image_id': getattr(self, 'nginx_image_id', None),
                  'error_type': type(error).__name__ if error else None,
                  'limitations': ['임시 자체 서명 인증서를 사용한 로컬 HTTPS 검사입니다. 운영 서버를 변경하지 않습니다.',
                                  '다운로드 파일은 보안 서비스에 등록한 합성 바이트입니다. 회계 계산 결과의 정확성은 검사하지 않습니다.',
                                  'Streamlit의 실제 비정상 준비 상태(503)는 이 브라우저 검사에서 유도하지 않았습니다.']}
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'passed': passed, 'checks': len(self.checks), 'error_type': report['error_type'],
                          'result': str(self.output)}, ensure_ascii=False), flush=True)
        return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='hoyeonhan/sollume-lab:auth-20261020-37f77d6')
    # parser.add_argument('--output', default=str(ROOT / '.codex/user-management/health-fix-local-browser-results.json'))
    # 2026-11-05 hoyeon.han: 정식 검증 경로와 개인 입력·결과 경로를 분리한다.
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT_DIR / 'health-fix-local-browser-results.json'))
    args = parser.parse_args()
    runtime = BrowserRuntime(args.image, args.output)
    error = None
    try:
        runtime.setup()
        runtime.exercise()
    except Exception as caught:
        error = caught
        print('검증 중단: ' + type(caught).__name__, flush=True)
        # 2026-10-21 hoyeon.han: 입력값 대신 실패한 함수·행 번호만 진단한다.
        print('실패 위치: ' + ', '.join(frame.name + ':' + str(frame.lineno)
              for frame in traceback.extract_tb(caught.__traceback__)
              if frame.filename == __file__), flush=True)
        reason = str(caught).splitlines()[0]
        for sensitive in [getattr(runtime, 'key', ''), getattr(runtime, 'initial_password', ''),
                          *getattr(runtime, 'passwords', {}).values(),
                          *getattr(runtime, 'invitations', {}).values(),
                          *runtime.enrollment_secrets.values()]:
            if sensitive:
                reason = reason.replace(sensitive, '[REDACTED]')
        reason = re.sub(r'(/downloads/)[A-Za-z0-9_-]+', r'\1[REDACTED]', reason)
        print('진단: ' + reason, flush=True)
    finally:
        runtime.close()
    if not runtime.finish(error):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
