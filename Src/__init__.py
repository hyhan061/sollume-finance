"""
Sollume Finance 비즈니스 로직 모듈

작성일: 2025-11-29
작성자: hoyeon.han
"""

# 2025-11-29 hoyeon.han: Phase 1 구현 - 오류 처리 및 로깅 시스템
from .exceptions import (
    ErrorCategory,
    ErrorSeverity,
    SollumeBaseException,
    MasterFileNotFoundError,
    SheetNotFoundError,
    ColumnNotFoundError,
    NoDataForDateError,
    EmptyFileError,
    DateParseError,
    DataValidationError,
    BusinessNumberMissingWarning,
    ProcessingError
)

from .logger import (
    SollumeLogger,
    get_logger,
    log_info,
    log_warning,
    log_error
)

from .validators import DataValidator

__all__ = [
    # Exceptions
    'ErrorCategory',
    'ErrorSeverity',
    'SollumeBaseException',
    'MasterFileNotFoundError',
    'SheetNotFoundError',
    'ColumnNotFoundError',
    'NoDataForDateError',
    'EmptyFileError',
    'DateParseError',
    'DataValidationError',
    'BusinessNumberMissingWarning',
    'ProcessingError',
    # Logger
    'SollumeLogger',
    'get_logger',
    'log_info',
    'log_warning',
    'log_error',
    # Validators
    'DataValidator',
]
