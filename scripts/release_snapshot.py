#!/usr/bin/env python3
"""2026-10-15 hoyeon.han: 현재 회계 시스템의 오프라인 배포 복구 도구.

모듈 import와 plan은 DB·Docker·Nginx를 변경하지 않는다. apply만 운영 상태를
변경한다. subprocess는 인자 목록만 사용하며 비밀 설정·DB 내용은 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import base64
import copy
# 2026-10-15 hoyeon.han: SQLite 트랜잭션 종료와 함께 연결도 즉시 닫아 WAL 정리를 지연하지 않습니다.
# 2026-10-19 hoyeon.han: 선택 추출 검증의 임시 수명 관리를 추가합니다.
# from contextlib import closing
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from getpass import getpass
import hashlib
import gzip
import hmac
import http.client
import json
import os
# 2026-10-19 hoyeon.han: POSIX 압축 경로를 호스트 파일 경로와 구분합니다.
# from pathlib import Path
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex
import signal
import socket
import sqlite3
import ssl
import stat
import subprocess
import sys
import tempfile
import tarfile
import time
from urllib.parse import quote, urlsplit


SERVICES = {'sollume-app': 8501, 'sollume-api': 8502, 'sollume-auth': 8503}
EXPECTED_PUBLISHED_PORTS = SERVICES.copy()
ALLOWED_MOUNTS = {'/app/database', '/app/processed', '/app/uploads', '/app/order_data',
                  '/app/logs', '/app/Src/거래처마스터.xlsx'}
SESSION_TABLES = ('security_sessions', 'security_challenges', 'security_enrollments', 'security_downloads')
SECRET_NAME = re.compile(r'(KEY|PASSWORD|SECRET|TOKEN|CREDENTIAL)', re.I)
ENV_KEYS = {'AUTH_PUBLIC_ORIGIN', 'AUTH_ENCRYPTION_KEY', 'AUTH_SIGNING_KEY',
            'AUTH_ENV', 'ORDER_API_KEY', 'COMPOSE_PROJECT_NAME', 'TZ'}
MOUNT_SETS = {
    'sollume-app': {'/app/database', '/app/processed', '/app/uploads', '/app/order_data', '/app/logs', '/app/Src/거래처마스터.xlsx'},
    'sollume-auth': {'/app/database', '/app/processed', '/app/logs'},
    'sollume-api': {'/app/order_data', '/app/logs'},
}
# 2026-10-19 hoyeon.han: office1 전용 템플릿·고정 ACME 경로만 승인하며 기존 전체 정책을 대체합니다.
# APPROVED_NGINX_SHA256 = '628df0b4489d9bfccf1aec0e09e394d50d33bcb183f2ce19c3f027fc49be2820'
# 2026-10-21 hoyeon.han: health를 기존 로그인 검사·Streamlit 전달 경로로 돌린 정책만 승인한다.
# APPROVED_NGINX_SHA256 = '291f15ba4a6ad62449911ea7161157f1501e9b757e277d554d442b1a95b56a51'
APPROVED_NGINX_SHA256 = '882188cc54f73c6bf318eb87eaf4b145fc1bf0d88f04fdb2bf628d0a89f184be'


class SafetyError(ValueError):
    """비밀정보를 포함하지 않는 운영 오류."""


class CommandRunner:
    """QA는 이 어댑터만 교체한다. CLI에는 검사 우회 옵션이 없다."""

    def run(self, argv, *, input=None, env=None):
        try:
            result = subprocess.run(list(argv), input=input, env=env, text=True,
                                    capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            # Docker stderr와 전체 명령에는 설정값이 포함될 수 있으므로 전달하지 않는다.
            raise SafetyError('외부 명령에 실패했습니다. 서비스 상태와 비공개 운영 로그를 확인하세요.') from exc
        return result.stdout

    def https_status(self, origin, path, headers=None):
        parsed = urlsplit(origin)
        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, context=context, timeout=10)
        try:
            connection.sock = context.wrap_socket(
                socket.create_connection(('127.0.0.1', parsed.port or 443), timeout=10),
                server_hostname=parsed.hostname)
            connection.request('GET', path, headers={'Host': parsed.netloc, **(headers or {})})
            response = connection.getresponse()
            response.read()
            return response.status
        except (OSError, http.client.HTTPException):
            return 0
        finally:
            connection.close()

    def internal_health(self, port, host=None):
        path = {8501: '/_stcore/health', 8502: '/health', 8503: '/auth/health'}[port]
        return self.internal_status(port, path, host=host) == 200

    def http_status(self, origin, path, headers=None):
        # 2026-10-19 hoyeon.han: 기존 HTTP 회계 도메인의 차단도 루프백 실제 응답으로 확인합니다.
        parsed = urlsplit(origin)
        connection = http.client.HTTPConnection('127.0.0.1', parsed.port or 80, timeout=5)
        try:
            connection.request('GET', path, headers={'Host': parsed.netloc, **(headers or {})})
            response = connection.getresponse(); response.read()
            return response.status
        except (OSError, http.client.HTTPException):
            return 0
        finally:
            connection.close()

    def internal_status(self, port, path, host=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        try:
            connection.request('GET', path, headers={'Host': host or 'localhost', **(headers or {})})
            response = connection.getresponse()
            response.read()
            return response.status
        except (OSError, http.client.HTTPException):
            return 0
        finally:
            connection.close()


def _digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _preserve_owner(path, descriptor):
    # 2026-10-15 hoyeon.han: sudo 복구도 기존 운영 파일의 소유자를 보존하고 신규 비공개 백업은 변경하지 않습니다.
    if os.geteuid() != 0:
        return
    try:
        previous = Path(path).lstat()
    except FileNotFoundError:
        return
    os.fchown(descriptor, previous.st_uid, previous.st_gid)


def _atomic(path, data, mode=0o600):
    """같은 디렉토리의 새 파일을 fsync한 뒤 교체한다. 대상 링크는 직접 따라가지 않는다."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        # 2026-10-15 hoyeon.han: 기존 UID/GID를 원자 교체 전에 복사하며 오류 시에도 temp fd를 닫습니다.
        # os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, 'wb') as stream:
            _preserve_owner(path, stream.fileno())
            os.fchmod(stream.fileno(), mode)
            stream.write(data.encode() if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_env(path):
    """회계 서비스에 필요한 단일 행 dotenv 값만 해석한다. shell 실행은 하지 않는다."""
    result = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key.strip()):
            raise SafetyError('.env의 단일 행 KEY=VALUE 형식을 확인하세요.')
        if key.strip() not in ENV_KEYS:
            raise SafetyError('.env에 지원하지 않는 실행환경 설정이 있습니다.')
        value = value.strip()
        if value.startswith(('"', "'")):
            try:
                parsed = shlex.split(value, posix=True)
            except ValueError as exc:
                raise SafetyError('.env의 따옴표 형식을 확인하세요.') from exc
            if len(parsed) != 1:
                raise SafetyError('.env 값에 여러 토큰을 사용할 수 없습니다.')
            value = parsed[0]
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0]
        result[key.strip()] = value
    return result


def _db_schema(path):
    # immutable은 plan에서 WAL/SHM 파일을 만들지 않기 위한 용도이며 스키마 확인에만 쓴다.
    # 2026-10-15 hoyeon.han: 기존 트랜잭션 정책을 유지하고 연결을 명시적으로 닫습니다.
    # with sqlite3.connect('file:' + quote(str(Path(path).resolve())) + '?mode=ro&immutable=1', uri=True) as conn:
    with closing(sqlite3.connect('file:' + quote(str(Path(path).resolve())) + '?mode=ro&immutable=1', uri=True)) as conn, conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'users' not in tables:
            raise SafetyError('사용자 DB의 users 표가 없습니다.')
        columns = {row[1] for row in conn.execute('PRAGMA table_info(users)')}
        required = {'id', 'username', 'password_hash', 'is_active', 'is_admin'}
        if not required <= columns:
            raise SafetyError('사용자 DB 형식을 확인할 수 없습니다.')
        if 'security_meta' not in tables:
            if {'mfa_enrolled', 'session_version'} & columns:
                raise SafetyError('인증 스키마가 불완전합니다.')
            return {'kind': 'legacy', 'version': 0}
        versions = [row[0] for row in conn.execute('SELECT version FROM security_meta')]
        if versions != [1] or not set(SESSION_TABLES) <= tables or 'session_version' not in columns:
            raise SafetyError('지원하지 않는 인증 스키마입니다.')
        return {'kind': 'secure', 'version': 1}


