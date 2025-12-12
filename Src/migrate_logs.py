"""
기존 로그 파일 마이그레이션 스크립트

기능:
- logs/app.log → 일자별 app_YYYYMMDD.log로 분리 (불가능, 날짜 정보 없음)
- logs/errors.log → 일자별 errors_YYYYMMDD.log로 분리 (불가능, 날짜 정보 없음)
- 기존 파일은 백업 폴더로 이동

주의사항:
- 기존 로그 파일에는 날짜별로 분리할 수 있는 정보가 부족함
- 따라서 기존 로그는 backup/ 폴더로 이동만 함
- 새로운 v3.0 로거는 처음부터 일자별로 생성됨

작성일: 2025-12-10 hoyeon.han
버전: 1.0
"""

from pathlib import Path
from datetime import datetime
import shutil


def migrate_logs(log_dir: str = "logs"):
    """
    기존 로그 파일을 백업 폴더로 이동

    처리 과정:
    1. logs/ 디렉토리 확인
    2. logs/backup/ 폴더 생성
    3. 기존 app.log, errors.log를 backup/으로 이동
    4. backup/ 파일명에 현재 날짜 추가 (백업 시점 표시)

    Args:
        log_dir: 로그 디렉토리 경로 (기본: logs)

    Returns:
        이동한 파일 개수

    2025-12-10 hoyeon.han: 로그 v3.0 마이그레이션
    """
    # Path(): 파일 경로를 객체로 다룸
    log_dir_path = Path(log_dir)

    # 로그 디렉토리가 없으면 생성
    # exist_ok=True: 이미 존재해도 에러 안 남
    log_dir_path.mkdir(exist_ok=True)

    # 백업 폴더 생성
    # logs/backup 폴더에 기존 로그 파일 이동
    backup_dir = log_dir_path / "backup"
    backup_dir.mkdir(exist_ok=True)

    # 현재 날짜 (백업 파일명에 사용)
    # strftime(): 날짜를 문자열로 포맷
    # %Y%m%d: 20251210 형식
    today = datetime.now().strftime('%Y%m%d')

    # 이동한 파일 카운트
    moved_count = 0

    # 마이그레이션 대상 파일 목록
    # app.log: 일반 로그
    # errors.log: 에러 로그
    # app_*.json: JSON 로그 (여러 개 있을 수 있음)
    files_to_migrate = [
        'app.log',
        'errors.log'
    ]

    # 각 파일 처리
    for filename in files_to_migrate:
        # 원본 파일 경로
        source_file = log_dir_path / filename

        # 파일이 존재하는지 확인
        # .exists(): 파일/폴더가 존재하면 True
        if source_file.exists():
            # 백업 파일 경로
            # 파일명에 백업 날짜 추가
            # 예: app.log → backup/app_backup_20251210.log
            backup_filename = f"{source_file.stem}_backup_{today}{source_file.suffix}"
            dest_file = backup_dir / backup_filename

            # 파일 이동
            # shutil.move(): 파일을 다른 위치로 이동 (복사 후 삭제)
            shutil.move(str(source_file), str(dest_file))

            # 이동 완료 메시지
            print(f"✅ 백업 완료: {filename} → backup/{backup_filename}")
            moved_count += 1
        else:
            # 파일이 없으면 건너뜀
            print(f"⏭️ 파일 없음: {filename} (건너뜀)")

    # JSON 로그 파일들도 백업
    # app_*.json 패턴의 모든 파일 찾기
    # .glob(): 패턴에 맞는 파일들 찾기
    for json_file in log_dir_path.glob('app_*.json'):
        # 백업 파일명: 기존 이름 유지 (이미 날짜가 포함되어 있음)
        # 예: app_20251201.json → backup/app_20251201.json
        dest_file = backup_dir / json_file.name

        # 파일 이동
        shutil.move(str(json_file), str(dest_file))

        print(f"✅ JSON 백업 완료: {json_file.name} → backup/{json_file.name}")
        moved_count += 1

    # 마이그레이션 완료 메시지
    print("\n" + "=" * 60)
    print(f"📦 마이그레이션 완료: {moved_count}개 파일을 backup/ 폴더로 이동")
    print(f"📁 백업 위치: {backup_dir}")
    print("=" * 60)
    print("\n💡 안내:")
    print("  - 새로운 v3.0 로거는 일자별 로그 파일을 자동 생성합니다.")
    print("  - 7일 이상 된 로그는 자동으로 압축됩니다. (archive/ 폴더)")
    print("  - 30일 이상 된 압축 파일은 자동으로 삭제됩니다.")
    print("  - 백업 파일은 수동으로 삭제하거나 보관하세요.")

    return moved_count


