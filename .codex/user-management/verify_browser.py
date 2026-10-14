# 2026-10-14 hoyeon.han: 임시 DB·격리 브라우저에서 실제 로그인/업무 WebSocket 회수 확인.
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
import requests
import pyotp
from cryptography.fernet import Fernet
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Src'))
from security_service import SecurityService


def main():
    results = []
    children = []
    with tempfile.TemporaryDirectory(prefix='sollume-auth-browser-', dir='/private/tmp') as temp:
        temp = Path(temp)
        key = Fernet.generate_key().decode()
        db = temp / 'users.db'
        service = SecurityService(db, key, temp / 'processed' / 'secure_downloads')
        admin = service.bootstrap_user('qa_admin', 'Initial-Admin-2026!', is_admin=True)
        staff = service.bootstrap_user('qa_staff', 'Initial-Staff-2026!', is_admin=False, permissions=['order-summary'])
        invites = {admin['username']: service.issue_enrollment_local(admin['id']), staff['username']: service.issue_enrollment_local(staff['id'])}
        env = dict(os.environ, AUTH_ENV='development', AUTH_ENCRYPTION_KEY=key,
                   AUTH_DB_PATH=str(db), AUTH_DOWNLOAD_DIR=str(temp / 'processed' / 'secure_downloads'),
                   AUTH_PUBLIC_ORIGIN='http://localhost:18703', AUTH_DEV_APP_ORIGIN='http://localhost:18701',
                   TRUSTED_PROXY_NETWORKS='127.0.0.1/32,::1/128', PYTHONPATH=str(ROOT / 'Src'))
        for name in ('AUTH_SIGNING_KEY',): env.pop(name, None)
        logfile = (temp / 'server.log').open('w')
        try:
            children.append(subprocess.Popen([sys.executable, '-m', 'flask', '--app', 'auth_gateway:create_app', 'run', '--host=127.0.0.1', '--port=18703', '--no-reload', '--no-debugger'], env=env, cwd=temp, stdout=logfile, stderr=logfile))
            children.append(subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'Home.py'), '--server.address=127.0.0.1', '--server.port=18701', '--server.headless=true', '--server.fileWatcherType=none', '--server.enableCORS=true', '--server.enableXsrfProtection=true', '--browser.serverAddress=localhost', '--browser.serverPort=18701', '--browser.gatherUsageStats=false'], env=env, cwd=temp, stdout=logfile, stderr=logfile))
            for _ in range(100):
                try:
                    if requests.get('http://localhost:18703/auth/health', timeout=.5).status_code == 200 and requests.get('http://localhost:18701/_stcore/health', timeout=.5).status_code == 200: break
                except requests.RequestException: pass
                if any(p.poll() is not None for p in children): raise RuntimeError('검증 서버 시작 실패')
                time.sleep(.2)
            else: raise RuntimeError('검증 서버 준비 시간 초과')
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless=True)
                # 2026-10-14 hoyeon.han: 재로그인 검증에도 합성 인증 앱을 사용한다.
                enrollment_secrets = {}
                def enroll(context, username, initial, new):
                    page = context.new_page()
                    page.on('request', lambda r: print('POST 출처 검증:', {'origin':r.headers.get('origin'), 'sec-fetch-site':r.headers.get('sec-fetch-site')}) if r.method == 'POST' else None)
                    page.goto('http://localhost:18703/auth/login')
                    page.get_by_label('사용자 ID').fill(username)
                    page.get_by_label('비밀번호', exact=True).fill(initial)
                    page.get_by_role('button', name='다음: 2단계 인증').click()
                    try: page.locator('#enrollment_code').wait_for(timeout=5000)
                    except Exception:
                        print('비밀번호 제출 후 주소:',page.url)
                        print('표시 내용:',page.locator('body').inner_text()[:1500])
                        print('서버 진단:',(temp / 'server.log').read_text()[-2200:])
                        raise
                    page.get_by_label('일회용 등록 코드').fill(invites[username])
                    page.get_by_role('button', name='등록 코드 확인').click()
                    challenge = next(c['value'] for c in context.cookies() if c['name'] == 'sollume_dev_challenge')
                    secret = service.get_challenge(challenge)['pending_secret']
                    enrollment_secrets[username] = secret
                    page.get_by_label('새 비밀번호 — 12자 이상', exact=True).fill(new)
                    page.get_by_label('새 비밀번호 확인', exact=True).fill(new)
                    page.get_by_label('연결한 인증 앱의 6자리 번호').fill(pyotp.TOTP(secret).now())
                    page.get_by_role('button', name='등록 완료하고 로그인').click()
                    page.wait_for_url('http://localhost:18701/')
                    page.get_by_text(username, exact=True).wait_for(timeout=20000)
                    token = next(c['value'] for c in context.cookies() if c['name'] == 'sollume_dev_session')
                    return page, token
                admin_context = browser.new_context()
                admin_page, admin_token = enroll(admin_context, 'qa_admin', 'Initial-Admin-2026!', 'Changed-Admin-2026!')
                admin_page.get_by_role('link', name='사용자관리', exact=True).click()
                admin_page.get_by_role('button', name='직원 계정 생성', exact=True).wait_for(timeout=20000)
                assert not admin_page.locator('[data-testid="stException"]').count()
                results.append('실제 브라우저 최초 MFA 등록 및 관리자 사용자관리 화면 접근')
                admin_page.screenshot(path=str(ROOT / '.Codex/user-management/admin-browser.png'), full_page=True)
                staff_context = browser.new_context()
                staff_page, staff_token = enroll(staff_context, 'qa_staff', 'Initial-Staff-2026!', 'Changed-Staff-2026!')
                assert staff_page.get_by_role('link', name='요약', exact=True).count() == 1
                assert staff_page.get_by_role('link', name='사용자관리', exact=True).count() == 0
                assert staff_page.get_by_role('link', name='시스템 관리', exact=True).count() == 0
                results.append('직원 브라우저 메뉴에서 허용 화면만 표시')
                # 2026-10-14 hoyeon.han: 실제 관리자 폼에서 직원 권한을 바꾸고 재로그인 결과를 검증한다.
                admin_page.reload()
                admin_page.get_by_role('tab', name='계정·접근 권한 설정', exact=True).click()
                admin_page.get_by_test_id('stSelectbox').filter(has_text='설정할 직원').get_by_role('combobox').click()
                admin_page.get_by_role('option', name='qa_staff ·', exact=False).click()
                permission = admin_page.get_by_test_id('stMultiSelect').filter(has_text='직원에게 허용할 화면').get_by_role('combobox')
                permission.click()
                permission.press('Backspace')
                permission.fill('일별 전표')
                admin_page.get_by_role('option', name='일별 전표', exact=True).click()
                permission.press('Escape')
                admin_page.screenshot(path=str(ROOT / '.Codex/user-management/permissions-browser.png'), full_page=True)
                admin_page.get_by_role('button', name='계정과 화면 권한 저장', exact=True).click()
                for _ in range(100):
                    if service.get_user_local('qa_staff')['permissions'] == ['daily-voucher']: break
                    time.sleep(.1)
                else: raise AssertionError('관리자 폼의 권한 변경이 저장되지 않음')
                staff_page.get_by_role('link', name='🔒 로그인 화면으로 이동').wait_for(timeout=25000)
                assert not staff_page.get_by_role('link', name='요약', exact=True).count()
                results.append('관리자 폼의 직원별 권한 변경과 열린 기존 로그인 회수')
                # 동일 OTP 재사용을 허용하지 않으므로 실제 인증 앱의 다음 시간 구간을 기다린다.
                time.sleep(31 - time.time() % 30)
                staff_page.goto('http://localhost:18703/auth/login')
                staff_page.get_by_label('사용자 ID').fill('qa_staff')
                staff_page.get_by_label('비밀번호', exact=True).fill('Changed-Staff-2026!')
                staff_page.get_by_role('button', name='다음: 2단계 인증').click()
                staff_page.get_by_label('인증 앱 번호', exact=True).fill(pyotp.TOTP(enrollment_secrets['qa_staff']).now())
                staff_page.get_by_role('button', name='인증하고 로그인', exact=True).click()
                staff_page.wait_for_url('http://localhost:18701/')
                staff_page.get_by_role('link', name='일별 전표', exact=True).wait_for(timeout=20000)
                assert not staff_page.get_by_role('link', name='요약', exact=True).count()
                assert not staff_page.get_by_role('link', name='사용자관리', exact=True).count()
                results.append('직원 MFA 재로그인 후 관리자 폼에서 변경한 화면 권한만 적용')
                # 이미 열린 Streamlit WebSocket은 새 인증 HTTP 요청 없이 다음 주기 검사로 폐기해야 함.
                # service.admin_update_user(admin_token, staff['id'], is_active=False)
                # 2026-10-14 hoyeon.han: 계정 정지도 실제 관리자 폼에서 실행한다.
                admin_page.get_by_role('tab', name='계정·접근 권한 설정', exact=True).click()
                admin_page.get_by_test_id('stCheckbox').filter(has_text='계정 활성').get_by_text('계정 활성', exact=True).click()
                admin_page.get_by_role('button', name='계정과 화면 권한 저장', exact=True).click()
                for _ in range(100):
                    if not service.get_user_local('qa_staff')['is_active']: break
                    time.sleep(.1)
                else: raise AssertionError('관리자 폼의 직원 정지가 저장되지 않음')
                staff_page.get_by_role('link', name='🔒 로그인 화면으로 이동').wait_for(timeout=25000)
                assert staff_page.get_by_role('link', name='요약', exact=True).count() == 0
                assert staff_page.get_by_text('qa_staff', exact=True).count() == 0
                results.append('이미 열린 WebSocket의 계정 정지 후 주기 검사·업무 화면 정리')
                admin_page.get_by_role('link', name='로그아웃', exact=True).click()
                admin_page.get_by_role('button', name='로그아웃', exact=True).click()
                admin_page.wait_for_url('**/auth/login')
                assert not any(c['name'] == 'sollume_dev_session' for c in admin_context.cookies())
                try: service.get_session(admin_token)
                except ValueError: pass
                else: raise AssertionError('로그아웃 세션이 남음')
                results.append('브라우저 POST 로그아웃 후 쿠키 제거와 DB 세션 폐기')
                browser.close()
        finally:
            for p in reversed(children):
                if p.poll() is None: p.terminate()
            for p in reversed(children):
                try: p.wait(timeout=5)
                except subprocess.TimeoutExpired: p.kill(); p.wait()
            logfile.close()
    report = {'passed': len(results), 'scenarios': results, 'data': '합성 임시 DB, 실제 업무자료 미사용', 'browser': '격리된 headless Chrome', 'scope': 'development loopback, production TLS/Nginx 별도 검증'}
    (ROOT / '.Codex/user-management/browser-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__': main()