def _current_db_schema(path):
    wal = Path(str(path) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise SafetyError('현재 사용자 DB에 WAL 변경이 있습니다. 안전하게 정리한 뒤 계획을 다시 확인하세요.')
    return _db_schema(path)


def _sqlite_backup(source, destination):
    if not Path(source).is_file():
        raise SafetyError('백업할 DB가 없습니다.')
    destination = Path(destination)
    descriptor, name = tempfile.mkstemp(prefix='.' + destination.name + '.', dir=destination.parent)
    # os.close(descriptor)
    temporary = Path(name)
    try:
        # 2026-10-15 hoyeon.han: users.db 교체도 기존 UID/GID를 유지하고 새 백업은 생성자의 0600을 유지합니다.
        try:
            _preserve_owner(destination, descriptor)
        finally:
            os.close(descriptor)
        # 2026-10-15 hoyeon.han: 기존 트랜잭션 정책을 유지하고 연결을 명시적으로 닫습니다.
        # with sqlite3.connect('file:' + quote(str(Path(source).resolve())) + '?mode=ro', uri=True) as src:
        with closing(sqlite3.connect('file:' + quote(str(Path(source).resolve())) + '?mode=ro', uri=True)) as src, src:
            # 2026-10-15 hoyeon.han: 기존 트랜잭션 정책을 유지하고 연결을 명시적으로 닫습니다.
            # with sqlite3.connect(temporary) as dst:
            with closing(sqlite3.connect(temporary)) as dst, dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise SafetyError('SQLite 무결성 검사가 실패했습니다.')
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _certificates(content):
    found = {}
    # 2026-10-15 hoyeon.han: 따옴표 내부 #은 인증서 경로의 일부이므로 lexer로 주석을 구분합니다.
    # for line in content.splitlines():
    #     line = line.split('#', 1)[0].strip()
    #     match = re.fullmatch(r'(ssl_certificate|ssl_certificate_key)\s+(.+);', line)
    #     if match:
    #         values = shlex.split(match[2])
    lexer = shlex.shlex(content, posix=False, punctuation_chars='{};')
    lexer.whitespace_split = True
    lexer.commenters = '#'
    tokens = []
    for token in lexer:
        tokens.extend(token if set(token) <= set('{};') else [token])
    for index, token in enumerate(tokens):
        if token in ('ssl_certificate', 'ssl_certificate_key'):
            if index + 2 >= len(tokens) or tokens[index + 2] != ';':
                raise SafetyError('인증서 지시문의 형식이 다릅니다.')
            values = shlex.split(tokens[index + 1])
            if len(values) != 1 or '$' in values[0] or not Path(values[0]).is_absolute():
                raise SafetyError('고정된 절대 TLS 인증서 경로가 필요합니다.')
            # if match[1] in found and found[match[1]] != values[0]:
            if token in found and found[token] != values[0]:
                raise SafetyError('여러 인증서 경로가 있는 사이트는 수동 검토가 필요합니다.')
            # found[match[1]] = values[0]
            found[token] = values[0]
    if set(found) != {'ssl_certificate', 'ssl_certificate_key'}:
        raise SafetyError('사이트의 TLS 인증서·키 경로를 확인할 수 없습니다.')
    return {'cert': found['ssl_certificate'], 'key': found['ssl_certificate_key']}


def _approved_nginx(content):
    lexer = shlex.shlex(content, posix=False, punctuation_chars='{};')
    lexer.whitespace_split = True
    lexer.commenters = '#'
    tokens = []
    for token in lexer:
        tokens.extend(token if set(token) <= set('{};') else [token])
    counts = {'ssl_certificate': 0, 'ssl_certificate_key': 0}
    for index, token in enumerate(tokens):
        if token in counts:
            if index + 2 >= len(tokens) or tokens[index + 2] != ';':
                raise SafetyError('인증서 지시문의 형식이 다릅니다.')
            counts[token] += 1
            tokens[index + 1] = '@' + token + '@'
    encoded = json.dumps(tokens, ensure_ascii=False, separators=(',', ':')).encode()
    if any(count != 1 for count in counts.values()) or hashlib.sha256(encoded).hexdigest() != APPROVED_NGINX_SHA256:
        raise SafetyError('승인된 Cloud Nginx 인증 정책과 다릅니다. 자동 공개 복구를 거절합니다.')


class ReleaseManager:
    def __init__(self, app_dir, nginx_config, runner=None, clock=None):
        if not Path(app_dir).is_absolute() or not Path(nginx_config).is_absolute():
            raise SafetyError('앱과 Nginx 경로는 절대 경로로 지정하세요.')
        self.app_dir = Path(app_dir).resolve()
        self.nginx_config = Path(os.path.abspath(nginx_config))
        self.runner = runner or CommandRunner()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.releases_dir = self.app_dir / 'database' / 'backups' / 'releases'
        self.secrets_dir = self.app_dir / 'database' / '.release-secrets'
        self.compose_path = self.app_dir / 'docker-compose.cloud.yml'

    def _environment(self):
        result = _read_env(self.app_dir / '.env')
        if not result.get('ORDER_API_KEY'):
            raise SafetyError('현재 .env에 기존 API 키가 필요합니다.')
        return result

    def _command_env(self):
        # 호출자의 export 값이 현재 .env를 덮어쓰지 않게 한다.
        env = dict(os.environ)
        for key in _read_env(self.app_dir / '.env'):
            env.pop(key, None)
        return env

    def _render(self, path, project=None):
        args = ['docker', 'compose', '--project-directory', str(self.app_dir), '--env-file', str(self.app_dir / '.env')]
        if project:
            args += ['--project-name', project]
        args += ['--file', str(path), 'config', '--format', 'json']
        return json.loads(self.runner.run(args, env=self._command_env()))

    def _compose_command(self, project, *arguments):
        return ['docker', 'compose', '--project-directory', str(self.app_dir), '--env-file', str(self.app_dir / '.env'),
                '--project-name', project, '--file', str(self.compose_path), *arguments]

    def _run_compose(self, project, *arguments):
        return self.runner.run(self._compose_command(project, *arguments), env=self._command_env())

    def _containers(self, project, expected, require_complete=True):
        ids = self.runner.run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project]).split()
        if not ids:
            if require_complete:
                raise SafetyError('현재 실행 중인 Compose 프로젝트가 없습니다.')
            return {}
        containers = json.loads(self.runner.run(['docker', 'inspect', *ids]))
        result = {}
        for item in containers:
            labels = item['Config'].get('Labels') or {}
            name = labels.get('com.docker.compose.service')
            if labels.get('com.docker.compose.project') != project or name not in expected or name in result:
                raise SafetyError('컨테이너 프로젝트 또는 서비스 구성이 일치하지 않습니다.')
            working_dir = labels.get('com.docker.compose.project.working_dir')
            if not working_dir or Path(working_dir).resolve() != self.app_dir:
                raise SafetyError('컨테이너의 원래 앱 경로가 다릅니다.')
            for mount in item.get('Mounts', []):
                if mount.get('Type') == 'tmpfs' and mount.get('Destination') == '/tmp':
                    continue
                target = mount.get('Destination')
                relative = {'/app/Src/거래처마스터.xlsx': '거래처마스터.xlsx'}.get(target, str(target).removeprefix('/app/'))
                if (mount.get('Type') != 'bind' or target not in ALLOWED_MOUNTS
                        or Path(mount['Source']).resolve() != (self.app_dir / relative).resolve()):
                    raise SafetyError('실행 중인 서비스가 다른 원본 데이터를 사용합니다.')
            actual_bind_targets = {mount['Destination'] for mount in item.get('Mounts', []) if mount.get('Type') == 'bind'}
            if actual_bind_targets != MOUNT_SETS[name]:
                raise SafetyError('실행 중인 서비스의 필수 데이터 마운트가 누락되거나 추가되었습니다.')
            if require_complete and not item.get('State', {}).get('Running'):
                raise SafetyError('모든 관련 서비스를 실행한 상태에서 복구 지점을 준비하세요.')
            result[name] = item
        if require_complete and set(result) != set(expected):
            raise SafetyError('관련 서비스가 누락되었습니다.')
        return result

    def _validate_compose(self, config):
        services = config.get('services', {})
        if not {'sollume-app', 'sollume-api'} <= set(services) or not set(services) <= set(SERVICES):
            raise SafetyError('지원하는 Cloud 서비스 구성만 사용할 수 있습니다.')
        for name, service in services.items():
            if service.get('privileged') or service.get('network_mode'):
                raise SafetyError('특권 또는 호스트 네트워크 서비스는 복구할 수 없습니다.')
            ports = service.get('ports', [])
            if len(ports) != 1 or int(ports[0]['target']) != SERVICES[name] or ports[0].get('host_ip') != '127.0.0.1':
                raise SafetyError('8501·8502·8503 서비스는 루프백에만 게시해야 합니다.')
            if ports[0].get('protocol', 'tcp') != 'tcp' or int(ports[0]['published']) != EXPECTED_PUBLISHED_PORTS[name]:
                raise SafetyError('게시 포트 설정을 확인하세요.')
            volumes = service.get('volumes', [])
            if {volume.get('target') for volume in volumes} != MOUNT_SETS[name] or len(volumes) != len(MOUNT_SETS[name]):
                raise SafetyError('서비스별 필수 데이터 마운트 구성이 다릅니다.')
            for volume in service.get('volumes', []):
                source = Path(volume.get('source', ''))
                if volume.get('type') != 'bind' or volume.get('target') not in ALLOWED_MOUNTS:
                    raise SafetyError('알 수 없는 마운트 구성이 있습니다.')
                if not source.is_absolute() or not source.resolve().is_relative_to(self.app_dir):
                    raise SafetyError('마운트가 원래 앱 경로 밖을 가리킵니다.')
                if not source.exists():
                    raise SafetyError('기존 데이터 마운트 경로가 없습니다.')
                expected_source = self.app_dir / ({'/app/Src/거래처마스터.xlsx': '거래처마스터.xlsx'}.get(
                    volume['target'], volume['target'].removeprefix('/app/')))
                if source.resolve() != expected_source.resolve():
                    raise SafetyError('서비스 데이터와 도구가 관리하는 원본 경로가 다릅니다.')
                if (name == 'sollume-api' and volume['target'] == '/app/order_data'
                        or volume['target'] == '/app/Src/거래처마스터.xlsx') and not volume.get('read_only'):
                    raise SafetyError('원본 조회 마운트의 읽기 전용 설정이 누락되었습니다.')
        return services

    def _verify_networks(self, config, containers):
        network_names = set()
        for name, item in containers.items():
            configured = config['services'][name].get('networks') or {}
            expected = {config['networks'][key].get('name', config['name'] + '_' + key) for key in configured}
            actual = set(item.get('NetworkSettings', {}).get('Networks', {}))
            if actual != expected or not actual:
                raise SafetyError('실제 서비스 네트워크와 Compose 연결이 다릅니다.')
            network_names.update(actual)
        if network_names:
            networks = json.loads(self.runner.run(['docker', 'network', 'inspect', *sorted(network_names)]))
            if {item['Name'] for item in networks} != network_names or any(item['Driver'] != 'bridge' for item in networks):
                raise SafetyError('승인된 bridge 네트워크만 복구할 수 있습니다.')

    def _assert_runtime(self, config, current):
        """현재 .env로 해석한 설정과 실제 실행 결과를 대조한다."""
        for name, item in current.items():
            service = config['services'][name]
            actual_env = dict(value.split('=', 1) for value in item['Config'].get('Env', []) if '=' in value)
            if any(str(value) != actual_env.get(key) for key, value in service.get('environment', {}).items()):
                raise SafetyError('실제 서비스 환경 설정이 현재 .env 해석과 다릅니다.')
            if 'command' in service and service['command'] != item['Config'].get('Cmd'):
                raise SafetyError('실제 서비스 실행 명령이 다릅니다.')
            if 'read_only' in service and bool(service['read_only']) != bool(item['HostConfig'].get('ReadonlyRootfs')):
                raise SafetyError('서비스 루트 파일시스템 보호가 다릅니다.')
            for volume in service.get('volumes', []):
                actual = next((mount for mount in item['Mounts'] if mount['Destination'] == volume['target']), None)
                if not actual or bool(actual.get('RW')) == bool(volume.get('read_only', False)):
                    raise SafetyError('실제 데이터 읽기 전용 보호가 다릅니다.')
            limits = service.get('deploy', {}).get('resources', {}).get('limits', {})
            reservation = service.get('deploy', {}).get('resources', {}).get('reservations', {})
            for field, value in {'NanoCpus': int(float(limits.get('cpus', 0)) * 1_000_000_000),
                                 'Memory': int(limits.get('memory', 0)),
                                 'MemoryReservation': int(reservation.get('memory', 0))}.items():
                if item['HostConfig'].get(field) != value:
                    raise SafetyError('실제 CPU·메모리 정책이 다릅니다.')
            bindings = item['HostConfig'].get('PortBindings') or {}
            expected = {}
            for port in service.get('ports', []):
                expected[str(port['target']) + '/tcp'] = [{
                    'HostIp': port.get('host_ip') or '0.0.0.0', 'HostPort': str(port['published'])}]
            normalized = {key: [{'HostIp': value.get('HostIp') or '0.0.0.0', 'HostPort': str(value['HostPort'])}
                                 for value in values] for key, values in bindings.items()}
            if normalized != expected:
                raise SafetyError('실제 루프백 포트 연결이 설정과 다릅니다.')

    def _new_release(self, release):
        self.releases_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.secrets_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.releases_dir.chmod(0o700)
        self.secrets_dir.chmod(0o700)
        name = self.clock().strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(4)
        path = Path(release) if release else self.releases_dir / name
        if not path.is_absolute() or path.parent.resolve() != self.releases_dir.resolve():
            raise SafetyError('복구 지점은 앱의 database/backups/releases 바로 아래에 저장하세요.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', path.name):
            raise SafetyError('복구 지점 이름 형식을 확인하세요.')
        if path.exists() or path.is_symlink():
            raise SafetyError('이미 존재하는 복구 지점을 덮어쓰지 않습니다.')
        path.mkdir(mode=0o700)
        secret = self.secrets_dir / path.name
        if secret.exists() or secret.is_symlink():
            raise SafetyError('같은 이름의 비밀 보관소가 있습니다.')
        secret.mkdir(mode=0o700)
        return path, secret

    def _seal(self, release, manifest):
        manifest = copy.deepcopy(manifest)
        manifest.pop('hmac', None)
        key = (self.secrets_dir / release.name / '.env.local').read_bytes()
        manifest['hmac'] = hmac.new(key, _canonical(manifest), hashlib.sha256).hexdigest()
        _atomic(release / 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        return manifest

    def _backup_data(self, release):
        _sqlite_backup(self.app_dir / 'database/users.db', release / 'users.db')
        _sqlite_backup(self.app_dir / 'database/customer_master.db', release / 'customer_master.db')
        for name in ('current.xlsm', 'current.meta.json'):
            source = self.app_dir / 'order_data' / name
            if source.exists():
                destination = release / ('order-' + name)
                _atomic(destination, source.read_bytes())
            else:
                stale = release / ('order-' + name)
                if stale.exists():
                    stale.unlink()

    def _checksums(self, release):
        return {path.name: _digest(path) for path in release.iterdir()
                if path.is_file() and path.name not in ('manifest.json', 'rollback-receipt.json')}

    def capture(self, release=None, _recovery=False):
        env = self._environment()
        config = self._render(self.compose_path)
        project = config.get('name')
        if not project or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', project):
            raise SafetyError('Compose 프로젝트 이름을 확인할 수 없습니다.')
        names = set(config.get('services', {}))
        if not {'sollume-app', 'sollume-api'} <= names or not names <= set(SERVICES):
            raise SafetyError('Cloud 회계 서비스 구성이 아닙니다.')
        current = self._containers(project, names, require_complete=not _recovery)
        if not _recovery:
            self._assert_runtime(config, current)
            self._verify_networks(config, current)
        secure = 'sollume-auth' in names
        schema = _db_schema(self.app_dir / 'database/users.db')
        if secure and schema['kind'] != 'secure' and not _recovery:
            raise SafetyError('인증 서비스와 사용자 DB 스키마가 다릅니다.')
        frozen = copy.deepcopy(config)
        images, ids = {}, []
        for name, container in current.items():
            service = frozen['services'][name]
            actual_env = dict(value.split('=', 1) for value in container['Config'].get('Env', []) if '=' in value)
            for key, value in service.get('environment', {}).items():
                if not _recovery and str(value) != actual_env.get(key):
                    raise SafetyError('실행 중인 서비스와 현재 환경 설정이 다릅니다.')
            mounts = {volume['Destination']: volume for volume in container.get('Mounts', [])}
            for volume in service.get('volumes', []):
                actual = mounts.pop(volume['target'], None)
                if not actual or actual.get('Type') != 'bind' or Path(actual['Source']).resolve() != Path(volume['source']).resolve():
                    raise SafetyError('실행 중인 데이터 마운트와 설정이 다릅니다.')
                if bool(actual.get('RW')) == bool(volume.get('read_only', False)):
                    raise SafetyError('마운트 읽기 전용 설정이 다릅니다.')
            # tmpfs는 호스트 원본 데이터 마운트와 구분한다.
            declared_tmpfs = {value.split(':', 1)[0] for value in service.get('tmpfs', [])}
            for destination in tuple(mounts):
                if mounts[destination].get('Type') == 'tmpfs' and destination in declared_tmpfs:
                    mounts.pop(destination)
            if mounts:
                raise SafetyError('등록되지 않은 실행 마운트가 있습니다.')
            actual_tmpfs = container['HostConfig'].get('Tmpfs') or {}
            if set(actual_tmpfs) != declared_tmpfs:
                raise SafetyError('실행 중인 tmpfs 경로와 설정이 다릅니다.')
            if not _recovery and 'command' in service and service['command'] != container['Config'].get('Cmd'):
                raise SafetyError('실행 명령과 Compose 설정이 다릅니다.')
            image_id = container['Image']
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id):
                raise SafetyError('실제 실행 이미지 ID가 올바르지 않습니다.')
            metadata = json.loads(self.runner.run(['docker', 'image', 'inspect', image_id]))[0]
            images[name] = {'image_id': image_id, 'architecture': metadata['Architecture'], 'os': metadata['Os'],
                            'mounts': service.get('volumes', []),
                            'resources': service.get('deploy', {}).get('resources', {}),
                            'host_resources': {key: container['HostConfig'].get(key) for key in ('NanoCpus', 'Memory', 'MemoryReservation')}}
            policy = service.get('deploy', {}).get('resources', {})
            limits, reserve = policy.get('limits', {}), policy.get('reservations', {})
            expected_resources = {'NanoCpus': int(float(limits.get('cpus', 0)) * 1_000_000_000),
                                  'Memory': int(limits.get('memory', 0)),
                                  'MemoryReservation': int(reserve.get('memory', 0))}
            if not _recovery and images[name]['host_resources'] != expected_resources:
                raise SafetyError('실행 중인 CPU·메모리 정책이 Compose와 다릅니다.')
            ids.append(image_id)
            service['image'] = image_id
            service.pop('build', None)
            service['pull_policy'] = 'never'
            for port in service.get('ports', []):
                if secure and port.get('host_ip') != '127.0.0.1':
                    raise SafetyError('보안 서비스의 직접 공개 포트를 먼저 차단하세요.')
                port['host_ip'] = '127.0.0.1'
            # for key in service.get('environment', {}):
            #     if SECRET_NAME.search(key) or key in env and key != 'AUTH_PUBLIC_ORIGIN':
            #         service['environment'][key] = '${' + key + ':?복구에 필요한 현재 설정이 없습니다}'
        # 2026-10-15 hoyeon.han: 정지·누락된 서비스의 설정도 포함하여 모든 비밀 환경값을 가립니다.
        for service in frozen['services'].values():
            for key in service.get('environment', {}):
                if SECRET_NAME.search(key) or key in env and key != 'AUTH_PUBLIC_ORIGIN':
                    service['environment'][key] = '${' + key + ':?복구에 필요한 현재 설정이 없습니다}'
        self._validate_compose(frozen)
        # 복구 직전 불완전한 상태는 증거·자료 보관용이며 정상 복구 대상으로 선택하지 못한다.
        # 누락 서비스의 intended latest를 안전한 이미지로 오인하지 않도록 별도 표시한다.
        if _recovery:
            for name in names - set(current):
                images[name] = {'missing': True, 'intended_image': config['services'][name].get('image')}
        nginx_content = self.nginx_config.read_text()
        if secure and not _recovery:
            _approved_nginx(nginx_content)
        try:
            tls = _certificates(nginx_content)
        except SafetyError:
            if secure and not _recovery:
                raise
            # 보안 도입 전 HTTP-only 사이트도 변경 전에 보관할 수 있다.
            tls = {'cert': None, 'key': None}
        nginx = {'path': str(self.nginx_config), 'real_path': str(self.nginx_config.resolve()),
                 'link_target': os.readlink(self.nginx_config) if self.nginx_config.is_symlink() else None, **tls}
        path, secret = self._new_release(release)
        _atomic(secret / '.env', (self.app_dir / '.env').read_bytes())
        _atomic(secret / '.env.local', secrets.token_bytes(32))
        _atomic(secret / '.env.compose.local', self.compose_path.read_bytes())
        _atomic(path / 'compose.json', json.dumps(frozen, ensure_ascii=False, indent=2) + '\n')
        _atomic(path / 'nginx.site', nginx_content)
        # 원본의 인라인 키도 DB와 함께 저장하지 않는다. 원문은 별도 비밀 보관소에만 둔다.
        _atomic(path / 'compose.original', json.dumps(frozen, ensure_ascii=False, indent=2) + '\n')
        self._backup_data(path)
        _atomic(path / 'images.tar', b'')
        if ids:
            self.runner.run(['docker', 'image', 'save', '--output', str(path / 'images.tar'), *sorted(set(ids))])
        manifest = {'version': 1, 'id': path.name, 'created_at': self.clock().isoformat(), 'app_dir': str(self.app_dir),
                    'project': project, 'secure': secure, 'recoverable': not _recovery,
                    'db_schema': schema, 'nginx': nginx, 'services': images,
                    'auth_key_sha256': hashlib.sha256(env.get('AUTH_ENCRYPTION_KEY', '').encode()).hexdigest() if secure else None,
                    'checksums': self._checksums(path)}
        self._seal(path, manifest)
        return {'release': str(path), 'project': project, 'secure': secure, 'captured': True}

    def _load(self, release):
        path = Path(release)
        if not path.is_absolute() or path.is_symlink() or path.parent.resolve() != self.releases_dir.resolve():
            raise SafetyError('원래 앱의 복구 지점을 선택하세요.')
        if path.stat().st_mode & 0o077:
            raise SafetyError('복구 지점은 소유자만 접근할 수 있어야 합니다.')
        manifest = json.loads((path / 'manifest.json').read_text())
        if manifest.get('version') != 1 or manifest.get('id') != path.name or manifest.get('app_dir') != str(self.app_dir):
            raise SafetyError('복구 지점의 버전 또는 원본 앱 경로가 다릅니다.')
        saved_mac = manifest.pop('hmac', None)
        seal_file = self.secrets_dir / path.name / '.env.local'
        if seal_file.is_symlink() or seal_file.stat().st_mode & 0o077:
            raise SafetyError('비밀 보관소의 접근 권한을 확인하세요.')
        expected = hmac.new(seal_file.read_bytes(), _canonical(manifest), hashlib.sha256).hexdigest()
        if not isinstance(saved_mac, str) or not hmac.compare_digest(saved_mac, expected):
            raise SafetyError('복구 지점 manifest가 변경되었습니다.')
        manifest['hmac'] = saved_mac
        required = {'compose.json', 'compose.original', 'nginx.site', 'users.db', 'customer_master.db', 'images.tar'}
        if not required <= set(manifest.get('checksums', {})):
            raise SafetyError('필수 복구 파일이 누락되었습니다.')
        for name, digest in manifest['checksums'].items():
            file = path / name
            if Path(name).name != name or file.is_symlink() or not file.is_file() or _digest(file) != digest:
                raise SafetyError('복구 파일의 경로 또는 체크섬이 다릅니다.')
        if manifest['nginx']['path'] != str(self.nginx_config):
            raise SafetyError('캡처한 Nginx 사이트 경로와 다릅니다.')
        return path, manifest

    def plan(self, release, legacy_private=False, restore_users=False):
        path, manifest = self._load(release)
        if not manifest.get('recoverable'):
            raise SafetyError('불완전한 장애 상태의 자료 보관본은 자동 복구 대상으로 선택할 수 없습니다.')
        if not manifest['secure'] and not (legacy_private and restore_users):
            raise SafetyError('보안 도입 전 복구는 --legacy-private와 --restore-users가 모두 필요합니다.')
        if manifest['secure'] and (legacy_private or restore_users):
            raise SafetyError('정상 보안 복구에서는 사용자 DB를 과거 상태로 되돌리지 않습니다.')
        snapshot_schema = _db_schema(path / 'users.db')
        current_schema = _current_db_schema(self.app_dir / 'database/users.db')
        if manifest['secure'] and (snapshot_schema['kind'] != 'secure' or current_schema != snapshot_schema):
            raise SafetyError('현재 사용자 DB와 복구 이미지의 인증 스키마가 호환되지 않습니다.')
        if manifest['secure']:
            _approved_nginx((path / 'nginx.site').read_text())
        if not manifest['secure'] and snapshot_schema['kind'] != 'legacy':
            raise SafetyError('구버전용 사용자 DB 형식이 아닙니다.')
        env = self._environment()
        if manifest['secure']:
            try:
                key = base64.urlsafe_b64decode(env.get('AUTH_ENCRYPTION_KEY', '').encode('ascii'))
                assert len(key) == 32
            except (ValueError, UnicodeError, AssertionError) as exc:
                raise SafetyError('현재 AUTH_ENCRYPTION_KEY 설정이 필요합니다.') from exc
            # 2026-10-19 hoyeon.han: 별도 운영 사이트인 루트 도메인을 회계 복구 대상으로 사용하지 않습니다.
            # if env.get('AUTH_PUBLIC_ORIGIN') != 'https://sollumeesthe.com':
            if env.get('AUTH_PUBLIC_ORIGIN') != 'https://office1.sollumeesthe.com':
                raise SafetyError('현재 HTTPS 공개 주소를 확인하세요.')
            if hashlib.sha256(env['AUTH_ENCRYPTION_KEY'].encode()).hexdigest() != manifest.get('auth_key_sha256'):
                raise SafetyError('스냅샷 이후 암호화 키가 바뀌었습니다. 자동 키 회전 복구는 지원하지 않습니다.')
        pinned = json.loads((path / 'compose.json').read_text())
        services = self._validate_compose(pinned)
        if set(services) != set(manifest['services']) or pinned.get('name') != manifest['project']:
            raise SafetyError('저장된 프로젝트 또는 서비스 목록이 다릅니다.')
        for name, service in services.items():
            if service['image'] != manifest['services'][name]['image_id'] or service.get('pull_policy') != 'never':
                raise SafetyError('오프라인 이미지 고정 정책이 변경되었습니다.')
            for key, value in service.get('environment', {}).items():
                if isinstance(value, str) and value.startswith('${') and not env.get(key):
                    raise SafetyError('현재 .env에 복구 서비스의 필수 설정이 없습니다.')
        current = self._render(self.compose_path)
        if current.get('name') != manifest['project']:
            raise SafetyError('현재 실행 프로젝트와 복구 프로젝트가 다릅니다.')
        self._validate_compose(current) if 'sollume-auth' in current['services'] else None
        self._containers(manifest['project'], current['services'], require_complete=False)
        current_tls = _certificates(self.nginx_config.read_text())
        if not all(Path(value).is_file() for value in current_tls.values()):
            raise SafetyError('현재 TLS 인증서 파일을 보존할 수 없습니다.')
        return {'release': str(path), 'project': manifest['project'], 'secure': manifest['secure'],
                'dry_run': True, 'validated': True, 'restore_users': restore_users,
                'preserve_business_data': True, 'public_resume': manifest['secure']}

    def _write_nginx(self, content, layout):
        entry = Path(layout['path'])
        target = Path(layout['real_path'])
        if entry != self.nginx_config or not target.is_absolute():
            raise SafetyError('Nginx 복원 경로가 다릅니다.')
        _atomic(target, content, 0o644)
        link = layout.get('link_target')
        if link is not None:
            temporary = entry.with_name('.' + entry.name + '.' + secrets.token_hex(8))
            try:
                os.symlink(link, temporary)
                os.replace(temporary, entry)
            finally:
                if temporary.is_symlink():
                    temporary.unlink()
        elif entry != target:
            raise SafetyError('Nginx 일반 파일 경로가 일치하지 않습니다.')
        self.runner.run(['sudo', 'nginx', '-t'])
        self.runner.run(['sudo', 'systemctl', 'reload', 'nginx'])

    def _wait_https_status(self, path, expected, headers=None):
        # 2026-10-15 hoyeon.han: reload 뒤 이전 worker가 잠시 응답할 수 있어 기대 상태를 유한 재확인합니다.
        deadline = time.monotonic() + 5.0
        # 2026-10-15 hoyeon.han: 이전·신규 worker 응답이 섞여도 첫 일치만으로 적용 완료를 가정하지 않습니다.
        consecutive = 0
        while True:
            # if self.runner.https_status('https://sollumeesthe.com', path, headers) == expected:
            #     return True
            # 2026-10-19 hoyeon.han: 승인한 office1 호스트의 실제 TLS·차단 응답만 확인합니다.
            # status = self.runner.https_status('https://sollumeesthe.com', path, headers)
            status = self.runner.https_status('https://office1.sollumeesthe.com', path, headers)
            consecutive = consecutive + 1 if status == expected else 0
            remaining = deadline - time.monotonic()
            if consecutive >= 3 and remaining >= 0:
                return True
            if remaining <= 0:
                return False
            time.sleep(min(0.2, remaining))

    @staticmethod
    def _maintenance(tls):
        cert = json.dumps(tls['cert'], ensure_ascii=False)
        key = json.dumps(tls['key'], ensure_ascii=False)
        # 2026-10-19 hoyeon.han: 기존 전체 호스트 차단 표현을 보존하고 office1 업무 경로만 차단합니다.
        # return ('# 2026-10-15 hoyeon.han: 복구 중 모든 외부 업무 요청을 차단한다.\n'
        #         'server { listen 80 default_server; server_name _; return 503; }\n'
        #         'server { listen 443 ssl default_server; server_name sollumeesthe.com;\n'
        #         f' ssl_certificate {cert}; ssl_certificate_key {key};\n'
        #         ' ssl_protocols TLSv1.2 TLSv1.3; add_header Cache-Control no-store always; return 503; }\n')
        return ('# 2026-10-19 hoyeon.han: office1 업무 요청 차단 중 고정된 ACME 갱신 경로를 유지한다.\n'
                'server { listen 80; server_name office1.sollumeesthe.com;\n'
                ' location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; '
                'default_type text/plain; try_files $uri =404; }\n'
                ' location / { add_header Cache-Control no-store always; return 503; } }\n'
                'server { listen 443 ssl; server_name office1.sollumeesthe.com;\n'
                f' ssl_certificate {cert}; ssl_certificate_key {key};\n'
                ' ssl_protocols TLSv1.2 TLSv1.3; add_header Cache-Control no-store always; return 503; }\n')

    @staticmethod
    def _replace_tls(content, tls):
        for directive, key in (('ssl_certificate', 'cert'), ('ssl_certificate_key', 'key')):
            content = re.sub(r'(?m)^(\s*' + directive + r'\s+)[^;]+;',
                             lambda match: match[1] + json.dumps(tls[key], ensure_ascii=False) + ';', content)
        _certificates(content)
        return content

    def _receipt(self, release, value):
        seal = (self.secrets_dir / release.name / '.env.local').read_bytes()
        result = dict(value)
        result['hmac'] = hmac.new(seal, _canonical(value), hashlib.sha256).hexdigest()
        _atomic(release / 'rollback-receipt.json', json.dumps(result, ensure_ascii=False, indent=2) + '\n')

    def _revoke_sessions(self):
        # 2026-10-15 hoyeon.han: 기존 트랜잭션 정책을 유지하고 연결을 명시적으로 닫습니다.
        # with sqlite3.connect(self.app_dir / 'database/users.db') as conn:
        with closing(sqlite3.connect(self.app_dir / 'database/users.db')) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('UPDATE users SET session_version=session_version+1')
            for table in SESSION_TABLES:
                conn.execute('DELETE FROM ' + table)

    def _legacy_users(self, path, current_backup):
        def users(db):
            # 2026-10-15 hoyeon.han: 기존 트랜잭션 정책을 유지하고 연결을 명시적으로 닫습니다.
            # with sqlite3.connect('file:' + quote(str(db)) + '?mode=ro&immutable=1', uri=True) as conn:
            with closing(sqlite3.connect('file:' + quote(str(db)) + '?mode=ro&immutable=1', uri=True)) as conn, conn:
                return {row[0]: row for row in conn.execute('SELECT id,username,password_hash,is_active,is_admin FROM users')}
        latest = users(current_backup)
        destination = self.app_dir / 'database/users.db'
        # 모든 writer를 종료한 뒤 DB 전체를 backup API로 교체하고 옛 WAL은 혼입하지 않는다.
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(destination) + suffix)
            if sidecar.exists():
                raise SafetyError('중지한 사용자 DB의 부속 파일을 먼저 안전하게 점검하세요.')
        _sqlite_backup(path / 'users.db', destination)
        stopped = []
        # 2026-10-15 hoyeon.han: 기존 트랜잭션 정책을 유지하고 연결을 명시적으로 닫습니다.
        # with sqlite3.connect(destination) as conn:
        with closing(sqlite3.connect(destination)) as conn, conn:
            for old in conn.execute('SELECT id,username,password_hash,is_active,is_admin FROM users').fetchall():
                now = latest.get(old[0])
                same_identity = now is not None and old[1] == now[1]
                same_password = same_identity and old[2] == now[2]
                active = bool(same_password and old[3] and now[3])
                admin = bool(same_identity and old[4] and now[4])
                conn.execute('UPDATE users SET is_active=?,is_admin=? WHERE id=?', (int(active), int(admin), old[0]))
                if same_identity and now[3] and not same_password:
                    stopped.append(old[0])
        return stopped

    def rollback(self, release, apply=False, legacy_private=False, restore_users=False):
        plan = self.plan(release, legacy_private, restore_users)
        if not apply:
            return plan
        path, manifest = self._load(release)
        current_config = self._render(self.compose_path)
        tls = _certificates(self.nginx_config.read_text())
        layout = {'path': str(self.nginx_config), 'real_path': str(self.nginx_config.resolve()),
                  'link_target': os.readlink(self.nginx_config) if self.nginx_config.is_symlink() else None}
        maintenance = self._maintenance(tls)
        receipt = {'release': str(path), 'project': manifest['project'], 'legacy_private': not manifest['secure'],
                   'started_at': self.clock().isoformat(), 'completed': False, 'stage': 'capture_current',
                   'operation': 'rollback'}
        rescue = None
        try:
            rescue = Path(self.capture(_recovery=True)['release'])
            receipt['recovery_release'] = str(rescue)
            receipt['stage'] = 'maintenance'
            self._write_nginx(maintenance, layout)
            # 2026-10-15 hoyeon.han: Nginx reload 반영을 확인한 뒤에만 writer를 중지합니다.
            # if self.runner.https_status('https://sollumeesthe.com', '/') != 503:
            if not self._wait_https_status('/', 503):
                raise SafetyError('외부 503 차단을 확인할 수 없습니다.')
            receipt['stage'] = 'stop_writers'
            self._run_compose(manifest['project'], 'down')
            if self.runner.run(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + manifest['project']]).strip():
                raise SafetyError('관련 서비스가 완전히 중지되지 않았습니다.')
            for name in ('users.db', 'customer_master.db'):
                # 2026-10-15 hoyeon.han: 기존 트랜잭션 정책을 유지하고 연결을 명시적으로 닫습니다.
                # with sqlite3.connect(self.app_dir / 'database' / name) as conn:
                with closing(sqlite3.connect(self.app_dir / 'database' / name)) as conn, conn:
                    if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                        raise SafetyError('중지한 DB의 WAL 정리를 완료하지 못했습니다.')
            # 중지 직전까지의 자료를 다시 보관한다. 업무 DB는 복원하지 않는다.
            self._backup_data(rescue)
            rescue_manifest = json.loads((rescue / 'manifest.json').read_text())
            rescue_manifest['checksums'] = self._checksums(rescue)
            self._seal(rescue, rescue_manifest)
            stopped_schema = _db_schema(rescue / 'users.db')
            if manifest['secure'] and stopped_schema != _db_schema(path / 'users.db'):
                raise SafetyError('서비스 정지 후 사용자 DB 스키마 호환성을 다시 확인하지 못했습니다.')
            receipt['stage'] = 'load_offline_images'
            self.runner.run(['docker', 'image', 'load', '--input', str(path / 'images.tar')])
            for service in manifest['services'].values():
                info = json.loads(self.runner.run(['docker', 'image', 'inspect', service['image_id']]))[0]
                if info['Id'] != service['image_id'] or info['Architecture'] != service['architecture'] or info['Os'] != service['os']:
                    raise SafetyError('불러온 이미지 ID 또는 플랫폼이 다릅니다.')
            receipt['stage'] = 'user_state'
            if manifest['secure']:
                self._revoke_sessions()
            else:
                receipt['password_reset_required_ids'] = self._legacy_users(path, rescue / 'users.db')
                receipt['operator_action'] = '옛 비밀번호 부활을 막기 위해 중지한 계정은 운영자의 명시적 재설정이 필요합니다.'
            _atomic(self.compose_path, (path / 'compose.json').read_bytes())
            receipt['stage'] = 'start_saved_services'
            self._run_compose(manifest['project'], 'up', '-d', '--pull', 'never', '--no-build', '--wait', '--wait-timeout', '120')
            started_config = self._render(self.compose_path, manifest['project'])
            started = self._containers(manifest['project'], manifest['services'])
            if any(started[name]['Image'] != meta['image_id'] for name, meta in manifest['services'].items()):
                raise SafetyError('실제로 시작한 이미지가 고정 이미지와 다릅니다.')
            self._assert_runtime(started_config, started)
            for name in manifest['services']:
                # 2026-10-19 hoyeon.han: 인증 서비스의 허용 Host도 office1과 일치시킵니다.
                # if not self.runner.internal_health(SERVICES[name], host='sollumeesthe.com'):
                if not self.runner.internal_health(SERVICES[name], host='office1.sollumeesthe.com'):
                    raise SafetyError('복구 서비스의 내부 상태 검사가 실패했습니다.')
            if manifest['secure']:
                receipt['stage'] = 'restore_secure_nginx'
                for denied_path in ('/auth/check', '/downloads/' + '0' * 32):
                    # 2026-10-19 hoyeon.han: 접근·다운로드 거절 검증은 office1 Host를 사용합니다.
                    # if self.runner.internal_status(8503, denied_path, host='sollumeesthe.com',
                    if self.runner.internal_status(8503, denied_path, host='office1.sollumeesthe.com',
                                                   headers={'X-Forwarded-Proto': 'https'}) != 401:
                        raise SafetyError('내부 인증 서버의 미인증 접근 거부를 확인하지 못했습니다.')
                candidate = self._replace_tls((path / 'nginx.site').read_text(), tls)
                _approved_nginx(candidate)
                self._write_nginx(candidate, layout)
                # 2026-10-15 hoyeon.han: reload의 이전 503 응답이 사라진 뒤 인증·다운로드 차단을 판정합니다.
                # if (self.runner.https_status('https://sollumeesthe.com', '/', {'Accept': 'application/json'}) != 401
                #         or self.runner.https_status('https://sollumeesthe.com', '/media/rollback-check') != 403):
                if (not self._wait_https_status('/', 401, {'Accept': 'application/json'})
                        or not self._wait_https_status('/media/rollback-check', 403)):
                    raise SafetyError('복구한 인증·다운로드 차단을 확인하지 못했습니다.')
            receipt.update(completed=True, stage='completed', public_resume=manifest['secure'], finished_at=self.clock().isoformat())
            self._receipt(path, receipt)
            return {'release': str(path), 'recovery_release': str(rescue), 'completed': True,
                    'legacy_private': not manifest['secure'], 'public_resume': manifest['secure'],
                    'password_reset_required': bool(receipt.get('password_reset_required_ids'))}
        except BaseException as exc:
            # 단계 실패 시 구버전 사이트를 공개하지 않는다. 503 자체가 실패하면 서비스도 중지한다.
            try:
                self._write_nginx(maintenance, layout)
                # 2026-10-15 hoyeon.han: 실패 정리도 503 적용 완료를 제한 시간 안에 확인합니다.
                # if self.runner.https_status('https://sollumeesthe.com', '/') != 503:
                if not self._wait_https_status('/', 503):
                    raise SafetyError('차단 확인 실패')
                receipt['maintenance_confirmed'] = True
            except BaseException:
                receipt['maintenance_confirmed'] = False
                try:
                    self._run_compose(manifest['project'], 'down')
                except BaseException:
                    receipt['manual_access_block_required'] = True
            receipt['failed'] = True
            self._receipt(path, receipt)
            raise SafetyError('복구에 실패했습니다. 외부 차단 상태와 비공개 rollback-receipt.json을 확인하세요.') from exc

    def legacy_password(self, release, username, apply=False):
        path, manifest = self._load(release)
        if manifest['secure']:
            raise SafetyError('구버전 비밀번호 복구 전용 기능입니다.')
        receipt = json.loads((path / 'rollback-receipt.json').read_text())
        saved = receipt.pop('hmac', None)
        seal = (self.secrets_dir / path.name / '.env.local').read_bytes()
        if not saved or not hmac.compare_digest(saved, hmac.new(seal, _canonical(receipt), hashlib.sha256).hexdigest()):
            raise SafetyError('구버전 복구 기록이 변경되었습니다.')
        if not receipt.get('completed') or not receipt.get('legacy_private'):
            raise SafetyError('구버전 비공개 복구를 먼저 완료하세요.')
        rescue, _ = self._load(receipt['recovery_release'])
        current = self._containers(manifest['project'], manifest['services'])
        if any(current[name]['Image'] != meta['image_id'] for name, meta in manifest['services'].items()):
            raise SafetyError('실행 중인 구버전 이미지가 다릅니다.')
        # 2026-10-15 hoyeon.han: 구버전 계정 복구도 외부 차단의 실제 응답을 유한 재확인합니다.
        # if self.runner.https_status('https://sollumeesthe.com', '/') != 503:
        if not self._wait_https_status('/', 503):
            raise SafetyError('외부 503 차단 상태가 아닙니다.')
        def lookup(db):
            # 2026-10-15 hoyeon.han: 기존 트랜잭션 정책을 유지하고 연결을 명시적으로 닫습니다.
            # with sqlite3.connect('file:' + quote(str(db)) + '?mode=ro&immutable=1', uri=True) as conn:
            with closing(sqlite3.connect('file:' + quote(str(db)) + '?mode=ro&immutable=1', uri=True)) as conn, conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute('SELECT id,username,is_active,is_admin FROM users WHERE username=?', (username,)).fetchone()
                return dict(row) if row else None
        latest = lookup(rescue / 'users.db')
        target = lookup(self.app_dir / 'database/users.db')
        if not latest or not target or latest['id'] != target['id'] or not latest['is_active']:
            raise SafetyError('삭제·정지되었거나 동일성을 확인할 수 없는 계정은 복구할 수 없습니다.')
        if not apply:
            return {'dry_run': True, 'validated': True, 'legacy_private': True, 'account_id': target['id']}
        if not sys.stdin.isatty():
            raise SafetyError('숨김 입력이 가능한 터미널에서 실행하세요.')
        password = getpass('새 비밀번호(12자 이상, UTF-8 72바이트 이하): ')
        if len(password) < 12 or len(password.encode()) > 72 or password != getpass('새 비밀번호 확인: '):
            raise SafetyError('비밀번호 길이·확인을 점검하세요.')
        image = manifest['services']['sollume-app']['image_id']
        try:
            receipt['password_reset_stage'] = 'generate_hash'
            encoded = self.runner.run(['docker', 'run', '--rm', '-i', '--pull', 'never', '--network', 'none', '--read-only',
                                       '--entrypoint', 'python', image, '-B', '-c',
                                       'import bcrypt,sys; print(bcrypt.hashpw(sys.stdin.buffer.read(),bcrypt.gensalt(rounds=12)).decode())'], input=password).strip()
            if not re.fullmatch(r'\$2[aby]\$12\$[./A-Za-z0-9]{53}', encoded):
                raise SafetyError('구버전 비밀번호 해시 생성에 실패했습니다.')
            receipt['password_reset_stage'] = 'stop_writers'
            self._run_compose(manifest['project'], 'down')
            if self.runner.run(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + manifest['project']]).strip():
                raise SafetyError('계정 수정 전 관련 서비스가 중지되지 않았습니다.')
            backup = path / ('before-password-' + secrets.token_hex(8) + '.db')
            _sqlite_backup(self.app_dir / 'database/users.db', backup)
            manifest['checksums'] = self._checksums(path)
            self._seal(path, manifest)
            receipt['password_reset_stage'] = 'update_account'
            # 2026-10-15 hoyeon.han: 기존 트랜잭션 정책을 유지하고 연결을 명시적으로 닫습니다.
            # with sqlite3.connect(self.app_dir / 'database/users.db') as conn:
            with closing(sqlite3.connect(self.app_dir / 'database/users.db')) as conn, conn:
                conn.execute('UPDATE users SET password_hash=?,is_active=1,is_admin=? WHERE id=? AND username=?',
                             (encoded, int(bool(target['is_admin'] and latest['is_admin'])), target['id'], username))
            self._run_compose(manifest['project'], 'up', '-d', '--pull', 'never', '--no-build', '--wait', '--wait-timeout', '120')
            after_reset = self._containers(manifest['project'], manifest['services'])
            if any(after_reset[name]['Image'] != meta['image_id'] for name, meta in manifest['services'].items()):
                raise SafetyError('비밀번호 복구 후 실제 이미지가 다릅니다.')
            self._assert_runtime(self._render(self.compose_path, manifest['project']), after_reset)
            # 2026-10-15 hoyeon.han: 복구 완료 전에도 503 유지 상태를 실제 응답으로 확인합니다.
            # if self.runner.https_status('https://sollumeesthe.com', '/') != 503:
            if not self._wait_https_status('/', 503):
                raise SafetyError('비밀번호 복구 후 외부 차단 상태가 다릅니다.')
            receipt['password_reset_stage'] = 'completed'
            receipt['password_reset_account_id'] = target['id']
            self._receipt(path, receipt)
        except BaseException as exc:
            receipt['password_reset_failed'] = True
            receipt['password_reset_account_id'] = target['id']
            try:
                tls = _certificates(self.nginx_config.read_text())
                layout = {'path': str(self.nginx_config), 'real_path': str(self.nginx_config.resolve()),
                          'link_target': os.readlink(self.nginx_config) if self.nginx_config.is_symlink() else None}
                self._write_nginx(self._maintenance(tls), layout)
                # 2026-10-15 hoyeon.han: 비밀번호 복구 실패 정리도 reload 성공만으로 차단을 가정하지 않습니다.
                if not self._wait_https_status('/', 503):
                    raise SafetyError('차단 확인 실패')
            except BaseException:
                receipt['manual_access_block_required'] = True
                try:
                    self._run_compose(manifest['project'], 'down')
                except BaseException:
                    pass
            self._receipt(path, receipt)
            raise SafetyError('비밀번호 복구에 실패했습니다. 외부 503은 유지하고 운영자 점검을 진행하세요.') from exc
        return {'completed': True, 'legacy_private': True, 'account_id': target['id'], 'public_resume': False}



