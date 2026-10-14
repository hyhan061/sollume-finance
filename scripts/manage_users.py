#!/usr/bin/env python3
# 2026-10-14 hoyeon.han: 기존 CLI 보존(실행되지 않음)
# #!/usr/bin/env python3
# # manage_users.py
# # 2025-12-17 hoyeon.han
# # 사용자 관리 스크립트 (생성, 비밀번호 변경, 조회, 삭제)
#
# import sys
# from pathlib import Path
# import importlib.util
#
# # 프로젝트 루트
# project_root = Path(__file__).parent.parent
#
# # user_db.py를 직접 로드 (Src/__init__.py 우회)
# spec = importlib.util.spec_from_file_location(
#     "user_db",
#     project_root / "Src" / "user_db.py"
# )
# user_db_module = importlib.util.module_from_spec(spec)
# spec.loader.exec_module(user_db_module)
# UserDB = user_db_module.UserDB
#
#
# def print_menu():
#     """메뉴 출력"""
#     print("\n" + "=" * 50)
#     print("  솔루미랩 회계 시스템 - 사용자 관리")
#     print("=" * 50)
#     print("\n[메뉴]")
#     print("  1. 사용자 목록 조회")
#     print("  2. 사용자 생성")
#     print("  3. 비밀번호 변경")
#     print("  4. 사용자 비활성화 (삭제)")
#     print("  5. 사용자 활성화")
#     print("  0. 종료")
#     print()
#
#
# def list_users(db: UserDB):
#     """사용자 목록 조회"""
#     print("\n" + "=" * 80)
#     print("  사용자 목록")
#     print("=" * 80)
#
#     users = db.list_users()
#
#     if not users:
#         print("\n등록된 사용자가 없습니다.")
#         return
#
#     print(f"\n{'ID':<5} {'Username':<15} {'이름':<20} {'관리자':<8} {'상태':<8} {'로그인수':<10} {'최근로그인'}")
#     print("-" * 80)
#
#     for user in users:
#         user_id = user['id']
#         username = user['username']
#         full_name = user['full_name'] or '-'
#         is_admin = '✓' if user['is_admin'] else ''
#         is_active = '활성' if user['is_active'] else '비활성'
#         login_count = user['login_count']
#         last_login = user['last_login'] or '-'
#
#         if user['last_login']:
#             # 날짜만 표시
#             last_login = user['last_login'].split()[0]
#
#         print(f"{user_id:<5} {username:<15} {full_name:<20} {is_admin:<8} {is_active:<8} {login_count:<10} {last_login}")
#
#     print(f"\n총 {len(users)}명")
#
#
# def create_user(db: UserDB):
#     """사용자 생성"""
#     print("\n" + "=" * 50)
#     print("  새 사용자 생성")
#     print("=" * 50)
#
#     username = input("\n사용자 ID: ").strip()
#     if not username:
#         print("❌ 사용자 ID는 필수입니다.")
#         return
#
#     password = input("비밀번호 (최소 8자): ").strip()
#     if len(password) < 8:
#         print("❌ 비밀번호는 최소 8자 이상이어야 합니다.")
#         return
#
#     confirm = input("비밀번호 확인: ").strip()
#     if password != confirm:
#         print("❌ 비밀번호가 일치하지 않습니다.")
#         return
#
#     full_name = input("이름 (선택): ").strip()
#     email = input("이메일 (선택): ").strip()
#
#     is_admin_input = input("관리자 권한 부여? (y/N): ").strip().lower()
#     is_admin = is_admin_input == 'y'
#
#     print("\n생성할 사용자 정보:")
#     print(f"  - Username: {username}")
#     print(f"  - Name: {full_name or '(없음)'}")
#     print(f"  - Email: {email or '(없음)'}")
#     print(f"  - Admin: {'예' if is_admin else '아니오'}")
#     print()
#
#     confirm = input("생성하시겠습니까? (y/N): ").strip().lower()
#     if confirm != 'y':
#         print("취소되었습니다.")
#         return
#
#     success = db.create_user(
#         username=username,
#         password=password,
#         full_name=full_name,
#         email=email,
#         is_admin=is_admin
#     )
#
#     if success:
#         print(f"\n✅ 사용자 '{username}' 생성 완료!")
#     else:
#         print(f"\n❌ 사용자 생성 실패! (중복된 username일 수 있습니다)")
#
#
# def change_password(db: UserDB):
#     """비밀번호 변경"""
#     print("\n" + "=" * 50)
#     print("  비밀번호 변경")
#     print("=" * 50)
#
#     username = input("\n사용자 ID: ").strip()
#     if not username:
#         print("❌ 사용자 ID는 필수입니다.")
#         return
#
#     # 사용자 존재 확인
#     user = db.get_user(username)
#     if not user:
#         print(f"❌ 사용자 '{username}'를 찾을 수 없습니다.")
#         return
#
#     print(f"\n사용자 정보:")
#     print(f"  - Username: {user['username']}")
#     print(f"  - Name: {user['full_name'] or '(없음)'}")
#     print()
#
#     new_password = input("새 비밀번호 (최소 8자): ").strip()
#     if len(new_password) < 8:
#         print("❌ 비밀번호는 최소 8자 이상이어야 합니다.")
#         return
#
#     confirm = input("비밀번호 확인: ").strip()
#     if new_password != confirm:
#         print("❌ 비밀번호가 일치하지 않습니다.")
#         return
#
#     success = db.change_password(username, new_password)
#
#     if success:
#         print(f"\n✅ 비밀번호 변경 완료!")
#     else:
#         print(f"\n❌ 비밀번호 변경 실패!")
#
#
# def deactivate_user(db: UserDB):
#     """사용자 비활성화"""
#     print("\n" + "=" * 50)
#     print("  사용자 비활성화 (삭제)")
#     print("=" * 50)
#
#     username = input("\n사용자 ID: ").strip()
#     if not username:
#         print("❌ 사용자 ID는 필수입니다.")
#         return
#
#     # 사용자 존재 확인
#     user = db.get_user(username)
#     if not user:
#         print(f"❌ 사용자 '{username}'를 찾을 수 없습니다.")
#         return
#
#     print(f"\n사용자 정보:")
#     print(f"  - Username: {user['username']}")
#     print(f"  - Name: {user['full_name'] or '(없음)'}")
#     print(f"  - Admin: {'예' if user['is_admin'] else '아니오'}")
#     print()
#
#     confirm = input("⚠️  정말 비활성화하시겠습니까? (y/N): ").strip().lower()
#     if confirm != 'y':
#         print("취소되었습니다.")
#         return
#
#     success = db.delete_user(username)
#
#     if success:
#         print(f"\n✅ 사용자 '{username}' 비활성화 완료!")
#         print("   (데이터는 삭제되지 않았으며, 로그인만 차단됩니다)")
#     else:
#         print(f"\n❌ 사용자 비활성화 실패!")
#
#
# def activate_user(db: UserDB):
#     """사용자 활성화"""
#     print("\n" + "=" * 50)
#     print("  사용자 활성화")
#     print("=" * 50)
#
#     username = input("\n사용자 ID: ").strip()
#     if not username:
#         print("❌ 사용자 ID는 필수입니다.")
#         return
#
#     # 사용자 존재 확인
#     user = db.get_user(username)
#     if not user:
#         print(f"❌ 사용자 '{username}'를 찾을 수 없습니다.")
#         return
#
#     print(f"\n사용자 정보:")
#     print(f"  - Username: {user['username']}")
#     print(f"  - Name: {user['full_name'] or '(없음)'}")
#     print(f"  - 현재 상태: {'활성' if user['is_active'] else '비활성'}")
#     print()
#
#     if user['is_active']:
#         print("이미 활성화된 사용자입니다.")
#         return
#
#     confirm = input("활성화하시겠습니까? (y/N): ").strip().lower()
#     if confirm != 'y':
#         print("취소되었습니다.")
#         return
#
#     success = db.update_user(username, is_active=True)
#
#     if success:
#         print(f"\n✅ 사용자 '{username}' 활성화 완료!")
#     else:
#         print(f"\n❌ 사용자 활성화 실패!")
#
#
# def main():
#     """메인 함수"""
#     db_path = project_root / "database" / "users.db"
#
#     # DB 파일 존재 확인
#     if not db_path.exists():
#         print("❌ 사용자 데이터베이스가 없습니다!")
#         print("   먼저 다음 명령으로 초기화하세요:")
#         print("   python scripts/init_users_db.py")
#         sys.exit(1)
#
#     db = UserDB(str(db_path))
#
#     while True:
#         print_menu()
#
#         try:
#             choice = input("메뉴 선택: ").strip()
#
#             if choice == '0':
#                 print("\n프로그램을 종료합니다.")
#                 break
#             elif choice == '1':
#                 list_users(db)
#             elif choice == '2':
#                 create_user(db)
#             elif choice == '3':
#                 change_password(db)
#             elif choice == '4':
#                 deactivate_user(db)
#             elif choice == '5':
#                 activate_user(db)
#             else:
#                 print("\n❌ 잘못된 선택입니다. 다시 입력하세요.")
#
#         except KeyboardInterrupt:
#             print("\n\n프로그램을 종료합니다.")
#             break
#         except Exception as e:
#             print(f"\n❌ 오류 발생: {e}")
#
#
# if __name__ == "__main__":
#     main()

