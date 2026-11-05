"""2026-10-15 hoyeon.han: 합성 데이터로만 수행하는 실제 로컬 Docker 롤백 리허설.

운영 서비스/원본 DB/기존 localhost:8501·8503을 변경하지 않는다.
Runner는 호스트 Nginx 명령만 임시 컨테이너에 연결하며 나머지 검사는 원문을 실행한다.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
import pty
from pathlib import Path
import secrets
import re
import select
import shutil
import socket
import sqlite3
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from contextlib import closing

import bcrypt
from cryptography.fernet import Fernet
import requests

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == 'user-management' else Path.cwd()
sys.path.insert(0, str(ROOT / 'Src'))
from security_service import SecurityService


def module():
    spec = importlib.util.spec_from_file_location('sollume_release_qa', ROOT / 'scripts/release_snapshot.py')
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def command(args, *, input=None, env=None, check=True):
    result = subprocess.run(list(map(str, args)), input=input, env=env, text=True,
                            capture_output=True, timeout=300)
    if check and result.returncode:
        raise RuntimeError('격리 명령 실패: ' + ' '.join(map(str, args[:2])))
    return result.stdout if check else result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def image_id(name):
    # Docker Desktop의 저장소 태그 정규화 차이에도 실제 로컬 ID만 사용한다.
    result = command(['docker', 'image', 'ls', '--no-trunc', '--format', '{{.ID}}', name]).strip().splitlines()
    if not result:
        raise RuntimeError('필요한 로컬 fixture 이미지가 없습니다.')
    identifier = result[0]
    command(['docker', 'image', 'inspect', identifier])
    return identifier


class LocalRunner:
    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []
        self.fail_stage = None
        self.injected = False
        self.nginx_checks = 0
        self.https_observations = []
        # 2026-10-19 hoyeon.han: HTTP ACME 응답도 실제 상태·본문 해시로 기록한다.
        self.http_observations = []
        self.docker_failures = []

    def run(self, argv, *, input=None, env=None):
        argv = list(map(str, argv))
        self.calls.append(argv)
        if argv == ['sudo', 'nginx', '-t']:
            self.fixture.render_runtime_nginx()
            self.nginx_checks += 1
            if self.fail_stage == 'nginx' and not self.injected and self.nginx_checks == 2:
                self.injected = True
                raise self.fixture.api.SafetyError('합성 Nginx 검사 실패 주입')
            argv = ['docker', 'exec', self.fixture.nginx_name, 'nginx', '-t']
        elif argv == ['sudo', 'systemctl', 'reload', 'nginx']:
            self.fixture.render_runtime_nginx()
            argv = ['docker', 'exec', self.fixture.nginx_name, 'nginx', '-s', 'reload']
        elif argv[:3] == ['docker', 'image', 'load'] and self.fail_stage == 'image' and not self.injected:
            self.injected = True
            raise self.fixture.api.SafetyError('합성 이미지 읽기 실패 주입')
        elif argv[:3] == ['docker', 'image', 'load'] and self.fail_stage == 'interrupt' and not self.injected:
            self.injected = True
            raise KeyboardInterrupt('합성 중단 주입')
        elif argv[:2] == ['docker', 'compose'] and 'up' in argv and self.fail_stage == 'start' and not self.injected:
            self.injected = True
            raise self.fixture.api.SafetyError('합성 서비스 시작 실패 주입')
        if argv[0] != 'docker':
            raise self.fixture.api.SafetyError('로컬 fixture에서 지원하지 않는 호스트 명령')
        result = command(argv, input=input, env=env, check=False)
        if result.returncode:
            # 2026-10-15 hoyeon.han: 환경값/로그 본문 없이 실제 컨테이너 상태만 진단한다.
            identifiers = command(['docker','ps','-aq','--filter','label=sollume.rollback.qa='+self.fixture.project]).split()
            states=[]
            if identifiers:
                for item in json.loads(command(['docker','inspect',*identifiers])):
                    state=item.get('State',{})
                    states.append({'service':item['Config']['Labels'].get('com.docker.compose.service','fixture-nginx'),
                                   'status':state.get('Status'),'exit_code':state.get('ExitCode'),
                                   'health':state.get('Health',{}).get('Status')})
            self.docker_failures.append({'operation':next((v for v in ('up','load','down') if v in argv),'docker'),
                                         'exit_code':result.returncode,'containers':states})
            raise self.fixture.api.SafetyError('실제 격리 Docker 명령 실패')
        return result.stdout

    def https_status(self, origin, path, headers=None):
        started=time.monotonic()
        def observed(value):
            self.https_observations.append({'path':path,'status':value,'elapsed_seconds':round(time.monotonic()-started,3)})
            return value
        context = ssl.create_default_context(cafile=str(self.fixture.app / 'ssl/fullchain.pem'))
        request = urllib.request.Request('https://127.0.0.1:' + str(self.fixture.https_port) + path,
                                         # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
                                         # headers={'Host': 'sollumeesthe.com', **(headers or {})})
                                         headers={'Host': 'office1.sollumeesthe.com', **(headers or {})})
        # Redirect는 외부 실제 도메인에 연결하지 않고 상태만 읽는다.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), NoRedirect())
        try:
            with opener.open(request, timeout=10) as response:
                response.read()
                return observed(response.status)
        except urllib.error.HTTPError as exc:
            return observed(exc.code)
        except (OSError, urllib.error.URLError):
            return observed(0)

    def internal_health(self, target, host=None):
        if self.fail_stage == 'health' and not self.injected:
            self.injected = True
            return False
        path = {8501: '/_stcore/health', 8502: '/health', 8503: '/auth/health'}[target]
        request = urllib.request.Request('http://127.0.0.1:' + str(self.fixture.ports[target]) + path,
                                         headers={'Host': host or 'localhost'})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
                return response.status == 200
        except (OSError, urllib.error.URLError):
            return False

    def internal_status(self, target, path, host=None, headers=None):
        request = urllib.request.Request('http://127.0.0.1:' + str(self.fixture.ports[target]) + path,
                                         headers={'Host': host or 'localhost', **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except (OSError, urllib.error.URLError):
            return 0


class Fixture:
    def __init__(self, *, legacy=False):
        self.api = module()
        # self.app = Path(tempfile.mkdtemp(prefix='sollume-rollback-qa-', dir='/private/tmp'))
        # 2026-11-04 hoyeon.han: Linux와 macOS의 기본 임시 폴더를 실제 경로로 사용한다.
        self.app = Path(tempfile.mkdtemp(prefix='sollume-rollback-qa-')).resolve()
        self.project = self.app.name
        self.network = self.project + '-bridge'
        self.nginx_name = self.project + '-nginx'
        self.image_tag = self.project + '/release:latest'
        self.legacy = legacy
        self.ports = {target: port() for target in (8501, 8502, 8503)}
        # 2026-10-15 hoyeon.han: 기존 로컬 서버를 보존하기 위한 테스트 프로세스 상수 대체.
        # 운영 CLI에는 포트 정책을 바꾸는 인자나 환경변수가 없다.
        self.api.EXPECTED_PUBLISHED_PORTS = {name:self.ports[target] for name,target in self.api.SERVICES.items()}
        self.https_port = port()
        # 2026-10-19 hoyeon.han: 업무·비밀 폴더와 분리한 공개 검증 파일만 Nginx에 제공한다.
        self.http_port = port()
        # self.acme_root = Path(tempfile.mkdtemp(prefix='sollume-acme-qa-', dir='/private/tmp'))
        # 2026-11-04 hoyeon.han: ACME 시험 폴더도 같은 운영체제 기본 경로에 만든다.
        self.acme_root = Path(tempfile.mkdtemp(prefix='sollume-acme-qa-')).resolve()
        self.acme_root.chmod(0o755)
        self.acme_path = '/.well-known/acme-challenge/office1-rehearsal.txt'
        self.acme_body = 'office1-acme-rehearsal-' + self.project
        challenge = self.acme_root / self.acme_path.lstrip('/')
        challenge.parent.mkdir(parents=True, mode=0o755)
        challenge.parent.parent.chmod(0o755)
        challenge.write_text(self.acme_body)
        challenge.chmod(0o644)
        self.unrelated_site = self.app / 'unrelated-nginx.site'
        self.unrelated_domain = 'canary.sollume.invalid'
        self.unrelated_body = 'unrelated-site-kept-' + self.project
        self.canary_ids = []
        self.key = Fernet.generate_key().decode()
        self.password = 'Synthetic-rollback-old-' + secrets.token_urlsafe(20)
        self.next_password = 'Synthetic-rollback-new-' + secrets.token_urlsafe(20)
        self.secrets = [self.key, self.password, self.next_password]
        self.mfa_secret = base64.b32encode(secrets.token_bytes(20)).decode()
        self.session_token = secrets.token_urlsafe(32)
        self.secrets += [self.mfa_secret, self.session_token]
        self.runner = LocalRunner(self)
        self.manager = self.api.ReleaseManager(self.app, self.app / 'nginx.site', runner=self.runner)
        self.archive = None
        self.owned_releases = []
        self.fixture_ready = False

    def compose(self, *args):
        return ['docker', 'compose', '--project-directory', str(self.app), '--env-file', str(self.app / '.env'),
                '--project-name', self.project, '--file', str(self.app / 'docker-compose.cloud.yml'), *args]

    def prepare(self):
        for name in ('database', 'processed/secure_downloads', 'uploads', 'logs', 'order_data', 'ssl'):
            (self.app / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.image = image_id('sollume-finance-sollume-app:latest' if self.legacy else 'sollume-finance-security:venv-test')
        self.nginx_image = image_id('nginx:alpine')
        command(['docker', 'tag', self.image, self.image_tag])
        for octet in range(205, 230):
            result = command(['docker', 'network', 'create', '--driver', 'bridge', '--subnet', f'172.31.{octet}.0/24',
                              '--label', 'sollume.rollback.qa=' + self.project, self.network], check=False)
            if result.returncode == 0:
                self.subnet = f'172.31.{octet}'
                break
        else:
            raise RuntimeError('격리 네트워크 생성 실패')
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # env = {'AUTH_ENV': 'production', 'AUTH_PUBLIC_ORIGIN': 'https://sollumeesthe.com',
        env = {'AUTH_ENV': 'production', 'AUTH_PUBLIC_ORIGIN': 'https://office1.sollumeesthe.com',
               'AUTH_ENCRYPTION_KEY': self.key, 'ORDER_API_KEY': secrets.token_urlsafe(32)}
        self.secrets.append(env['ORDER_API_KEY'])
        self.api_key = env['ORDER_API_KEY']
        (self.app / '.env').write_text('\n'.join(key + '=' + value for key, value in env.items()) + '\n')
        (self.app / '.env').chmod(0o600)
        self.seed_users()
        with closing(sqlite3.connect(self.app / 'database/customer_master.db')) as conn, conn:
            conn.execute('CREATE TABLE customers(id INTEGER PRIMARY KEY, label TEXT)')
            conn.execute('INSERT INTO customers VALUES(1,?)', ('합성 거래처 원본',))
        conn.close()
        (self.app / 'order_data/current.xlsm').write_bytes(b'synthetic immutable old order fixture')
        (self.app / 'order_data/current.meta.json').write_text('{"original_name":"합성 발주내역.xlsm"}')
        (self.app / '거래처마스터.xlsx').write_bytes(b'synthetic master fixture not operational data')
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
                        # '-subj', '/CN=sollumeesthe.com', '-addext', 'subjectAltName=DNS:sollumeesthe.com,IP:127.0.0.1',
                        '-subj', '/CN=office1.sollumeesthe.com', '-addext', 'subjectAltName=DNS:office1.sollumeesthe.com,IP:127.0.0.1',
                        '-keyout', str(self.app / 'ssl/privkey.pem'), '-out', str(self.app / 'ssl/fullchain.pem')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (self.app / 'ssl/privkey.pem').chmod(0o600)
        nginx = (ROOT / 'nginx-host-api.conf.example').read_text()
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # nginx = nginx.replace('/etc/letsencrypt/live/sollumeesthe.com/fullchain.pem', str(self.app / 'ssl/fullchain.pem'))
        nginx = nginx.replace('/etc/letsencrypt/live/office1.sollumeesthe.com/fullchain.pem', str(self.app / 'ssl/fullchain.pem'))
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # nginx = nginx.replace('/etc/letsencrypt/live/sollumeesthe.com/privkey.pem', str(self.app / 'ssl/privkey.pem'))
        nginx = nginx.replace('/etc/letsencrypt/live/office1.sollumeesthe.com/privkey.pem', str(self.app / 'ssl/privkey.pem'))
        if self.legacy:
            # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
            # nginx = ('server {\n listen 443 ssl default_server;\n server_name sollumeesthe.com;\n'
            nginx = ('server {\n listen 443 ssl default_server;\n server_name office1.sollumeesthe.com;\n'
                     f' ssl_certificate {self.app}/ssl/fullchain.pem;\n ssl_certificate_key {self.app}/ssl/privkey.pem;\n'
                     ' location / { proxy_pass http://sollume-app:8501; }\n}\n')
            # 2026-10-19 hoyeon.han: 인증 도입 전 fixture에도 실제 준비 서버와 같은 ACME 경로가 있다.
            nginx = ('server { listen 80; server_name office1.sollumeesthe.com;\n'
                     ' location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; '
                     'default_type text/plain; try_files $uri =404; }\n'
                     ' location / { return 301 https://office1.sollumeesthe.com$request_uri; } }\n') + nginx
        (self.app / 'nginx.site').write_text(nginx)
        # 2026-10-19 hoyeon.han: 다른 서비스의 가상 호스트는 별도 파일로 유지하고 복구 대상에서 제외한다.
        self.unrelated_site.write_text(
            'server { listen 80; server_name ' + self.unrelated_domain + '; location / { return 200 "' + self.unrelated_body + '"; } }\n'
            'server { listen 443 ssl; server_name ' + self.unrelated_domain + ';\n'
            f' ssl_certificate {self.app}/ssl/fullchain.pem; ssl_certificate_key {self.app}/ssl/privkey.pem;\n'
            ' location / { return 200 "' + self.unrelated_body + '"; } }\n')
        self.unrelated_hash = sha(self.unrelated_site)
        self.render_runtime_nginx()
        # 2026-10-19 hoyeon.han: 기존 단일 사이트 include를 보존하고 다른 도메인도 함께 로드한다.
        # (self.app / 'nginx-base.conf').write_text('worker_processes 1;\nevents { worker_connections 256; }\nhttp {\n'
        #                                         + f'include {self.app}/nginx-runtime.site;\n' + '}\n')
        (self.app / 'nginx-base.conf').write_text('worker_processes 1;\nevents { worker_connections 256; }\nhttp {\n'
                                                + f'include {self.app}/nginx-runtime.site;\ninclude {self.unrelated_site};\n' + '}\n')
        services = {}
        roles = {'sollume-app': 8501, 'sollume-api': 8502}
        if not self.legacy:
            roles['sollume-auth'] = 8503
        for name, target in roles.items():
            paths = {'sollume-app': ('database', 'processed', 'logs', 'uploads', 'order_data'),
                     'sollume-auth': ('database', 'processed', 'logs'), 'sollume-api': ('logs', 'order_data')}[name]
            volumes = [{'type': 'bind', 'source': str(self.app / path), 'target': '/app/' + path,
                        'read_only': name == 'sollume-api' and path == 'order_data'}
                       for path in paths]
            if name == 'sollume-app':
                volumes.append({'type': 'bind', 'source': str(self.app / '거래처마스터.xlsx'),
                                'target': '/app/Src/거래처마스터.xlsx', 'read_only': True})
            environment = {'TZ': 'Asia/Seoul', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
                           'ORDER_API_KEY': '${ORDER_API_KEY}', 'AUTH_ENV': 'production',
                           'AUTH_PUBLIC_ORIGIN': '${AUTH_PUBLIC_ORIGIN}', 'AUTH_ENCRYPTION_KEY': '${AUTH_ENCRYPTION_KEY}',
                           'AUTH_DB_PATH': '/app/database/users.db', 'AUTH_DOWNLOAD_DIR': '/app/processed/secure_downloads',
                           'TRUSTED_PROXY_NETWORKS': self.subnet + '.10/32,' + self.subnet + '.1/32,127.0.0.1/32',
                           'STREAMLIT_SERVER_HEADLESS': 'true', 'STREAMLIT_SERVER_FILE_WATCHER_TYPE': 'none',
                           'STREAMLIT_BROWSER_GATHER_USAGE_STATS': 'false', 'STREAMLIT_SERVER_RUN_ON_SAVE': 'false',
                           # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
                           # 'STREAMLIT_BROWSER_SERVER_ADDRESS': 'sollumeesthe.com', 'STREAMLIT_BROWSER_SERVER_PORT': '443'}
                           'STREAMLIT_BROWSER_SERVER_ADDRESS': 'office1.sollumeesthe.com', 'STREAMLIT_BROWSER_SERVER_PORT': '443'}
            service = {'image': self.image_tag, 'pull_policy': 'never', 'environment': environment,
                       'volumes': volumes, 'ports': [{'host_ip': '127.0.0.1', 'published': str(self.ports[target]), 'target': target}],
                       'read_only': True, 'tmpfs': ['/tmp:size=256m'], 'security_opt': ['no-new-privileges:true'],
                       'labels': {'sollume.rollback.qa': self.project}, 'networks': ['sollume-network']}
            # 2026-10-15 hoyeon.han: 운영 Compose와 동일하게 서비스별 상태 경로를 명시한다.
            # 이미지 기본 8501 검사를 API/인증 서비스가 잘못 상속하지 않게 한다.
            health_path = {8501: '/_stcore/health', 8502: '/health', 8503: '/auth/health'}[target]
            health_args = ['CMD', 'curl', '-f']
            if target == 8503:
                # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
                # health_args += ['-H', 'Host: sollumeesthe.com']
                health_args += ['-H', 'Host: office1.sollumeesthe.com']
            service['healthcheck'] = {'test': health_args + ['http://localhost:' + str(target) + health_path],
                                      'interval': '2s', 'timeout': '10s', 'retries': 3, 'start_period': '5s'}
            if name == 'sollume-app':
                service['deploy'] = {'resources': {'limits': {'cpus': '4', 'memory': '20G'},
                                                    'reservations': {'cpus': '2', 'memory': '4G'}}}
                service['command'] = ['streamlit', 'run', 'Home.py', '--server.address=0.0.0.0', '--server.port=8501']
            else:
                service['command'] = ['gunicorn', '--bind', '0.0.0.0:' + str(target), '--workers', '1',
                                      '--pythonpath', '/app/Src', 'auth_gateway:create_app()' if target == 8503 else 'api_server:app']
                if name == 'sollume-api':
                    service['deploy'] = {'resources': {'limits': {'cpus': '1', 'memory': '2G'}}}
            services[name] = service
        compose = {'name': self.project, 'services': services,
                   'networks': {'sollume-network': {'external': True, 'name': self.network}}}
        (self.app / 'docker-compose.cloud.yml').write_text(json.dumps(compose, ensure_ascii=False, indent=2))
        command(self.compose('up', '-d', '--pull', 'never', '--no-build'))
        # 2026-10-19 hoyeon.han: 기존 HTTPS 전용 실행을 보존하고 비밀 없는 ACME 경로·HTTP 고포트만 추가한다.
        # command(['docker', 'run', '-d', '--name', self.nginx_name, '--network', self.network,
        #          '--ip', self.subnet + '.10', '--label', 'sollume.rollback.qa=' + self.project,
        #          '-p', '127.0.0.1:' + str(self.https_port) + ':443',
        #          '-v', f'{self.app}:{self.app}:ro', '-v', f'{self.app}/nginx-base.conf:/etc/nginx/nginx.conf:ro', self.nginx_image])
        command(['docker', 'run', '-d', '--pull', 'never', '--name', self.nginx_name, '--network', self.network,
                 '--ip', self.subnet + '.10', '--label', 'sollume.rollback.qa=' + self.project,
                 '-p', '127.0.0.1:' + str(self.https_port) + ':443', '-p', '127.0.0.1:' + str(self.http_port) + ':80',
                 '-v', f'{self.acme_root}:/var/www/letsencrypt:ro',
                 '-v', f'{self.app}:{self.app}:ro', '-v', f'{self.app}/nginx-base.conf:/etc/nginx/nginx.conf:ro', self.nginx_image])
        for label in ('n8n', 'goodsfoundry'):
            self.canary_ids.append(command(['docker', 'run', '-d', '--pull', 'never', '--network', 'none', '--read-only',
                '--name', self.project + '-canary-' + label, '--label', 'sollume.rollback.qa=' + self.project,
                '--entrypoint', 'sh', self.nginx_image, '-c', 'sleep 1800']).strip())
        for attempt in range(45):
            # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
            # if all(self.runner.internal_health(target, 'sollumeesthe.com') for target in roles.values()):
            if all(self.runner.internal_health(target, 'office1.sollumeesthe.com') for target in roles.values()):
                break
            time.sleep(1)
        else:
            raise RuntimeError('격리 회계 서비스 준비 실패')
        self.fixture_ready = True

    def render_runtime_nginx(self):
        content = (self.app / 'nginx.site').read_text()
        for target, name in ((8501, 'sollume-app'), (8502, 'sollume-api'), (8503, 'sollume-auth')):
            # 2026-10-15 hoyeon.han: 운영과 같은 고정 host loopback 포트를 경유한다.
            # 삭제된 컨테이너 IP의 5초 blackhole 대신 실제 published 포트의 즉시 연결거부를 검증한다.
            content = content.replace('http://127.0.0.1:' + str(target),
                                      'http://host.docker.internal:' + str(self.ports[target]))
        (self.app / 'nginx-runtime.site').write_text(content)

    # 2026-10-19 hoyeon.han: 외부 DNS·프록시 없이 격리 포트로만 요청하며 상태와 본문을 함께 확인한다.
    def site_probe(self, scheme, host, path='/'):
        target_port = self.https_port if scheme == 'https' else self.http_port
        handlers = [urllib.request.ProxyHandler({})]
        if scheme == 'https':
            handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(self.app / 'ssl/fullchain.pem'))))
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        handlers.append(NoRedirect())
        request = urllib.request.Request(f'{scheme}://127.0.0.1:{target_port}{path}', headers={'Host': host})
        try:
            with urllib.request.build_opener(*handlers).open(request, timeout=10) as response:
                status, body = response.status, response.read(4096)
        except urllib.error.HTTPError as exc:
            status, body = exc.code, exc.read(4096)
        except (OSError, urllib.error.URLError):
            status, body = 0, b''
        observations = self.runner.http_observations if scheme == 'http' else self.runner.https_observations
        observations.append({'host': host, 'path': path, 'status': status, 'body_sha256': hashlib.sha256(body).hexdigest()})
        return status, body

    def acme_available(self):
        return self.site_probe('http', 'office1.sollumeesthe.com', self.acme_path) == (200, self.acme_body.encode())

    def unrelated_preserved(self):
        current = json.loads(command(['docker', 'inspect', *self.canary_ids]))
        return (sha(self.unrelated_site) == self.unrelated_hash
                and all(item['State']['Running'] and item['Image'] == self.nginx_image for item in current)
                and all(self.site_probe(scheme, self.unrelated_domain) == (200, self.unrelated_body.encode()) for scheme in ('http', 'https')))

    def seed_users(self):
        hashed = bcrypt.hashpw(self.password.encode(), bcrypt.gensalt()).decode()
        self.secrets.append(hashed)
        with closing(sqlite3.connect(self.app / 'database/users.db')) as conn, conn:
            conn.execute('''CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,full_name TEXT,email TEXT,is_active BOOLEAN DEFAULT 1,is_admin BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,last_login TIMESTAMP,login_count INTEGER DEFAULT 0)''')
            for uid, username, admin in ((42, 'qa_changed', 1), (43, 'qa_stable', 0), (77, 'qa_demoted', 1),
                                         (99, 'qa_stopped', 0), (105, 'qa_deleted', 0), (109, 'qa_renamed', 0)):
                conn.execute('INSERT INTO users(id,username,password_hash,full_name,email,is_admin) VALUES(?,?,?,?,?,?)',
                             (uid, username, hashed, '합성 직원', 'fixture@example.invalid', admin))
        conn.close()
        if not self.legacy:
            self.service = SecurityService(self.app / 'database/users.db', self.key, self.app / 'processed/secure_downloads')

    def capture(self, name):
        result = self.manager.capture(str(self.app / 'database/backups/releases' / name))
        path = Path(result['release'])
        self.owned_releases.append(path)
        return path

    def prune_rescues(self, keep):
        releases = self.app / 'database/backups/releases'
        if releases.exists():
            for release in releases.iterdir():
                if release not in keep:
                    shutil.rmtree(release)
                    shutil.rmtree(self.app / 'database/.release-secrets' / release.name, ignore_errors=True)

    def real_https_mfa_login(self):
        browser = requests.Session()
        base = 'https://127.0.0.1:' + str(self.https_port)
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # headers = {'Host': 'sollumeesthe.com', 'Origin': 'https://sollumeesthe.com'}
        headers = {'Host': 'office1.sollumeesthe.com', 'Origin': 'https://office1.sollumeesthe.com'}
        def request(method, path, **kwargs):
            return browser.request(method, base + path, headers=headers,
                                   verify=str(self.app / 'ssl/fullchain.pem'), allow_redirects=False, timeout=15, **kwargs)
        page = request('GET', '/auth/login')
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        response = request('POST', '/auth/login', data={'csrf_token': token, 'username': 'qa_stable', 'password': self.password})
        if response.status_code != 303 or response.headers.get('Location') != '/auth/mfa':
            return False
        page = request('GET', '/auth/mfa')
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        otp = SecurityService._totp(self.mfa_secret, int(time.time() // 30))
        response = request('POST', '/auth/mfa', data={'csrf_token': token, 'otp': otp})
        return response.status_code == 303 and request('GET', '/').status_code == 200

    def cleanup(self):
        if (self.app / 'docker-compose.cloud.yml').exists():
            command(self.compose('down', '--remove-orphans'), check=False)
        command(['docker', 'rm', '-f', self.nginx_name], check=False)
        ids = command(['docker', 'ps', '-aq', '--filter', 'label=sollume.rollback.qa=' + self.project]).split()
        for identifier in ids:
            command(['docker', 'rm', '-f', identifier], check=False)
        command(['docker', 'network', 'rm', self.network], check=False)
        command(['docker', 'image', 'rm', self.image_tag], check=False)
        remaining = command(['docker', 'ps', '-aq', '--filter', 'label=sollume.rollback.qa=' + self.project]).strip()
        shutil.rmtree(self.app, ignore_errors=True)
        # 2026-10-19 hoyeon.han: 독립 ACME 공개 파일 경로도 테스트 종료 시 제거한다.
        shutil.rmtree(self.acme_root, ignore_errors=True)
        networks=command(['docker','network','ls','--filter','label=sollume.rollback.qa='+self.project,'--format','{{.ID}}']).strip()
        tags=command(['docker','image','ls','--format','{{.Repository}}:{{.Tag}}',self.image_tag]).strip()
        # 2026-10-19 hoyeon.han: 기존 정리 조건에 독립 ACME 임시 폴더 제거를 추가한다.
        # return not remaining and not networks and not tags and not self.app.exists()
        return not remaining and not networks and not tags and not self.app.exists() and not self.acme_root.exists()


class Verification:
    def __init__(self, output):
        self.output = Path(output)
        self.checks = []
        self.scenarios = {}
        self.fixtures = []
        self.cleanup = True
        self.failure = None
        self.smoke = False
        self.scope = 'complete rollback rehearsal'
        self.started = datetime.now(timezone.utc).isoformat()
        self.sources = {name: sha(ROOT / name) for name in ('scripts/release_snapshot.py', 'rollback-oracle.sh', 'deploy-oracle.sh',
                                                          '.codex/user-management/verify_rollback.py','.codex/tests/test_rollback.py')}
        self.baseline = json.loads((ROOT / '.codex/user-management/data-baseline.json').read_text())

    def check(self, name, passed, *, evidence='actual', **values):
        self.checks.append({'name': name, 'passed': bool(passed), 'evidence': evidence, **values})
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)
        if not passed:
            raise AssertionError(name)

    def secure(self):
        fixture = Fixture()
        self.fixtures.append(fixture)
        fixture.prepare()
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # self.check('initial_real_https_requires_auth', fixture.runner.https_status('https://sollumeesthe.com', '/') == 401)
        self.check('initial_real_https_requires_auth', fixture.runner.https_status('https://office1.sollumeesthe.com', '/') == 401)
        # 2026-10-19 hoyeon.han: 정상 인증 설정에서도 갱신 경로와 다른 서비스를 유지한다.
        self.check('secure_acme_http200_body_matches_and_other_sites_preserved', fixture.acme_available() and fixture.unrelated_preserved())
        # 미체크포인트 WAL에 커밋된 행도 SQLite backup API로 캡처되어야 한다.
        held = sqlite3.connect(fixture.app / 'database/users.db')
        held.execute('PRAGMA journal_mode=WAL')
        held.execute('UPDATE users SET full_name=? WHERE id=43', ('합성 WAL 변경',))
        held.commit()
        snapshot = fixture.capture('secure-original')
        with closing(sqlite3.connect(snapshot / 'users.db')) as conn, conn:
            wal_saved = conn.execute('SELECT full_name FROM users WHERE id=43').fetchone()[0]
        conn.close()
        try:
            fixture.manager.plan(str(snapshot))
            wal_rejected=False
        except fixture.api.SafetyError as exc:
            wal_rejected='WAL' in str(exc)
        self.check('plan_rejects_uncheckpointed_current_wal_without_mutation',wal_rejected)
        held.close()
        with closing(sqlite3.connect(fixture.app/'database/users.db')) as conn, conn:
            if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                raise AssertionError('fixture 초기 WAL checkpoint 실패')
        conn.close()
        self.check('capture_includes_committed_wal_data', wal_saved == '합성 WAL 변경')
        self.check('offline_image_archive_exists_and_manifest_checksum_matches', (snapshot / 'images.tar').stat().st_size > 0
                   and json.loads((snapshot / 'manifest.json').read_text())['checksums']['images.tar'] == sha(snapshot / 'images.tar'))
        self.check('release_secret_files_owner_only',
                   all(stat.S_IMODE(p.stat().st_mode) == 0o700 for p in (snapshot, fixture.app / 'database/.release-secrets' / snapshot.name))
                   and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in snapshot.iterdir() if p.is_file())
                   and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in (fixture.app / 'database/.release-secrets' / snapshot.name).iterdir() if p.is_file()))
        textfiles = [p for p in snapshot.iterdir() if p.suffix in ('.json', '.site', '.original') or p.name == 'compose.original']
        self.check('public_release_metadata_contains_no_plaintext_secrets',
                   all(not any(secret in p.read_text() for secret in fixture.secrets) for p in textfiles))
        before = {name: sha(fixture.app / name) for name in ('.env', 'nginx.site', 'docker-compose.cloud.yml', 'database/users.db')}
        plan = fixture.manager.rollback(str(snapshot))
        after = {name: sha(fixture.app / name) for name in before}
        self.check('default_rollback_is_readonly_plan', plan['dry_run'] and plan['validated'] and before == after)
        wrapper = command(['bash', str(ROOT / 'rollback-oracle.sh'), '--app-dir', str(fixture.app),
                           '--nginx-config', str(fixture.app / 'nginx.site'), '--release', str(snapshot)],
                          env=dict(os.environ, SOLLUME_OPS_PYTHON=sys.executable), check=False)
        help_text = command(['bash', str(ROOT/'rollback-oracle.sh'), '--help'],
                            env=dict(os.environ,SOLLUME_OPS_PYTHON=sys.executable))
        self.check('real_shell_wrapper_keeps_production_port_checks_and_exposes_explicit_apply',
                   wrapper.returncode != 0 and '--apply' in help_text and before == after)
        self.preflight_guards(fixture, snapshot)
        with closing(sqlite3.connect(fixture.app / 'database/users.db')) as conn, conn:
            conn.execute('UPDATE users SET password_hash=?,permissions=?,is_admin=0 WHERE id=77',
                         (SecurityService.hash_password(fixture.next_password), '["daily-voucher"]'))
            conn.execute('UPDATE users SET is_active=0 WHERE id=99')
            conn.execute('UPDATE users SET mfa_enrolled=1,mfa_secret_cipher=?,must_change_password=0 WHERE id=43',
                         (Fernet(fixture.key.encode()).encrypt(fixture.mfa_secret.encode()).decode(),))
            now=time.time()
            version=conn.execute('SELECT session_version FROM users WHERE id=43').fetchone()[0]
            conn.execute('INSERT INTO security_sessions VALUES(?,?,?,?,?,?,?,?)',
                         ('f'*32,hashlib.sha256(fixture.session_token.encode()).hexdigest(),43,version,now,now,now,None))
            conn.execute('INSERT INTO security_challenges(token_hash,user_id,version,expires_at,ip_address) VALUES(?,?,?,?,?)',
                         ('d'*64,43,version,now+300,'192.0.2.1'))
            conn.execute('INSERT INTO security_enrollments VALUES(?,?,?,?)',('c'*64,43,now+300,None))
            conn.execute('INSERT INTO security_downloads VALUES(?,?,?,?,?,?,?,?)',
                         ('b'*48,43,'f'*32,'daily-voucher',0,'합성.xls','application/vnd.ms-excel',now+300))
            latest = conn.execute('SELECT id,username,password_hash,is_active,is_admin,permissions,mfa_secret_cipher FROM users ORDER BY id').fetchall()
        conn.close()
        with closing(sqlite3.connect(fixture.app / 'database/customer_master.db')) as conn, conn:
            conn.execute('INSERT INTO customers VALUES(2,?)', ('합성 최신 거래처',))
        conn.close()
        # WAL의 커밋을 버리지 않는다. 활성 writer가 없을 때 checkpoint하고 정상 복구를 계속한다.
        with closing(sqlite3.connect(fixture.app/'database/users.db')) as conn, conn:
            row=conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if row[0]!=0:
                raise AssertionError('fixture WAL checkpoint가 완료되지 않았습니다.')
            conn.execute('PRAGMA journal_mode=DELETE')
        conn.close()
        (fixture.app / 'order_data/current.xlsm').write_bytes(b'synthetic latest order must survive rollback')
        business = {name: sha(fixture.app / name) for name in ('database/customer_master.db', 'order_data/current.xlsm', 'order_data/current.meta.json')}
        command(['docker', 'tag', fixture.nginx_image, fixture.image_tag])
        original_environment = {key: os.environ.get(key) for key in ('AUTH_ENCRYPTION_KEY', 'ORDER_API_KEY')}
        os.environ['AUTH_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
        os.environ['ORDER_API_KEY'] = secrets.token_urlsafe(32)
        try:
            restored = fixture.manager.rollback(str(snapshot), apply=True)
        finally:
            for key,value in original_environment.items():
                if value is None:
                    os.environ.pop(key,None)
                else:
                    os.environ[key]=value
        self.check('secure_restore_completed_with_public_auth_guards', restored['completed'] and restored['public_resume']
                   # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
                   # and fixture.runner.https_status('https://sollumeesthe.com', '/') == 401
                   and fixture.runner.https_status('https://office1.sollumeesthe.com', '/') == 401
                   # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
                   # and fixture.runner.https_status('https://sollumeesthe.com', '/media/qa') == 403)
                   and fixture.runner.https_status('https://office1.sollumeesthe.com', '/media/qa') == 403)
        # 2026-10-19 hoyeon.han: 성공한 보안 복구 후 ACME 예외가 업무·다운로드 인증을 우회하지 않는다.
        self.check('secure_restore_acme200_download401_and_other_sites_preserved', fixture.acme_available()
                   and fixture.runner.https_status('https://office1.sollumeesthe.com', '/downloads/blocked-test') == 401
                   and fixture.unrelated_preserved())
        with closing(sqlite3.connect(fixture.app / 'database/users.db')) as conn, conn:
            current = conn.execute('SELECT id,username,password_hash,is_active,is_admin,permissions,mfa_secret_cipher FROM users ORDER BY id').fetchall()
            counts = {table: conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in fixture.api.SESSION_TABLES}
        self.check('secure_restore_keeps_latest_password_role_grants_and_mfa', latest == current)
        self.check('secure_restore_clears_sessions_pending_enrollment_and_downloads', all(value == 0 for value in counts.values()))
        self.check('secure_restore_keeps_latest_customer_and_order_files', all(sha(fixture.app / name) == value for name, value in business.items()))
        actual = json.loads(command(['docker', 'inspect', *command(fixture.compose('ps', '-aq')).split()]))
        manifest = json.loads((snapshot / 'manifest.json').read_text())
        self.check('tag_movement_does_not_change_restored_image_ids', all(item['Image'] == fixture.image for item in actual))
        self.check('actual_cpu_memory_and_bind_mounts_preserved', all(
            {key: item['HostConfig'].get(key) for key in ('NanoCpus', 'Memory', 'MemoryReservation')}
            == manifest['services'][item['Config']['Labels']['com.docker.compose.service']]['host_resources']
            and all(Path(m['Source']).is_relative_to(fixture.app) for m in item['Mounts'] if m['Type'] == 'bind')
            for item in actual))
        self.check('actual_readonly_root_and_tmpfs_preserved',all(
            item['HostConfig']['ReadonlyRootfs'] and '/tmp' in item['HostConfig'].get('Tmpfs',{}) for item in actual))
        self.check('shell_export_contamination_cannot_replace_saved_dotenv_auth_keys', all(
            dict(value.split('=',1) for value in item['Config']['Env']).get('ORDER_API_KEY') == fixture.api_key
            and dict(value.split('=',1) for value in item['Config']['Env']).get('AUTH_ENCRYPTION_KEY') == fixture.key
            for item in actual))
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # self.check('revoked_pre_rollback_session_cookie_is_denied', fixture.runner.https_status('https://sollumeesthe.com', '/',
        self.check('revoked_pre_rollback_session_cookie_is_denied', fixture.runner.https_status('https://office1.sollumeesthe.com', '/',
                   {'Cookie':'__Host-sollume_session='+fixture.session_token}) == 401)
        self.check('actual_https_mfa_login_with_preserved_encrypted_secret_succeeds', fixture.real_https_mfa_login())
        self.scenarios['secure_restore'] = {'passed': True, 'evidence': 'actual Docker/Compose/SQLite/HTTPS'}
        fixture.prune_rescues({snapshot})
        if not self.smoke:
            self.failure_paths(fixture, snapshot)
            self.partial_service_restore(fixture, snapshot)

    def preflight_guards(self, fixture, snapshot):
        production = module()
        rendered = json.loads(command(fixture.compose('config', '--format', 'json')))
        try:
            production.ReleaseManager(fixture.app, fixture.app/'nginx.site')._validate_compose(rendered)
            production_rejected_high_ports = False
        except production.SafetyError:
            production_rejected_high_ports = True
        self.check('production_default_rejects_fixture_high_published_ports', production_rejected_high_ports)
        original = (snapshot / 'manifest.json').read_bytes()
        def denied():
            before = len(fixture.runner.calls)
            try:
                fixture.manager.plan(str(snapshot))
                return False
            except fixture.api.SafetyError:
                return not any('up' in cmd or 'down' in cmd or cmd[:2] == ['sudo', 'systemctl'] for cmd in fixture.runner.calls[before:])
        manifest = json.loads(original)
        manifest['project'] = 'malicious-other-project'
        (snapshot / 'manifest.json').write_text(json.dumps(manifest))
        self.check('manifest_project_tampering_rejected_before_mutation', denied())
        (snapshot / 'manifest.json').write_bytes(original)
        archive = snapshot / 'images.tar'
        with archive.open('r+b') as stream:
            old = stream.read(1)
            stream.seek(0)
            stream.write(bytes([old[0] ^ 1]))
        self.check('offline_archive_corruption_rejected_before_mutation', denied())
        with archive.open('r+b') as stream:
            stream.write(old)
        bad = fixture.app / 'database/backups/releases/../outside'
        try:
            fixture.manager.plan(str(bad))
            reject_path = False
        except (fixture.api.SafetyError, FileNotFoundError):
            reject_path = True
        self.check('release_path_outside_allowed_directory_rejected', reject_path)
        env = (fixture.app / '.env').read_bytes()
        (fixture.app / '.env').write_bytes(env + b'LD_PRELOAD=/tmp/untrusted.so\n')
        self.check('unsafe_environment_key_rejected_before_mutation', denied())
        (fixture.app / '.env').write_bytes(env)
        # 2026-10-15 hoyeon.han: 실제 현재 구성의 DB mount 경로 불일치는 복원 시작 전에 거부한다.
        original_compose=(fixture.app/'docker-compose.cloud.yml').read_bytes()
        wrong_config=json.loads(original_compose)
        for mount in wrong_config['services']['sollume-auth']['volumes']:
            if mount['target']=='/app/database':
                mount['source']=str(fixture.app/'other-database')
        (fixture.app/'docker-compose.cloud.yml').write_text(json.dumps(wrong_config))
        self.check('current_database_mount_path_mismatch_rejected_before_mutation',denied())
        (fixture.app/'docker-compose.cloud.yml').write_bytes(original_compose)
        self.scenarios['preflight_guards'] = {'passed': True, 'evidence': 'actual validator + tampered synthetic artifacts'}

    def failure_paths(self, fixture, snapshot):
        results = {}
        for stage in ('nginx', 'image', 'start', 'health','interrupt'):
            fixture.runner.fail_stage = stage
            fixture.runner.injected = False
            fixture.runner.nginx_checks = 0
            try:
                fixture.manager.rollback(str(snapshot), apply=True)
                rejected = False
            except fixture.api.SafetyError:
                rejected = True
            receipt = json.loads((snapshot / 'rollback-receipt.json').read_text())
            rescue = Path(receipt['recovery_release'])
            passed = rejected and fixture.runner.injected and (rescue / 'users.db').is_file()
            # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
            # passed = passed and fixture.runner.https_status('https://sollumeesthe.com', '/') == 503
            passed = passed and fixture.runner.https_status('https://office1.sollumeesthe.com', '/') == 503
            self.check(stage + '_failure_keeps_actual_https503_and_current_state_backup', passed,
                       evidence='actual Docker/HTTPS with one injected failing operation')
            # 2026-10-19 hoyeon.han: 각 실제 503 실패 상태에서도 공개 ACME만 유지한다.
            self.check(stage + '_failure_acme200_download503_and_other_sites_preserved', fixture.acme_available()
                       and fixture.runner.https_status('https://office1.sollumeesthe.com', '/downloads/blocked-test') == 503
                       and fixture.unrelated_preserved())
            results[stage] = {'passed': True, 'evidence': 'actual Docker/HTTPS; failing operation injected'}
            fixture.runner.fail_stage = None
            retried = fixture.manager.rollback(str(snapshot), apply=True)
            self.check(stage + '_failure_can_retry_from_partially_stopped_services', retried['completed'])
            self.check(stage + '_retry_acme200_and_other_sites_preserved', fixture.acme_available() and fixture.unrelated_preserved())
            fixture.prune_rescues({snapshot})
        self.scenarios['failure_paths'] = results

    def partial_service_restore(self, fixture, snapshot):
        command(fixture.compose('stop', 'sollume-auth'))
        command(fixture.compose('rm', '-f', 'sollume-auth'))
        result = fixture.manager.rollback(str(snapshot), apply=True)
        rescue=Path(result['recovery_release'])
        metadata=[p for p in rescue.iterdir() if p.suffix in ('.json','.site','.original') or p.name=='compose.original']
        self.check('missing_service_recovery_metadata_contains_no_plaintext_secrets',all(
            not any(secret in p.read_text() for secret in fixture.secrets) for p in metadata))
        self.check('missing_auth_service_after_failed_deployment_can_restore', result['completed']
                   # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
                   # and fixture.runner.https_status('https://sollumeesthe.com', '/') == 401)
                   and fixture.runner.https_status('https://office1.sollumeesthe.com', '/') == 401)
        fixture.prune_rescues({snapshot})

    def legacy(self):
        fixture = Fixture(legacy=True)
        self.fixtures.append(fixture)
        fixture.prepare()
        snapshot = fixture.capture('legacy-original')
        snapshot_users_hash = sha(snapshot/'users.db')
        self.check('legacy_snapshot_contains_unmodified_original_user_db', fixture.api._db_schema(snapshot/'users.db')['kind']=='legacy')
        # 실제 구버전에서 현재 보안 버전의 세 서비스 구성으로 전환한 뒤 구버전 복구를 수행.
        command(fixture.compose('down'))
        current = copy.deepcopy(json.loads((self.fixtures[0].app/'docker-compose.cloud.yml').read_text()))
        current['name']=fixture.project
        for service in current['services'].values():
            for volume in service['volumes']:
                relative=Path(volume['source']).relative_to(self.fixtures[0].app)
                volume['source']=str(fixture.app/relative)
            for binding in service['ports']:
                binding['published']=str(fixture.ports[int(binding['target'])])
            service['labels']['sollume.rollback.qa']=fixture.project
            service['environment']['TRUSTED_PROXY_NETWORKS']=fixture.subnet+'.10/32,'+fixture.subnet+'.1/32,127.0.0.1/32'
        current['networks']['sollume-network']={'external':True,'name':fixture.network}
        (fixture.app/'docker-compose.cloud.yml').write_text(json.dumps(current,ensure_ascii=False,indent=2))
        service=SecurityService(fixture.app/'database/users.db',fixture.key,fixture.app/'processed/secure_downloads')
        service.reset_password_local(42,fixture.next_password)
        service.update_user_local(77,is_admin=False)
        service.update_user_local(99,is_active=False)
        with closing(sqlite3.connect(fixture.app/'database/users.db')) as conn, conn:
            conn.execute('DELETE FROM users WHERE id=105')
            conn.execute('UPDATE users SET username=? WHERE id=109',('qa_new_identity',))
        command(fixture.compose('up','-d','--pull','never','--no-build'))
        site=(ROOT/'nginx-host-api.conf.example').read_text()
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # site=site.replace('/etc/letsencrypt/live/sollumeesthe.com/fullchain.pem',str(fixture.app/'ssl/fullchain.pem'))
        site=site.replace('/etc/letsencrypt/live/office1.sollumeesthe.com/fullchain.pem',str(fixture.app/'ssl/fullchain.pem'))
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # site=site.replace('/etc/letsencrypt/live/sollumeesthe.com/privkey.pem',str(fixture.app/'ssl/privkey.pem'))
        site=site.replace('/etc/letsencrypt/live/office1.sollumeesthe.com/privkey.pem',str(fixture.app/'ssl/privkey.pem'))
        (fixture.app/'nginx.site').write_text(site)
        fixture.runner.run(['sudo','nginx','-t'])
        fixture.runner.run(['sudo','systemctl','reload','nginx'])
        for attempt in range(30):
            # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
            # if fixture.runner.internal_health(8503,'sollumeesthe.com'):
            if fixture.runner.internal_health(8503,'office1.sollumeesthe.com'):
                break
            time.sleep(1)
        current_hash=sha(fixture.app/'database/users.db')
        for flags in ({},{'legacy_private':True},{'restore_users':True}):
            try:
                fixture.manager.rollback(str(snapshot),**flags)
                denied=False
            except fixture.api.SafetyError:
                denied=True
            self.check('legacy_missing_required_flags_denied_'+str(len(flags))+'_'+str(flags.get('restore_users',False)),
                       denied and sha(fixture.app/'database/users.db')==current_hash)
        plan=fixture.manager.rollback(str(snapshot),legacy_private=True,restore_users=True)
        self.check('explicit_legacy_restore_still_defaults_readonly',plan['dry_run'] and not plan['public_resume']
                   and sha(fixture.app/'database/users.db')==current_hash)
        restored=fixture.manager.rollback(str(snapshot),apply=True,legacy_private=True,restore_users=True)
        self.check('legacy_restore_keeps_real_https503',restored['completed'] and not restored['public_resume']
                   # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
                   # and all(fixture.runner.https_status('https://sollumeesthe.com',p)==503 for p in ('/','/auth/login','/media/test','/downloads/test')))
                   and all(fixture.runner.https_status('https://office1.sollumeesthe.com',p)==503 for p in ('/','/auth/login','/media/test','/downloads/test')))
        # 2026-10-19 hoyeon.han: 구버전 복구는 업무503을 유지하면서 인증서 갱신과 타 서비스는 보존한다.
        self.check('legacy_restore_acme200_body_matches_and_other_sites_preserved',fixture.acme_available() and fixture.unrelated_preserved())
        with closing(sqlite3.connect(fixture.app/'database/users.db')) as conn, conn:
            rows={row[0]:row for row in conn.execute('SELECT id,username,password_hash,is_active,is_admin FROM users')}
        self.check('legacy_restore_does_not_revive_changed_deleted_stopped_or_reassigned_accounts',
                   all(rows[uid][3]==0 for uid in (42,99,105,109)) and rows[43][3]==1
                   and rows[77][3]==1 and rows[77][4]==0)
        self.check('legacy_capture_user_db_stays_unchanged',sha(snapshot/'users.db')==snapshot_users_hash)
        self.check('unchanged_legacy_bcrypt_password_still_matches',bcrypt.checkpw(fixture.password.encode(),rows[43][2].encode()))
        self.old_image_login(fixture,'qa_stable',fixture.password,expected=True)
        self.old_image_login(fixture,'qa_changed',fixture.password,expected=False)
        for username in ('qa_stopped','qa_deleted','qa_renamed'):
            try:
                fixture.manager.legacy_password(str(snapshot),username)
                denied=False
            except fixture.api.SafetyError:
                denied=True
            self.check('legacy_password_recovery_denies_'+username,denied)
        password_plan=fixture.manager.legacy_password(str(snapshot),'qa_changed')
        self.check('legacy_password_recovery_defaults_to_plan',password_plan['dry_run'] and password_plan['account_id']==42)
        try:
            fixture.manager.legacy_password(str(snapshot),'qa_changed',apply=True)
            non_tty=False
        except fixture.api.SafetyError:
            non_tty=True
        self.check('legacy_password_apply_requires_hidden_input_tty',non_tty)
        self.legacy_password_tty(fixture,snapshot)
        self.old_image_login(fixture,'qa_changed',fixture.next_password,expected=True)
        # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
        # self.check('legacy_password_reset_never_reopens_public_https',fixture.runner.https_status('https://sollumeesthe.com','/')==503)
        self.check('legacy_password_reset_never_reopens_public_https',fixture.runner.https_status('https://office1.sollumeesthe.com','/')==503)
        self.scenarios['legacy_restore']={'passed':True,'evidence':'actual legacy/current images, SQLite, Docker/Compose, HTTPS, PTY'}

    def old_image_login(self,fixture,username,password,*,expected):
        program='import json,sys;sys.path.insert(0,"/app/Src");from user_db import UserDB;v=json.loads(sys.stdin.read());u=UserDB("/app/database/users.db").verify_credentials(v["username"],v["password"]);print(json.dumps({"accepted":bool(u)}))'
        result=command(['docker','run','--rm','-i','--network','none','--read-only','--tmpfs','/tmp',
                        '-v',str(fixture.app/'database')+':/app/database','--entrypoint','python',fixture.image,'-B','-c',program],
                       input=json.dumps({'username':username,'password':password}))
        self.check('actual_old_image_auth_'+username+('_success' if expected else '_denied'),json.loads(result)['accepted']==expected)

    def legacy_password_tty(self,fixture,snapshot):
        state={'app':str(fixture.app),'project':fixture.project,'nginx_name':fixture.nginx_name,
               'ports':fixture.ports,'https_port':fixture.https_port,'release':str(snapshot)}
        path=fixture.app/'tty-fixture-state.json'
        path.write_text(json.dumps(state))
        path.chmod(0o600)
        master,slave=pty.openpty()
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--legacy-password-worker',str(path)],
                                 stdin=slave,stdout=slave,stderr=slave,cwd=ROOT)
        os.close(slave)
        transcript=bytearray()
        def collect():
            if select.select([master],[],[],0.25)[0]:
                try:
                    data=os.read(master,65536)
                    transcript.extend(data)
                    return bool(data)
                except OSError:
                    return False
            return True
        def send_after(marker):
            deadline=time.monotonic()+90
            while marker not in transcript.decode(errors='replace'):
                if process.poll() is not None or time.monotonic()>deadline:
                    raise AssertionError('구버전 비밀번호 숨김입력 prompt 확인 실패')
                collect()
            os.write(master,(fixture.next_password+'\n').encode())
        try:
            send_after('새 비밀번호(12자 이상, UTF-8 72바이트 이하): ')
            send_after('새 비밀번호 확인: ')
            deadline=time.monotonic()+180
            while process.poll() is None and time.monotonic()<deadline:
                collect()
            if process.poll() is None:
                raise AssertionError('숨김 입력 복구 작업 시간 초과')
            while collect() and select.select([master],[],[],0)[0]:
                pass
            self.check('actual_tty_legacy_password_reset_succeeds_without_password_echo',process.returncode==0
                       and fixture.next_password not in transcript.decode(errors='replace'))
        finally:
            if process.poll() is None:
                process.kill();process.wait()
            os.close(master)
            path.unlink(missing_ok=True)

    def finish(self):
        diagnostics=[]
        for fixture in self.fixtures:
            receipts=[]
            for path in (fixture.app/'database/backups/releases').glob('*/rollback-receipt.json'):
                value=json.loads(path.read_text())
                receipts.append({key:value.get(key) for key in ('stage','completed','failed','maintenance_confirmed')})
            diagnostics.append({'https_observations':fixture.runner.https_observations,
                                'docker_failures':fixture.runner.docker_failures,'receipts':receipts})
        for fixture in reversed(self.fixtures):
            try:
                self.cleanup = fixture.cleanup() and self.cleanup
            except Exception:
                self.cleanup = False
        originals = all(sha(ROOT / name) == value for name, value in self.baseline.items())
        sources = all(sha(ROOT / name) == value for name, value in self.sources.items())
        passed = self.failure is None and self.cleanup and originals and sources and all(item['passed'] for item in self.checks)
        exception_chain=[]
        problem=self.failure
        while problem is not None:
            message=str(problem)
            for fixture in self.fixtures:
                for value in fixture.secrets:
                    message=message.replace(value,'[비밀 제거]')
            exception_chain.append({'type':type(problem).__name__,'message':message})
            problem=problem.__cause__
        report = {'started_at': self.started, 'generated_at': datetime.now(timezone.utc).isoformat(),
                  'scope': self.scope,
                  'passed': passed, 'check_count': len(self.checks), 'checks': self.checks, 'scenarios': self.scenarios,
                  'cleanup_complete': self.cleanup, 'original_nine_files_unchanged': originals,
                  'source_unchanged_during_run': sources, 'source_sha256': self.sources,
                  'production_deployed': False, 'error_type': type(self.failure).__name__ if self.failure else None,
                  'diagnostics':diagnostics,'exception_chain':exception_chain,
                  'limitations': ['Nginx sudo 명령은 fixture 컨테이너에 연결하고 upstream만 host.docker.internal의 임시 published 포트로 변환했다. 실제 운영 서버에는 연결하지 않았다.',
                                  'TLS는 임시 자체 서명 인증서이며 fixture CA로 검증했다.',
                                  '테스트 프로세스의 EXPECTED_PUBLISHED_PORTS만 격리 고포트로 대체했다. 운영 기본 고정포트 정책의 고포트 거부는 별도로 확인했다.']}
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if any(value in serialized for fixture in self.fixtures for value in fixture.secrets):
            raise AssertionError('비밀값이 검증 보고서에 포함되었습니다.')
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(serialized)
        self.output.with_suffix('.md').write_text('# 롤백 검증 결과\n\n2026-10-15 hoyeon.han\n\n'
             + f'전체 결과: {passed}, 검증 {len(self.checks)}개. 원본 자료 불변: {originals}. 정리: {self.cleanup}.\n\n'
             + '| 검증 | 결과 | 증거 범위 |\n|---|---|---|\n'
             + '\n'.join(f"| {item['name']} | {item['passed']} | {item['evidence']} |" for item in self.checks) + '\n')
        print(json.dumps({'passed': passed, 'checks': len(self.checks), 'cleanup_complete': self.cleanup,
                          'original_nine_files_unchanged': originals, 'source_unchanged': sources}, ensure_ascii=False), flush=True)
        return passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / '.codex/user-management/rollback-results.json'))
    parser.add_argument('--legacy-password-worker')
    parser.add_argument('--legacy-smoke',action='store_true',help='현재/구버전 및 TTY 복구만 수직 검증')
    parser.add_argument('--partial-smoke',action='store_true',help='부분 서비스 누락 복구만 수직 검증')
    parser.add_argument('--smoke',action='store_true',help='구현 계약 점검용 secure capture/restore만 수행')
    args = parser.parse_args()
    if args.legacy_password_worker:
        state=json.loads(Path(args.legacy_password_worker).read_text())
        fixture=Fixture.__new__(Fixture)
        fixture.api=module();fixture.app=Path(state['app']);fixture.project=state['project'];fixture.nginx_name=state['nginx_name']
        fixture.ports={int(key):value for key,value in state['ports'].items()};fixture.https_port=state['https_port']
        fixture.api.EXPECTED_PUBLISHED_PORTS={name:fixture.ports[target] for name,target in fixture.api.SERVICES.items()}
        fixture.runner=LocalRunner(fixture)
        manager=fixture.api.ReleaseManager(fixture.app,fixture.app/'nginx.site',runner=fixture.runner)
        result=manager.legacy_password(state['release'],'qa_changed',apply=True)
        print(json.dumps({'completed':result['completed'],'public_resume':result['public_resume']}))
        return 0
    verify = Verification(args.output)
    verify.smoke=args.smoke or args.partial_smoke or args.legacy_smoke
    if args.partial_smoke:
        verify.scope='secure plus missing-service vertical rehearsal'
    elif args.legacy_smoke:
        verify.scope='secure plus legacy/TTY vertical rehearsal'
    elif args.smoke:
        verify.scope='secure smoke only'
    try:
        verify.secure()
        if args.partial_smoke:
            verify.partial_service_restore(verify.fixtures[0],verify.fixtures[0].owned_releases[0])
        if args.legacy_smoke or (not args.smoke and not args.partial_smoke):
            verify.legacy()
    except BaseException as exc:
        verify.failure = exc
        print('롤백 검증 중단: ' + type(exc).__name__, flush=True)
    finally:
        passed = verify.finish()
    if verify.failure:
        raise verify.failure
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
