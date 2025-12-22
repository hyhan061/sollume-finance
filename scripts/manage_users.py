#!/usr/bin/env python3
# manage_users.py
# 2025-12-17 hoyeon.han
# 사용자 관리 스크립트 (생성, 비밀번호 변경, 조회, 삭제)

import sys
from pathlib import Path
import importlib.util

# 프로젝트 루트
project_root = Path(__file__).parent.parent

# user_db.py를 직접 로드 (Src/__init__.py 우회)
spec = importlib.util.spec_from_file_location(
    "user_db",
    project_root / "Src" / "user_db.py"
)
user_db_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(user_db_module)
UserDB = user_db_module.UserDB


def print_menu():
    """메뉴 출력"""
    print("\n" + "=" * 50)
    print("  솔루미랩 회계 시스템 - 사용자 관리")
    print("=" * 50)
    print("\n[메뉴]")
    print("  1. 사용자 목록 조회")
    print("  2. 사용자 생성")
    print("  3. 비밀번호 변경")
    print("  4. 사용자 비활성화 (삭제)")
    print("  5. 사용자 활성화")
    print("  0. 종료")
    print()


def list_users(db: UserDB):
    """사용자 목록 조회"""
    print("\n" + "=" * 80)
    print("  사용자 목록")
    print("=" * 80)

    users = db.list_users()

    if not users:
        print("\n등록된 사용자가 없습니다.")
        return

    print(f"\n{'ID':<5} {'Username':<15} {'이름':<20} {'관리자':<8} {'상태':<8} {'로그인수':<10} {'최근로그인'}")
    print("-" * 80)

    for user in users:
        user_id = user['id']
        username = user['username']
        full_name = user['full_name'] or '-'
        is_admin = '✓' if user['is_admin'] else ''
        is_active = '활성' if user['is_active'] else '비활성'
        login_count = user['login_count']
        last_login = user['last_login'] or '-'

        if user['last_login']:
            # 날짜만 표시
            last_login = user['last_login'].split()[0]

        print(f"{user_id:<5} {username:<15} {full_name:<20} {is_admin:<8} {is_active:<8} {login_count:<10} {last_login}")

    print(f"\n총 {len(users)}명")


def create_user(db: UserDB):
    """사용자 생성"""
    print("\n" + "=" * 50)
    print("  새 사용자 생성")
    print("=" * 50)

    username = input("\n사용자 ID: ").strip()
    if not username:
        print("❌ 사용자 ID는 필수입니다.")
        return

    password = input("비밀번호 (최소 8자): ").strip()
    if len(password) < 8:
        print("❌ 비밀번호는 최소 8자 이상이어야 합니다.")
        return

    confirm = input("비밀번호 확인: ").strip()
    if password != confirm:
        print("❌ 비밀번호가 일치하지 않습니다.")
        return

    full_name = input("이름 (선택): ").strip()
    email = input("이메일 (선택): ").strip()

    is_admin_input = input("관리자 권한 부여? (y/N): ").strip().lower()
    is_admin = is_admin_input == 'y'

    print("\n생성할 사용자 정보:")
    print(f"  - Username: {username}")
    print(f"  - Name: {full_name or '(없음)'}")
    print(f"  - Email: {email or '(없음)'}")
    print(f"  - Admin: {'예' if is_admin else '아니오'}")
    print()

    confirm = input("생성하시겠습니까? (y/N): ").strip().lower()
    if confirm != 'y':
        print("취소되었습니다.")
        return

    success = db.create_user(
        username=username,
        password=password,
        full_name=full_name,
        email=email,
        is_admin=is_admin
    )

    if success:
        print(f"\n✅ 사용자 '{username}' 생성 완료!")
    else:
        print(f"\n❌ 사용자 생성 실패! (중복된 username일 수 있습니다)")


