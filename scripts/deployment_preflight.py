#!/usr/bin/env python3
"""2026-10-20 hoyeon.han: 회계 배포 전후 Nginx·실제 게시 포트 읽기 전용 검사.

설정·DB·Docker를 변경하지 않으며 응답과 진단에 환경변수·키·설정 원문을 넣지 않는다.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import socket
import ssl
import subprocess
import sys
from urllib.parse import urlsplit

try:
    from release_snapshot import CommandRunner, SafetyError, _approved_nginx
except ModuleNotFoundError:
    # 2026-10-20 hoyeon.han: importlib로 독립 로딩한 로컬 시험에서도 같은 형제 모듈을 사용한다.
    _spec = importlib.util.spec_from_file_location('sollume_preflight_release_snapshot', Path(__file__).with_name('release_snapshot.py'))
    _release = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_release)
    CommandRunner, SafetyError, _approved_nginx = _release.CommandRunner, _release.SafetyError, _release._approved_nginx


OFFICE = 'office1.sollumeesthe.com'
LEGACY = {'sol-fin.duckdns.org', 'sollume-finance.duckdns.org'}
DOMAINS = LEGACY | {OFFICE}
SERVICES = {'sollume-app': 8501, 'sollume-api': 8502, 'sollume-auth': 8503}
PORTS = set(SERVICES.values())
DENIED = {403, 404, 410, 503}
DOWNLOAD = '/downloads/' + '0' * 32
WEBSOCKET = {'Connection': 'Upgrade', 'Upgrade': 'websocket', 'Sec-WebSocket-Version': '13',
             'Sec-WebSocket-Key': 'cHJlZmxpZ2h0LWNoZWNrIQ==', 'Origin': 'https://' + OFFICE}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _json(value, expected):
    try:
        decoded = json.loads(value)
    except (ValueError, UnicodeError) as exc:
        raise SafetyError('점검용 JSON 형식을 확인할 수 없습니다.') from exc
    if not isinstance(decoded, expected):
        raise SafetyError('점검용 JSON 자료형이 다릅니다.')
    return decoded


class ReadOnlyRunner(CommandRunner):
    def run(self, argv, **kwargs):
        # 2026-10-20 hoyeon.han: 무한 대기와 외부 명령의 비밀 stderr 출력을 막는다.
        try:
            return subprocess.run(list(argv), text=True, capture_output=True, check=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise SafetyError('읽기 전용 점검 명령이 실패하거나 제한 시간을 초과했습니다.') from exc

    def probe(self, origin, path, headers=None):
        parsed = urlsplit(origin)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        connection = None
        try:
            if parsed.scheme == 'https':
                context = ssl.create_default_context()
                connection = http.client.HTTPSConnection(parsed.hostname, port, timeout=10, context=context)
                connection.sock = context.wrap_socket(socket.create_connection(('127.0.0.1', port), timeout=10),
                                                       server_hostname=parsed.hostname)
            else:
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            connection.request('GET', path, headers={'Host': parsed.netloc, **(headers or {})})
            response = connection.getresponse()
            # 본문을 읽거나 리다이렉트를 따라가지 않아 회계자료가 진단 출력에 들어가지 않는다.
            return {'status': response.status, 'location': response.getheader('Location')}
        except (OSError, http.client.HTTPException):
            return {'status': 0, 'location': None}
        finally:
            if connection is not None:
                connection.close()


class Node:
    def __init__(self, name, args, children, owner):
        self.name, self.args, self.children, self.owner = name, args, children, owner


def _parse(text, owner):
    lexer = shlex.shlex(text, posix=True, punctuation_chars='{};')
    lexer.whitespace_split = True
    lexer.commenters = '#'
    try:
        tokens = []
        for token in lexer:
            tokens.extend(token if token and set(token) <= set('{};') else [token])
    except ValueError as exc:
        raise SafetyError('Nginx 지시문을 안전하게 해석할 수 없습니다.') from exc
    if len(tokens) > 300000:
        raise SafetyError('Nginx 점검 항목 제한을 초과했습니다.')
    position = 0

    def block(depth=0):
        nonlocal position
        if depth > 32:
            raise SafetyError('Nginx 블록 깊이 제한을 초과했습니다.')
        result = []
        while position < len(tokens):
            if tokens[position] == '}':
                if not depth:
                    raise SafetyError('Nginx 블록 경계가 다릅니다.')
                position += 1
                return result
            head = []
            while position < len(tokens) and tokens[position] not in ('{', '}', ';'):
                head.append(tokens[position]); position += 1
            if not head or position >= len(tokens) or tokens[position] == '}':
                raise SafetyError('Nginx 지시문 경계가 다릅니다.')
            terminal = tokens[position]; position += 1
            children = block(depth + 1) if terminal == '{' else None
            result.append(Node(head[0], head[1:], children, owner))
        if depth:
            raise SafetyError('Nginx 블록이 종료되지 않았습니다.')
        return result
    return block()


def _walk(nodes):
    for node in nodes:
        yield node
        if node.children is not None:
            yield from _walk(node.children)


def _listen(node):
    if not node.args:
        raise SafetyError('Nginx listen 주소가 없습니다.')
    endpoint = node.args[0]
    try:
        port = int(endpoint.rsplit(':', 1)[-1])
    except ValueError as exc:
        raise SafetyError('Nginx listen 포트를 확인할 수 없습니다.') from exc
    return port


def _target_port(value):
    """2026-10-20 hoyeon.han: HTTP·TCP 대상의 포트를 정수화하여 선행 0 우회도 검사한다."""
    try:
        if '://' in value:
            return urlsplit(value).port
        if value.startswith('unix:'):
            return None
        address, separator, port = value.rpartition(':')
        return int(port) if separator and address and port.isdigit() else None
    except (ValueError, TypeError) as exc:
        raise SafetyError('프록시 대상 포트를 안전하게 해석할 수 없습니다.') from exc


def _identity(path):
    try:
        source = path.lstat(); target = path.stat(); raw = path.read_bytes()
    except OSError as exc:
        raise SafetyError('선택한 Nginx 파일을 읽을 수 없습니다.') from exc
    if not path.is_file() or len(raw) > 8 * 1024 ** 2:
        raise SafetyError('선택한 Nginx 파일의 형식·크기가 다릅니다.')
    return {'path': str(path), 'real_path': str(path.resolve()), 'inode': source.st_ino, 'device': source.st_dev,
            'target_inode': target.st_ino, 'target_device': target.st_dev,
            'link': os.readlink(path) if path.is_symlink() else None, 'sha256': _sha(raw)}, raw.decode('utf-8')


class Preflight:
    def __init__(self, app_dir, sites, runner=None):
        if not Path(app_dir).is_absolute() or not sites or any(not Path(site).is_absolute() for site in sites):
            raise SafetyError('앱과 모든 Nginx 사이트의 절대 경로가 필요합니다.')
        self.app_dir = Path(app_dir).resolve()
        self.sites = [Path(os.path.abspath(site)) for site in sites]
        if len({path.resolve() for path in self.sites}) != len(self.sites):
            raise SafetyError('Nginx 사이트 경로가 중복되었습니다.')
        self.runner = runner or ReadOnlyRunner()
        self.state = {}

    def _configuration(self):
        dump = self.runner.run(['sudo', '-n', 'nginx', '-T'])
        if not isinstance(dump, str) or len(dump) > 32 * 1024 ** 2:
            raise SafetyError('Nginx 전체 설정을 확인할 수 없습니다.')
        parts = re.split(r'(?m)^# configuration file (.+):[ \t]*$', dump)
        if len(parts) < 3:
            raise SafetyError('Nginx 전체 설정의 파일 경계가 없습니다.')
        sections = {}
        for index in range(1, len(parts), 2):
            path = Path(parts[index]); text = parts[index + 1]
            if text.startswith('\n'):
                text = text[1:]
            if not path.is_absolute() or str(path) in sections:
                raise SafetyError('Nginx 전체 설정의 파일 경로가 다릅니다.')
            sections[str(path)] = {'text': text, 'nodes': _parse(text, str(path)), 'real': str(path.resolve())}
        identities = []
        for path in self.sites:
            identity, text = _identity(path)
            matching = [item for item in sections.values() if item['real'] == identity['real_path']]
            if len(matching) != 1 or matching[0]['text'].rstrip('\n') != text.rstrip('\n'):
                raise SafetyError('선택한 사이트가 비활성이거나 Nginx 조회 내용과 다릅니다.')
            identities.append(identity)
        return {'dump_sha256': _sha(dump.encode()), 'sites': identities, 'sections': sections}

    def _effective_nodes(self, configuration):
        sections = configuration['sections']
        main = next((name for name in sections if Path(name).name == 'nginx.conf'), None)
        prefix = Path(main).parent if main else Path('/etc/nginx')

        def targets(node):
            if len(node.args) != 1 or '$' in node.args[0]:
                raise SafetyError('동적으로 결정되는 Nginx include는 지원하지 않습니다.')
            pattern = str(Path(node.args[0]) if Path(node.args[0]).is_absolute() else prefix / node.args[0])
            matches = [name for name in sections if fnmatch.fnmatchcase(name, pattern)]
            if not matches and not any(char in pattern for char in '*?['):
                raise SafetyError('Nginx include 대상이 전체 설정에 없습니다.')
            return matches

        referenced = set()
        for item in sections.values():
            for node in _walk(item['nodes']):
                if node.name == 'include':
                    referenced.update(targets(node))
        roots = [main] if main else [name for name in sections if name not in referenced]
        if not roots:
            raise SafetyError('Nginx include 진입점을 확인할 수 없습니다.')
        count = 0

        def expand(nodes, seen):
            nonlocal count
            result = []
            for node in nodes:
                count += 1
                if count > 300000 or len(seen) > 32:
                    raise SafetyError('Nginx include 점검 제한을 초과했습니다.')
                if node.name == 'include':
                    for name in targets(node):
                        if name in seen:
                            raise SafetyError('Nginx include가 순환합니다.')
                        result.extend(expand(sections[name]['nodes'], seen | {name}))
                else:
                    children = expand(node.children, seen) if node.children is not None else None
                    result.append(Node(node.name, node.args, children, node.owner))
            return result
        result = []
        for name in roots:
            result.extend(expand(sections[name]['nodes'], {name}))
        return result

    @staticmethod
    def _action(node):
        if node.name != 'return' or node.children is not None or not node.args:
            raise SafetyError('기존 회계 주소의 업무 차단 지시문이 다릅니다.')
        if node.args[0] in ('301', '308') and node.args[1:] == ['https://' + OFFICE + '$request_uri']:
            return {'status': int(node.args[0]), 'redirect': True}
        if len(node.args) == 1 and node.args[0].isdigit() and int(node.args[0]) in DENIED:
            return {'status': int(node.args[0]), 'redirect': False}
        raise SafetyError('기존 회계 주소는 고정 office1 이동 또는 업무 차단만 허용합니다.')

    def _legacy(self, nodes):
        expected = {}
        for server in nodes:
            if server.name != 'server' or server.args or server.children is None:
                raise SafetyError('기존 회계 사이트는 전용 server 블록만 허용합니다.')
            directives = server.children
            names = [value for node in directives if node.name == 'server_name' for value in node.args]
            listens = [node for node in directives if node.name == 'listen']
            if not names or not set(names) <= LEGACY or not listens:
                raise SafetyError('기존 회계 사이트의 도메인·listen이 다릅니다.')
            ports = {_listen(node) for node in listens}
            if not ports <= {80, 443} or len(ports) != 1:
                raise SafetyError('기존 회계 HTTP·HTTPS server는 각각 분리해야 합니다.')
            if any(any(value not in ('ssl', 'http2') for value in node.args[1:]) for node in listens):
                raise SafetyError('기존 회계 listen의 추가 옵션은 지원하지 않습니다.')
            if any(('ssl' in node.args) != (_listen(node) == 443) for node in listens):
                raise SafetyError('기존 회계 HTTPS 인증서 연결을 확인하세요.')
            actions, acme = [], False
            for node in directives:
                if node.name in ('listen', 'server_name') and node.children is None:
                    continue
                if node.name in ('ssl_certificate', 'ssl_certificate_key') and node.children is None:
                    if len(node.args) != 1 or not Path(node.args[0]).is_absolute() or '$' in node.args[0]:
                        raise SafetyError('기존 회계 TLS 파일은 고정 절대 경로여야 합니다.')
                    continue
                if node.name == 'ssl_protocols' and node.children is None and set(node.args) <= {'TLSv1.2', 'TLSv1.3'}:
                    continue
                if node.name == 'add_header' and node.args == ['Cache-Control', 'no-store', 'always'] and node.children is None:
                    continue
                if node.name == 'return':
                    actions.append(self._action(node)); continue
                if node.name == 'location' and node.args == ['/'] and node.children is not None:
                    body = [child for child in node.children if not (child.name == 'add_header' and child.args == ['Cache-Control', 'no-store', 'always'] and child.children is None)]
                    if len(body) != 1:
                        raise SafetyError('기존 회계 업무 경로의 추가 지시문을 허용하지 않습니다.')
                    actions.append(self._action(body[0])); continue
                if node.name == 'location' and node.args == ['^~', '/.well-known/acme-challenge/'] and node.children is not None:
                    shape = [(child.name, child.args, child.children) for child in node.children]
                    if acme or ports != {80} or shape != [('root', ['/var/www/letsencrypt'], None), ('default_type', ['text/plain'], None), ('try_files', ['$uri', '=404'], None)]:
                        raise SafetyError('기존 회계 ACME 경로는 고정된 HTTP webroot만 허용합니다.')
                    acme = True; continue
                raise SafetyError('기존 회계 사이트에 프록시·include·파일 제공 등 미승인 지시문이 있습니다.')
            if len(actions) != 1:
                raise SafetyError('기존 회계 주소의 단일 업무 차단을 확인할 수 없습니다.')
            for host in names:
                key = (host, 'https' if ports == {443} else 'http')
                if key in expected:
                    raise SafetyError('기존 회계 도메인의 listen이 중복되었습니다.')
                expected[key] = actions[0]
        return expected

    def _ingress(self, configuration):
        sections = configuration['sections']
        primary = next(item for item in sections.values() if item['real'] == str(self.sites[0].resolve()))
        _approved_nginx(primary['text'])
        expected = {}
        for site in self.sites[1:]:
            item = next(item for item in sections.values() if item['real'] == str(site.resolve()))
            for key, action in self._legacy(item['nodes']).items():
                if key in expected:
                    raise SafetyError('기존 회계 도메인의 사이트가 중복되었습니다.')
                expected[key] = action
        if set(expected) != {(host, scheme) for host in LEGACY for scheme in ('http', 'https')}:
            raise SafetyError('기존 두 DuckDNS 주소의 HTTP·HTTPS 진입점을 모두 지정하세요.')
        effective = self._effective_nodes(configuration)
        selected = {str(path.resolve()) for path in self.sites}
        seen = set()
        protected_upstreams = set()
        for node in _walk(effective):
            # 2026-10-20 hoyeon.han: http 전역 satisfy any 상속은 access 허용으로 office1 인증 검사를 우회할 수 있다.
            # 무관한 다른 server 내부의 satisfy 정책에는 영향을 주지 않는다.
            if (node.name == 'http' and node.children is not None
                    and any(child.name == 'satisfy' and child.args == ['any'] for child in node.children)):
                raise SafetyError('Nginx http 전역 satisfy any는 office1 인증 검사를 우회할 수 있어 허용하지 않습니다.')
            # 2026-10-20 hoyeon.han: 전역 인증 오류 재정의가 office1의 401·403 응답 계약에 상속되지 않게 한다.
            if (node.name == 'http' and node.children is not None
                    and any(child.name == 'error_page' and any(arg.isdigit() and int(arg) in (401, 403) for arg in child.args)
                            for child in node.children)):
                raise SafetyError('Nginx http 전역의 401·403 error_page 재정의는 office1 응답 검증과 호환되지 않습니다.')
            if node.name == 'upstream' and node.children is not None:
                if len(node.args) != 1:
                    raise SafetyError('Nginx upstream 이름을 확인할 수 없습니다.')
                for child in node.children:
                    if child.name == 'server' and child.args and _target_port(child.args[0]) in PORTS:
                        protected_upstreams.add(node.args[0])
                if node.args[0] in protected_upstreams:
                    raise SafetyError('보호 포트를 가리키는 별도 upstream은 승인하지 않습니다.')
            if node.name == 'server' and node.children is not None:
                names = [name.lower().rstrip('.') for child in node.children if child.name == 'server_name'
                         for name in child.args if name.lower().rstrip('.') in DOMAINS]
                listens = [child for child in node.children if child.name == 'listen']
                for host in names:
                    for port in {_listen(child) for child in listens}:
                        key = (host, port)
                        if key in seen or str(Path(node.owner).resolve()) not in selected:
                            raise SafetyError('회계 도메인의 활성 server_name이 중복되거나 선택에서 누락되었습니다.')
                        seen.add(key)
            if node.name in ('proxy_pass', 'fastcgi_pass', 'uwsgi_pass', 'scgi_pass', 'grpc_pass'):
                if not node.args or '$' in node.args[0]:
                    raise SafetyError('동적 프록시는 전체 회계 진입점을 확정할 수 없어 지원하지 않습니다.')
                protected = _target_port(node.args[0]) in PORTS
                if protected and str(Path(node.owner).resolve()) != str(self.sites[0].resolve()):
                    raise SafetyError('선택한 인증 사이트 외에 보호 포트로 연결되는 경로가 있습니다.')
            if node.name in ('root', 'alias') and str(Path(node.owner).resolve()) != str(self.sites[0].resolve()):
                if len(node.args) != 1 or '$' in node.args[0]:
                    raise SafetyError('동적 파일 제공 경로의 회계자료 접근 여부를 확정할 수 없습니다.')
                root = Path(node.args[0]).resolve()
                protected_paths = [self.app_dir / name for name in ('database', 'processed', 'uploads', 'order_data')]
                if any(root.is_relative_to(path) or path.is_relative_to(root) for path in protected_paths):
                    raise SafetyError('다른 사이트가 회계자료 디렉토리를 직접 제공하고 있습니다.')
        if seen != {(host, port) for host in DOMAINS for port in (80, 443)}:
            raise SafetyError('세 회계 주소의 활성 HTTP·HTTPS 진입점을 모두 확인할 수 없습니다.')
        return expected

    @staticmethod
    def _compose(value):
        if isinstance(value, dict):
            config = _json(_canonical(value), dict)
        else:
            path = Path(value)
            if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 ** 2:
                raise SafetyError('후보 Compose JSON의 실제 절대 파일 경로가 필요합니다.')
            config = _json(path.read_bytes(), dict)
        services = config.get('services')
        if not isinstance(services, dict) or set(services) != set(SERVICES):
            raise SafetyError('후보 Compose는 회계앱·API·인증 세 서비스여야 합니다.')
        for name, port in SERVICES.items():
            service = services[name]
            if (not isinstance(service, dict) or service.get('network_mode') or service.get('privileged')
                    or service.get('pid') == 'host' or service.get('ipc') == 'host'
                    or service.get('cap_add') or service.get('devices') or service.get('device_requests') or service.get('volumes_from')):
                raise SafetyError('후보 Compose에 지원하지 않는 실행 권한·네트워크가 있습니다.')
            bindings = service.get('ports')
            if not isinstance(bindings, list) or len(bindings) != 1 or not isinstance(bindings[0], dict):
                raise SafetyError('후보 Compose에 추가 게시 포트가 있습니다.')
            binding = bindings[0]
            if (binding.get('host_ip') != '127.0.0.1' or str(binding.get('target')) != str(port)
                    or str(binding.get('published')) != str(port) or binding.get('protocol', 'tcp') != 'tcp'
                    or binding.get('mode', 'ingress') != 'ingress'):
                raise SafetyError('후보 Compose의 보호 포트는 정확한 루프백 TCP 연결이어야 합니다.')
        return config

    def _collect_runtime(self):
        ids = self.runner.run(['docker', 'ps', '-q']).split()
        if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[a-fA-F0-9]{12,64}', value) for value in ids):
            raise SafetyError('실행 컨테이너 목록을 확인할 수 없습니다.')
        records = _json(self.runner.run(['docker', 'inspect', *sorted(ids)]), list) if ids else []
        if len(records) != len(ids):
            raise SafetyError('실행 컨테이너 검사 중 목록이 변경되었습니다.')
        listeners = self.runner.run(['ss', '-H', '-ltn'])
        return records, listeners

    @staticmethod
    def _bindings(value):
        if not isinstance(value, dict):
            raise SafetyError('실제 Docker 포트 정보의 자료형이 다릅니다.')
        result = {}
        for target, bindings in value.items():
            if bindings in (None, []):
                continue
            if not isinstance(target, str) or not isinstance(bindings, list):
                raise SafetyError('실제 Docker 포트 연결 형식이 다릅니다.')
            entries = []
            for binding in bindings:
                if not isinstance(binding, dict) or not isinstance(binding.get('HostIp'), str):
                    raise SafetyError('실제 Docker 포트 주소가 다릅니다.')
                host_port = binding.get('HostPort')
                if not isinstance(host_port, str) or not host_port.isdigit():
                    raise SafetyError('실제 Docker 게시 포트가 다릅니다.')
                entries.append((binding['HostIp'] or '0.0.0.0', host_port))
            result[target] = sorted(entries)
        return result

    def _runtime(self, config, phase, collected):
        records, listeners = collected
        project = config.get('name')
        matches = []
        for item in records:
            if not isinstance(item, dict) or not isinstance(item.get('Config'), dict):
                raise SafetyError('실제 컨테이너 정보의 자료형이 다릅니다.')
            labels = item['Config'].get('Labels') or {}
            if not isinstance(labels, dict):
                raise SafetyError('실제 컨테이너 프로젝트 정보가 다릅니다.')
            workdir = labels.get('com.docker.compose.project.working_dir', '')
            if workdir and Path(workdir).resolve() == self.app_dir:
                matches.append(item)
        projects = {item['Config']['Labels'].get('com.docker.compose.project') for item in matches}
        if project is None and len(projects) == 1:
            project = next(iter(projects))
        if not isinstance(project, str) or not project or projects != {project}:
            raise SafetyError('회계 실행 프로젝트·원본 작업 경로를 확인할 수 없습니다.')
        actual = {}
        for item in records:
            labels = item['Config'].get('Labels') or {}
            owned = labels.get('com.docker.compose.project') == project
            host = item.get('HostConfig') or {}; network = item.get('NetworkSettings') or {}
            host_bindings = self._bindings(host.get('PortBindings') or {})
            actual_bindings = self._bindings(network.get('Ports') or {})
            if owned:
                name = labels.get('com.docker.compose.service')
                if item not in matches or name not in SERVICES or name in actual:
                    raise SafetyError('회계 서비스의 작업 경로·서비스가 중복되거나 다릅니다.')
                if (not item.get('State', {}).get('Running') or host.get('NetworkMode') == 'host'
                        or str(host.get('NetworkMode', '')).startswith('container:')
                        or host.get('PidMode') == 'host' or host.get('IpcMode') == 'host'
                        or host.get('Privileged') or host.get('CapAdd') or host.get('Devices')
                        or host.get('DeviceRequests') or host.get('VolumesFrom')):
                    raise SafetyError('회계 컨테이너의 실제 실행 상태·권한이 다릅니다.')
                actual[name] = (item, host_bindings, actual_bindings)
            else:
                for bindings in (host_bindings, actual_bindings):
                    for target, ports in bindings.items():
                        target_port = target.split('/')[0]
                        if (target_port.isdigit() and int(target_port) in PORTS) or any(int(port) in PORTS for _, port in ports):
                            raise SafetyError('다른 컨테이너가 회계 보호 포트를 게시하고 있습니다.')
        pending = phase == 'ready' and set(actual) == {'sollume-app', 'sollume-api'}
        if set(actual) != (set(SERVICES) - {'sollume-auth'} if pending else set(SERVICES)):
            raise SafetyError('회계 실행 서비스 목록이 배포 단계와 다릅니다.')
        transition = False
        for name, (item, host_bindings, actual_bindings) in actual.items():
            port = SERVICES[name]; expected = {str(port) + '/tcp': [('127.0.0.1', str(port))]}
            if host_bindings == expected and actual_bindings == expected:
                continue
            wildcard_host = {str(port) + '/tcp': [('0.0.0.0', str(port))]}
            wildcard_actual = {str(port) + '/tcp': [('0.0.0.0', str(port)), ('::', str(port))]}
            if (pending and name == 'sollume-app' and host_bindings in (wildcard_host, wildcard_actual)
                    and actual_bindings in (wildcard_host, wildcard_actual)):
                transition = True; continue
            raise SafetyError('실제 Docker 보호 포트가 정확한 루프백 게시와 다릅니다.')
        for line in listeners.splitlines():
            fields = line.split()
            if len(fields) < 4:
                raise SafetyError('호스트 listen 조회 형식을 확인할 수 없습니다.')
            endpoint = fields[3]
            match = re.search(r':(8501|8502|8503)$', endpoint)
            if match:
                address = endpoint[:-(len(match[1]) + 1)]
                if address != '127.0.0.1' and not (transition and match[1] == '8501' and address in ('0.0.0.0', '*', '[::]', '::')):
                    raise SafetyError('호스트 프로세스가 회계 보호 포트를 외부에 노출합니다.')
        summary = [{'id': item.get('Id'), 'service': name, 'host': host, 'actual': published,
                    'running': item.get('State', {}).get('Running')}
                   for name, (item, host, published) in sorted(actual.items())]
        return {'project': project, 'runtime_transition_required': transition,
                'runtime_fingerprint': _sha(_canonical({'containers': summary, 'listeners': listeners}))}

    def _probe(self, origin, path, headers=None):
        method = getattr(self.runner, 'probe', None) or ReadOnlyRunner().probe
        result = method(origin, path, headers=headers)
        if not isinstance(result, dict) or type(result.get('status')) is not int:
            raise SafetyError('HTTP 차단 점검 응답을 확인할 수 없습니다.')
        return result

    def _responses(self, legacy, phase):
        paths = ('/', '/api/order-file/meta', '/media/preflight', DOWNLOAD, '/_stcore/stream')
        for (host, scheme), action in sorted(legacy.items()):
            for path in paths:
                result = self._probe(scheme + '://' + host, path, WEBSOCKET if path.endswith('/stream') else None)
                expected = action['status']
                if result['status'] != expected:
                    raise SafetyError('기존 회계 주소에서 업무 접근 차단을 확인하지 못했습니다.')
                if action['redirect'] and result.get('location') != 'https://' + OFFICE + path:
                    raise SafetyError('기존 회계 주소의 고정 HTTPS 이동 대상을 확인하지 못했습니다.')
        if phase == 'verify':
            for path, status in (('/', 401), ('/media/preflight', 403), (DOWNLOAD, 401),
                                 ('/_stcore/stream', 401), ('/auth/check', 404), ('/_stcore/health', 404)):
                headers = WEBSOCKET if path.endswith('/stream') else {'Accept': 'application/json'}
                if self._probe('https://' + OFFICE, path, headers)['status'] != status:
                    raise SafetyError('office1 인증·다운로드·WebSocket 접근 차단을 확인하지 못했습니다.')

    def _check(self, phase, compose_json, baseline=None):
        config = self._compose(compose_json)
        before = self._configuration()
        legacy = self._ingress(before)
        runtime_before = self._runtime(config, phase, self._collect_runtime())
        fingerprint = _sha(_canonical({'nginx': before['dump_sha256'], 'sites': before['sites'], 'compose': _sha(_canonical(config))}))
        if baseline is not None:
            if isinstance(baseline, dict):
                saved = baseline
            else:
                path = Path(baseline)
                if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 ** 2:
                    raise SafetyError('최초 점검 결과의 실제 절대 파일 경로가 필요합니다.')
                saved = _json(path.read_bytes(), dict)
            if saved.get('policy_fingerprint') != fingerprint:
                raise SafetyError('최초 점검 이후 Nginx·사이트 경로·후보 Compose가 변경되었습니다.')
        self._responses(legacy, phase)
        after = self._configuration()
        runtime_after = self._runtime(config, phase, self._collect_runtime())
        if (before['dump_sha256'] != after['dump_sha256'] or before['sites'] != after['sites']
                or config != self._compose(compose_json) or runtime_before != runtime_after):
            raise SafetyError('점검 도중 설정·사이트 경로·실행 컨테이너가 변경되었습니다.')
        self.state = {'phase': phase, 'validated': True, 'policy_fingerprint': fingerprint,
                      'project': runtime_before['project'], 'runtime_transition_required': runtime_before['runtime_transition_required'],
                      'domains': sorted(DOMAINS), 'cloud_firewall_checked': False}
        return dict(self.state)

    def ready(self, compose_json, baseline=None):
        try:
            return self._check('ready', compose_json, baseline)
        except SafetyError:
            raise
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            raise SafetyError('배포 전 점검 자료·경로·실행 정보의 형식이 다릅니다.') from exc

    def verify(self, compose_json, baseline=None):
        try:
            return self._check('verify', compose_json, baseline)
        except SafetyError:
            raise
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            raise SafetyError('배포 후 점검 자료·경로·실행 정보의 형식이 다릅니다.') from exc

    def inventory(self):
        result = {'phase': 'inventory', 'validated': False, 'issues': [], 'cloud_firewall_checked': False}
        try:
            configuration = self._configuration()
            self._ingress(configuration)
            result.update(active_site_count=len(configuration['sites']))
        except SafetyError as exc:
            result['issues'].append(str(exc))
        # 2026-10-20 hoyeon.han: 새 인증 설정이 아직 준비되지 않아도 기존 공개 게시를 독립적으로 진단한다.
        try:
            records, listeners = self._collect_runtime()
            published = []
            for item in records:
                for origin in ('HostConfig', 'NetworkSettings'):
                    field = 'PortBindings' if origin == 'HostConfig' else 'Ports'
                    for target, bindings in self._bindings(item.get(origin, {}).get(field) or {}).items():
                        for address, port in bindings:
                            if (target.split('/')[0].isdigit() and int(target.split('/')[0]) in PORTS) or int(port) in PORTS:
                                entry = {'target_port': target, 'address': address, 'published_port': int(port)}
                                if entry not in published:
                                    published.append(entry)
            external = any(item['address'] != '127.0.0.1' for item in published)
            listener_count = 0
            for line in listeners.splitlines():
                fields = line.split()
                if len(fields) >= 4 and _target_port(fields[3]) in PORTS:
                    listener_count += 1
                    if fields[3].rsplit(':', 1)[0] != '127.0.0.1':
                        external = True
            result.update(running_container_count=len(records), protected_publications=published,
                          protected_listener_count=listener_count, external_protected_port=external)
            if external:
                result['issues'].append('현재 회계 보호 포트가 외부 주소에 게시되어 전환이 필요합니다.')
        except SafetyError as exc:
            result['issues'].append(str(exc))
        result['validated'] = not result['issues']
        self.state = dict(result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='회계 배포 전후 읽기 전용 진입점 점검')
    parser.add_argument('phase', choices=('inventory', 'ready', 'verify'))
    parser.add_argument('--app-dir', required=True)
    parser.add_argument('--nginx-config', action='append', required=True)
    parser.add_argument('--compose-json')
    parser.add_argument('--baseline')
    args = parser.parse_args(argv)
    if sys.prefix == sys.base_prefix:
        parser.error('Python 가상환경에서 실행하세요.')
    if args.phase != 'inventory' and not args.compose_json:
        parser.error('ready/verify에는 --compose-json이 필요합니다.')
    try:
        checker = Preflight(args.app_dir, args.nginx_config)
        result = checker.inventory() if args.phase == 'inventory' else getattr(checker, args.phase)(args.compose_json, args.baseline)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['validated'] else 1
    except SafetyError as exc:
        print('배포 사전검증 실패: ' + str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        # 2026-10-20 hoyeon.han: 예외 원문에 키·환경·전체 설정이 포함될 가능성을 차단한다.
        print('배포 사전검증 실패: 비공개 점검 결과와 서비스 설정을 확인하세요.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
