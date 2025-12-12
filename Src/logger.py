"""
솔루미랩 구조화된 로깅 시스템 v3.0
텍스트 로그와 JSON 로그를 동시에 제공하여 사람과 기계 모두 읽기 쉽게 함

주요 기능:
- 일자별 로그 파일 자동 생성 (텍스트, JSON, 에러)
- 7일 이상 된 로그 자동 압축 (gzip)
- 30일 이상 된 압축 파일 자동 삭제
- APScheduler를 통한 자동 로그 관리

작성 이력:
- 2025-11-29 hoyeon.han: 초기 버전 (v2.0)
- 2025-12-10 hoyeon.han: 로그 로테이션 및 압축 추가 (v3.0)
"""

import logging
# 2025-12-10 hoyeon.han: TimedRotatingFileHandler 추가 (일자별 로그 로테이션)
from logging.handlers import TimedRotatingFileHandler
import json
import gzip  # 2025-12-10 hoyeon.han: 로그 압축용
import shutil  # 2025-12-10 hoyeon.han: 파일 복사용
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
import traceback
import re  # 2025-12-10 hoyeon.han: 정규식 (파일명 패턴 매칭)
import threading  # 2025-12-10 hoyeon.han: 스케줄러 fallback용

# 2025-12-10 hoyeon.han: APScheduler (선택사항, 없으면 threading 사용)
# APScheduler: 백그라운드에서 주기적으로 작업을 실행하는 라이브러리
# 매일 자정에 로그 압축/정리 작업을 자동으로 실행하기 위해 사용
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    HAS_APSCHEDULER = True  # APScheduler 사용 가능
except ImportError:
    # APScheduler가 설치되지 않은 경우 threading.Timer로 대체
    HAS_APSCHEDULER = False


# =============================================================================
# 2025-12-10 hoyeon.han: 압축 기능이 포함된 로그 로테이션 핸들러
# =============================================================================

class CompressingTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    TimedRotatingFileHandler를 확장하여 압축 기능 추가

    기능:
    1. 매일 자정에 새로운 로그 파일 생성 (예: app_20251210.log)
    2. 지정된 일수(기본 7일) 이상 된 로그 파일을 gzip으로 자동 압축
    3. 압축 파일은 archive/ 폴더로 이동

    2025-12-10 hoyeon.han: 로그 압축 자동화
    """

    def __init__(self, *args, compress_days=7, **kwargs):
        """
        초기화 함수

        Args:
            *args: 부모 클래스(TimedRotatingFileHandler)의 매개변수
            compress_days: 며칠 이상 된 로그를 압축할지 (기본 7일)
            **kwargs: 부모 클래스의 키워드 매개변수

        매개변수 설명:
        - *args: 가변 인자 (여러 개의 인자를 튜플로 받음)
        - **kwargs: 가변 키워드 인자 (여러 개의 키=값 쌍을 딕셔너리로 받음)

        주의사항:
        - 'suffix' 파라미터는 TimedRotatingFileHandler가 자체적으로 설정하므로
          kwargs에서 제거하고 별도로 설정

        2025-12-10 hoyeon.han: suffix 처리 추가
        """
        # 2025-12-10 hoyeon.han: suffix를 kwargs에서 분리
        # TimedRotatingFileHandler.__init__()은 suffix 파라미터를 받지 않음
        # 대신 인스턴스 속성으로 설정해야 함
        self.custom_suffix = kwargs.pop('suffix', '_%Y%m%d')  # 기본값: _%Y%m%d

        # super(): 부모 클래스의 메서드 호출
        # TimedRotatingFileHandler의 __init__ 호출
        super().__init__(*args, **kwargs)

        # 2025-12-10 hoyeon.han: suffix를 수동으로 설정
        # suffix: 백업 파일명에 추가될 날짜 형식 (예: _%Y%m%d → _20251210)
        self.suffix = self.custom_suffix

        # 압축 기준 일수 저장
        self.compress_days = compress_days

    def doRollover(self):
        """
        로그 파일 롤오버 시 호출되는 메서드

        롤오버(Rollover)란?
        - 로그 파일이 일정 조건(시간, 크기 등)에 도달하면 새 파일로 전환하는 것
        - 예: 자정이 되면 app.log → app_20251210.log로 이름 변경, 새로운 app.log 생성

        처리 순서:
        1. 부모 클래스의 롤오버 수행 (새 파일 생성)
        2. 오래된 로그 파일 압축

        2025-12-10 hoyeon.han: 롤오버 후 자동 압축
        """
        # 기본 롤오버 수행 (새 파일 생성)
        super().doRollover()

        # 오래된 로그 압축
        self._compress_old_logs()

    def _compress_old_logs(self):
        """
        compress_days 이상 된 로그 파일을 gzip으로 압축

        처리 과정:
        1. 로그 파일이 저장된 디렉토리 확인
        2. archive/ 폴더 생성 (없으면)
        3. compress_days 이전 날짜 계산 (예: 7일 전)
        4. 패턴에 맞는 로그 파일 찾기 (예: app_20251203.log)
        5. 각 파일의 날짜 추출 및 비교
        6. 오래된 파일이면 gzip 압축
        7. 압축 파일은 archive/로 이동, 원본 삭제

        gzip이란?
        - GNU zip의 약자
        - 파일을 압축하는 알고리즘 (보통 90% 이상 압축)
        - 예: 1MB → 100KB로 줄어듦
        """
        # Path 객체: 파일 경로를 다루는 객체지향 방식
        # self.baseFilename: 로그 파일의 기본 경로 (예: logs/app.log)
        # .parent: 부모 디렉토리 (예: logs/)
        log_dir = Path(self.baseFilename).parent

        # archive 폴더 생성
        # exist_ok=True: 이미 존재해도 에러 발생 안 함
        archive_dir = log_dir / "archive"  # logs/archive
        archive_dir.mkdir(exist_ok=True)

        # 압축 기준 날짜 계산
        # datetime.now(): 현재 시각
        # timedelta(days=N): N일을 나타내는 객체
        # cutoff_date: 이 날짜 이전의 로그는 압축 대상
        cutoff_date = datetime.now() - timedelta(days=self.compress_days)

        # 로그 파일 패턴 찾기
        # Path(self.baseFilename).stem: 파일명에서 확장자 제외 (예: app.log → app)
        # pattern: 찾을 파일 패턴 (예: app_*.log)
        pattern = Path(self.baseFilename).stem + "_*.log"

        # .glob(): 패턴에 맞는 파일들 찾기
        # 예: logs/app_20251201.log, logs/app_20251202.log, ...
        for log_file in log_dir.glob(pattern):
            try:
                # 파일명에서 날짜 추출
                # re.search(): 정규식으로 패턴 찾기
                # r'_(\d{8})\.log$': _로 시작, 8자리 숫자, .log로 끝
                # 예: app_20251203.log → 20251203 추출
                date_match = re.search(r'_(\d{8})\.log$', log_file.name)

                if not date_match:
                    # 패턴에 맞지 않으면 건너뜀
                    continue

                # group(1): 첫 번째 괄호 안의 내용 (날짜 부분)
                date_str = date_match.group(1)  # "20251203"

                # 문자열을 datetime 객체로 변환
                # %Y: 4자리 연도, %m: 2자리 월, %d: 2자리 일
                file_date = datetime.strptime(date_str, '%Y%m%d')

                # 압축 대상인지 확인
                # file_date < cutoff_date: 파일 날짜가 기준 날짜보다 이전이면
                if file_date < cutoff_date:
                    # gzip 압축 파일 경로
                    # archive_dir / (log_file.name + '.gz')
                    # 예: logs/archive/app_20251203.log.gz
                    gz_file = archive_dir / (log_file.name + '.gz')

                    # gzip 압축 수행
                    # with 문: 자원을 안전하게 사용하고 자동으로 닫음
                    # 'rb': read binary (바이너리 읽기 모드)
                    # 'wb': write binary (바이너리 쓰기 모드)
                    with open(log_file, 'rb') as f_in:
                        with gzip.open(gz_file, 'wb') as f_out:
                            # shutil.copyfileobj(): 파일 내용을 다른 파일로 복사
                            # f_in의 내용을 읽어서 f_out (압축 파일)에 씀
                            shutil.copyfileobj(f_in, f_out)

                    # 원본 파일 삭제
                    # .unlink(): 파일 삭제 (Unix의 unlink 시스템 콜)
                    log_file.unlink()

                    # 압축 완료 메시지 출력 (콘솔)
                    print(f"로그 압축 완료: {log_file.name} → {gz_file.name}")

            except Exception as e:
                # 예외(에러) 발생 시 메시지 출력하고 계속 진행
                # str(e): 예외 객체를 문자열로 변환
                print(f"로그 압축 실패: {log_file.name}, {str(e)}")


# =============================================================================
# SollumeLogger 클래스 (v3.0으로 업그레이드)
# =============================================================================

class SollumeLogger:
    """
    구조화된 로깅 시스템

    - 텍스트 로그 (app.log): 사람이 읽기 쉬운 형태
    - JSON 로그 (app_YYYYMMDD.json): 기계가 파싱하기 쉬운 형태
    - 오류 전용 로그 (errors.log): 오류만 별도 추적
    """

    # 로깅 스키마 버전 (향후 변경 시 마이그레이션 용)
    # 2025-11-29 hoyeon.han: 검토 의견 반영 - 버전 관리 추가
    # 2025-12-10 hoyeon.han: v3.0으로 업그레이드 (로그 로테이션 및 압축)
    # VERSION = "2.0"  # 2025-12-10 hoyeon.han: v2.0 (기존)
    VERSION = "3.0"  # 2025-12-10 hoyeon.han: v3.0 (일자별 로그, 자동 압축)

    def __init__(self, log_dir: str = "logs"):
        """
        로거 초기화

        Args:
            log_dir: 로그 파일을 저장할 디렉토리 경로 (기본: logs)

        처리 과정:
        1. 로그 디렉토리 생성 (없으면)
        2. archive 디렉토리 생성 (압축 파일 보관용)
        3. 텍스트 로거 설정
        4. JSON 로거 설정
        5. 오류 전용 로거 설정
        6. 자동 압축 스케줄러 시작

        2025-12-10 hoyeon.han: archive 폴더 및 스케줄러 추가
        """
        # Path(): 파일 경로를 객체로 다룸 (문자열보다 편리)
        self.log_dir = Path(log_dir)
        # mkdir(): 디렉토리 생성
        # exist_ok=True: 이미 존재해도 에러 안 남
        self.log_dir.mkdir(exist_ok=True)

        # 2025-12-10 hoyeon.han: 압축 파일 보관용 폴더 생성
        # archive 폴더: 7일 이상 된 로그의 압축 파일(.gz)을 저장
        self.archive_dir = self.log_dir / "archive"  # logs/archive
        self.archive_dir.mkdir(exist_ok=True)

        # 일반 로거 (텍스트 로그)
        # 2025-12-10 hoyeon.han: 일자별 로그 파일로 변경
        self.text_logger = self._setup_text_logger()

        # 구조화된 로거 (JSON 로그)
        self.json_logger = self._setup_json_logger()

        # 2025-11-29 hoyeon.han: 검토 의견 반영 - 오류 전용 로거 추가
        # 2025-12-10 hoyeon.han: 일자별 로그 파일로 변경
        self.error_logger = self._setup_error_logger()

        # 2025-12-10 hoyeon.han: 자동 압축 스케줄러 시작
        # 매일 자정에 오래된 압축 파일(.gz) 삭제 (30일 이상 된 파일)
        self.scheduler = self._start_scheduler()

    # 2025-12-10 hoyeon.han: 기존 방식 (단일 파일)
    # def _setup_text_logger(self) -> logging.Logger:
    #     """기존 텍스트 로그 유지 (호환성)"""
    #     logger = logging.getLogger("sollume_text")
    #     logger.setLevel(logging.INFO)
    #
    #     # 기존 핸들러 제거 (중복 방지)
    #     logger.handlers.clear()
    #
    #     # 파일 핸들러
    #     fh = logging.FileHandler(self.log_dir / "app.log", encoding="utf-8")
    #     fh.setLevel(logging.INFO)
    #
    #     # 포맷
    #     formatter = logging.Formatter(
    #         '%(asctime)s [%(levelname)s] %(message)s',
    #         datefmt='%Y-%m-%d %H:%M:%S'
    #     )
    #     fh.setFormatter(formatter)
    #     logger.addHandler(fh)
    #
    #     return logger

    def _setup_text_logger(self) -> logging.Logger:
        """
        일자별 텍스트 로그 설정

        기능:
        - 매일 자정에 새로운 로그 파일 생성 (예: app_20251210.log)
        - 7일 이상 된 로그는 자동으로 gzip 압축
        - 압축 파일은 archive/ 폴더로 이동

        파일 형식:
        - app.log: 현재 로그 (항상 최신)
        - app_20251210.log: 자정이 지나면 이전 로그
        - archive/app_20251203.log.gz: 7일 이상 된 로그 (압축)

        2025-12-10 hoyeon.han: v3.0 일자별 로그
        """
        # getLogger(): 로거 가져오기 (없으면 생성)
        # 이름으로 로거를 구분 (sollume_text는 텍스트 로그 전용)
        logger = logging.getLogger("sollume_text")

        # setLevel(): 로그 레벨 설정
        # INFO: 정보성 메시지 이상만 기록 (DEBUG는 제외)
        logger.setLevel(logging.INFO)

        # 기존 핸들러 제거 (중복 방지)
        # 핸들러(Handler): 로그를 어디에 출력할지 결정 (파일, 콘솔 등)
        logger.handlers.clear()

        # 2025-12-10 hoyeon.han: CompressingTimedRotatingFileHandler 사용
        # 일자별 로그 파일 생성 + 자동 압축
        fh = CompressingTimedRotatingFileHandler(
            filename=str(self.log_dir / "app.log"),  # 기본 파일명
            when='midnight',  # 자정마다 새 파일 생성
            interval=1,  # 1일마다
            backupCount=7,  # 7개 파일까지 유지 (7일치)
            encoding='utf-8',  # 한글 지원
            delay=False,  # 즉시 파일 생성
            utc=False,  # 로컬 시간 사용
            # suffix: 백업 파일 이름 형식
            # %Y: 4자리 연도, %m: 2자리 월, %d: 2자리 일
            # 예: app_20251210.log
            suffix="_%Y%m%d",
            compress_days=7  # 7일 이상 된 파일은 압축
        )
        fh.setLevel(logging.INFO)

        # 포맷터(Formatter): 로그 메시지 형식 지정
        # %(asctime)s: 시간 (2025-12-10 14:30:00)
        # %(levelname)s: 로그 레벨 (INFO, WARNING, ERROR)
        # %(message)s: 실제 로그 메시지
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        fh.setFormatter(formatter)

        # addHandler(): 로거에 핸들러 추가
        # 이제 이 로거로 로그를 남기면 설정한 파일에 기록됨
        logger.addHandler(fh)

        return logger

    def _setup_json_logger(self) -> logging.Logger:
        """구조화된 JSON 로그"""
        logger = logging.getLogger("sollume_json")
        logger.setLevel(logging.INFO)

        # 기존 핸들러 제거
        logger.handlers.clear()

        # 일별 로그 파일
        today = datetime.now().strftime("%Y%m%d")
        fh = logging.FileHandler(
            self.log_dir / f"app_{today}.json",
            encoding="utf-8"
        )
        fh.setLevel(logging.INFO)
        logger.addHandler(fh)

        return logger

    # 2025-12-10 hoyeon.han: 기존 방식 (단일 파일)
    # def _setup_error_logger(self) -> logging.Logger:
    #     """
    #     오류 전용 로거
    #     2025-11-29 hoyeon.han: 검토 의견 반영 - 오류만 별도 추적
    #     """
    #     logger = logging.getLogger("sollume_error")
    #     logger.setLevel(logging.ERROR)
    #
    #     # 기존 핸들러 제거
    #     logger.handlers.clear()
    #
    #     # 오류 전용 파일
    #     fh = logging.FileHandler(
    #         self.log_dir / "errors.log",
    #         encoding="utf-8"
    #     )
    #     fh.setLevel(logging.ERROR)
    #
    #     formatter = logging.Formatter(
    #         '%(asctime)s [%(levelname)s] %(message)s',
    #         datefmt='%Y-%m-%d %H:%M:%S'
    #     )
    #     fh.setFormatter(formatter)
    #     logger.addHandler(fh)
    #
    #     return logger

    def _setup_error_logger(self) -> logging.Logger:
        """
        일자별 오류 전용 로거

        기능:
        - 매일 자정에 새로운 에러 로그 파일 생성 (예: errors_20251210.log)
        - 7일 이상 된 에러 로그는 자동으로 gzip 압축
        - 압축 파일은 archive/ 폴더로 이동

        파일 형식:
        - errors.log: 현재 에러 로그 (항상 최신)
        - errors_20251210.log: 자정이 지나면 이전 에러 로그
        - archive/errors_20251203.log.gz: 7일 이상 된 에러 로그 (압축)

        2025-11-29 hoyeon.han: 검토 의견 반영 - 오류만 별도 추적
        2025-12-10 hoyeon.han: v3.0 일자별 에러 로그
        """
        # getLogger(): 에러 전용 로거 가져오기
        logger = logging.getLogger("sollume_error")

        # ERROR 레벨 이상만 기록 (INFO, WARNING은 제외)
        logger.setLevel(logging.ERROR)

        # 기존 핸들러 제거 (중복 방지)
        logger.handlers.clear()

        # 2025-12-10 hoyeon.han: CompressingTimedRotatingFileHandler 사용
        # 일자별 에러 로그 파일 생성 + 자동 압축
        fh = CompressingTimedRotatingFileHandler(
            filename=str(self.log_dir / "errors.log"),  # 기본 파일명
            when='midnight',  # 자정마다 새 파일 생성
            interval=1,  # 1일마다
            backupCount=7,  # 7개 파일까지 유지 (7일치)
            encoding='utf-8',  # 한글 지원
            delay=False,  # 즉시 파일 생성
            utc=False,  # 로컬 시간 사용
            suffix="_%Y%m%d",  # errors_20251210.log
            compress_days=7  # 7일 이상 된 파일은 압축
        )
        fh.setLevel(logging.ERROR)

        # 포맷터: 에러 로그 형식
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        fh.setFormatter(formatter)

        # 핸들러 추가
        logger.addHandler(fh)

        return logger

    def log_info(self, message: str, **context):
        """정보 로그"""
        self.text_logger.info(message)
        self._log_json("INFO", message, context)

    def log_warning(self, message: str, **context):
        """경고 로그"""
        self.text_logger.warning(message)
        self._log_json("WARNING", message, context)

    def log_error(self, message: str, error: Optional[Exception] = None, **context):
        """오류 로그"""
        # 텍스트 로그
        self.text_logger.error(message, exc_info=error is not None)

        # 오류 전용 로그에도 기록
        self.error_logger.error(message, exc_info=error is not None)

        # JSON 로그
        error_context = context.copy()
        if error:
            error_context["error_type"] = type(error).__name__
            error_context["error_message"] = str(error)
            error_context["traceback"] = traceback.format_exc()

        self._log_json("ERROR", message, error_context)

    def log_processing_start(self, file_name: str, date: str, file_size: int):
        """처리 시작 로그"""
        self.log_info(
            f"처리 시작: {file_name} ({date})",
            event="processing_start",
            file_name=file_name,
            date=date,
            file_size=file_size
        )

    def log_processing_success(self, file_name: str, date: str,
                               sales_count: int, purchase_count: int,
                               duration_sec: float):
        """처리 성공 로그"""
        self.log_info(
            f"처리 완료: {file_name} - 매출 {sales_count}건, 매입 {purchase_count}건 ({duration_sec:.2f}초)",
            event="processing_success",
            file_name=file_name,
            date=date,
            sales_count=sales_count,
            purchase_count=purchase_count,
            duration_sec=duration_sec
        )

    def log_processing_error(self, file_name: str, date: str,
                            error: Exception, duration_sec: float):
        """처리 실패 로그"""
        self.log_error(
            f"처리 실패: {file_name}",
            error=error,
            event="processing_error",
            file_name=file_name,
            date=date,
            duration_sec=duration_sec
        )

    def log_custom_exception(self, exception: 'SollumeBaseException'):
        """커스텀 예외 로그"""
        self.text_logger.error(
            f"[{exception.error_id}] {exception.user_message}"
        )

        # 오류 전용 로그
        self.error_logger.error(
            f"[{exception.error_id}] {exception.category.value}: {exception.user_message}"
        )

        # JSON 로그
        self._log_json("ERROR", exception.user_message, exception.to_dict())

    def log_performance(self, operation: str, duration_sec: float,
                       rows_processed: int):
        """
        성능 측정 로그
        2025-11-29 hoyeon.han: 검토 의견 반영 - 성능 로그 추가
        """
        rows_per_sec = rows_processed / duration_sec if duration_sec > 0 else 0

        self.log_info(
            f"성능: {operation} - {duration_sec:.2f}초, "
            f"{rows_processed}행, {rows_per_sec:.0f}행/초",
            event="performance",
            operation=operation,
            duration_sec=duration_sec,
            rows_processed=rows_processed,
            rows_per_second=rows_per_sec
        )

    def _start_scheduler(self):
        """
        자동 압축 파일 정리 스케줄러 시작

        기능:
        - 매일 자정(00:00)에 cleanup_compressed_logs() 실행
        - 30일 이상 된 압축 파일(.gz) 자동 삭제

        사용 라이브러리:
        - APScheduler (우선): 백그라운드 스케줄러 (권장)
        - threading.Timer (대체): APScheduler 없을 때 fallback

        APScheduler란?
        - Advanced Python Scheduler의 약자
        - 백그라운드에서 주기적으로 작업을 실행
        - cron 스타일 스케줄링 지원 (예: "매일 자정")

        threading.Timer란?
        - 일정 시간 후 함수를 실행하는 타이머
        - 반복 실행을 위해 재귀적으로 자기 자신 호출

        2025-12-10 hoyeon.han: 자동 압축 파일 정리
        """
        if HAS_APSCHEDULER:
            # APScheduler를 사용한 스케줄링 (권장)
            # BackgroundScheduler: 백그라운드 스레드에서 실행
            scheduler = BackgroundScheduler()

            # add_job(): 스케줄러에 작업 추가
            # self.cleanup_compressed_logs: 실행할 함수
            # 'cron': cron 형식 스케줄 (Unix의 cron과 동일)
            # hour=0, minute=0: 매일 자정(00:00)에 실행
            scheduler.add_job(
                func=self.cleanup_compressed_logs,  # 실행할 함수
                trigger='cron',  # cron 스타일 트리거
                hour=0,  # 0시
                minute=0,  # 0분
                id='cleanup_logs',  # 작업 ID (중복 방지)
                replace_existing=True  # 기존 작업이 있으면 교체
            )

            # start(): 스케줄러 시작
            # 이제 백그라운드에서 매일 자정에 cleanup_compressed_logs() 실행
            scheduler.start()

            print("✅ APScheduler로 자동 로그 정리 시작 (매일 자정)")
            return scheduler

        else:
            # APScheduler가 없으면 threading.Timer로 대체
            # 24시간마다 cleanup_compressed_logs() 실행
            print("⚠️ APScheduler 미설치, threading.Timer 사용")

            # _schedule_with_timer(): 재귀적으로 타이머 설정
            self._schedule_with_timer()
            return None

    def _schedule_with_timer(self):
        """
        threading.Timer를 사용한 스케줄링 (fallback)

        동작 방식:
        1. cleanup_compressed_logs() 실행
        2. 24시간 후 다시 이 함수를 호출하는 타이머 설정
        3. 재귀적으로 반복 (무한 루프처럼 동작)

        재귀(Recursion)란?
        - 함수가 자기 자신을 호출하는 것
        - 이 경우: _schedule_with_timer() → Timer → _schedule_with_timer() → ...

        2025-12-10 hoyeon.han: APScheduler 대체용
        """
        # 압축 파일 정리 실행
        self.cleanup_compressed_logs()

        # 24시간 후 다시 이 함수 호출
        # threading.Timer(초, 함수): 지정된 시간 후 함수 실행
        # 86400초 = 24시간
        timer = threading.Timer(
            interval=86400,  # 24시간 (60 * 60 * 24초)
            function=self._schedule_with_timer  # 다시 이 함수 호출
        )

        # daemon=True: 데몬 스레드로 설정
        # 데몬 스레드란? 메인 프로그램이 종료되면 같이 종료되는 스레드
        # False면 프로그램이 끝나도 타이머가 계속 실행됨
        timer.daemon = True

        # start(): 타이머 시작
        timer.start()

    def cleanup_compressed_logs(self, days_to_keep: int = 30):
        """
        오래된 압축 파일(.gz) 삭제

        기능:
        - archive/ 폴더의 .gz 파일 중 30일 이상 된 파일 삭제
        - 디스크 공간 절약

        처리 과정:
        1. archive/ 폴더의 모든 .gz 파일 찾기
        2. 각 파일의 수정 시간 확인
        3. 30일 이상 된 파일이면 삭제
        4. 삭제 개수 로그 기록

        Args:
            days_to_keep: 보관할 일수 (기본 30일)

        Returns:
            삭제된 파일 개수

        2025-12-10 hoyeon.han: 압축 파일 자동 정리
        """
        # 삭제 기준 날짜 계산
        # 30일 전 날짜: 이 날짜 이전 파일은 삭제 대상
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        # 삭제된 파일 카운트
        deleted_count = 0

        # archive/ 폴더의 모든 .gz 파일 찾기
        # .glob('*.gz'): 확장자가 .gz인 모든 파일
        for gz_file in self.archive_dir.glob('*.gz'):
            try:
                # stat(): 파일 정보 가져오기 (크기, 수정 시간 등)
                # st_mtime: modification time (수정 시간)
                # 유닉스 타임스탬프 (1970년 1월 1일부터 경과한 초)
                file_time = datetime.fromtimestamp(gz_file.stat().st_mtime)

                # 파일이 cutoff_date보다 오래되었는지 확인
                if file_time < cutoff_date:
                    # .unlink(): 파일 삭제
                    gz_file.unlink()
                    deleted_count += 1

                    # 삭제 로그 출력
                    print(f"오래된 압축 파일 삭제: {gz_file.name}")

            except Exception as e:
                # 삭제 실패 시 에러 출력 (다른 파일은 계속 처리)
                print(f"압축 파일 삭제 실패: {gz_file.name}, {str(e)}")

        # 삭제 완료 로그
        if deleted_count > 0:
            print(f"압축 파일 정리 완료: {deleted_count}개 파일 삭제")

        return deleted_count

    def cleanup_old_logs(self, days_to_keep: int = 30):
        """
        오래된 로그 파일 삭제
        2025-11-29 hoyeon.han: 검토 의견 반영 - 로그 정리 기능 추가

        Args:
            days_to_keep: 보관할 일수 (기본 30일)
        """
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        deleted_count = 0

        # JSON 로그 파일만 정리 (app_YYYYMMDD.json)
        for log_file in self.log_dir.glob("app_*.json"):
            try:
                # 파일명에서 날짜 추출 (app_20251129.json)
                date_str = log_file.stem.split('_')[1]  # '20251129'
                file_date = datetime.strptime(date_str, '%Y%m%d')

                if file_date < cutoff_date:
                    log_file.unlink()
                    deleted_count += 1
                    self.log_info(f"오래된 로그 삭제: {log_file.name}")
            except (IndexError, ValueError):
                # 파일명 형식이 다르면 건너뜀
                pass

        if deleted_count > 0:
            self.log_info(f"로그 정리 완료: {deleted_count}개 파일 삭제")

        return deleted_count

    def _sanitize_context(self, context: dict) -> dict:
        """
        로그에서 민감 정보 마스킹
        2025-11-29 hoyeon.han: 검토 의견 반영 - 민감정보 보호

        Args:
            context: 원본 컨텍스트

        Returns:
            마스킹된 컨텍스트
        """
        # 민감한 정보 키워드
        sensitive_keys = ['사업자번호', '전화번호', '주소', 'password', 'token']

        sanitized = context.copy()
        for key in sensitive_keys:
            if key in sanitized:
                value = str(sanitized[key])
                # 앞 3자리 + *** + 뒤 2자리 (5자 이상인 경우)
                if len(value) > 5:
                    sanitized[key] = value[:3] + "***" + value[-2:]
                else:
                    sanitized[key] = "***"

        return sanitized

    def _log_json(self, level: str, message: str, context: dict):
        """
        JSON 로그 기록

        Args:
            level: 로그 레벨 (INFO, WARNING, ERROR)
            message: 로그 메시지
            context: 추가 컨텍스트 정보
        """
        # 민감정보 마스킹
        sanitized_context = self._sanitize_context(context)

        log_entry = {
            "version": self.VERSION,  # 스키마 버전
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            **sanitized_context
        }

        self.json_logger.info(json.dumps(log_entry, ensure_ascii=False))


# 전역 로거 인스턴스 (싱글톤 패턴)
_logger_instance: Optional[SollumeLogger] = None


def get_logger() -> SollumeLogger:
    """
    싱글톤 로거 가져오기

    Returns:
        SollumeLogger 인스턴스
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = SollumeLogger()
    return _logger_instance


# 편의 함수들
def log_info(message: str, **context):
    """정보 로그 (전역 함수)"""
    get_logger().log_info(message, **context)


def log_warning(message: str, **context):
    """경고 로그 (전역 함수)"""
    get_logger().log_warning(message, **context)


def log_error(message: str, error: Optional[Exception] = None, **context):
    """오류 로그 (전역 함수)"""
    get_logger().log_error(message, error, **context)
