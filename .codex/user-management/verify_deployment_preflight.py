"""2026-10-20 hoyeon.han: 실제 격리 Docker/Nginx/TLS로 배포 진입점 검사만 검증한다.

업무 이미지·DB·운영 서버는 사용하지 않는다. 논리 8501~8503 metadata는 실제
fixture의 loopback 고포트에 대응하며 기존 로컬 서비스는 조회 외 변경하지 않는다.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
DOMAINS = ('office1.sollumeesthe.com', 'sol-fin.duckdns.org', 'sollume-finance.duckdns.org')
SERVICES = {'sollume-app': 8501, 'sollume-api': 8502, 'sollume-auth': 8503}
CACHE = ('sollume-finance-sollume-app:latest', 'sollume-finance-sollume-api:latest',
         'sollume-finance-security:venv-test', 'nginx:alpine')


def command(argv, *, check=True):
    result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=60)
    if check and result.returncode:
        raise RuntimeError('격리 검증 명령 실패: ' + ' '.join(map(str, argv[:2])))
    return result.stdout if check else result


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def load_api():
    spec = importlib.util.spec_from_file_location('actual_deployment_preflight', ROOT / 'scripts/deployment_preflight.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def existing_containers():
    identifiers = command(['docker', 'ps', '-aq']).split()
    if not identifiers:
        return {}
    records = json.loads(command(['docker', 'inspect', *identifiers]))
    return {record['Id']: {'image': record['Image'], 'name': record['Name'],
                          'started_at': record['State'].get('StartedAt'),
                          'restart_count': record.get('RestartCount'),
                          'state': {key: record['State'].get(key) for key in ('Status', 'Running', 'Paused', 'Restarting', 'Dead')},
                          'health': record['State'].get('Health', {}).get('Status')}
            for record in records}


# 2026-10-20 hoyeon.han: Docker Desktop의 태그 정규화 차이에도 로컬 목록에서 실제 ID만 사용한다.
def local_image(tag):
    values = set(command(['docker', 'image', 'ls', '--no-trunc', '--format', '{{.ID}}', tag]).split())
    if len(values) != 1:
        raise RuntimeError('필요한 로컬 QA 캐시 이미지를 한 개로 확인할 수 없습니다.')
    identifier = values.pop()
    command(['docker', 'image', 'inspect', identifier])
    return identifier


def image_cache():
    # return {tag: command(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag]).strip() for tag in CACHE}
    return {tag: local_image(tag) for tag in CACHE}


class Fixture:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix='sollume-preflight-qa-', dir='/private/tmp'))
        self.root.chmod(0o700)
        self.app = self.root / 'app'
        self.app.mkdir(mode=0o700)
        self.project = self.root.name
        self.network = self.project + '-network'
        self.label = 'sollume.preflight.qa=' + self.project
        self.sources = self.root / 'sites'
        self.runtimes = self.root / 'sites-runtime'
        self.sources.mkdir()
        self.runtimes.mkdir()
        self.main = self.root / 'nginx-logical.conf'
        self.runtime_main = self.root / 'nginx-runtime.conf'
        self.sites = [self.sources / ('0' + str(index) + '-' + domain) for index, domain in enumerate(DOMAINS)]
        self.canary = self.sources / '90-unrelated-canary'
        self.http_port, self.https_port = free_port(), free_port()
        self.ports = {port: free_port() for port in (*SERVICES.values(), 5678, 8901)}
        self.names = {service: self.project + '-' + service for service in SERVICES}
        self.frontend = self.project + '-nginx'
        self.owned = []
        self.created_network = False
        self.phase = 'legacy'
        self.probes = []
        self.calls = []
        self.logical_runtime_observations = []
        self.compose = {'name': self.project, 'services': {
            service: {'image': 'nginx:alpine', 'ports': [{'host_ip': '127.0.0.1', 'published': str(port), 'target': port, 'protocol': 'tcp'}],
                      'environment': {'AUTH_ENV': 'production', 'AUTH_PUBLIC_ORIGIN': 'https://' + DOMAINS[0]}}
            for service, port in SERVICES.items()}}

    def render(self, path):
        text = path.read_text()
        for domain in DOMAINS:
            text = text.replace('/etc/letsencrypt/live/' + domain + '/fullchain.pem', str(self.root / 'ssl/fullchain.pem'))
            text = text.replace('/etc/letsencrypt/live/' + domain + '/privkey.pem', str(self.root / 'ssl/privkey.pem'))
        for port in SERVICES.values():
            text = text.replace('http://127.0.0.1:' + str(port), 'http://host.docker.internal:' + str(self.ports[port]))
        return text

    def prepare(self):
        # 2026-10-20 hoyeon.han: 기존 캐시 태그 조회를 보존하고 실제 로컬 ID를 사용한다.
        # self.image = command(['docker', 'image', 'inspect', '--format', '{{.Id}}', 'nginx:alpine']).strip()
        self.image = local_image('nginx:alpine')
        command(['docker', 'network', 'create', '--label', self.label, self.network])
        self.created_network = True
        (self.root / 'ssl').mkdir(mode=0o700)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=office1.sollumeesthe.com', '-addext', 'subjectAltName=DNS:office1.sollumeesthe.com,IP:127.0.0.1',
                        '-keyout', str(self.root / 'ssl/privkey.pem'), '-out', str(self.root / 'ssl/fullchain.pem')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (self.root / 'ssl/privkey.pem').chmod(0o600)
        self.sites[0].write_text((ROOT / 'nginx-host-api.conf.example').read_text())
        for host, path in zip(DOMAINS[1:], self.sites[1:]):
            path.write_text(f'server {{ listen 80; server_name {host}; return 301 https://office1.sollumeesthe.com$request_uri; }}\n'
                            f'server {{ listen 443 ssl; server_name {host};\n'
                            f'ssl_certificate /etc/letsencrypt/live/{host}/fullchain.pem;\n'
                            f'ssl_certificate_key /etc/letsencrypt/live/{host}/privkey.pem;\n'
                            'return 301 https://office1.sollumeesthe.com$request_uri; }\n')
        self.canary.write_text('server { listen 80; server_name unrelated.example.invalid; return 200 "canary-preserved"; }\n'
                              'server { listen 443 ssl; server_name unrelated.example.invalid;\n'
                              'ssl_certificate /etc/letsencrypt/live/office1.sollumeesthe.com/fullchain.pem;\n'
                              'ssl_certificate_key /etc/letsencrypt/live/office1.sollumeesthe.com/privkey.pem;\n'
                              'return 200 "canary-preserved"; }\n')
        self.canary_hash = digest(self.canary)
        self.main.write_text('worker_processes 1;\nevents { worker_connections 256; }\nhttp { include ' + str(self.sources) + '/*; }\n')
        self.runtime_main.write_text(self.main.read_text().replace(str(self.sources), str(self.runtimes)))
        for path in (*self.sites, self.canary):
            (self.runtimes / path.name).write_text(self.render(path))
        self.start_backend('sollume-app', 8501)
        self.start_backend('sollume-api', 8502)
        self.start_backend('n8n-canary', 5678, accounting=False)
        self.start_backend('goodsfoundry-canary', 8901, accounting=False)
        self.run_container(self.frontend, [
            '-p', f'127.0.0.1:{self.http_port}:80', '-p', f'127.0.0.1:{self.https_port}:443',
            '-v', str(self.root) + ':' + str(self.root) + ':ro',
            '-v', str(self.runtime_main) + ':/etc/nginx/nginx.conf:ro'])
        for attempt in range(30):
            if self.probe('http://unrelated.example.invalid', '/')['status'] == 200:
                break
            time.sleep(0.5)
        else:
            raise AssertionError('격리 Nginx 준비 실패')
        self.canary_containers = {record['Id']: record['State']['StartedAt'] for record in self.actual_records()
                                  if 'canary' in record['Name']}

    def run_container(self, name, args):
        self.owned.append(name)
        return command(['docker', 'run', '-d', '--pull', 'never', '--name', name, '--network', self.network,
                        '--label', self.label, '--read-only', '--tmpfs', '/var/cache/nginx', '--tmpfs', '/var/run',
                        '--tmpfs', '/tmp', *args, '--entrypoint', 'nginx', self.image, '-g', 'daemon off;'])

    def start_backend(self, service, port, accounting=True):
        name = self.names[service] if accounting else self.project + '-' + service
        path = self.root / (service + '.backend.conf')
        body = ('location = /auth/check { return 401; } location = /auth/health { return 200 "ok"; } '
                'location = /auth/login { return 200 "synthetic login"; } location / { return 401; }') if port == 8503 else 'location / { return 200 "synthetic backend"; }'
        path.write_text('events {}\nhttp { server { listen ' + str(port) + '; ' + body + ' } }\n')
        args = ['-p', f'127.0.0.1:{self.ports[port]}:{port}', '-v', str(path) + ':/etc/nginx/nginx.conf:ro']
        if accounting:
            args += ['--label', 'com.docker.compose.project=' + self.project,
                     '--label', 'com.docker.compose.service=' + service,
                     '--label', 'com.docker.compose.project.working_dir=' + str(self.app)]
        self.run_container(name, args)

    def actual_records(self):
        ids = command(['docker', 'ps', '-q']).split()
        return json.loads(command(['docker', 'inspect', *ids])) if ids else []

    def logical_records(self, records):
        records = copy.deepcopy(records)
        for record in records:
            if record['Name'].lstrip('/') not in self.owned:
                continue
            for field in ('PortBindings', 'Ports'):
                section = record['HostConfig'] if field == 'PortBindings' else record['NetworkSettings']
                for bindings in (section.get(field) or {}).values():
                    for binding in bindings or []:
                        logical = next((target for target, published in self.ports.items() if str(published) == binding['HostPort']), None)
                        if logical is None:
                            continue
                        binding['HostPort'] = str(logical)
                        if self.phase == 'legacy' and logical == 8501:
                            binding['HostIp'] = '0.0.0.0'
        return records

    def logical_dump(self):
        actual = command(['docker', 'exec', self.frontend, 'nginx', '-T'])
        parts = re.split(r'^# configuration file (.+):\s*$', actual, flags=re.MULTILINE)
        output = []
        for index in range(1, len(parts), 2):
            name, body = parts[index], parts[index + 1]
            if name == '/etc/nginx/nginx.conf':
                source, expected = self.main, self.runtime_main.read_text()
            else:
                runtime = Path(name)
                if runtime.parent != self.runtimes:
                    raise AssertionError('격리 Nginx에 예상하지 못한 include가 있습니다.')
                source = self.sources / runtime.name
                expected = self.render(source)
            if body.strip() != expected.strip():
                raise AssertionError('실제 Nginx -T와 원본/런타임 경로 대응이 다릅니다.')
            output.append('# configuration file ' + str(source) + ':\n' + source.read_text())
        return '\n'.join(output)

    def run(self, argv):
        argv = list(map(str, argv))
        self.calls.append(argv)
        if argv == ['sudo', '-n', 'nginx', '-T']:
            return self.logical_dump()
        if argv == ['docker', 'ps', '-q']:
            return command(argv)
        if argv[:2] == ['docker', 'inspect']:
            return json.dumps(self.logical_records(json.loads(command(argv))))
        if argv == ['ss', '-H', '-ltn']:
            rows = []
            for record in self.logical_records(self.actual_records()):
                for bindings in record['HostConfig'].get('PortBindings', {}).values():
                    for binding in bindings or []:
                        rows.append('LISTEN 0 4096 ' + binding['HostIp'] + ':' + binding['HostPort'] + ' 0.0.0.0:*')
            return '\n'.join(rows)
        raise AssertionError('읽기 전용 preflight 외 명령입니다: ' + repr(argv[:3]))

    def probe(self, origin, path, headers=None):
        from urllib.parse import urlsplit
        parsed = urlsplit(origin)
        connection = (http.client.HTTPSConnection('127.0.0.1', self.https_port,
                      context=ssl.create_default_context(cafile=str(self.root / 'ssl/fullchain.pem')), timeout=10)
                      if parsed.scheme == 'https' else http.client.HTTPConnection('127.0.0.1', self.http_port, timeout=10))
        try:
            connection.request('GET', path, headers={'Host': parsed.hostname, **(headers or {})})
            response = connection.getresponse()
            result = {'status': response.status, 'location': response.getheader('Location')}
            body = response.read(4096)
        except (OSError, http.client.HTTPException):
            result, body = {'status': 0, 'location': None}, b''
        finally:
            connection.close()
        self.probes.append({'origin': origin, 'path': path, **result, 'body_sha256': hashlib.sha256(body).hexdigest()})
        return result

    def canaries_unchanged(self):
        actual = {record['Id']: record['State']['StartedAt'] for record in self.actual_records() if 'canary' in record['Name']}
        return (actual == self.canary_containers and digest(self.canary) == self.canary_hash
                and all(self.probe(scheme + '://unrelated.example.invalid', '/')['status'] == 200 for scheme in ('http', 'https')))

    def cleanup(self):
        okay = True
        for name in reversed(self.owned):
            result = command(['docker', 'rm', '-f', name], check=False)
            okay = (result.returncode == 0) and okay
        if self.created_network:
            okay = command(['docker', 'network', 'rm', self.network], check=False).returncode == 0 and okay
        remaining = command(['docker', 'ps', '-aq', '--filter', 'label=' + self.label]).strip()
        networks = command(['docker', 'network', 'ls', '--filter', 'label=' + self.label, '--format', '{{.ID}}']).strip()
        shutil.rmtree(self.root)
        return okay and not remaining and not networks and not self.root.exists()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / '.Codex/user-management/deployment-preflight-results.json'))
    args = parser.parse_args()
    if sys.prefix == sys.base_prefix:
        parser.error('가상환경 Python으로 실행하세요.')
    baseline_names = json.loads((ROOT / '.codex/user-management/data-baseline.json').read_text())
    business_before = {name: digest(ROOT / name) for name in baseline_names}
    containers_before, cache_before = existing_containers(), image_cache()
    source_before = digest(ROOT / 'scripts/deployment_preflight.py')
    fixture = Fixture()
    checks = []
    failure = None
    cleanup = False
    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})
        print(('PASS ' if value else 'FAIL ') + name, flush=True)
        if not value:
            raise AssertionError(name)
    try:
        fixture.prepare()
        api = load_api()
        checker = api.Preflight(fixture.app, fixture.sites, runner=fixture)
        inventory = checker.inventory()
        ready = checker.ready(fixture.compose)
        check('actual_nginx_inventory_and_readiness_accept_exact_legacy_transition',
              isinstance(inventory, dict) and ready['validated'] and ready['runtime_transition_required'])
        check('other_virtual_hosts_and_canary_containers_preserved_before_transition', fixture.canaries_unchanged())
        try:
            checker.verify(fixture.compose, baseline=ready)
            rejected = False
        except ValueError:
            rejected = True
        check('verification_rejects_modeled_old_wildcard_and_missing_auth_container', rejected)
        fixture.start_backend('sollume-auth', 8503)
        fixture.phase = 'secure'
        for attempt in range(30):
            if fixture.probe('https://' + DOMAINS[0], '/')['status'] == 401:
                break
            time.sleep(0.5)
        verified = checker.verify(fixture.compose, baseline=ready)
        check('actual_tls_domain_paths_and_readonly_port_inventory_verify', verified['validated'] and not verified['runtime_transition_required'])
        check('legacy_https_and_http_destinations_checked_without_following_redirects',
              all(any(row['origin'] == scheme + '://' + host and row['status'] == 301 and
                      row['location'] == 'https://' + DOMAINS[0] + row['path'] for row in fixture.probes)
                  for host in DOMAINS[1:] for scheme in ('http', 'https')))
        check('other_virtual_hosts_and_canary_containers_preserved_after_transition', fixture.canaries_unchanged())
        # 2026-10-20 hoyeon.han: http 전역 상속이 canonical auth_request를 실제로 우회하는지 재현한다.
        original_main = fixture.main.read_text()
        original_runtime_main = fixture.runtime_main.read_text()
        fixture.main.write_text(original_main.replace('http {', 'http { satisfy any; allow all;', 1))
        fixture.runtime_main.write_text(fixture.main.read_text().replace(str(fixture.sources), str(fixture.runtimes)))
        command(['docker', 'exec', fixture.frontend, 'nginx', '-t'])
        command(['docker', 'exec', fixture.frontend, 'nginx', '-s', 'reload'])
        for attempt in range(30):
            if fixture.probe('https://' + DOMAINS[0], '/')['status'] == 200:
                break
            time.sleep(0.2)
        check('actual_global_satisfy_any_allow_all_bypasses_auth_with_root200',
              fixture.probe('https://' + DOMAINS[0], '/')['status'] == 200)
        try:
            checker.ready(fixture.compose)
            rejected = False
        except ValueError:
            rejected = True
        check('preflight_rejects_inherited_satisfy_any_before_false_success', rejected)
        fixture.main.write_text(original_main)
        fixture.runtime_main.write_text(original_runtime_main)
        command(['docker', 'exec', fixture.frontend, 'nginx', '-t'])
        command(['docker', 'exec', fixture.frontend, 'nginx', '-s', 'reload'])
        for attempt in range(30):
            if fixture.probe('https://' + DOMAINS[0], '/')['status'] == 401:
                break
            time.sleep(0.2)
        restored = checker.verify(fixture.compose, baseline=ready)
        check('restored_original_policy_reinstates_auth401_and_keeps_canaries',
              restored['validated'] and fixture.canaries_unchanged())
        fixture.sites[1].write_text(fixture.sites[1].read_text() + '\n# changed since readiness\n')
        # 2026-10-20 hoyeon.han: 실제 nginx-T에도 같은 파일 변경이 나타나야 fingerprint 자체를 검사한다.
        (fixture.runtimes / fixture.sites[1].name).write_text(fixture.render(fixture.sites[1]))
        try:
            checker.verify(fixture.compose, baseline=ready)
            rejected = False
        except ValueError:
            rejected = True
        check('policy_change_is_rejected_before_false_success', rejected)
    except BaseException as exc:
        failure = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        try:
            cleanup = fixture.cleanup()
        except BaseException as exc:
            cleanup = False
            failure = failure or {'type': type(exc).__name__, 'message': '격리 리소스 정리 실패'}
    business_after = {name: digest(ROOT / name) for name in baseline_names}
    containers_after, cache_after = existing_containers(), image_cache()
    checks += [{'name': 'original_nine_business_files_unchanged', 'passed': business_after == business_before},
               {'name': 'all_preexisting_container_ids_images_startedat_restartcount_state_unchanged', 'passed': containers_after == containers_before},
               {'name': 'four_cached_image_tags_and_ids_unchanged', 'passed': cache_after == cache_before},
               {'name': 'preflight_source_unchanged_during_execution', 'passed': source_before == digest(ROOT / 'scripts/deployment_preflight.py')},
               {'name': 'all_fixture_resources_cleaned', 'passed': cleanup}]
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'passed': failure is None and all(row['passed'] for row in checks),
              'checks': checks, 'check_count': len(checks), 'failure': failure, 'cleanup_complete': cleanup,
              'business_before': business_before, 'business_after': business_after,
              'containers_before': containers_before, 'containers_after': containers_after,
              'cache_before': cache_before, 'cache_after': cache_after, 'probes': fixture.probes,
              'source_sha256': source_before, 'production_accessed': False,
              'limitations': ['백엔드는 캐시된 Nginx의 합성 응답이다. 실제 직원 로그인·MFA 기능은 이 시험 범위가 아니다.',
                             '실제 Docker 게시 포트는 모두 loopback 고포트다. 어댑터가 fixture metadata만 논리 8501~8503으로 대응하며 ready의 옛 wildcard는 metadata로 재현했다.',
                             'macOS에 Linux ss가 없어 실제 Docker 바인딩을 ss 형식으로 변환했다. Linux ss 파싱과 거부 조건은 단위 테스트에서 검증한다.',
                             'nginx -T는 실제 컨테이너 결과를 원본과 대조한 뒤 fixture TLS·고포트·원본 경로만 논리 경로로 대응한다.',
                             'TLS는 fixture 자체 서명 CA로 검증하며 외부 DNS·운영 서버에 접속하지 않았다.']}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    output.chmod(0o600)
    print(json.dumps({'passed': report['passed'], 'checks': len(checks), 'cleanup_complete': cleanup, 'failure': failure}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
