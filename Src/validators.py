"""
솔루미랩 데이터 검증 레이어
Excel 파일 및 데이터 품질을 단계별로 검증

작성일: 2025-11-29
작성자: hoyeon.han
"""

import pandas as pd
import os
from typing import List, Tuple, Optional
from .exceptions import (
    SheetNotFoundError,
    ColumnNotFoundError,
    NoDataForDateError,
    DataValidationError,
    EmptyFileError,
    BusinessNumberMissingWarning
)


class DataValidator:
    """
    데이터 검증 클래스

    검증 단계:
    1. 파일 레벨 검증 (크기, 읽기 가능 여부)
    2. 구조 검증 (시트, 컬럼 존재)
    3. 데이터 품질 검증 (형식, 일관성)
    4. 비즈니스 룰 검증 (마스터 데이터 조인 등)
    """

    # 필수 컬럼 정의
    REQUIRED_COLUMNS_SALES = [
        '출고일', '계산서', '업체명', '제품', '수량', '상품매출',
        '판매배송비', '도선료', '과세구분', '특이사항'
    ]

    REQUIRED_COLUMNS_PURCHASE = [
        '출고일', '매입처', '제품', '수량', '상품매입',
        '매입배송비', '도선료.1', '과세구분', '특이사항'
    ]

    REQUIRED_MASTER_COLUMNS = [
        '거래처명_솔루미랩', '사업자번호'
    ]

    # 파일 크기 제한 (MB)
    MAX_FILE_SIZE_MB = 50

    @staticmethod
    def validate_file_size(file_path: str, max_mb: int = None) -> bool:
        """
        파일 크기 검증
        2025-11-29 hoyeon.han: 검토 의견 반영 - 파일 크기 체크 추가

        Args:
            file_path: 파일 경로
            max_mb: 최대 크기 (MB), None이면 기본값 사용

        Returns:
            True (정상)

        Raises:
            DataValidationError: 파일이 너무 큼
            EmptyFileError: 파일이 비어있음
        """
        if max_mb is None:
            max_mb = DataValidator.MAX_FILE_SIZE_MB

        if not os.path.exists(file_path):
            return True  # 존재 여부는 다른 곳에서 체크

        file_size = os.path.getsize(file_path)
        size_mb = file_size / (1024 * 1024)

        # 빈 파일 체크
        if file_size == 0:
            raise EmptyFileError(os.path.basename(file_path), file_size)

        # 크기 제한 체크
        if size_mb > max_mb:
            raise DataValidationError(
                message=f"파일 크기가 너무 큽니다 ({size_mb:.1f}MB)",
                details=f"최대 크기: {max_mb}MB, 현재: {size_mb:.1f}MB",
                hints=[
                    "1. 불필요한 시트를 삭제해주세요",
                    "2. 파일을 연도별로 분리해주세요",
                    "3. 오래된 데이터는 별도 파일로 보관해주세요"
                ]
            )

        return True

    @staticmethod
    def validate_sheet_exists(excel_file: pd.ExcelFile, sheet_name: str,
                             file_name: str) -> bool:
        """
        시트 존재 확인

        Args:
            excel_file: pandas ExcelFile 객체
            sheet_name: 찾을 시트명
            file_name: 파일명 (오류 메시지용)

        Returns:
            True (정상)

        Raises:
            SheetNotFoundError: 시트 없음
        """
        if sheet_name not in excel_file.sheet_names:
            raise SheetNotFoundError(sheet_name, file_name)

        return True

    @staticmethod
    def validate_columns(df: pd.DataFrame, required_columns: List[str],
                         sheet_name: str) -> Tuple[bool, List[str]]:
        """
        필수 컬럼 확인

        Args:
            df: 검증할 데이터프레임
            required_columns: 필수 컬럼 목록
            sheet_name: 시트명 (오류 메시지용)

        Returns:
            (성공 여부, 누락 컬럼 목록)

        Raises:
            ColumnNotFoundError: 필수 컬럼 없음 (첫 번째 누락 컬럼)
        """
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            # 첫 번째 누락 컬럼만 보고
            raise ColumnNotFoundError(
                missing_columns[0],
                sheet_name,
                df.columns.tolist()
            )

        return True, []

    @staticmethod
    def validate_date_data_exists(df: pd.DataFrame, date: str,
                                  total_rows: int = 0) -> bool:
        """
        해당 날짜 데이터 존재 확인

        Args:
            df: 필터링된 데이터프레임
            date: 날짜 (YYYY-MM-DD)
            total_rows: 원본 전체 행 수

        Returns:
            True (정상)

        Raises:
            NoDataForDateError: 해당 날짜 데이터 없음
        """
        if len(df) == 0:
            raise NoDataForDateError(date, total_rows)

        return True

    @staticmethod
    def validate_required_data_exists(df: pd.DataFrame, column: str,
                                     allow_ratio: float = 0.0) -> bool:
        """
        필수 데이터 존재 확인
        2025-11-29 hoyeon.han: 검토 의견 반영 - 필수 데이터 검증 추가

        Args:
            df: 검증할 데이터프레임
            column: 검증할 컬럼명
            allow_ratio: 허용 가능한 결측 비율 (0.0 = 허용 안함)

        Returns:
            True (정상)

        Raises:
            DataValidationError: 필수 데이터 누락
        """
        if column not in df.columns:
            return True  # 컬럼 존재 여부는 다른 곳에서 체크

        null_count = df[column].isna().sum()
        total_count = len(df)

        if null_count > 0:
            ratio = null_count / total_count

            if ratio > allow_ratio:
                raise DataValidationError(
                    message=f"필수 항목 '{column}'이(가) 비어있는 데이터가 있습니다",
                    details=f"전체 {total_count}건 중 {null_count}건 ({ratio*100:.1f}%)",
                    hints=[
                        f"1. '{column}' 컬럼에 빈 셀이 없는지 확인해주세요",
                        "2. Excel 필터를 해제하고 전체 데이터를 확인해주세요",
                        "3. 데이터 입력이 완료된 파일인지 확인해주세요"
                    ]
                )

        return True

    @staticmethod
    def validate_numeric_columns(df: pd.DataFrame,
                                 numeric_cols: List[str]) -> List[str]:
        """
        숫자 컬럼 검증

        Args:
            df: 검증할 데이터프레임
            numeric_cols: 숫자여야 하는 컬럼 목록

        Returns:
            경고 메시지 목록
        """
        warnings = []

        for col in numeric_cols:
            if col not in df.columns:
                continue

            # NaN이 아닌데 숫자 변환 실패하는 값 확인
            non_null = df[col].notna()
            if non_null.sum() > 0:
                try:
                    # 숫자 변환 시도
                    pd.to_numeric(df.loc[non_null, col], errors='raise')
                except (ValueError, TypeError):
                    # 변환 실패한 값 찾기
                    invalid_values = []
                    for val in df.loc[non_null, col].unique()[:5]:
                        try:
                            pd.to_numeric(val)
                        except:
                            invalid_values.append(str(val)[:20])

                    if invalid_values:
                        warnings.append(
                            f"'{col}' 컬럼에 숫자가 아닌 값이 있습니다: {', '.join(invalid_values)}"
                        )

        return warnings

    @staticmethod
    def validate_data_consistency(df: pd.DataFrame) -> List[str]:
        """
        데이터 일관성 검증
        2025-11-29 hoyeon.han: 검토 의견 반영 - 일관성 검증 추가

        Args:
            df: 검증할 데이터프레임

        Returns:
            경고 메시지 목록
        """
        warnings = []

        # 1. 수량이 0인데 금액이 있는 경우
        # 2025-11-29 hoyeon.han: pandas 3.0 대비 - .copy() 후 직접 할당
        if '수량' in df.columns and '상품매출' in df.columns:
            df_temp = df.copy()
            df_temp.loc[:, '수량'] = pd.to_numeric(df_temp['수량'], errors='coerce')
            df_temp.loc[:, '상품매출'] = pd.to_numeric(df_temp['상품매출'], errors='coerce')

            inconsistent = df_temp[
                (df_temp['수량'] == 0) & (df_temp['상품매출'] > 0)
            ]
            if len(inconsistent) > 0:
                warnings.append(
                    f"수량이 0인데 금액이 있는 행: {len(inconsistent)}개"
                )

        # 2. 음수 금액 (반품 외)
        # 2025-11-29 hoyeon.han: pandas 3.0 대비 - .copy() 후 직접 할당
        if '수량' in df.columns and '상품매출' in df.columns:
            df_temp = df.copy()
            df_temp.loc[:, '수량'] = pd.to_numeric(df_temp['수량'], errors='coerce')
            df_temp.loc[:, '상품매출'] = pd.to_numeric(df_temp['상품매출'], errors='coerce')

            negative_amount = df_temp[
                (df_temp['상품매출'] < 0) & (df_temp['수량'] >= 0)
            ]
            if len(negative_amount) > 0:
                warnings.append(
                    f"수량은 양수인데 금액이 음수인 행: {len(negative_amount)}개"
                )

        # 3. 날짜 형식 확인
        # 2025-11-29 hoyeon.han: pandas 3.0 대비 - .copy() 후 직접 할당
        if '출고일' in df.columns:
            try:
                df_temp = df.copy()
                df_temp.loc[:, '출고일_parsed'] = pd.to_datetime(
                    df_temp['출고일'],
                    errors='coerce'
                )
                invalid_dates = df_temp[df_temp['출고일_parsed'].isna() & df_temp['출고일'].notna()]

                if len(invalid_dates) > 0:
                    warnings.append(
                        f"날짜 형식이 잘못된 행: {len(invalid_dates)}개"
                    )
            except:
                pass

        return warnings

    @staticmethod
    def validate_master_data_join(df_result: pd.DataFrame,
                                   original_count: int) -> List[str]:
        """
        마스터 데이터 조인 결과 검증

        Args:
            df_result: 조인 결과 데이터프레임
            original_count: 원본 데이터 행 수

        Returns:
            경고 메시지 목록
        """
        warnings = []

        # 사업자번호가 없는 거래처 확인
        if '사업자번호' in df_result.columns and '거래처명' in df_result.columns:
            missing_biz_number = df_result[df_result['사업자번호'].isna()]

            if len(missing_biz_number) > 0:
                missing_companies = missing_biz_number['거래처명'].unique()

                # 고유 거래처명만 표시
                companies_display = list(missing_companies[:5])
                if len(missing_companies) > 5:
                    companies_display.append(f"외 {len(missing_companies) - 5}개")

                warnings.append(
                    f"사업자번호가 없는 거래처: {', '.join(companies_display)}"
                )

        return warnings

    @staticmethod
    def get_validation_warnings(df: pd.DataFrame, data_type: str = "sales") -> List[str]:
        """
        종합 검증 및 경고 수집

        Args:
            df: 검증할 데이터프레임
            data_type: 데이터 유형 ("sales" 또는 "purchase")

        Returns:
            모든 경고 메시지 목록
        """
        all_warnings = []

        # 숫자 컬럼 검증
        numeric_cols = ['수량', '상품매출', '판매배송비', '도선료']
        if data_type == "purchase":
            numeric_cols = ['수량', '상품매입', '매입배송비', '매입도선료']

        warnings = DataValidator.validate_numeric_columns(df, numeric_cols)
        all_warnings.extend(warnings)

        # 데이터 일관성 검증
        warnings = DataValidator.validate_data_consistency(df)
        all_warnings.extend(warnings)

        return all_warnings