"""2026-10-14 hoyeon.han: 서버 운영자 전용 복구·관리 CLI. 웹 경로에 노출하지 않는다."""
from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'Src'))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from auth_gateway import get_service, load_security_settings
from security_service import PAGE_PERMISSIONS, SecurityError
from run_local import prepare_development_environment


def load_service(development=False):
    if sys.prefix == sys.base_prefix:
        raise ValueError('가상환경을 활성화한 뒤 실행하세요.')
    if development:
        os.environ.update(prepare_development_environment())
    return get_service(load_security_settings())


def read_password():
    # getpass는 입력과 비밀번호를 화면·로그에 출력하지 않는다. 기본 비밀번호는 없다.
    if not sys.stdin.isatty():
        raise SecurityError('비밀번호를 숨겨 입력할 수 있는 터미널에서 직접 실행하세요.')
    password = getpass('비밀번호(12자 이상): ')
    if password != getpass('비밀번호 확인: '):
        raise SecurityError('비밀번호가 일치하지 않습니다.')
    return password


def choose_user(service):
    username = input('사용자 ID: ').strip()
    user = service.get_user_local(username)
    if not user:
        raise SecurityError('해당 사용자가 없습니다.')
    return user


def print_users(service):
    users = service.list_users_local()
    for user in users:
        role = '관리자' if user['is_admin'] else '직원'
        state = '활성' if user['is_active'] else '정지'
        mfa = '등록' if user['mfa_enrolled'] else '등록 필요'
        print(f"{user['username']} | {user.get('full_name') or '-'} | {role} | {state} | 인증 앱: {mfa}")
    print(f'총 {len(users)}명. 계정·비밀번호 해시·인증키는 출력하지 않습니다.')


