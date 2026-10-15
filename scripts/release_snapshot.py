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
from contextlib import closing
from datetime import datetime, timezone
from getpass import getpass
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
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
APPROVED_NGINX_SHA256 = '628df0b4489d9bfccf1aec0e09e394d50d33bcb183f2ce19c3f027fc49be2820'


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
            if env.get('AUTH_PUBLIC_ORIGIN') != 'https://sollumeesthe.com':
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
            status = self.runner.https_status('https://sollumeesthe.com', path, headers)
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
        return ('# 2026-10-15 hoyeon.han: 복구 중 모든 외부 업무 요청을 차단한다.\n'
                'server { listen 80 default_server; server_name _; return 503; }\n'
                'server { listen 443 ssl default_server; server_name sollumeesthe.com;\n'
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
                if not self.runner.internal_health(SERVICES[name], host='sollumeesthe.com'):
                    raise SafetyError('복구 서비스의 내부 상태 검사가 실패했습니다.')
            if manifest['secure']:
                receipt['stage'] = 'restore_secure_nginx'
                for denied_path in ('/auth/check', '/downloads/' + '0' * 32):
                    if self.runner.internal_status(8503, denied_path, host='sollumeesthe.com',
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


def main(argv=None):
    parser = argparse.ArgumentParser(description='회계 시스템 비공개 오프라인 복구 준비·검증·실행')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('capture', 'plan', 'rollback', 'legacy-password'):
        command = commands.add_parser(name)
        command.add_argument('--app-dir', required=True)
        command.add_argument('--nginx-config', required=True)
        command.add_argument('--release', required=name != 'capture')
        if name in ('plan', 'rollback'):
            command.add_argument('--legacy-private', action='store_true')
            command.add_argument('--restore-users', action='store_true')
        if name in ('rollback', 'legacy-password'):
            command.add_argument('--apply', action='store_true')
        if name == 'legacy-password':
            command.add_argument('--username', required=True)
    args = parser.parse_args(argv)
    if sys.prefix == sys.base_prefix:
        parser.error('명시적인 Python 가상환경으로 실행하세요.')
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        manager = ReleaseManager(args.app_dir, args.nginx_config)
        if args.command == 'capture':
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
    except (SafetyError, OSError, ValueError, sqlite3.Error, KeyError) as exc:
        # 예상하지 못한 JSON/경로 오류에도 설정이나 비밀값을 출력하지 않는다.
        print(str(exc) if isinstance(exc, SafetyError) else '복구 자료·권한·설정 검증에 실패했습니다.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