# 2026-10-19 hoyeon.han: 운영 수동 백업 3종을 원본 변경 없이 검증·봉인·비공개 복구합니다.
MANUAL_FILES = ('application.tar.gz', 'images.tar', 'containers.json')
MANUAL_SERVICES = {'sollume-app', 'sollume-api'}
MANUAL_MAX_APP = 4 * 1024 ** 3
MANUAL_MAX_IMAGES = 12 * 1024 ** 3
MANUAL_MAX_DB = 256 * 1024 ** 2
# 2026-10-19 hoyeon.han: 다른 사이트인 루트 도메인을 제외하고 회계 진입점 세 곳만 승인합니다.
# MANUAL_DOMAINS = {'sollumeesthe.com', 'sol-fin.duckdns.org', 'sollume-finance.duckdns.org'}
MANUAL_DOMAINS = {'office1.sollumeesthe.com', 'sol-fin.duckdns.org', 'sollume-finance.duckdns.org'}


def _manual_name(name):
    if not isinstance(name, str) or '\\' in name or '\x00' in name or name.startswith('/') or len(name) > 4096:
        raise SafetyError('압축 파일의 경로가 안전하지 않습니다.')
    parts = name.split('/')
    if '..' in parts or any(':' in part for part in parts):
        raise SafetyError('압축 경로 이탈을 허용하지 않습니다.')
    return '/'.join(part for part in parts if part not in ('', '.'))


