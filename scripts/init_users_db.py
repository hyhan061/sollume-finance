#!/usr/bin/env python3
# 2026-10-14 hoyeon.han: 기존 초기화 코드 보존(실행되지 않음)
# #!/usr/bin/env python3
# # init_users_db.py
# # 2025-12-17 hoyeon.han
# # 사용자 데이터베이스 초기화 스크립트
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
# def main():
#     """사용자 데이터베이스 초기화"""
#     print("=" * 50)
#     print("  솔루미랩 회계 시스템 - 사용자 DB 초기화")
#     print("=" * 50)
#     print()
#
#     # DB 경로
#     db_path = project_root / "database" / "users.db"
#
#     # DB 생성
#     print(f"📁 데이터베이스 생성: {db_path}")
#     user_db = UserDB(str(db_path))
#     print("✅ 데이터베이스 생성 완료")
#     print()
#
#     # 기존 사용자 확인
#     existing_users = user_db.list_users()
#     if existing_users:
#         print(f"⚠️  기존 사용자가 {len(existing_users)}명 있습니다:")
#         for user in existing_users:
#             admin_mark = " (관리자)" if user['is_admin'] else ""
#             print(f"   - {user['username']}{admin_mark}")
#         print()
#
#         response = input("기존 데이터를 유지하고 관리자 계정만 추가하시겠습니까? (y/N): ")
#         if response.lower() != 'y':
#             print("초기화를 취소했습니다.")
#             return
#
#     # 관리자 계정 생성
#     print("🔑 관리자 계정 생성")
#     print("-" * 50)
#
#     # 기본값 설정
#     default_username = "admin"
#     default_password = "admin123"
#     default_name = "시스템 관리자"
#
#     # 사용자 입력 받기
#     username = input(f"관리자 ID (기본: {default_username}): ").strip() or default_username
#     password = input(f"비밀번호 (기본: {default_password}): ").strip() or default_password
#
#     # 비밀번호 길이 확인
#     if len(password) < 8:
#         print("❌ 비밀번호는 최소 8자 이상이어야 합니다!")
#         return
#
#     full_name = input(f"이름 (기본: {default_name}): ").strip() or default_name
#     email = input("이메일 (선택사항): ").strip()
#
#     print()
#
#     # 계정 생성
#     success = user_db.create_user(
#         username=username,
#         password=password,
#         full_name=full_name,
#         email=email if email else "",
#         is_admin=True
#     )
#
#     if success:
#         print()
#         print("=" * 50)
#         print("  ✅ 초기화 완료!")
#         print("=" * 50)
#         print()
#         print("📋 생성된 관리자 계정:")
#         print(f"   - Username: {username}")
#         print(f"   - Password: {password}")
#         print(f"   - Name: {full_name}")
#         if email:
#             print(f"   - Email: {email}")
#         print()
#         print("⚠️  보안을 위해 초기 비밀번호를 변경하는 것을 권장합니다.")
#         print()
#         print("🚀 이제 Streamlit 앱을 실행하세요:")
#         print("   ./start.sh  (Mac/Linux)")
#         print("   또는")
#         print("   streamlit run Home.py")
#         print()
#     else:
#         print()
#         print("❌ 계정 생성 실패!")
#         print("   사용자 ID가 이미 존재하거나 오류가 발생했습니다.")
#         print()
#
#
# if __name__ == "__main__":
#     try:
#         main()
#     except KeyboardInterrupt:
#         print("\n\n초기화를 중단했습니다.")
#         sys.exit(0)
#     except Exception as e:
#         print(f"\n❌ 오류 발생: {e}")
#         sys.exit(1)

# 2026-10-14 hoyeon.han: 기존 DB는 보존하고 최초 관리자만 명시적으로 생성한다.
import argparse
import sys
from manage_users import load_service, create_user


def main():
    parser = argparse.ArgumentParser(description='기존 사용자·로그인 이력을 보존하는 최초 관리자 등록')
    parser.add_argument('--development', action='store_true', help='로컬 시작과 같은 개발키 사용')
    args = parser.parse_args()
    try:
        service = load_service(args.development)
        users = service.list_users_local()
        if any(user['is_admin'] and user['is_active'] for user in users):
            print('기존 활성 관리자가 있어 추가 계정을 자동 생성하지 않습니다.')
            print('기존 관리자의 MFA 등록 코드는 scripts/manage_users.py --enroll 사용자ID로 발급하세요.')
            print('로컬 환경에서는 위 명령에 --development를 추가하세요.')
            return 0
        print('기존 계정과 데이터는 유지합니다. 기본 비밀번호나 자동 생성 계정은 없습니다.')
        create_user(service, admin=True)
        return 0
    except KeyboardInterrupt:
        print('등록을 중단했습니다.')
        return 0
    except (ValueError, OSError) as exc:
        print(f'관리자 등록 실패: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
