"""
SollumeLogger v3.0 테스트 스크립트

테스트 항목:
1. 일자별 로그 파일 생성 확인
2. 압축 핸들러 동작 확인
3. 스케줄러 시작 확인
4. 로그 메시지 기록 확인

작성일: 2025-12-10 hoyeon.han
"""

import sys
import os
from pathlib import Path
import time

# Src 디렉토리를 import 경로에 추가
# sys.path: 파이썬이 모듈을 찾을 때 검색하는 경로 리스트
# insert(0, ...): 맨 앞에 추가 (우선순위 최상)
sys.path.insert(0, str(Path(__file__).parent / "Src"))

# logger 모듈 import
from logger import get_logger


def test_logger_v3():
    """
    v3.0 로거 테스트

    테스트 시나리오:
    1. 로거 인스턴스 생성
    2. 다양한 레벨의 로그 기록
    3. 로그 파일 생성 확인
    4. 스케줄러 상태 확인

    2025-12-10 hoyeon.han: v3.0 테스트
    """
    print("\n" + "=" * 60)
    print("🧪 SollumeLogger v3.0 테스트")
    print("=" * 60)

    # 로거 인스턴스 가져오기
    # get_logger(): 싱글톤 패턴으로 로거 반환
    print("\n[1단계] 로거 인스턴스 생성")
    logger = get_logger()
    print(f"✅ 로거 버전: {logger.VERSION}")
    print(f"✅ 로그 디렉토리: {logger.log_dir}")
    print(f"✅ 아카이브 디렉토리: {logger.archive_dir}")

    # 스케줄러 상태 확인
    print("\n[2단계] 스케줄러 상태 확인")
    if logger.scheduler:
        print("✅ APScheduler 실행 중")
        # .get_jobs(): 등록된 작업 목록
        jobs = logger.scheduler.get_jobs()
        print(f"   등록된 작업 수: {len(jobs)}")
        for job in jobs:
            # job.id: 작업 ID
            # job.next_run_time: 다음 실행 시각
            print(f"   - {job.id}: 다음 실행 {job.next_run_time}")
    else:
        print("✅ threading.Timer 사용 중")

    # 테스트 로그 기록
    print("\n[3단계] 테스트 로그 기록")

    # INFO 로그
    logger.log_info("테스트 INFO 로그", event="test", level="info")
    print("✅ INFO 로그 기록")

    # WARNING 로그
    logger.log_warning("테스트 WARNING 로그", event="test", level="warning")
    print("✅ WARNING 로그 기록")

    # ERROR 로그
    try:
        # 의도적으로 에러 발생
        # ZeroDivisionError: 0으로 나누기 에러
        result = 1 / 0
    except Exception as e:
        logger.log_error("테스트 ERROR 로그", error=e, event="test", level="error")
        print("✅ ERROR 로그 기록 (의도적 에러)")

    # 처리 시작/완료 로그
    logger.log_processing_start("test_file.xlsx", "2025-12-10", 1024)
    print("✅ 처리 시작 로그 기록")

    # 잠시 대기 (로그 기록 시간 확보)
    # time.sleep(초): 지정된 시간만큼 프로그램 일시 정지
    time.sleep(0.5)

    logger.log_processing_success("test_file.xlsx", "2025-12-10", 10, 5, 1.5)
    print("✅ 처리 완료 로그 기록")

    # 성능 로그
    logger.log_performance("test_operation", 2.5, 1000)
    print("✅ 성능 로그 기록")

    # 로그 파일 확인
    print("\n[4단계] 로그 파일 생성 확인")

    # logs/ 디렉토리의 파일 목록
    log_files = list(logger.log_dir.glob('*.log'))
    json_files = list(logger.log_dir.glob('*.json'))

    print(f"\n📁 로그 파일 ({len(log_files)}개):")
    for f in sorted(log_files):
        # .stat().st_size: 파일 크기 (바이트)
        size_kb = f.stat().st_size / 1024
        print(f"  - {f.name} ({size_kb:.1f} KB)")

    print(f"\n📄 JSON 파일 ({len(json_files)}개):")
    for f in sorted(json_files):
        size_kb = f.stat().st_size / 1024
        print(f"  - {f.name} ({size_kb:.1f} KB)")

    # 로그 파일 내용 확인 (마지막 5줄)
    print("\n[5단계] 로그 파일 내용 확인 (app.log 마지막 5줄)")
    app_log = logger.log_dir / "app.log"
    if app_log.exists():
        # with: 파일을 안전하게 열고 자동으로 닫음
        # 'r': read mode (읽기 모드)
        # encoding='utf-8': 한글 지원
        with open(app_log, 'r', encoding='utf-8') as f:
            # .readlines(): 모든 줄을 리스트로 읽기
            # [-5:]: 마지막 5개 항목만
            lines = f.readlines()[-5:]
            for line in lines:
                # .strip(): 앞뒤 공백 제거
                print(f"  {line.strip()}")
    else:
        print("  ⚠️ app.log 파일이 아직 생성되지 않았습니다.")

    # 테스트 완료
    print("\n" + "=" * 60)
    print("✅ 모든 테스트 완료!")
    print("=" * 60)
    print("\n💡 확인 사항:")
    print("  1. logs/ 폴더에 app.log, errors.log 파일 생성 확인")
    print("  2. logs/ 폴더에 app_YYYYMMDD.json 파일 생성 확인")
    print("  3. 스케줄러가 정상 실행 중인지 확인")
    print("  4. 로그 내용이 올바르게 기록되었는지 확인")
    print("\n💡 다음 단계:")
    print("  1. 앱을 실행하여 실제 환경에서 테스트")
    print("  2. 7일 후 로그 압축 기능 동작 확인 (또는 수동 테스트)")
    print("  3. 30일 후 압축 파일 삭제 기능 동작 확인 (또는 수동 테스트)")


if __name__ == "__main__":
    """
    스크립트 직접 실행 시 수행

    사용법:
        python test_logger_v3.py

    2025-12-10 hoyeon.han: 메인 실행 블록
    """
    test_logger_v3()