@contextmanager
def _manual_tar(path, maximum):
    try:
        with tarfile.open(path, 'r:*') as archive:
            members, size = {}, 0
            for member in archive:
                name = _manual_name(member.name)
                if name in members:
                    raise SafetyError('압축 파일에 중복 경로가 있습니다.')
                if len(members) >= 150000 or member.size < 0 or member.size > maximum:
                    raise SafetyError('압축 파일의 항목 또는 크기 제한을 초과했습니다.')
                if member.issparse() or any(key.startswith('GNU.sparse') for key in member.pax_headers):
                    raise SafetyError('희소 압축 항목은 지원하지 않습니다.')
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise SafetyError('장치·특수 압축 항목을 허용하지 않습니다.')
                size += member.size
                if size > maximum or size > max(64 * 1024 ** 2, Path(path).stat().st_size * 200):
                    raise SafetyError('압축 해제 크기 제한을 초과했습니다.')
                if member.isfile() and name.startswith('database/backups/releases/'):
                    raise SafetyError('백업을 다시 포함하는 재귀 압축은 허용하지 않습니다.')
                members[name] = member
            yield archive, members
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise SafetyError('압축 파일을 안전하게 읽을 수 없습니다.') from exc


def _manual_read(archive, members, name, limit):
    member = members.get(name)
    if member is None or not member.isfile() or member.size > limit:
        raise SafetyError('필수 압축 항목이 없거나 일반 파일이 아닙니다.')
    stream = archive.extractfile(member)
    if stream is None:
        raise SafetyError('필수 압축 파일을 읽을 수 없습니다.')
    with stream:
        value = stream.read(limit + 1)
    if len(value) != member.size or len(value) > limit:
        raise SafetyError('압축 항목의 크기가 다릅니다.')
    return value


