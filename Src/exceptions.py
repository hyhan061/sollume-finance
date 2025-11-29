"""
솔루미랩 커스텀 예외 클래스
비즈니스 로직에서 발생하는 다양한 오류를 구조화하여 처리

작성일: 2025-11-29
작성자: hoyeon.han
"""

from enum import Enum
from typing import Dict, Any, List
from datetime import datetime
import uuid
import time


class ErrorCategory(Enum):
    """오류 카테고리"""
    FILE_ERROR = "파일 오류"           # 파일 없음, 권한 문제
    DATA_ERROR = "데이터 오류"         # 시트 없음, 컬럼 없음, 잘못된 데이터
    VALIDATION_ERROR = "검증 오류"     # 비즈니스 룰 위반
    PROCESSING_ERROR = "처리 오류"     # 연산 중 오류
    SYSTEM_ERROR = "시스템 오류"       # 알 수 없는 오류


class ErrorSeverity(Enum):
    """사용자에게 표시할 오류 심각도"""
    INFO = "정보"       # 경고성, 계속 진행 가능
    WARNING = "주의"    # 일부 데이터 누락 가능
    ERROR = "오류"      # 처리 실패, 재시도 필요
    CRITICAL = "심각"   # 시스템 문제, 개발자 연락 필요


class SollumeBaseException(Exception):
    """
    솔루미랩 예외 기본 클래스

    모든 커스텀 예외의 부모 클래스로, 사용자 친화적 메시지와
    개발자용 디버깅 정보를 함께 제공합니다.

    Attributes:
        error_id (str): 고유 오류 ID (타임스탬프 + UUID)
        timestamp (datetime): 오류 발생 시각
        user_message (str): 사용자에게 표시할 메시지
        category (ErrorCategory): 오류 카테고리
        severity (ErrorSeverity): 오류 심각도
        technical_details (str): 개발자용 상세 정보
        solution_hints (List[str]): 해결 방법 힌트
        context (Dict[str, Any]): 오류 발생 컨텍스트
    """

    def __init__(
        self,
        user_message: str,          # 사용자에게 표시할 메시지
        category: ErrorCategory,
        severity: ErrorSeverity,
        technical_details: str = "", # 개발자용 상세 정보
        solution_hints: List[str] = None, # 해결 방법 힌트
        context: Dict[str, Any] = None  # 오류 발생 컨텍스트
    ):
        # 2025-11-29 hoyeon.han: 타임스탬프 + UUID 조합으로 충돌 방지
        timestamp_ms = int(time.time() * 1000) % 100000
        uuid_short = str(uuid.uuid4())[:4]
        self.error_id = f"{timestamp_ms:05d}-{uuid_short}"

        self.timestamp = datetime.now()
        self.user_message = user_message
        self.category = category
        self.severity = severity
        self.technical_details = technical_details
        self.solution_hints = solution_hints or []
        self.context = context or {}

        super().__init__(user_message)

    def to_dict(self) -> dict:
        """로그 기록용 딕셔너리 변환"""
        return {
            "error_id": self.error_id,
            "timestamp": self.timestamp.isoformat(),
            "category": self.category.value,
            "severity": self.severity.value,
            "user_message": self.user_message,
            "technical_details": self.technical_details,
            "solution_hints": self.solution_hints,
            "context": self.context
        }

    def __str__(self) -> str:
        """문자열 표현"""
        return f"[{self.error_id}] {self.category.value}: {self.user_message}"


# =============================================================================
# 파일 관련 예외
# =============================================================================

class MasterFileNotFoundError(SollumeBaseException):
    """거래처마스터 파일 없음"""
    def __init__(self, file_path: str):
        super().__init__(
            user_message="거래처마스터 파일을 찾을 수 없습니다",
            category=ErrorCategory.FILE_ERROR,
            severity=ErrorSeverity.ERROR,
            technical_details=f"파일 경로: {file_path}",
            solution_hints=[
                "1. 'Src/거래처마스터.xlsx' 파일이 있는지 확인해주세요",
                "2. 파일 이름이 정확한지 확인해주세요 (한글 포함)",
                "3. 문제가 계속되면 스크린샷을 찍어 개발자에게 문의하세요"
            ],
            context={"file_path": file_path}
        )


class EmptyFileError(SollumeBaseException):
    """업로드한 파일이 비어있음"""
    # 2025-11-29 hoyeon.han: 검토 의견 반영 - 빈 파일 체크 추가
    def __init__(self, file_name: str, file_size: int = 0):
        super().__init__(
            user_message=f"업로드한 파일 '{file_name}'이(가) 비어있습니다",
            category=ErrorCategory.DATA_ERROR,
            severity=ErrorSeverity.ERROR,
            technical_details=f"파일 크기: {file_size} bytes",
            solution_hints=[
                "1. 파일에 데이터가 있는지 확인해주세요",
                "2. 올바른 발주내역 파일을 선택했는지 확인해주세요",
                "3. 파일이 손상되지 않았는지 확인해주세요"
            ],
            context={"file_name": file_name, "file_size": file_size}
        )


# =============================================================================
# 데이터 구조 관련 예외
# =============================================================================

class SheetNotFoundError(SollumeBaseException):
    """Excel 시트 없음"""
    def __init__(self, sheet_name: str, file_name: str):
        super().__init__(
            user_message=f"Excel 파일에서 '{sheet_name}' 시트를 찾을 수 없습니다",
            category=ErrorCategory.DATA_ERROR,
            severity=ErrorSeverity.ERROR,
            technical_details=f"파일: {file_name}, 시트: {sheet_name}",
            solution_hints=[
                f"1. 업로드한 파일에 '{sheet_name}' 시트가 있는지 확인해주세요",
                "2. 시트 이름에 오타가 없는지 확인해주세요",
                "3. 올바른 발주내역 파일을 선택했는지 확인해주세요"
            ],
            context={"sheet_name": sheet_name, "file_name": file_name}
        )


