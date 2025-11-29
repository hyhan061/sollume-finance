"""
솔루미랩 구조화된 로깅 시스템
텍스트 로그와 JSON 로그를 동시에 제공하여 사람과 기계 모두 읽기 쉽게 함

작성일: 2025-11-29
작성자: hoyeon.han
"""

import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
import traceback


class SollumeLogger:
    """
    구조화된 로깅 시스템

    - 텍스트 로그 (app.log): 사람이 읽기 쉬운 형태
    - JSON 로그 (app_YYYYMMDD.json): 기계가 파싱하기 쉬운 형태
    - 오류 전용 로그 (errors.log): 오류만 별도 추적
    """

    # 로깅 스키마 버전 (향후 변경 시 마이그레이션 용)
    # 2025-11-29 hoyeon.han: 검토 의견 반영 - 버전 관리 추가
    VERSION = "2.0"

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # 일반 로거 (텍스트 로그)
        self.text_logger = self._setup_text_logger()

        # 구조화된 로거 (JSON 로그)
        self.json_logger = self._setup_json_logger()

        # 2025-11-29 hoyeon.han: 검토 의견 반영 - 오류 전용 로거 추가
        self.error_logger = self._setup_error_logger()

    def _setup_text_logger(self) -> logging.Logger:
        """기존 텍스트 로그 유지 (호환성)"""
        logger = logging.getLogger("sollume_text")
        logger.setLevel(logging.INFO)

        # 기존 핸들러 제거 (중복 방지)
        logger.handlers.clear()

        # 파일 핸들러
        fh = logging.FileHandler(self.log_dir / "app.log", encoding="utf-8")
        fh.setLevel(logging.INFO)

        # 포맷
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        fh.setFormatter(formatter)
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

    def _setup_error_logger(self) -> logging.Logger:
        """
        오류 전용 로거
        2025-11-29 hoyeon.han: 검토 의견 반영 - 오류만 별도 추적
        """
        logger = logging.getLogger("sollume_error")
        logger.setLevel(logging.ERROR)

        # 기존 핸들러 제거
        logger.handlers.clear()

        # 오류 전용 파일
        fh = logging.FileHandler(
            self.log_dir / "errors.log",
            encoding="utf-8"
        )
        fh.setLevel(logging.ERROR)

        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        fh.setFormatter(formatter)
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