def _manual_wal(path):
    """WAL을 임시 복사본에서만 검사합니다. SQLite가 손상 WAL을 조용히 무시하지 못하게 합니다."""
    path = Path(path)
    if not path.exists() or not path.stat().st_size:
        return
    data = path.read_bytes()
    if len(data) < 32:
        raise SafetyError('백업 WAL 헤더가 불완전합니다.')
    magic = int.from_bytes(data[:4], 'big')
    if magic not in (0x377f0682, 0x377f0683):
        raise SafetyError('백업 WAL 형식이 다릅니다.')
    page = int.from_bytes(data[8:12], 'big')
    if page < 512 or page > 65536 or page & (page - 1) or (len(data) - 32) % (page + 24):
        raise SafetyError('백업 WAL 프레임이 불완전합니다.')
    order = 'little' if magic == 0x377f0682 else 'big'
    def checksum(chunk, state=(0, 0)):
        a, b = state
        for offset in range(0, len(chunk), 8):
            a = (a + int.from_bytes(chunk[offset:offset + 4], order) + b) & 0xffffffff
            b = (b + int.from_bytes(chunk[offset + 4:offset + 8], order) + a) & 0xffffffff
        return a, b
    state = checksum(data[:24])
    stored = lambda value: (int.from_bytes(value[:4], 'big'), int.from_bytes(value[4:8], 'big'))
    if state != stored(data[24:32]):
        raise SafetyError('백업 WAL 헤더 체크섬이 다릅니다.')
    for offset in range(32, len(data), page + 24):
        frame = data[offset:offset + page + 24]
        if frame[8:16] != data[16:24] or not int.from_bytes(frame[:4], 'big'):
            raise SafetyError('백업 WAL 세대 또는 페이지가 다릅니다.')
        state = checksum(frame[:8] + frame[24:], state)
        if state != stored(frame[16:24]):
            raise SafetyError('백업 WAL 프레임 체크섬이 다릅니다.')