class ColumnNotFoundError(SollumeBaseException):
    """필수 컬럼 없음"""
    def __init__(self, column_name: str, sheet_name: str, available_columns: List[str] = None):
        super().__init__(
            user_message=f"필수 항목 '{column_name}'이(가) 없습니다",
            category=ErrorCategory.DATA_ERROR,
            severity=ErrorSeverity.ERROR,
            technical_details=f"시트: {sheet_name}, 컬럼: {column_name}",
            solution_hints=[
                f"1. '{sheet_name}' 시트에 '{column_name}' 열이 있는지 확인해주세요",
                "2. Excel 파일이 최신 양식인지 확인해주세요",
                "3. 파일을 다시 다운로드 받아 시도해보세요"
            ],
            context={
                "column_name": column_name,
                "sheet_name": sheet_name,
                "available_columns": available_columns[:10] if available_columns else None
            }
        )


# =============================================================================
# 데이터 품질 관련 예외
# =============================================================================

class NoDataForDateError(SollumeBaseException):
    """해당 날짜 데이터 없음"""
    def __init__(self, date: str, total_rows: int = 0):
        super().__init__(
            user_message=f"{date} 날짜의 처리 가능한 데이터가 없습니다",
            category=ErrorCategory.VALIDATION_ERROR,
            severity=ErrorSeverity.WARNING,
            technical_details=f"출고일={date}, 계산서='대상' 조건에 맞는 데이터 0건 (전체 {total_rows}건)",
            solution_hints=[
                "1. 선택한 날짜가 맞는지 확인해주세요",
                "2. 해당 날짜에 출고된 주문이 있는지 확인해주세요",
                "3. '계산서' 항목이 '대상'으로 설정되어 있는지 확인해주세요"
            ],
            context={"date": date, "total_rows": total_rows}
        )


class DateParseError(SollumeBaseException):
    """날짜 형식 오류"""
    # 2025-11-29 hoyeon.han: 검토 의견 반영 - 날짜 파싱 오류 추가
    def __init__(self, column_name: str, invalid_values: List[Any]):
        samples = [str(v)[:50] for v in invalid_values[:5]]  # 최대 5개, 길이 제한
        super().__init__(
            user_message=f"'{column_name}' 컬럼의 날짜 형식이 올바르지 않습니다",
            category=ErrorCategory.DATA_ERROR,
            severity=ErrorSeverity.WARNING,
            technical_details=f"유효하지 않은 날짜 값: {samples}",
            solution_hints=[
                "1. 날짜가 올바른 형식인지 확인해주세요",
                "2. 빈 셀이나 텍스트가 포함되어 있는지 확인해주세요",
                "3. Excel에서 날짜 셀 형식을 '날짜'로 설정해주세요"
            ],
            context={"column": column_name, "samples": samples, "count": len(invalid_values)}
        )


class DataValidationError(SollumeBaseException):
    """데이터 검증 실패 (범용)"""
    def __init__(self, message: str, details: str, hints: List[str] = None):
        super().__init__(
            user_message=message,
            category=ErrorCategory.VALIDATION_ERROR,
            severity=ErrorSeverity.WARNING,
            technical_details=details,
            solution_hints=hints or ["데이터를 확인하고 다시 시도해주세요"],
            context={}
        )


class BusinessNumberMissingWarning(SollumeBaseException):
    """사업자번호 누락 경고 (처리는 계속)"""
    # 2025-11-29 hoyeon.han: 검토 의견 반영 - WARNING 레벨 예외 추가
    def __init__(self, company_names: List[str]):
        companies_display = ", ".join(company_names[:10])
        if len(company_names) > 10:
            companies_display += f" 외 {len(company_names) - 10}개"

        super().__init__(
            user_message=f"{len(company_names)}개 거래처의 사업자번호가 없습니다",
            category=ErrorCategory.VALIDATION_ERROR,
            severity=ErrorSeverity.WARNING,
            technical_details=f"거래처: {companies_display}",
            solution_hints=[
                "1. 거래처마스터 파일에 해당 거래처가 있는지 확인해주세요",
                "2. 거래처 이름 오타가 없는지 확인해주세요",
                "3. 일단 파일은 생성되지만, 경리나라 업로드 시 오류 가능합니다"
            ],
            context={"missing_companies": company_names, "count": len(company_names)}
        )


# =============================================================================
# 처리 중 오류
# =============================================================================

class ProcessingError(SollumeBaseException):
    """처리 중 오류"""
    def __init__(self, step: str, original_error: Exception):
        super().__init__(
            user_message=f"데이터 처리 중 오류가 발생했습니다 ({step})",
            category=ErrorCategory.PROCESSING_ERROR,
            severity=ErrorSeverity.ERROR,
            technical_details=f"단계: {step}, 오류: {type(original_error).__name__}: {str(original_error)}",
            solution_hints=[
                "1. 파일을 다시 업로드해보세요",
                "2. 다른 날짜로 시도해보세요",
                "3. 문제가 계속되면 아래 오류 ID를 개발자에게 알려주세요"
            ],
            context={
                "step": step,
                "original_error_type": type(original_error).__name__,
                "original_error": str(original_error)
            }
        )
