# 2026-11-05 hoyeon.han: 재사용 검증 소스를 tests의 보안·운영 테스트로 분리한다.
"""2026-10-20 hoyeon.han: 배포 전후 전체 도메인·직접 포트 우회 검증 계약."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOMAINS = ('office1.sollumeesthe.com', 'sol-fin.duckdns.org', 'sollume-finance.duckdns.org')
PORTS = {'sollume-app': 8501, 'sollume-api': 8502, 'sollume-auth': 8503}


def load_api():
    name = 'deployment_preflight_unit_' + str(id(object()))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/deployment_preflight.py')
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def legacy_site(domain, action='return 301 https://office1.sollumeesthe.com$request_uri;'):
    return ('# 2026-10-20 hoyeon.han: 합성 구주소 전용 차단 설정.\n'
            f'server {{ listen 80; server_name {domain}; location / {{ {action} }} }}\n'
            f'server {{ listen 443 ssl; server_name {domain};\n'
            f'ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;\n'
            f'ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;\n'
            f'location / {{ {action} }} }}\n')


def container(identifier, name, service, bindings, project, app):
    return {'Id': identifier * 64, 'Name': '/' + name, 'Image': 'sha256:' + 'a' * 64,
            'State': {'Running': True},
            'Config': {'Env': ['ORDER_API_KEY=synthetic-never-print-preflight-secret'],
                       'Labels': {'com.docker.compose.project': project,
                                  'com.docker.compose.service': service,
                                  'com.docker.compose.project.working_dir': str(app)} if service else {}},
            'HostConfig': {'NetworkMode': project + '_network', 'PortBindings': copy.deepcopy(bindings)},
            'NetworkSettings': {'Ports': copy.deepcopy(bindings)}}


class Fixture:
    def __init__(self, root):
        self.root = root
        self.app = root / 'sollume-finance'
        self.app.mkdir()
        self.project = self.app.name
        self.folder = root / 'nginx-sites'
        self.folder.mkdir()
        self.sites = [self.folder / domain for domain in DOMAINS]
        self.sites[0].write_text((ROOT / 'nginx-host-api.conf.example').read_text())
        for domain, path in zip(DOMAINS[1:], self.sites[1:]):
            path.write_text(legacy_site(domain))
        self.main = root / 'nginx.conf'
        self.main.write_text('events {}\nhttp { include ' + str(self.folder) + '/*; }\n')
        self.files = [self.main, *self.sites]
        self.canary = self.folder / 'unrelated'
        self.add(self.canary,
                 'server { listen 443 ssl; server_name sollume-n8n.duckdns.org; '
                 'location / { proxy_pass http://127.0.0.1:5678; } }\n'
                 'server { listen 80; server_name goods.example.invalid; '
                 'location / { proxy_pass http://127.0.0.1:8901; } }\n')
        self.calls = []
        self.probes = []
        self.overrides = {}
        self.on_run = None
        self.compose = {'name': self.project, 'services': {
            name: {'image': 'sha256:' + 'a' * 64,
                   'ports': [{'target': port, 'published': str(port), 'host_ip': '127.0.0.1', 'protocol': 'tcp'}],
                   'environment': {'AUTH_ENV': 'production', 'AUTH_PUBLIC_ORIGIN': 'https://' + DOMAINS[0],
                                   'AUTH_ENCRYPTION_KEY': 'synthetic-never-print-preflight-secret'}}
            for name, port in PORTS.items()}}
        self.records = []
        self.set_runtime(secure=False)

    def add(self, path, text):
        path.write_text(text)
        if path not in self.files:
            self.files.append(path)

    def set_runtime(self, secure):
        self.records = []
        for index, (service, port) in enumerate(PORTS.items()):
            if not secure and service == 'sollume-auth':
                continue
            addresses = ['127.0.0.1'] if secure or service != 'sollume-app' else ['0.0.0.0', '::']
            bindings = {str(port) + '/tcp': [{'HostIp': address, 'HostPort': str(port)} for address in addresses]}
            self.records.append(container(str(index + 1), 'sollume-finance-' + service.removeprefix('sollume-'),
                                          service, bindings, self.project, self.app))
        self.records += [container('7', 'n8n', '', {'5678/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '5678'}]}, '', self.app),
                         container('8', 'goodsfoundry', '', {'3000/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8901'}]}, '', self.app)]
        self.ss = '\n'.join('LISTEN 0 4096 ' + ('[::]' if binding['HostIp'] == '::' else binding['HostIp']) + ':' + binding['HostPort'] + ' 0.0.0.0:*'
                            for record in self.records for values in record['HostConfig']['PortBindings'].values() for binding in values)

    def dump(self):
        return '\n'.join('# configuration file ' + str(path) + ':\n' + path.read_text() for path in self.files)

    def run(self, argv):
        argv = list(map(str, argv))
        self.calls.append(argv)
        if self.on_run:
            self.on_run(argv)
        if argv == ['sudo', '-n', 'nginx', '-T']:
            return self.dump()
        if argv == ['docker', 'ps', '-q']:
            return '\n'.join(record['Id'] for record in self.records)
        if argv[:2] == ['docker', 'inspect']:
            return json.dumps([record for record in self.records if record['Id'] in argv[2:]])
        if argv == ['ss', '-H', '-ltn']:
            return self.ss
        raise AssertionError('승인되지 않은 시험 명령: ' + repr(argv[:3]))

    def probe(self, origin, path, headers=None):
        self.probes.append((origin, path, headers))
        if (origin, path) in self.overrides:
            return self.overrides[origin, path]
        if any(domain in origin for domain in DOMAINS[1:]):
            return {'status': 301, 'location': 'https://' + DOMAINS[0] + path}
        # 2026-10-21 hoyeon.han: health의 미로그인 응답은 401이며 실제 내부 검사 경로만 404다.
        # status = 403 if path.startswith('/media/') else 404 if path in ('/auth/check', '/_stcore/health') else 401
        status = 403 if path.startswith('/media/') else 404 if path == '/auth/check' else 401
        return {'status': status, 'location': None}

    def checker(self, sites=None):
        return load_api().Preflight(self.app, self.sites if sites is None else sites, runner=self)

    def hashes(self):
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.files}


@pytest.fixture
def fixture(tmp_path):
    return Fixture(tmp_path)


def rejected(fixture, *, compose=None, sites=None):
    before = fixture.hashes()
    with pytest.raises(ValueError):
        fixture.checker(sites).ready(fixture.compose if compose is None else compose)
    assert fixture.hashes() == before
    assert all(call[:3] in (['sudo', '-n', 'nginx'], ['docker', 'ps', '-q'], ['ss', '-H', '-ltn'])
               or call[:2] == ['docker', 'inspect'] for call in fixture.calls)


def test_inventory_and_ready_accept_only_known_legacy_transition_without_mutation(fixture, capsys):
    before = fixture.hashes()
    checker = fixture.checker()
    assert isinstance(checker.inventory(), dict)
    ready = checker.ready(fixture.compose)
    assert ready['validated'] and ready['runtime_transition_required']
    assert fixture.hashes() == before
    # 2026-10-20 hoyeon.han: 준비 단계도 기존 주소의 실제 차단만 확인하며 새 인증 upstream은 요구하지 않는다.
    # assert not fixture.probes
    assert fixture.probes and all(any(domain in origin for domain in DOMAINS[1:]) for origin, _, _ in fixture.probes)
    assert 'synthetic-never-print-preflight-secret' not in json.dumps(ready) + capsys.readouterr().out


def test_secure_transition_verifies_all_domains_paths_without_following_redirects(fixture):
    checker = fixture.checker()
    ready = checker.ready(fixture.compose)
    fixture.set_runtime(secure=True)
    verified = checker.verify(fixture.compose, baseline=ready)
    assert verified['validated'] and not verified['runtime_transition_required']
    assert {origin for origin, _, _ in fixture.probes} >= {'http://' + host for host in DOMAINS[1:]} | {'https://' + host for host in DOMAINS}
    assert any(path == '/_stcore/stream' and headers.get('Upgrade', '').lower() == 'websocket' for _, path, headers in fixture.probes if headers)


def test_missing_legacy_argument_is_rejected(fixture):
    rejected(fixture, sites=fixture.sites[:2])


# 2026-10-20 hoyeon.han: 승인한 고정 차단 코드와 308 이동도 준비 단계에서 실제 응답까지 검사한다.
# 2026-10-20 hoyeon.han: 444는 일반 연결 실패와 구분할 수 없어 확정 정책에서 제외한다.
# @pytest.mark.parametrize('status', [308, 403, 404, 410, 444, 503])
@pytest.mark.parametrize('status', [308, 403, 404, 410, 503])
def test_explicit_legacy_denial_or_permanent_redirect_is_accepted(fixture, status):
    action = 'return 308 https://office1.sollumeesthe.com$request_uri;' if status == 308 else f'return {status};'
    paths = ('/', '/api/order-file/meta', '/media/preflight', '/downloads/' + '0' * 32, '/_stcore/stream')
    for host, path in zip(DOMAINS[1:], fixture.sites[1:]):
        path.write_text(legacy_site(host, action))
        for scheme in ('http', 'https'):
            for request_path in paths:
                fixture.overrides[scheme + '://' + host, request_path] = {
                    'status': 0 if status == 444 else status,
                    'location': 'https://' + DOMAINS[0] + request_path if status == 308 else None}
    assert fixture.checker().ready(fixture.compose)['validated']


def test_legacy_444_cannot_be_proven_by_indistinguishable_connection_failure(fixture):
    fixture.sites[1].write_text(legacy_site(DOMAINS[1], 'return 444;'))
    rejected(fixture)


def test_primary_must_remain_exact_approved_authentication_template(fixture):
    fixture.sites[0].write_text(fixture.sites[0].read_text().replace('auth_request /_auth_check;', ''))
    rejected(fixture)


# 2026-10-21 hoyeon.han: 연결을 막던 이전 404 정책과 인증을 우회하는 가짜 성공 정책을 모두 거부한다.
@pytest.mark.parametrize('directive', [
    'location = /_stcore/health { return 404; }',
    'location = /_stcore/health { return 200; }',
    'location = /_stcore/health { proxy_pass http://127.0.0.1:8501; }',
])
def test_primary_health_cannot_restore_404_or_bypass_session_check(fixture, directive):
    content = fixture.sites[0].read_text()
    previous = '# location = /_stcore/health { return 404; }'
    assert content.count(previous) == 1
    fixture.sites[0].write_text(content.replace(previous, directive))
    rejected(fixture)


# 2026-10-21 hoyeon.han: 정적 설정이 맞아도 실제 미로그인 health가 401이 아니면 배포 검증을 거부한다.
@pytest.mark.parametrize('status', [200, 302, 404, 503])
def test_verify_rejects_health_without_expected_session_denial(fixture, status):
    checker = fixture.checker()
    ready = checker.ready(fixture.compose)
    fixture.set_runtime(secure=True)
    fixture.overrides['https://' + DOMAINS[0], '/_stcore/health'] = {'status': status, 'location': None}
    with pytest.raises(ValueError, match='office1'):
        checker.verify(fixture.compose, baseline=ready)


@pytest.mark.parametrize('action', [
    'proxy_pass http://127.0.0.1:8501;',
    'proxy_pass http://127.0.0.1:8502;',
    'proxy_pass http://$backend;',
    'alias /app/processed/;',
    'root /home/ubuntu/sollume-finance;',
    'return 301 https://wrong.example.invalid$request_uri;',
    'return 302 https://office1.sollumeesthe.com$request_uri;',
    'return 301 https://office1.sollumeesthe.com/;',
    'return 200;',
])
def test_unsafe_legacy_proxy_static_or_redirect_is_rejected(fixture, action):
    fixture.sites[1].write_text(legacy_site(DOMAINS[1], action))
    rejected(fixture)


@pytest.mark.parametrize('location', ['/api/', '/media/', '/downloads/', '/_stcore/stream'])
def test_hidden_legacy_location_is_rejected_even_if_root_redirects(fixture, location):
    content = fixture.sites[1].read_text()
    fixture.sites[1].write_text(content.replace('location / {', 'location ' + location + ' { proxy_pass http://127.0.0.1:8501; } location / {', 1))
    rejected(fixture)


def test_unlisted_upstream_include_to_accounting_is_rejected(fixture):
    upstream = fixture.root / 'hidden-upstream.conf'
    fixture.main.write_text('events {}\nhttp { include ' + str(upstream) + '; include ' + str(fixture.folder) + '/*; }\n')
    fixture.add(upstream, 'upstream hidden_accounting { server 127.0.0.1:8501; }\n')
    fixture.add(fixture.folder / 'hidden-site', 'server { listen 443 ssl; server_name hidden.example.invalid; location / { proxy_pass http://hidden_accounting; } }')
    rejected(fixture)


# 2026-10-20 hoyeon.han: http 상속 satisfy any는 승인된 auth_request를 우회할 수 있다.
@pytest.mark.parametrize('through_include', [False, True])
def test_global_http_satisfy_any_is_rejected_directly_or_via_include(fixture, through_include):
    if through_include:
        snippet = fixture.root / 'inherited-access.conf'
        fixture.add(snippet, 'satisfy any; allow all;\n')
        inherited = 'include ' + str(snippet) + ';'
    else:
        inherited = 'satisfy any; allow all;'
    fixture.main.write_text(fixture.main.read_text().replace('http {', 'http { ' + inherited, 1))
    rejected(fixture)


def test_unrelated_n8n_server_satisfy_any_does_not_change_office_policy(fixture):
    fixture.canary.write_text(fixture.canary.read_text().replace('server { listen 443', 'server { satisfy any; allow all; listen 443', 1))
    assert fixture.checker().ready(fixture.compose)['validated']


# 2026-10-20 hoyeon.han: 전역 오류 매핑도 미인증/권한거절 응답을 성공 응답으로 바꾸지 못한다.
# 2026-10-20 hoyeon.han: include와 선행 0 표기도 동일한 인증 오류 매핑으로 검사한다.
# @pytest.mark.parametrize('status', [401, 403])
# def test_global_http_auth_error_page_rewrite_is_rejected(fixture, status):
#     fixture.main.write_text(fixture.main.read_text().replace('http {', f'http {{ error_page {status} =200 /auth/login;', 1))
@pytest.mark.parametrize('status', [401, 403, '0401', '0403'])
@pytest.mark.parametrize('through_include', [False, True])
def test_global_http_auth_error_page_rewrite_is_rejected(fixture, status, through_include):
    directive = f'error_page {status} =200 /auth/login;'
    if through_include:
        snippet = fixture.root / 'inherited-error.conf'
        fixture.add(snippet, directive)
        directive = 'include ' + str(snippet) + ';'
    fixture.main.write_text(fixture.main.read_text().replace('http {', 'http { ' + directive, 1))
    rejected(fixture)


@pytest.mark.parametrize('status', [500, 502])
def test_unrelated_global_server_error_page_does_not_change_auth_denials(fixture, status):
    fixture.main.write_text(fixture.main.read_text().replace('http {', f'http {{ error_page {status} =503 /failure;', 1))
    assert fixture.checker().ready(fixture.compose)['validated']


def test_unrelated_n8n_server_error_page_does_not_change_office_policy(fixture):
    fixture.canary.write_text(fixture.canary.read_text().replace('server { listen 443', 'server { error_page 401 =200 /login; listen 443', 1))
    assert fixture.checker().ready(fixture.compose)['validated']


def test_unknown_host_direct_accounting_proxy_is_rejected(fixture):
    fixture.add(fixture.folder / 'hidden-site', 'server { listen 80; server_name hidden.example.invalid; location / { proxy_pass http://localhost:8501; } }')
    rejected(fixture)


# 2026-10-20 hoyeon.han: 문자열 표기를 바꾸거나 다른 프로토콜로 숨긴 보호 포트도 거부한다.
@pytest.mark.parametrize('directive', ['proxy_pass http://127.0.0.1:08501;',
                                     'proxy_pass http://[::1]:8502;',
                                     'fastcgi_pass 127.0.0.1:8503;',
                                     'grpc_pass grpc://127.0.0.1:8501;'])
def test_unlisted_nonstandard_or_ipv6_accounting_upstream_is_rejected(fixture, directive):
    fixture.add(fixture.folder / 'hidden-site', 'server { listen 80; server_name hidden.example.invalid; location / { ' + directive + ' } }')
    rejected(fixture)


@pytest.mark.parametrize('directive', ['root', 'alias'])
def test_unrelated_static_site_cannot_expose_real_accounting_directory(fixture, directive):
    fixture.add(fixture.folder / 'hidden-static', 'server { listen 80; server_name files.example.invalid; location / { '
                + directive + ' ' + str(fixture.app / 'processed') + '; } }')
    rejected(fixture)


def test_inventory_reports_unlisted_domains_and_runtime_without_requiring_ready(fixture):
    fixture.add(fixture.folder / 'hidden-site', 'server { listen 80; server_name bypass.example.invalid; location / { proxy_pass http://127.0.0.1:8501; } }')
    result = fixture.checker().inventory()
    assert not result['validated'] and result['issues']
    assert any(call == ['docker', 'ps', '-q'] for call in fixture.calls)
    assert any(call == ['ss', '-H', '-ltn'] for call in fixture.calls)


def test_duplicate_domain_and_unexpected_host_in_legacy_are_rejected(fixture):
    fixture.add(fixture.folder / 'duplicate', legacy_site(DOMAINS[1]))
    rejected(fixture)
    fixture.files.pop()
    fixture.sites[1].write_text(fixture.sites[1].read_text().replace('server_name ' + DOMAINS[1], 'server_name ' + DOMAINS[1] + ' unexpected.example.invalid'))
    rejected(fixture)


@pytest.mark.parametrize('mutation', ['extra-service', 'extra-port', 'wildcard', 'ipv6', 'host-network', 'udp', 'wrong-published'])
def test_candidate_compose_cannot_add_or_expose_protected_ports(fixture, mutation):
    candidate = copy.deepcopy(fixture.compose)
    service = candidate['services']['sollume-app']
    if mutation == 'extra-service':
        candidate['services']['extra'] = copy.deepcopy(service)
    elif mutation == 'extra-port':
        service['ports'].append({'host_ip': '127.0.0.1', 'published': '9501', 'target': 8501})
    elif mutation in ('wildcard', 'ipv6'):
        service['ports'][0]['host_ip'] = '0.0.0.0' if mutation == 'wildcard' else '::'
    elif mutation == 'host-network':
        service['network_mode'] = 'host'
    elif mutation == 'udp':
        service['ports'][0]['protocol'] = 'udp'
    else:
        service['ports'][0]['published'] = '9501'
    rejected(fixture, compose=candidate)


@pytest.mark.parametrize('mutation', ['unrelated-protected-port', 'extra-protected-port', 'host-network', 'unknown-listener', 'ipv6-listener'])
def test_runtime_extra_ports_other_owners_and_unknown_listeners_are_rejected(fixture, mutation):
    if mutation == 'unrelated-protected-port':
        fixture.records[-1]['HostConfig']['PortBindings']['8503/tcp'] = [{'HostIp': '0.0.0.0', 'HostPort': '8503'}]
        fixture.records[-1]['NetworkSettings']['Ports'] = copy.deepcopy(fixture.records[-1]['HostConfig']['PortBindings'])
    elif mutation == 'extra-protected-port':
        fixture.records[0]['HostConfig']['PortBindings']['8501/tcp'].append({'HostIp': '127.0.0.1', 'HostPort': '9501'})
        fixture.records[0]['NetworkSettings']['Ports'] = copy.deepcopy(fixture.records[0]['HostConfig']['PortBindings'])
    elif mutation == 'host-network':
        fixture.records[0]['HostConfig']['NetworkMode'] = 'host'
    else:
        fixture.ss += '\nLISTEN 0 4096 ' + ('[::]:8503' if mutation == 'ipv6-listener' else '0.0.0.0:8503') + ' 0.0.0.0:*'
    rejected(fixture)


def test_verify_rejects_remaining_wildcard_or_modified_policy(fixture):
    checker = fixture.checker()
    ready = checker.ready(fixture.compose)
    with pytest.raises(ValueError):
        checker.verify(fixture.compose, baseline=ready)
    fixture.set_runtime(secure=True)
    fixture.sites[1].write_text(fixture.sites[1].read_text() + '\n# changed after readiness\n')
    with pytest.raises(ValueError):
        checker.verify(fixture.compose, baseline=ready)


@pytest.mark.parametrize('status,location', [(200, None), (302, 'https://office1.sollumeesthe.com/'), (301, 'https://wrong.example.invalid/'), (301, '//office1.sollumeesthe.com/')])
def test_verify_checks_legacy_destination_not_only_status(fixture, status, location):
    checker = fixture.checker()
    ready = checker.ready(fixture.compose)
    fixture.set_runtime(secure=True)
    fixture.overrides['https://' + DOMAINS[1], '/'] = {'status': status, 'location': location}
    with pytest.raises(ValueError):
        checker.verify(fixture.compose, baseline=ready)


def test_active_file_dump_mismatch_and_change_during_read_are_rejected(fixture):
    count = 0
    original = fixture.dump
    def inconsistent_dump():
        return original().replace('server_name sol-fin.duckdns.org;', 'server_name mismatched.example.invalid;', 1)
    fixture.dump = inconsistent_dump
    rejected(fixture)
    fixture.dump = original
    def change(argv):
        nonlocal count
        if argv == ['sudo', '-n', 'nginx', '-T']:
            count += 1
            if count == 2:
                fixture.sites[1].write_text(fixture.sites[1].read_text() + '\n# racing change\n')
    fixture.on_run = change
    with pytest.raises(ValueError):
        fixture.checker().ready(fixture.compose)


def test_actual_container_metadata_change_during_check_is_rejected(fixture):
    count = 0
    def change(argv):
        nonlocal count
        if argv[:2] == ['docker', 'inspect']:
            count += 1
            if count == 2:
                fixture.records[0]['Id'] = '9' * 64
    fixture.on_run = change
    with pytest.raises(ValueError):
        fixture.checker().ready(fixture.compose)