def _manual_db(path):
    _manual_wal(str(path) + '-wal')
    with closing(sqlite3.connect(path)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SafetyError('수동 백업 DB의 무결성 검사가 실패했습니다.')
        result = conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if result and result[0]:
            raise SafetyError('임시 백업 WAL을 일관되게 정리하지 못했습니다.')


def _manual_security(path):
    with closing(sqlite3.connect('file:' + quote(str(path)) + '?mode=ro&immutable=1', uri=True)) as conn:
        rows = conn.execute('SELECT id,username,password_hash,is_active,is_admin FROM users ORDER BY id').fetchall()
    return hashlib.sha256(_canonical(rows)).hexdigest()


def _manual_live_copy(source, destination):
    """운영 DB에 SQLite 연결을 열지 않습니다. 안정된 DB/WAL 바이트 복사본만 임시 폴더에서 엽니다."""
    source, destination = Path(source), Path(destination)
    paths = [source, Path(str(source) + '-wal'), Path(str(source) + '-journal')]
    for attempt in range(3):
        if paths[2].exists() and paths[2].stat().st_size:
            raise SafetyError('현재 사용자 DB에 rollback journal이 있습니다. 안정된 시점에 다시 확인하세요.')
        before = [_digest(path) if path.is_file() else None for path in paths]
        for path, digest in zip(paths[:2], before[:2]):
            target = Path(str(destination) + ('-wal' if path != source else ''))
            if digest is None:
                if target.exists(): target.unlink()
            else:
                _atomic(target, path.read_bytes())
        after = [_digest(path) if path.is_file() else None for path in paths]
        if paths[2].exists() and paths[2].stat().st_size:
            raise SafetyError('현재 사용자 DB에 rollback journal이 생겼습니다. 안정된 시점에 다시 확인하세요.')
        copied = [_digest(Path(str(destination) + ('-wal' if path != source else '')))
                  if Path(str(destination) + ('-wal' if path != source else '')).is_file() else None for path in paths[:2]]
        if before == after and copied == before[:2]:
            _manual_db(destination)
            return
    raise SafetyError('현재 사용자 DB가 변경 중입니다. 안정된 시점의 새 백업을 준비하세요.')


class ManualBackupManager(ReleaseManager):
    def __init__(self, app_dir, backup_dir, nginx_configs=None, runner=None, clock=None):
        self.sites = [Path(os.path.abspath(value)) for value in (nginx_configs or [])]
        if len(set(self.sites)) != len(self.sites) or any(not Path(value).is_absolute() for value in (nginx_configs or [])):
            raise SafetyError('Nginx 사이트는 중복 없이 절대 경로로 지정하세요.')
        super().__init__(app_dir, self.sites[0] if self.sites else Path(app_dir) / 'manual-unselected.site', runner, clock)
        self.backup_dir = Path(backup_dir)
        if not self.backup_dir.is_absolute() or self.backup_dir.is_symlink():
            raise SafetyError('수동 백업의 실제 절대 디렉토리를 지정하세요.')
        self.backup_dir = self.backup_dir.resolve()

    def _sources(self):
        result = {}
        for name in MANUAL_FILES:
            file = self.backup_dir / name
            if file.is_symlink() or not file.is_file():
                raise SafetyError('수동 백업 3개 일반 파일이 모두 필요합니다.')
            result[name] = _digest(file)
        if (self.backup_dir / 'containers.json').stat().st_size > 8 * 1024 ** 2:
            raise SafetyError('컨테이너 메타데이터 크기를 초과했습니다.')
        return result

    def _inspect(self):
        values = json.loads((self.backup_dir / 'containers.json').read_text())
        if not isinstance(values, list) or len(values) != 2:
            raise SafetyError('수동 백업은 회계 앱·API 두 서비스만 포함해야 합니다.')
        result, project = {}, None
        for item in values:
            labels = item['Config'].get('Labels') or {}
            name = labels.get('com.docker.compose.service')
            candidate = labels.get('com.docker.compose.project')
            if name not in MANUAL_SERVICES or name in result or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', candidate or ''):
                raise SafetyError('회계 앱·API 프로젝트를 확인할 수 없습니다.')
            if project is not None and project != candidate:
                raise SafetyError('백업의 두 서비스 프로젝트가 다릅니다.')
            project = candidate
            if Path(labels.get('com.docker.compose.project.working_dir', '')).resolve() != self.app_dir:
                raise SafetyError('수동 백업의 원래 앱 경로가 다릅니다.')
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', item.get('Image', '')):
                raise SafetyError('실행 이미지 ID가 올바르지 않습니다.')
            for field in ('Cmd', 'Entrypoint'):
                value = item['Config'].get(field)
                if value is not None and (not isinstance(value, list) or not all(isinstance(part, str) and '\x00' not in part for part in value)):
                    raise SafetyError('실행 명령의 argv 형식이 다릅니다.')
            host = item['HostConfig']
            if (host.get('Privileged') or host.get('NetworkMode') in ('host', 'none') or host.get('Binds') is None
                    or host.get('CapAdd') or host.get('Devices') or host.get('DeviceRequests') or host.get('VolumesFrom')
                    or host.get('PidMode') or host.get('IpcMode') not in (None, '', 'private', 'shareable')
                    or str(host.get('NetworkMode', '')).startswith('container:')):
                raise SafetyError('지원하지 않는 실행 권한·네트워크 구성입니다.')
            mounts = [entry for entry in item.get('Mounts', []) if entry.get('Type') != 'tmpfs']
            if {entry.get('Destination') for entry in mounts} != MOUNT_SETS[name] or len(mounts) != len(MOUNT_SETS[name]):
                raise SafetyError('수동 백업의 영속 마운트가 다릅니다.')
            for mount in mounts:
                target = mount['Destination']
                relative = '거래처마스터.xlsx' if target == '/app/Src/거래처마스터.xlsx' else target.removeprefix('/app/')
                if mount.get('Type') != 'bind' or Path(mount['Source']).resolve() != (self.app_dir / relative).resolve():
                    raise SafetyError('수동 백업의 데이터 경로가 다릅니다.')
                if (name == 'sollume-api' and target == '/app/order_data' or target.endswith('거래처마스터.xlsx')) and mount.get('RW'):
                    raise SafetyError('원본 조회 마운트는 읽기 전용이어야 합니다.')
            env = item['Config'].get('Env') or []
            if any(not isinstance(value, str) or '=' not in value or '\n' in value or '\r' in value or '\x00' in value for value in env):
                raise SafetyError('환경 설정은 안전한 단일 행이어야 합니다.')
            keys = [value.split('=', 1)[0] for value in env]
            if len(keys) != len(set(keys)) or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) for key in keys):
                raise SafetyError('중복되거나 잘못된 환경 설정입니다.')
            result[name] = item
        return project, result

    def _image_archive(self, identifiers):
        # 2026-10-19 hoyeon.han: classic config ID와 containerd OCI manifest ID를 모두 실제 해시 체인으로 검증합니다.
        metadata, configs = {}, {}
        # 2026-10-20 hoyeon.han: 잘못된 JSON·descriptor 자료형을 비밀 원문 없는 검증 오류로 통일합니다.
        def read_json(payload, expected):
            try:
                value = json.loads(payload)
            except (ValueError, UnicodeError) as exc:
                raise SafetyError('이미지 메타데이터의 JSON 형식이 다릅니다.') from exc
            if not isinstance(value, expected):
                raise SafetyError('이미지 메타데이터의 자료형이 다릅니다.')
            return value

        def reference(value):
            if not isinstance(value, dict):
                raise SafetyError('OCI 참조 descriptor의 자료형이 다릅니다.')
            digest, size = value.get('digest'), value.get('size')
            if (not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest)
                    or type(size) is not int or size < 0):
                raise SafetyError('OCI 참조 descriptor의 식별자·크기가 다릅니다.')
            return digest, size

        with _manual_tar(self.backup_dir / 'images.tar', MANUAL_MAX_IMAGES) as (archive, members):
            # 2026-10-20 hoyeon.han: 목록·Config 구조를 검사한 뒤 실행 플랫폼 집합을 만듭니다.
            # records = json.loads(_manual_read(archive, members, 'manifest.json', 4 * 1024 ** 2))
            records = read_json(_manual_read(archive, members, 'manifest.json', 4 * 1024 ** 2), list)
            if not isinstance(records, list) or not records:
                raise SafetyError('Docker save manifest가 없습니다.')
            for entry in records:
                # config = _manual_read(archive, members, _manual_name(entry['Config']), 8 * 1024 ** 2)
                # config_id = 'sha256:' + hashlib.sha256(config).hexdigest(); info = json.loads(config)
                if not isinstance(entry, dict): raise SafetyError('Docker save 항목의 자료형이 다릅니다.')
                config = _manual_read(archive, members, _manual_name(entry.get('Config')), 8 * 1024 ** 2)
                config_id = 'sha256:' + hashlib.sha256(config).hexdigest(); info = read_json(config, dict)
                if not isinstance(info.get('rootfs', {}), dict): raise SafetyError('이미지 rootfs 형식이 다릅니다.')
                layers = entry.get('Layers', []); digests = info.get('rootfs', {}).get('diff_ids', [])
                if not isinstance(layers, list) or not isinstance(digests, list):
                    raise SafetyError('이미지 계층 목록의 자료형이 다릅니다.')
                if len(layers) != len(digests): raise SafetyError('이미지 계층 목록이 다릅니다.')
                raw_layers = []
                for layer, expected in zip(layers, digests):
                    member = members.get(_manual_name(layer))
                    if member is None or not member.isfile(): raise SafetyError('이미지 계층 일반 파일이 없습니다.')
                    with archive.extractfile(member) as stream:
                        raw_digest, count = hashlib.sha256(), 0
                        prefix = stream.read(2); stream.seek(0)
                        while True:
                            block = stream.read(1024 * 1024)
                            if not block: break
                            raw_digest.update(block); count += len(block)
                        if count != member.size: raise SafetyError('이미지 계층 크기가 다릅니다.')
                        raw_layers.append(('sha256:' + raw_digest.hexdigest(), count)); stream.seek(0)
                        selected = gzip.GzipFile(fileobj=stream) if prefix == b'\x1f\x8b' else stream
                        digest, count = hashlib.sha256(), 0
                        while True:
                            block = selected.read(1024 * 1024)
                            if not block: break
                            count += len(block)
                            if count > MANUAL_MAX_IMAGES: raise SafetyError('이미지 계층 확장 크기를 초과했습니다.')
                            digest.update(block)
                        if selected is not stream: selected.close()
                    if 'sha256:' + digest.hexdigest() != expected: raise SafetyError('이미지 계층 내용 해시가 다릅니다.')
                # if not info.get('architecture') or info.get('os') != 'linux': raise SafetyError('지원하지 않는 이미지 플랫폼입니다.')
                if not isinstance(info.get('architecture'), str) or not info['architecture'] or info.get('os') != 'linux':
                    raise SafetyError('지원하지 않는 이미지 플랫폼입니다.')
                record = {'architecture': info['architecture'], 'os': info['os'], 'size': len(config), 'layers': raw_layers}
                if config_id in configs and configs[config_id] != record: raise SafetyError('이미지 Config가 중복되며 내용이 다릅니다.')
                configs[config_id] = record
            used = set()
            # 2026-10-20 hoyeon.han: variant나 태그 대신 실제 검증한 실행 Config의 OS·architecture만 기준으로 삼습니다.
            platforms = {(value['os'], value['architecture']) for value in configs.values()}
            def resolve(identifier, seen):
                if identifier in seen or len(seen) > 4: raise SafetyError('OCI 이미지 참조가 순환합니다.')
                if identifier in configs: return identifier
                if not re.fullmatch(r'sha256:[a-f0-9]{64}', identifier): raise SafetyError('OCI 이미지 식별자가 다릅니다.')
                value = _manual_read(archive, members, 'blobs/sha256/' + identifier[7:], 8 * 1024 ** 2)
                if 'sha256:' + hashlib.sha256(value).hexdigest() != identifier: raise SafetyError('OCI manifest 내용 해시가 다릅니다.')
                # descriptor = json.loads(value)
                descriptor = read_json(value, dict)
                if descriptor.get('schemaVersion') != 2: raise SafetyError('OCI manifest 형식을 지원하지 않습니다.')
                if 'manifests' in descriptor:
                    resolved = []
                    if not isinstance(descriptor['manifests'], list):
                        raise SafetyError('OCI 하위 manifest 목록의 자료형이 다릅니다.')
                    for child in descriptor['manifests']:
                        # 2026-10-20 hoyeon.han: Docker save가 생략한 비실행 플랫폼은 descriptor 검증 후에만 제외합니다.
                        # child_id = child.get('digest', '')
                        # if not re.fullmatch(r'sha256:[a-f0-9]{64}', child_id): raise SafetyError('OCI 하위 식별자가 다릅니다.')
                        # payload = _manual_read(archive, members, 'blobs/sha256/' + child_id[7:], 8 * 1024 ** 2)
                        # if child.get('size') != len(payload) or 'sha256:' + hashlib.sha256(payload).hexdigest() != child_id:
                        #     raise SafetyError('OCI 하위 manifest의 크기·해시가 다릅니다.')
                        # platform = child.get('platform') or {}
                        # if child.get('annotations', {}).get('vnd.docker.reference.type') == 'attestation-manifest':
                        #     if platform.get('os') != 'unknown' or platform.get('architecture') != 'unknown':
                        #         raise SafetyError('OCI 증명 자료의 플랫폼이 다릅니다.')
                        #     continue
                        child_id, child_size = reference(child)
                        platform, annotations = child.get('platform', {}), child.get('annotations', {})
                        if not isinstance(platform, dict) or not isinstance(annotations, dict):
                            raise SafetyError('OCI 플랫폼·주석의 자료형이 다릅니다.')
                        if (any(key in platform and (not isinstance(platform[key], str) or not platform[key])
                                for key in ('os', 'architecture'))
                                or any(not isinstance(key, str) or not isinstance(value, str) for key, value in annotations.items())):
                            raise SafetyError('OCI 플랫폼·주석의 값이 다릅니다.')
                        pair = (platform.get('os'), platform.get('architecture'))
                        attestation = annotations.get('vnd.docker.reference.type') == 'attestation-manifest'
                        if attestation and pair != ('unknown', 'unknown'):
                            raise SafetyError('OCI 증명 자료의 플랫폼이 다릅니다.')
                        foreign = all(pair) and 'unknown' not in pair and pair not in platforms
                        blob_name = 'blobs/sha256/' + child_id[7:]
                        if blob_name not in members and (foreign or attestation):
                            continue
                        payload = _manual_read(archive, members, blob_name, 8 * 1024 ** 2)
                        if child_size != len(payload) or 'sha256:' + hashlib.sha256(payload).hexdigest() != child_id:
                            raise SafetyError('OCI 하위 manifest의 크기·해시가 다릅니다.')
                        if foreign or attestation:
                            continue
                        selected = resolve(child_id, seen | {identifier})
                        if platform and (platform.get('architecture') != configs[selected]['architecture'] or platform.get('os') != configs[selected]['os']):
                            raise SafetyError('OCI 실행 플랫폼과 Config가 다릅니다.')
                        resolved.append(selected)
                    if len(resolved) != 1: raise SafetyError('단일 실행 플랫폼의 OCI 백업만 지원합니다.')
                    return resolved[0]
                # 2026-10-20 hoyeon.han: 선택된 실행 manifest의 Config·계층도 bool 크기를 포함한 잘못된 descriptor를 거절합니다.
                # config = descriptor.get('config') or {}; config_id = config.get('digest')
                # if config_id not in configs or config.get('size') != configs[config_id]['size']:
                config_id, config_size = reference(descriptor.get('config'))
                if config_id not in configs or config_size != configs[config_id]['size']:
                    raise SafetyError('OCI manifest의 Config 연결이 다릅니다.')
                # if [(layer.get('digest'), layer.get('size')) for layer in descriptor.get('layers', [])] != configs[config_id]['layers']:
                if not isinstance(descriptor.get('layers', []), list): raise SafetyError('OCI manifest 계층 목록의 자료형이 다릅니다.')
                if [reference(layer) for layer in descriptor.get('layers', [])] != configs[config_id]['layers']:
                    raise SafetyError('OCI manifest의 계층 연결이 다릅니다.')
                return config_id
            for identifier in identifiers:
                config_id = resolve(identifier, set()); used.add(config_id)
                metadata[identifier] = {key: configs[config_id][key] for key in ('architecture', 'os')}
            if used != set(configs): raise SafetyError('실행 이미지와 관계없는 이미지가 묶음에 있습니다.')
        return metadata

    @contextmanager
    def _application(self):
        with tempfile.TemporaryDirectory(prefix='sollume-manual-check-') as temporary:
            root = Path(temporary)
            with _manual_tar(self.backup_dir / 'application.tar.gz', MANUAL_MAX_APP) as (archive, members):
                required = ('.env', 'docker-compose.cloud.yml', 'database/users.db', 'database/customer_master.db')
                for name in required:
                    for parent in PurePosixPath(name).parents:
                        if str(parent) != '.' and str(parent) in members and not members[str(parent)].isdir():
                            raise SafetyError('필수 항목의 상위 압축 경로가 디렉토리가 아닙니다.')
                    file = root / name; file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    _atomic(file, _manual_read(archive, members, name, MANUAL_MAX_DB))
                for name in ('database/users.db', 'database/customer_master.db'):
                    for suffix in ('-wal', '-shm', '-journal'):
                        if name + suffix in members:
                            data = _manual_read(archive, members, name + suffix, MANUAL_MAX_DB)
                            if suffix == '-journal' and data:
                                raise SafetyError('실행 중 복사한 rollback journal은 지원하지 않습니다.')
                            if suffix == '-wal': _atomic(root / (name + suffix), data)
                    _manual_db(root / name)
                if _db_schema(root / 'database/users.db')['kind'] != 'legacy':
                    raise SafetyError('수동 백업 복구는 인증 도입 전 사용자 DB만 지원합니다.')
                env = _read_env(root / '.env')
                if not env.get('ORDER_API_KEY'):
                    raise SafetyError('백업의 API 키 설정을 확인할 수 없습니다.')
                yield root, env

    def _projection(self, item):
        host = item['HostConfig']
        return {'image': item['Image'], 'cmd': item['Config'].get('Cmd'), 'entrypoint': item['Config'].get('Entrypoint'),
                'working_dir': item['Config'].get('WorkingDir'), 'user': item['Config'].get('User'),
                'env': sorted(item['Config'].get('Env') or []), 'mounts': sorted(item.get('Mounts', []), key=lambda value: value['Destination']),
                'resources': {key: host.get(key, 0) for key in ('NanoCpus', 'Memory', 'MemoryReservation')},
                'readonly': host.get('ReadonlyRootfs'), 'tmpfs': host.get('Tmpfs') or {}, 'logging': host.get('LogConfig') or {}}

    def _assert_runtime(self, config, current):
        # 2026-10-19 hoyeon.han: inspect에서 복원한 엔트리포인트·작업경로·사용자·로그 정책도 검사합니다.
        super()._assert_runtime(config, current)
        for name, item in current.items():
            service = config['services'][name]
            if ((service.get('entrypoint') or []) != (item['Config'].get('Entrypoint') or [])
                    or (service.get('working_dir') or '/') != (item['Config'].get('WorkingDir') or '/')
                    or (service.get('user') or '') != (item['Config'].get('User') or '')):
                raise SafetyError('복원한 엔트리포인트·작업경로·실행 사용자가 다릅니다.')
            if service.get('logging'):
                actual = item['HostConfig'].get('LogConfig') or {}
                if (service['logging'].get('driver') != actual.get('Type') or
                        (service['logging'].get('options') or {}) != (actual.get('Config') or {})):
                    raise SafetyError('복원한 로그 제한 정책이 다릅니다.')

    def _check_current(self, records, root, env):
        project = next(iter(records.values()))['Config']['Labels']['com.docker.compose.project']
        current = self._containers(project, MANUAL_SERVICES)
        if any(self._projection(current[name]) != self._projection(item) for name, item in records.items()):
            raise SafetyError('현재 실행 이미지·명령·환경·마운트가 백업과 다릅니다. 새 수동 백업이 필요합니다.')
        current_env = self._environment()
        if current_env['ORDER_API_KEY'] != env['ORDER_API_KEY']:
            raise SafetyError('현재 API 키가 백업과 다릅니다. 새 백업을 준비하세요.')
        if _digest(self.compose_path) != _digest(root / 'docker-compose.cloud.yml'):
            raise SafetyError('현재 Compose 파일이 수동 백업과 다릅니다. 백업을 갱신하세요.')
        with tempfile.TemporaryDirectory(prefix='sollume-current-check-') as temporary:
            copy_path = Path(temporary) / 'users.db'
            _manual_live_copy(self.app_dir / 'database/users.db', copy_path)
            if _manual_security(copy_path) != _manual_security(root / 'database/users.db'):
                raise SafetyError('현재 계정·비밀번호·역할·활성 상태가 백업과 다릅니다. 수동 백업을 갱신하세요.')

    def plan(self):
        hashes = self._sources(); project, records = self._inspect()
        metadata = self._image_archive({item['Image'] for item in records.values()})
        with self._application() as (root, env):
            security = _manual_security(root / 'database/users.db')
        if hashes != self._sources():
            raise SafetyError('검증 도중 수동 백업 원본이 변경되었습니다.')
        return {'backup_dir': str(self.backup_dir), 'project': project, 'secure': False, 'validated': True,
                'dry_run': True, 'source_hashes': hashes, 'user_security_fingerprint': security,
                'images': metadata, 'public_resume': False}

    def _prepared(self):
        pointer_path = self.backup_dir / 'manual-prepared.json'
        if pointer_path.is_symlink() or pointer_path.stat().st_mode & 0o077:
            raise SafetyError('수동 백업 준비 기록은 비공개 일반 파일이어야 합니다.')
        pointer = json.loads(pointer_path.read_text()); release = Path(pointer['release'])
        if not release.is_absolute() or release.is_symlink() or release.parent.resolve() != self.releases_dir.resolve():
            raise SafetyError('준비된 복구 지점의 경로가 다릅니다.')
        if _digest(release / 'manifest.json') != pointer['manifest_sha256']:
            raise SafetyError('수동 백업 준비 기록의 해시가 다릅니다.')
        manifest = json.loads((release / 'manifest.json').read_text()); seal = manifest.pop('hmac', None)
        key = self.secrets_dir / release.name / '.env.local'
        if key.is_symlink() or key.stat().st_mode & 0o077 or release.stat().st_mode & 0o077:
            raise SafetyError('수동 복구 지점의 비공개 권한이 다릅니다.')
        expected = hmac.new(key.read_bytes(), _canonical(manifest), hashlib.sha256).hexdigest()
        if not isinstance(seal, str) or not hmac.compare_digest(seal, expected):
            raise SafetyError('수동 백업 검증 manifest가 변경되었습니다.')
        if manifest.get('kind') != 'manual-legacy' or manifest.get('app_dir') != str(self.app_dir) or manifest.get('backup_dir') != str(self.backup_dir):
            raise SafetyError('수동 백업의 원래 앱·자료 경로가 다릅니다.')
        if manifest['source_hashes'] != self._sources():
            raise SafetyError('준비 이후 수동 백업 원본이 변경되었습니다.')
        for name, digest in manifest['checksums'].items():
            file = release / name
            if Path(name).name != name or file.is_symlink() or not file.is_file() or _digest(file) != digest:
                raise SafetyError('준비된 복구 파일의 내용이 다릅니다.')
        for name, digest in manifest['private_checksums'].items():
            file = self.secrets_dir / release.name / name
            if Path(name).name != name or file.is_symlink() or file.stat().st_mode & 0o077 or _digest(file) != digest:
                raise SafetyError('비공개 복구 설정이 변경되었습니다.')
        manifest['hmac'] = seal
        return release, manifest

    def prepare(self, check_current=False):
        summary = self.plan(); project, records = self._inspect()
        with self._application() as (root, env):
            if check_current: self._check_current(records, root, env)
            if (self.backup_dir / 'manual-prepared.json').exists():
                release, manifest = self._prepared()
                if check_current:
                    secret = self.secrets_dir / release.name
                    _atomic(secret / '.env.approval.local', json.dumps({'source_hashes': summary['source_hashes'], 'current_checked': True,
                                                                      'operator_uid': os.geteuid(), 'verified_at': self.clock().isoformat()}))
                    manifest['private_checksums']['.env.approval.local'] = _digest(secret / '.env.approval.local')
                    self._seal(release, manifest)
                    _atomic(self.backup_dir / 'manual-prepared.json', json.dumps({'release': str(release), 'manifest_sha256': _digest(release / 'manifest.json')}) + '\n')
                return {**summary, 'release': str(release), 'prepared': True, 'reused': True, 'checked_current': check_current}
            release, secret = self._new_release(None)
            services = {}
            for name, item in records.items():
                host = item['HostConfig']; service_env = dict(value.split('=', 1) for value in item['Config'].get('Env') or [])
                raw_name = '.env.manual.' + name + '.local'
                _atomic(secret / raw_name, ''.join(key + '=' + value + '\n' for key, value in service_env.items()))
                mounts = [{'type': 'bind', 'source': entry['Source'], 'target': entry['Destination'], 'read_only': not entry['RW']}
                          for entry in item['Mounts'] if entry['Type'] == 'bind']
                service = {'image': item['Image'], 'pull_policy': 'never', 'command': [part.replace('$', '$$') for part in item['Config'].get('Cmd') or []],
                           'entrypoint': [part.replace('$', '$$') for part in item['Config']['Entrypoint']] if item['Config'].get('Entrypoint') is not None else None,
                           'working_dir': (item['Config'].get('WorkingDir') or '/app').replace('$', '$$'), 'user': item['Config'].get('User') or '',
                           'ports': [{'host_ip': '127.0.0.1', 'target': SERVICES[name], 'published': str(EXPECTED_PUBLISHED_PORTS[name])}],
                           'volumes': mounts, 'env_file': [{'path': str(secret / raw_name), 'format': 'raw'}],
                           'read_only': bool(host.get('ReadonlyRootfs')), 'tmpfs': [key + (':' + value if value else '') for key, value in (host.get('Tmpfs') or {}).items()],
                           'security_opt': ['no-new-privileges:true'], 'restart': 'unless-stopped',
                           'deploy': {'resources': {'limits': {'cpus': str(host.get('NanoCpus', 0) / 1e9), 'memory': str(int(host.get('Memory', 0)))},
                                                    'reservations': {'memory': str(int(host.get('MemoryReservation', 0)))}}},
                           'healthcheck': {'test': ['CMD', 'curl', '-f', 'http://localhost:' + str(SERVICES[name]) + ('/health' if name == 'sollume-api' else '/_stcore/health')],
                                           'interval': '5s', 'timeout': '10s', 'retries': 5, 'start_period': '10s'}}
                if host.get('LogConfig', {}).get('Type'):
                    service['logging'] = {'driver': host['LogConfig']['Type'], 'options': host['LogConfig'].get('Config') or {}}
                if name == 'sollume-api': service['environment'] = {'ORDER_API_KEY': '${ORDER_API_KEY:?현재 API 키가 필요합니다}'}
                services[name] = service
            config = {'name': project, 'services': services}
            _atomic(release / 'compose.json', json.dumps(config, ensure_ascii=False, indent=2) + '\n')
            _sqlite_backup(root / 'database/users.db', release / 'users.db')
            _sqlite_backup(root / 'database/customer_master.db', release / 'customer_master.db')
            _atomic(secret / '.env', (root / '.env').read_bytes()); _atomic(secret / '.env.local', secrets.token_bytes(32))
            _atomic(secret / '.env.approval.local', json.dumps({'source_hashes': summary['source_hashes'], 'current_checked': check_current,
                                                              'operator_uid': os.geteuid(), 'verified_at': self.clock().isoformat()}))
            manifest = {'version': 1, 'kind': 'manual-legacy', 'id': release.name, 'app_dir': str(self.app_dir), 'backup_dir': str(self.backup_dir),
                        'project': project, 'secure': False, 'source_hashes': summary['source_hashes'], 'images': summary['images'],
                        'services': {name: {'image_id': item['Image']} for name, item in records.items()},
                        'user_security_fingerprint': summary['user_security_fingerprint'], 'checksums': self._checksums(release),
                        'private_checksums': {file.name: _digest(file) for file in secret.iterdir() if file.name != '.env.local'},
                        'created_at': self.clock().isoformat()}
            if summary['source_hashes'] != self._sources():
                raise SafetyError('준비 도중 수동 백업 원본이 변경되었습니다.')
            self._seal(release, manifest)
            _atomic(self.backup_dir / 'manual-prepared.json', json.dumps({'release': str(release), 'manifest_sha256': _digest(release / 'manifest.json')}) + '\n')
        return {**summary, 'release': str(release), 'prepared': True, 'reused': False, 'checked_current': check_current}

    def _write_manual_nginx(self, content, layout):
        # 2026-10-19 hoyeon.han: 명시한 각 회계 사이트만 원래 심볼릭 링크 관계를 유지하여 교체합니다.
        entry = Path(layout['path']); target = Path(layout['real_path'])
        if entry not in self.sites or target != entry.resolve():
            raise SafetyError('승인한 회계 사이트 경로가 아닙니다.')
        _atomic(target, content, 0o644)
        if layout['link_target'] is not None and os.readlink(entry) != layout['link_target']:
            raise SafetyError('사이트 링크가 변경되었습니다.')
        self.runner.run(['sudo', '-n', 'nginx', '-t'])
        self.runner.run(['sudo', '-n', 'systemctl', 'reload', 'nginx'])

    def _blocked_sites(self, apply=False):
        if not self.sites or len({site.resolve() for site in self.sites}) != len(self.sites):
            raise SafetyError('모든 회계 Nginx 진입점을 중복 없이 지정하세요.')
        dump = self.runner.run(['sudo', '-n', 'nginx', '-T'])
        sections = re.split(r'(?m)^# configuration file (.+):\s*$', dump)
        if len(sections) < 3:
            raise SafetyError('Nginx 전체 설정의 파일 경계를 확인할 수 없습니다.')
        accounted = {site.resolve() for site in self.sites}
        for index in range(1, len(sections), 2):
            active = shlex.shlex(sections[index + 1], posix=False, punctuation_chars='{};')
            active.whitespace_split = True; active.commenters = '#'; values = list(active)
            for offset, token in enumerate(values):
                if token == 'proxy_pass' and offset + 1 < len(values) and '$' in values[offset + 1]:
                    raise SafetyError('변수로 결정되는 proxy_pass는 전체 회계 진입점을 확정할 수 없어 지원하지 않습니다.')
            if any(any(int(match) in set(SERVICES.values()) for match in re.findall(r':([0-9]+)(?=[/;?]|$)', token.strip('\"\''))) for token in values):
                if Path(sections[index]).resolve() not in accounted:
                    raise SafetyError('지정하지 않은 Nginx 사이트가 회계 서비스로 연결됩니다.')
        plans, writes = [], []
        for site in self.sites:
            content = site.read_text(); lexer = shlex.shlex(content, posix=False, punctuation_chars='{};')
            lexer.whitespace_split = True; lexer.commenters = '#'; tokens = []
            for token in lexer: tokens.extend(token if set(token) <= set('{};') else [token])
            blocks, index, prefix, local_plans = [], 0, [], []
            all_hosts = []
            while index < len(tokens):
                start = index
                if tokens[index:index + 2] != ['server', '{']:
                    if tokens[index] not in ('map', 'limit_req_zone'):
                        raise SafetyError('회계 전용 server/map/요청제한 설정만 지원합니다.')
                    depth = 0
                    while index < len(tokens):
                        depth += (tokens[index] == '{') - (tokens[index] == '}')
                        index += 1
                        if depth == 0 and tokens[index - 1] in (';', '}'): break
                    if depth or index == start:
                        raise SafetyError('Nginx 공통 지시문 경계가 다릅니다.')
                    prefix.append(' '.join(tokens[start:index]) + '\n'); continue
                level, end = 1, index + 2
                while end < len(tokens) and level:
                    level += (tokens[end] == '{') - (tokens[end] == '}'); end += 1
                if level: raise SafetyError('Nginx server 경계가 다릅니다.')
                body = tokens[index + 2:end - 1]; directives = []; depth = 0; start = 0
                for offset, token in enumerate(body):
                    if token == '{': depth += 1
                    elif token == '}': depth -= 1; start = offset + 1 if depth == 0 else start
                    elif token == ';' and depth == 0:
                        directive = body[start:offset]; start = offset + 1
                        if directive and directive[0] in ('listen', 'server_name', 'ssl_certificate', 'ssl_certificate_key', 'ssl_protocols'):
                            directives.append(directive)
                listens = [value[1:] for value in directives if value[0] == 'listen']
                hosts = [part.strip('"\'') for value in directives if value[0] == 'server_name' for part in value[1:]]
                if not listens or not hosts or any(host not in MANUAL_DOMAINS | {'_'} for host in hosts):
                    raise SafetyError('회계 사이트의 실제 DNS 이름·listen을 확인할 수 없습니다.')
                all_hosts.extend(host for host in hosts if host != '_')
                # 2026-10-19 hoyeon.han: 원본 location/root/alias/include는 복사하지 않고 고정 ACME 경로만 재생성합니다.
                # blocks.append('server {\n' + ''.join(' '.join(value) + ';\n' for value in directives) +
                #               'add_header Cache-Control no-store always; return 503;\n}\n')
                http_acme = ('office1.sollumeesthe.com' in hosts and
                             any(value[0].rsplit(':', 1)[-1] == '80' and 'ssl' not in value for value in listens))
                if http_acme and (hosts != ['office1.sollumeesthe.com'] or
                                  any(value[0].rsplit(':', 1)[-1] != '80' or 'ssl' in value for value in listens)):
                    raise SafetyError('office1 인증서 갱신용 HTTP server는 다른 도메인·HTTPS와 분리해야 합니다.')
                denied = 'add_header Cache-Control no-store always; return 503;\n'
                if http_acme:
                    denied = ('location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; '
                              'default_type text/plain; try_files $uri =404; }\n'
                              'location / { ' + denied + '}\n')
                blocks.append('server {\n' + ''.join(' '.join(value) + ';\n' for value in directives) + denied + '}\n')
                local_plans.append((hosts, listens)); index = end
            if not blocks or not all_hosts:
                raise SafetyError('차단할 회계 도메인을 확인할 수 없습니다.')
            plans.extend(([host for host in hosts if host != '_'] or sorted(set(all_hosts)), listens)
                         for hosts, listens in local_plans)
            layout = {'path': str(site), 'real_path': str(site.resolve()), 'link_target': os.readlink(site) if site.is_symlink() else None}
            writes.append((''.join(prefix + blocks), layout))
        if apply:
            for content, layout in writes: self._write_manual_nginx(content, layout)
        return plans

    def _confirm_blocked(self, plans):
        for hosts, listens in plans:
            for host in hosts:
                for listen in listens:
                    port_text = listen[0].rsplit(':', 1)[-1]
                    if not port_text.isdigit(): raise SafetyError('Nginx 포트를 확인할 수 없습니다.')
                    port = int(port_text); https = 'ssl' in listen or port == 443
                    origin = ('https://' if https else 'http://') + host + ((':' + str(port)) if port not in (80, 443) else '')
                    deadline, matched = time.monotonic() + 5, 0
                    while True:
                        if https:
                            status = self.runner.https_status(origin, '/')
                        else:
                            status = self.runner.http_status(origin, '/')
                        matched = matched + 1 if status == 503 else 0
                        remaining = deadline - time.monotonic()
                        if matched >= 3 and remaining >= 0: break
                        if remaining <= 0: raise SafetyError('전체 회계 도메인의 외부 503을 확인하지 못했습니다.')
                        time.sleep(min(0.2, remaining))

    def _restore_manual_users(self, release, latest):
        # 2026-10-19 hoyeon.han: 최근 추가 계정도 삭제하지 않고 비활성으로 보관하며 동일성 충돌은 교체 전에 거절합니다.
        def rows(path):
            with closing(sqlite3.connect('file:' + quote(str(path)) + '?mode=ro&immutable=1', uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                return {row['id']: dict(row) for row in conn.execute('SELECT * FROM users')}
        old, current = rows(release / 'users.db'), rows(latest)
        names = {row['username']: identifier for identifier, row in old.items()}
        for identifier, row in current.items():
            if (identifier in old and old[identifier]['username'] != row['username'] or
                    row['username'] in names and names[row['username']] != identifier):
                raise SafetyError('최근 계정의 ID·아이디가 백업과 충돌합니다. DB 교체 전에 새 백업을 준비하세요.')
        required = self._legacy_users(release, latest)
        with closing(sqlite3.connect(self.app_dir / 'database/users.db')) as conn, conn:
            columns = [row[1] for row in conn.execute('PRAGMA table_info(users)')]
            for identifier, row in current.items():
                if identifier in old: continue
                selected = [key for key in columns if key in row]
                if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) for key in selected):
                    raise SafetyError('지원하지 않는 사용자 열 이름입니다.')
                values = {key: row[key] for key in selected}; values['is_active'] = 0; values['is_admin'] = 0
                conn.execute('INSERT INTO users (' + ','.join(selected) + ') VALUES (' + ','.join('?' for key in selected) + ')',
                             [values[key] for key in selected])
                if row['is_active']: required.append(identifier)
        return required

    def rollback(self, apply=False, legacy_private=False, restore_users=False):
        summary = self.plan()
        if not apply: return summary
        if not (legacy_private and restore_users):
            raise SafetyError('수동 구버전 복구는 --legacy-private --restore-users 모두 필요합니다.')
        release, manifest = self._prepared()
        self._environment()
        current = self._containers(manifest['project'], set(SERVICES), require_complete=False)
        self._blocked_sites(False)
        # 2026-10-19 hoyeon.han: raw env_file 지원·현재 키·마운트를 변경 시작 전에 실제 Compose로 검증합니다.
        self._validate_compose(self._render(release / 'compose.json', manifest['project']))
        receipt = {'operation': 'manual-rollback', 'release': str(release), 'completed': False, 'public_resume': False, 'stage': 'preserve_current'}
        rescue = None
        try:
            rescue, secret = self._new_release(None); receipt['recovery_release'] = str(rescue)
            _atomic(secret / '.env', (self.app_dir / '.env').read_bytes()); _atomic(secret / '.env.local', secrets.token_bytes(32))
            _atomic(secret / '.env.compose.local', self.compose_path.read_bytes())
            _atomic(secret / '.env.containers.local', json.dumps(list(current.values()), ensure_ascii=False))
            layouts = []
            for index, site in enumerate(self.sites):
                name = '.env.nginx-' + str(index) + '.local'
                _atomic(secret / name, site.read_bytes())
                layouts.append({'path': str(site), 'real_path': str(site.resolve()), 'link_target': os.readlink(site) if site.is_symlink() else None, 'private_file': name})
            self._backup_data(rescue)
            def seal_rescue():
                self._seal(rescue, {'version': 1, 'kind': 'manual-rescue', 'id': rescue.name, 'app_dir': str(self.app_dir), 'recoverable': False,
                                   'nginx_layouts': layouts, 'checksums': self._checksums(rescue),
                                   'private_checksums': {file.name: _digest(file) for file in secret.iterdir() if file.name != '.env.local'},
                                   'created_at': self.clock().isoformat()})
            seal_rescue()
            receipt['stage'] = 'block_ingress'
            plans = self._blocked_sites(True); self._confirm_blocked(plans)
            receipt['stage'] = 'stop_writers'
            identifiers = [item['Id'] for item in current.values()]
            if identifiers:
                self.runner.run(['docker', 'stop', *identifiers]); self.runner.run(['docker', 'rm', *identifiers])
            if self._containers(manifest['project'], set(SERVICES), require_complete=False):
                raise SafetyError('회계 서비스 writer를 모두 중지하지 못했습니다.')
            for name in ('users.db', 'customer_master.db'):
                with closing(sqlite3.connect(self.app_dir / 'database' / name)) as conn:
                    if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]: raise SafetyError('최신 DB WAL 정리가 실패했습니다.')
            self._backup_data(rescue)
            seal_rescue()
            receipt['stage'] = 'load_images'
            self.runner.run(['docker', 'image', 'load', '--input', str(self.backup_dir / 'images.tar')])
            for image, info in manifest['images'].items():
                loaded = json.loads(self.runner.run(['docker', 'image', 'inspect', image]))[0]
                if loaded['Id'] != image or loaded['Architecture'] != info['architecture'] or loaded['Os'] != info['os']:
                    raise SafetyError('복구 이미지 ID 또는 플랫폼이 다릅니다.')
            receipt['stage'] = 'legacy_users'
            receipt['password_reset_required_ids'] = self._restore_manual_users(release, rescue / 'users.db')
            _atomic(self.compose_path, (release / 'compose.json').read_bytes())
            receipt['stage'] = 'start_legacy'
            self._run_compose(manifest['project'], 'up', '-d', '--pull', 'never', '--no-build', '--wait', '--wait-timeout', '120')
            started = self._containers(manifest['project'], MANUAL_SERVICES)
            self._assert_runtime(self._render(self.compose_path, manifest['project']), started)
            if any(started[name]['Image'] != value['image_id'] for name, value in manifest['services'].items()): raise SafetyError('실제 복구 이미지가 다릅니다.')
            self._confirm_blocked(plans)
            receipt.update(completed=True, stage='completed', maintenance_confirmed=True)
            self._receipt(release, receipt)
            return {'release': str(release), 'recovery_release': str(rescue), 'completed': True, 'public_resume': False}
        except BaseException as exc:
            receipt.update(failed=True, manual_recovery_required=True)
            try:
                self._confirm_blocked(self._blocked_sites(True)); receipt['maintenance_confirmed'] = True
            except BaseException:
                receipt['maintenance_confirmed'] = False
            # 2026-10-19 hoyeon.han: 기존 공개 8501 바인딩도 차단하므로 503 성공 여부와 무관하게 회계 writer를 중지합니다.
            try:
                remaining = self._containers(manifest['project'], set(SERVICES), require_complete=False)
                if remaining: self.runner.run(['docker', 'stop', *[item['Id'] for item in remaining.values()]])
            except BaseException:
                receipt['manual_access_block_required'] = True
            self._receipt(release, receipt)
            raise SafetyError('수동 백업 복구에 실패했습니다. 외부 차단과 비공개 복구 기록을 확인하세요.') from exc

    def password(self, username, apply=False):
        release, manifest = self._prepared()
        receipt = json.loads((release / 'rollback-receipt.json').read_text()); stored = receipt.pop('hmac', None)
        seal = (self.secrets_dir / release.name / '.env.local').read_bytes()
        if not isinstance(stored, str) or not hmac.compare_digest(stored, hmac.new(seal, _canonical(receipt), hashlib.sha256).hexdigest()):
            raise SafetyError('수동 복구 완료 기록이 변경되었습니다.')
        if not receipt.get('completed') or receipt.get('public_resume') or receipt.get('operation') != 'manual-rollback':
            raise SafetyError('비공개 수동 복구가 완료된 뒤 계정을 재설정하세요.')
        rescue = Path(receipt['recovery_release'])
        if not rescue.is_absolute() or rescue.is_symlink() or rescue.parent.resolve() != self.releases_dir.resolve():
            raise SafetyError('최근 계정 보관본의 경로가 다릅니다.')
        saved = json.loads((rescue / 'manifest.json').read_text()); signature = saved.pop('hmac', None)
        key = (self.secrets_dir / rescue.name / '.env.local').read_bytes()
        if not isinstance(signature, str) or not hmac.compare_digest(signature, hmac.new(key, _canonical(saved), hashlib.sha256).hexdigest()):
            raise SafetyError('최근 계정 보관본이 변경되었습니다.')
        if _digest(rescue / 'users.db') != saved['checksums']['users.db']:
            raise SafetyError('최근 사용자 DB 보관본이 변경되었습니다.')
        def lookup(path):
            with closing(sqlite3.connect('file:' + quote(str(path)) + '?mode=ro&immutable=1', uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute('SELECT id,username,password_hash,is_active,is_admin FROM users WHERE username=?', (username,)).fetchone()
                return dict(row) if row else None
        latest = lookup(rescue / 'users.db')
        with tempfile.TemporaryDirectory(prefix='sollume-password-check-') as temporary:
            copy_path = Path(temporary) / 'users.db'; _manual_live_copy(self.app_dir / 'database/users.db', copy_path)
            target = lookup(copy_path)
        if not latest or not target or latest['id'] != target['id'] or not latest['is_active']:
            raise SafetyError('최근 삭제·정지되었거나 동일성을 확인할 수 없는 계정은 복구할 수 없습니다.')
        if not target['is_active'] and target['id'] not in receipt.get('password_reset_required_ids', []):
            raise SafetyError('복구 후 별도로 정지된 계정은 비밀번호 재설정으로 활성화할 수 없습니다.')
        current = self._containers(manifest['project'], MANUAL_SERVICES)
        if any(current[name]['Image'] != value['image_id'] for name, value in manifest['services'].items()):
            raise SafetyError('현재 실행 이미지가 수동 복구 이미지와 다릅니다.')
        self._confirm_blocked(self._blocked_sites(False))
        if not apply: return {'dry_run': True, 'validated': True, 'public_resume': False, 'account_id': target['id']}
        if not sys.stdin.isatty(): raise SafetyError('숨김 입력이 가능한 터미널에서 실행하세요.')
        password = getpass('새 비밀번호(12자 이상, UTF-8 72바이트 이하): ')
        if len(password) < 12 or len(password.encode()) > 72 or password != getpass('새 비밀번호 확인: '):
            raise SafetyError('비밀번호 길이·확인을 점검하세요.')
        try:
            receipt['password_reset_stage'] = 'generate_hash'
            image = manifest['services']['sollume-app']['image_id']
            encoded = self.runner.run(['docker', 'run', '--rm', '-i', '--pull', 'never', '--network', 'none', '--read-only',
                                      '--entrypoint', 'python', image, '-B', '-c',
                                      'import bcrypt,sys; print(bcrypt.hashpw(sys.stdin.buffer.read(),bcrypt.gensalt(rounds=12)).decode())'], input=password).strip()
            if not re.fullmatch(r'\$2[aby]\$12\$[./A-Za-z0-9]{53}', encoded): raise SafetyError('비밀번호 해시 생성이 실패했습니다.')
            receipt['password_reset_stage'] = 'stop_writers'
            identifiers = [item['Id'] for item in current.values()]
            self.runner.run(['docker', 'stop', *identifiers]); self.runner.run(['docker', 'rm', *identifiers])
            if self._containers(manifest['project'], set(SERVICES), require_complete=False):
                raise SafetyError('계정 수정 전 writer가 남아 있습니다.')
            with tempfile.TemporaryDirectory(prefix='sollume-password-recheck-') as temporary:
                copy_path = Path(temporary) / 'users.db'; _manual_live_copy(self.app_dir / 'database/users.db', copy_path)
                if lookup(copy_path) != target:
                    raise SafetyError('입력 대기 중 대상 계정이 변경되어 재설정을 중단합니다.')
            before = release / ('before-password-' + secrets.token_hex(8) + '.db')
            _sqlite_backup(self.app_dir / 'database/users.db', before)
            manifest['checksums'] = self._checksums(release); self._seal(release, manifest)
            _atomic(self.backup_dir / 'manual-prepared.json', json.dumps({'release': str(release), 'manifest_sha256': _digest(release / 'manifest.json')}) + '\n')
            receipt['password_reset_stage'] = 'update_account'
            with closing(sqlite3.connect(self.app_dir / 'database/users.db')) as conn, conn:
                changed = conn.execute('UPDATE users SET password_hash=?,is_active=1,is_admin=? WHERE id=? AND username=?',
                                       (encoded, int(bool(target['is_admin'] and latest['is_admin'])), target['id'], username)).rowcount
                if changed != 1: raise SafetyError('재설정할 기존 계정을 확인할 수 없습니다.')
            self._run_compose(manifest['project'], 'up', '-d', '--pull', 'never', '--no-build', '--wait', '--wait-timeout', '120')
            started = self._containers(manifest['project'], MANUAL_SERVICES)
            self._assert_runtime(self._render(self.compose_path, manifest['project']), started)
            if any(started[name]['Image'] != value['image_id'] for name, value in manifest['services'].items()):
                raise SafetyError('재설정 후 실제 이미지가 다릅니다.')
            self._confirm_blocked(self._blocked_sites(False))
            receipt['password_reset_required_ids'] = [value for value in receipt.get('password_reset_required_ids', []) if value != target['id']]
            receipt.update(password_reset_stage='completed', password_reset_account_id=target['id'])
            self._receipt(release, receipt)
            return {'completed': True, 'account_id': target['id'], 'public_resume': False}
        except BaseException as exc:
            receipt.update(password_reset_failed=True, manual_recovery_required=True)
            try: self._confirm_blocked(self._blocked_sites(True))
            except BaseException:
                try:
                    remaining = self._containers(manifest['project'], set(SERVICES), require_complete=False)
                    if remaining: self.runner.run(['docker', 'stop', *[item['Id'] for item in remaining.values()]])
                except BaseException: pass
            self._receipt(release, receipt)
            raise SafetyError('비밀번호 복구가 실패했습니다. 공개 차단을 유지하고 비공개 기록을 확인하세요.') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description='회계 시스템 비공개 오프라인 복구 준비·검증·실행')
    commands = parser.add_subparsers(dest='command', required=True)
    # 2026-10-19 hoyeon.han: 수동 백업은 기존 자동 snapshot과 구분된 CLI로만 처리합니다.
    # for name in ('capture', 'plan', 'rollback', 'legacy-password'):
    for name in ('capture', 'plan', 'rollback', 'legacy-password', 'manual-plan', 'manual-prepare', 'manual-rollback', 'manual-password'):
        command = commands.add_parser(name)
        command.add_argument('--app-dir', required=True)
        # command.add_argument('--nginx-config', required=True)
        # command.add_argument('--release', required=name != 'capture')
        if name.startswith('manual-'):
            command.add_argument('--backup-dir', required=True)
            command.add_argument('--nginx-config', action='append', default=[])
        else:
            command.add_argument('--nginx-config', required=True)
            command.add_argument('--release', required=name != 'capture')
        if name == 'manual-prepare':
            command.add_argument('--check-current', action='store_true')
        # if name in ('plan', 'rollback'):
        if name in ('plan', 'rollback', 'manual-rollback'):
            command.add_argument('--legacy-private', action='store_true')
            command.add_argument('--restore-users', action='store_true')
        # if name in ('rollback', 'legacy-password'):
        if name in ('rollback', 'legacy-password', 'manual-rollback', 'manual-password'):
            command.add_argument('--apply', action='store_true')
        # if name == 'legacy-password':
        if name in ('legacy-password', 'manual-password'):
            command.add_argument('--username', required=True)
    args = parser.parse_args(argv)
    if sys.prefix == sys.base_prefix:
        parser.error('명시적인 Python 가상환경으로 실행하세요.')
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        # manager = ReleaseManager(args.app_dir, args.nginx_config)
        # if args.command == 'capture':
        manager = (ManualBackupManager(args.app_dir, args.backup_dir, args.nginx_config) if args.command.startswith('manual-')
                   else ReleaseManager(args.app_dir, args.nginx_config))
        if args.command == 'manual-plan':
            result = manager.plan()
        elif args.command == 'manual-prepare':
            result = manager.prepare(args.check_current)
        elif args.command == 'manual-rollback':
            result = manager.rollback(args.apply, args.legacy_private, args.restore_users)
        elif args.command == 'manual-password':
            result = manager.password(args.username, args.apply)
        elif args.command == 'capture':
            result = manager.capture(args.release)
        elif args.command == 'plan':
            result = manager.plan(args.release, args.legacy_private, args.restore_users)
        elif args.command == 'rollback':
            result = manager.rollback(args.release, args.apply, args.legacy_private, args.restore_users)
        else:
            result = manager.legacy_password(args.release, args.username, args.apply)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print('작업을 중단했습니다. 변경을 시작했다면 비공개 복구 기록과 외부 차단 상태를 확인하세요.', file=sys.stderr)
        return 130
    # 2026-10-19 hoyeon.han: 잘못된 수동 백업 자료형도 원문 메타데이터 없이 실패합니다.
    # except (SafetyError, OSError, ValueError, sqlite3.Error, KeyError) as exc:
    except (SafetyError, OSError, ValueError, sqlite3.Error, KeyError, TypeError, IndexError, tarfile.TarError) as exc:
        # 예상하지 못한 JSON/경로 오류에도 설정이나 비밀값을 출력하지 않는다.
        print(str(exc) if isinstance(exc, SafetyError) else '복구 자료·권한·설정 검증에 실패했습니다.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