def enrollment(service, user):
    # 관리자에게 명시적으로 요청된 단회 등록 코드만 표시한다. 비밀번호나 MFA키는 출력하지 않는다.
    code = service.issue_enrollment_local(user['id'])
    print(f"'{user['username']}'의 기존 로그인과 인증 앱 등록을 폐기했습니다.")
    print('등록 코드(24시간, 1회 사용): ' + code)
    print('직원의 본인을 확인한 비공개 채널로 전달하세요. 관리자 화면이나 로그인 이력에 저장하지 마세요.')


def permissions_input():
    keys = list(PAGE_PERMISSIONS)
    for index, key in enumerate(keys, 1):
        print(f'{index}. {PAGE_PERMISSIONS[key]}')
    raw = input('허용 화면 번호를 쉼표로 입력(빈 값은 접근 없음): ').strip()
    if not raw:
        return []
    try:
        indexes = [int(value.strip()) for value in raw.split(',')]
        if any(index < 1 or index > len(keys) for index in indexes):
            raise ValueError
        return list(dict.fromkeys(keys[index - 1] for index in indexes))
    except ValueError:
        raise SecurityError('표시된 화면 번호만 입력하세요.')


def create_user(service, *, admin=None):
    username = input('새 사용자 ID: ').strip()
    full_name = input('이름: ').strip()
    email = input('이메일(선택): ').strip()
    if admin is None:
        admin = input('관리자로 생성? (y/N): ').strip().lower() == 'y'
    permissions = [] if admin else permissions_input()
    password = read_password()
    user = service.bootstrap_user(username, password, full_name, email, is_admin=admin, permissions=permissions)
    print(f"'{user['username']}' 계정을 생성했습니다. 최초 로그인에서 새 비밀번호와 인증 앱을 등록해야 합니다.")
    enrollment(service, user)