def check_migration_status(log_dir: str = "logs"):
    """
    마이그레이션 상태 확인

    기능:
    - logs/ 폴더의 현재 상태 출력
    - backup/ 폴더의 파일 목록 출력
    - archive/ 폴더의 압축 파일 목록 출력

    Args:
        log_dir: 로그 디렉토리 경로 (기본: logs)

    2025-12-10 hoyeon.han: 마이그레이션 상태 확인
    """
    log_dir_path = Path(log_dir)

    print("\n" + "=" * 60)
    print("📊 로그 디렉토리 상태")
    print("=" * 60)

    # logs/ 폴더의 파일 목록
    print(f"\n📁 {log_dir}/ 폴더:")
    # .iterdir(): 디렉토리의 모든 항목 나열
    # .is_file(): 파일인지 확인 (폴더 제외)
    log_files = [f for f in log_dir_path.iterdir() if f.is_file()]
    if log_files:
        # sorted(): 정렬 (알파벳순)
        # .name: 파일명만 (경로 제외)
        for f in sorted(log_files):
            # .stat().st_size: 파일 크기 (바이트)
            # / 1024: KB로 변환
            size_kb = f.stat().st_size / 1024
            print(f"  - {f.name} ({size_kb:.1f} KB)")
    else:
        print("  (파일 없음)")

    # backup/ 폴더의 파일 목록
    backup_dir = log_dir_path / "backup"
    if backup_dir.exists():
        print(f"\n📦 backup/ 폴더:")
        backup_files = [f for f in backup_dir.iterdir() if f.is_file()]
        if backup_files:
            for f in sorted(backup_files):
                size_kb = f.stat().st_size / 1024
                print(f"  - {f.name} ({size_kb:.1f} KB)")
        else:
            print("  (파일 없음)")
    else:
        print(f"\n📦 backup/ 폴더: (존재하지 않음)")

    # archive/ 폴더의 압축 파일 목록
    archive_dir = log_dir_path / "archive"
    if archive_dir.exists():
        print(f"\n🗜️ archive/ 폴더:")
        archive_files = [f for f in archive_dir.iterdir() if f.is_file()]
        if archive_files:
            for f in sorted(archive_files):
                size_kb = f.stat().st_size / 1024
                print(f"  - {f.name} ({size_kb:.1f} KB)")
        else:
            print("  (파일 없음)")
    else:
        print(f"\n🗜️ archive/ 폴더: (존재하지 않음)")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    """
    스크립트 직접 실행 시 수행

    사용법:
        python Src/migrate_logs.py

    __name__ == "__main__" 이란?
    - 이 스크립트를 직접 실행하면 __name__은 "__main__"
    - 다른 파일에서 import하면 __name__은 모듈명 (예: "migrate_logs")
    - 따라서 직접 실행할 때만 이 블록이 실행됨

    2025-12-10 hoyeon.han: 메인 실행 블록
    """
    print("\n" + "=" * 60)
    print("🔄 로그 마이그레이션 스크립트 v1.0")
    print("=" * 60)

    # 마이그레이션 전 상태 확인
    print("\n[1단계] 마이그레이션 전 상태 확인")
    check_migration_status()

    # 사용자 확인
    # input(): 사용자 입력 받기
    # .strip(): 앞뒤 공백 제거
    # .lower(): 소문자로 변환
    response = input("📌 마이그레이션을 진행하시겠습니까? (y/n): ").strip().lower()

    if response == 'y':
        # 마이그레이션 실행
        print("\n[2단계] 마이그레이션 실행")
        migrate_logs()

        # 마이그레이션 후 상태 확인
        print("\n[3단계] 마이그레이션 후 상태 확인")
        check_migration_status()

        print("\n✅ 마이그레이션 완료!")
        print("💡 이제 애플리케이션을 실행하면 새로운 v3.0 로거가 작동합니다.")

    else:
        print("\n❌ 마이그레이션 취소")