def change_password(db: UserDB):
    """비밀번호 변경"""
    print("\n" + "=" * 50)
    print("  비밀번호 변경")
    print("=" * 50)

    username = input("\n사용자 ID: ").strip()
    if not username:
        print("❌ 사용자 ID는 필수입니다.")
        return

    # 사용자 존재 확인
    user = db.get_user(username)
    if not user:
        print(f"❌ 사용자 '{username}'를 찾을 수 없습니다.")
        return

    print(f"\n사용자 정보:")
    print(f"  - Username: {user['username']}")
    print(f"  - Name: {user['full_name'] or '(없음)'}")
    print()

    new_password = input("새 비밀번호 (최소 8자): ").strip()
    if len(new_password) < 8:
        print("❌ 비밀번호는 최소 8자 이상이어야 합니다.")
        return

    confirm = input("비밀번호 확인: ").strip()
    if new_password != confirm:
        print("❌ 비밀번호가 일치하지 않습니다.")
        return

    success = db.change_password(username, new_password)

    if success:
        print(f"\n✅ 비밀번호 변경 완료!")
    else:
        print(f"\n❌ 비밀번호 변경 실패!")


def deactivate_user(db: UserDB):
    """사용자 비활성화"""
    print("\n" + "=" * 50)
    print("  사용자 비활성화 (삭제)")
    print("=" * 50)

    username = input("\n사용자 ID: ").strip()
    if not username:
        print("❌ 사용자 ID는 필수입니다.")
        return

    # 사용자 존재 확인
    user = db.get_user(username)
    if not user:
        print(f"❌ 사용자 '{username}'를 찾을 수 없습니다.")
        return

    print(f"\n사용자 정보:")
    print(f"  - Username: {user['username']}")
    print(f"  - Name: {user['full_name'] or '(없음)'}")
    print(f"  - Admin: {'예' if user['is_admin'] else '아니오'}")
    print()

    confirm = input("⚠️  정말 비활성화하시겠습니까? (y/N): ").strip().lower()
    if confirm != 'y':
        print("취소되었습니다.")
        return

    success = db.delete_user(username)

    if success:
        print(f"\n✅ 사용자 '{username}' 비활성화 완료!")
        print("   (데이터는 삭제되지 않았으며, 로그인만 차단됩니다)")
    else:
        print(f"\n❌ 사용자 비활성화 실패!")


def activate_user(db: UserDB):
    """사용자 활성화"""
    print("\n" + "=" * 50)
    print("  사용자 활성화")
    print("=" * 50)

    username = input("\n사용자 ID: ").strip()
    if not username:
        print("❌ 사용자 ID는 필수입니다.")
        return

    # 사용자 존재 확인
    user = db.get_user(username)
    if not user:
        print(f"❌ 사용자 '{username}'를 찾을 수 없습니다.")
        return

    print(f"\n사용자 정보:")
    print(f"  - Username: {user['username']}")
    print(f"  - Name: {user['full_name'] or '(없음)'}")
    print(f"  - 현재 상태: {'활성' if user['is_active'] else '비활성'}")
    print()

    if user['is_active']:
        print("이미 활성화된 사용자입니다.")
        return

    confirm = input("활성화하시겠습니까? (y/N): ").strip().lower()
    if confirm != 'y':
        print("취소되었습니다.")
        return

    success = db.update_user(username, is_active=True)

    if success:
        print(f"\n✅ 사용자 '{username}' 활성화 완료!")
    else:
        print(f"\n❌ 사용자 활성화 실패!")


def main():
    """메인 함수"""
    db_path = project_root / "database" / "users.db"

    # DB 파일 존재 확인
    if not db_path.exists():
        print("❌ 사용자 데이터베이스가 없습니다!")
        print("   먼저 다음 명령으로 초기화하세요:")
        print("   python scripts/init_users_db.py")
        sys.exit(1)

    db = UserDB(str(db_path))

    while True:
        print_menu()

        try:
            choice = input("메뉴 선택: ").strip()

            if choice == '0':
                print("\n프로그램을 종료합니다.")
                break
            elif choice == '1':
                list_users(db)
            elif choice == '2':
                create_user(db)
            elif choice == '3':
                change_password(db)
            elif choice == '4':
                deactivate_user(db)
            elif choice == '5':
                activate_user(db)
            else:
                print("\n❌ 잘못된 선택입니다. 다시 입력하세요.")

        except KeyboardInterrupt:
            print("\n\n프로그램을 종료합니다.")
            break
        except Exception as e:
            print(f"\n❌ 오류 발생: {e}")


if __name__ == "__main__":
    main()