def main():
    parser = argparse.ArgumentParser(description='서버 운영자 전용 사용자 관리(기존 계정·데이터 유지)')
    parser.add_argument('--development', action='store_true', help='로컬 시작 스크립트와 같은 개발키 사용')
    parser.add_argument('--list', action='store_true', help='계정 목록 조회')
    parser.add_argument('--enroll', metavar='USER', help='해당 계정의 MFA 초기화와 단회 등록 코드 발급')
    args = parser.parse_args()
    try:
        service = load_service(args.development)
        if args.list:
            print_users(service)
            return 0
        if args.enroll:
            user = service.get_user_local(args.enroll)
            if not user:
                raise SecurityError('해당 사용자가 없습니다.')
            if input('기존 로그인·인증 앱을 폐기하고 재등록 코드를 발급합니까? (y/N): ').strip().lower() == 'y':
                enrollment(service, user)
            return 0
        while True:
            print('\n1 목록  2 생성  3 비밀번호 초기화  4 계정 정지  5 활성화  6 MFA 재등록  7 화면 권한  8 관리자 권한  0 종료')
            choice = input('선택: ').strip()
            try:
                if choice == '0':
                    return 0
                if choice == '1':
                    print_users(service)
                elif choice == '2':
                    create_user(service)
                elif choice in {'3', '4', '5', '6', '7', '8'}:
                    user = choose_user(service)
                    if choice == '3':
                        service.reset_password_local(user['id'], read_password())
                        print('기존 로그인 해제 및 비밀번호 초기화 완료. 다음 로그인에서 변경이 필요합니다.')
                    elif choice in {'4', '5'}:
                        if input('계정 활성 상태를 변경합니까? (y/N): ').strip().lower() == 'y':
                            service.update_user_local(user['id'], is_active=choice == '5')
                            print('계정 활성 상태 변경 완료. 기존 데이터는 유지됩니다.')
                    elif choice == '6':
                        if input('기존 인증 앱을 폐기하고 재등록합니까? (y/N): ').strip().lower() == 'y':
                            enrollment(service, user)
                    elif choice == '7':
                        service.update_user_local(user['id'], permissions=permissions_input())
                        print('화면 권한 변경 완료. 기존 로그인은 해제됩니다.')
                    elif choice == '8':
                        admin = input('관리자로 변경? (y/N): ').strip().lower() == 'y'
                        service.update_user_local(user['id'], is_admin=admin)
                        print('역할 변경 완료. 기존 로그인은 해제됩니다.')
                else:
                    print('표시된 메뉴 번호를 입력하세요.')
            except (SecurityError, ValueError) as exc:
                print(f'처리하지 못했습니다: {exc}')
    except KeyboardInterrupt:
        print('\n종료합니다.')
        return 0
    except (ValueError, OSError) as exc:
        print(f'인증 설정·데이터베이스를 확인하세요: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
