"""
Sollume Finance 데이터 처리 모듈 (개선 버전)
매출/매입 전표 데이터 생성 로직

수정이력:
2025-11-29 hoyeon.han: Phase 2 - 오류 처리 및 검증 추가
  - 커스텀 예외 사용
  - 단계별 검증 및 로깅
  - SettingWithCopyWarning 해결
  - 성능 로그 추가
2025-02-25 일괄등록 시트 생성 시 업체이름별로 구분되도록 수정
2025-10-21 숫자 변환 함수 추가
2024-11-15 Streamlit 전환을 위해 모듈 분리
"""

import pandas as pd
import numpy as np
from datetime import datetime
import xlwt
import os
# 2026-04-08 hoyeon.han: 미사용 타입 import 제거
# from typing import Tuple, Optional

# 2025-11-29 hoyeon.han: Phase 2 - 커스텀 예외 및 로거 import
# 2025-11-30 hoyeon.han: 상대 import를 절대 import로 변경 (ImportError 해결)
# 2025-12-16 hoyeon.han: Phase 5 - DB 사용 옵션 추가
from exceptions import (
    MasterFileNotFoundError,
    SheetNotFoundError,
    # 2026-04-08 hoyeon.han: 미사용 예외 import 제거
    # ColumnNotFoundError,
    NoDataForDateError,
    ProcessingError,
    SollumeBaseException,
)
from logger import get_logger
from validators import DataValidator

# 2025-12-16 hoyeon.han: DB 사용을 위한 import (옵션)
try:
    from customer_master_db import CustomerMasterDB

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


def to_num(s: pd.Series) -> pd.Series:
    """
    콤마/공백/숫자·소수점·부호 외 문자 제거 → 숫자 변환

    Args:
        s: 변환할 pandas Series

    Returns:
        숫자로 변환된 Series (변환 실패 시 NaN)
    """
    return pd.to_numeric(
        s.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace(r"[^0-9.\-]", "", regex=True),
        errors="coerce",
    )


def save_dataframe_to_xls(df: pd.DataFrame, xls_file: str):
    """
    DataFrame을 .xls 파일로 저장 (xlwt 사용)

    Args:
        df: 저장할 데이터프레임
        xls_file: 저장할 파일 경로
    """
    wb_xls = xlwt.Workbook()
    sheet_xls = wb_xls.add_sheet("Sheet1")

    # 헤더 저장
    for col_idx, column in enumerate(df.columns):
        sheet_xls.write(0, col_idx, column)

    # 데이터 저장
    for row_idx, row in enumerate(df.itertuples(index=False), start=1):
        for col_idx, value in enumerate(row):
            sheet_xls.write(row_idx, col_idx, value)

    # .xls 파일 저장
    wb_xls.save(xls_file)


def get_sales_daily(
    file_path: str,
    date: str,
    master_file_path: str = "거래처마스터.xlsx",
    use_db: bool = True,
    db_path: str = "database/customer_master.db",
) -> pd.DataFrame:
    """
    매출 데이터 처리 함수 (개선 버전)

    2025-11-29 hoyeon.han: Phase 2 개선
    - 오류 처리 및 검증 추가
    - 단계별 로깅
    - SettingWithCopyWarning 해결

    2025-12-16 hoyeon.han: Phase 5 개선
    - DB 사용 옵션 추가 (use_db 파라미터)
    - Excel과 DB를 선택적으로 사용 가능

    Args:
        file_path: 발주내역 파일 경로
        date: 처리 날짜 (YYYY-MM-DD)
        master_file_path: 거래처마스터 Excel 파일 경로 (use_db=False일 때)
        use_db: DB 사용 여부 (기본값: True)
        db_path: 거래처마스터 DB 파일 경로 (use_db=True일 때)

    Returns:
        경리나라 일괄등록 형식의 데이터프레임

    Raises:
        MasterFileNotFoundError: 거래처마스터 파일 없음
        SheetNotFoundError: 필수 시트 없음
        ColumnNotFoundError: 필수 컬럼 없음
        NoDataForDateError: 해당 날짜 데이터 없음
        ProcessingError: 처리 중 오류
    """
    logger = get_logger()
    sheet_name = "(누적)2025년 발주내역"
    start_time = datetime.now()

    try:
        logger.log_info(f"매출 데이터 처리 시작: {file_path}, {date}")

        # STEP 1: 파일 읽기
        logger.log_info("STEP 1: 발주내역 파일 읽기")
        try:
            # 파일 크기 검증
            DataValidator.validate_file_size(file_path)

            df = pd.read_excel(
                file_path, engine="openpyxl", sheet_name=sheet_name, header=3
            )
        except ValueError as e:
            if "Worksheet" in str(e):
                raise SheetNotFoundError(sheet_name, os.path.basename(file_path))
            raise ProcessingError("발주내역 파일 읽기", e)

        logger.log_info(f"발주내역 시트 읽기 완료: {len(df)}행")

        # STEP 2: 필수 컬럼 검증
        logger.log_info("STEP 2: 필수 컬럼 검증")
        DataValidator.validate_columns(
            df, DataValidator.REQUIRED_COLUMNS_SALES, sheet_name
        )

        # STEP 3: 거래처마스터 읽기
        # 2025-12-16 hoyeon.han: DB 또는 Excel에서 거래처마스터 읽기
        if use_db and DB_AVAILABLE:
            logger.log_info(f"STEP 3: 거래처마스터 DB 읽기 ({db_path})")
            if not os.path.exists(db_path):
                raise MasterFileNotFoundError(db_path)

            db = CustomerMasterDB(db_path)
            df_customer = db.get_all_customers()

            # 컬럼명 변환 (DB → Excel 형식)
            df_customer = df_customer.rename(
                columns={
                    "발주내역_거래처명": "거래처명_솔루미랩",
                    "경리나라_거래처명": "거래처명_경리나라",
                }
            )

            logger.log_info(f"거래처마스터 DB 읽기 완료: {len(df_customer)}행")
        else:
            logger.log_info("STEP 3: 거래처마스터 파일 읽기")
            if not os.path.exists(master_file_path):
                raise MasterFileNotFoundError(master_file_path)

            try:
                df_customer = pd.read_excel(
                    master_file_path,
                    engine="openpyxl",
                    sheet_name="거래처마스터",
                    header=0,
                )
            except ValueError as e:
                raise SheetNotFoundError(
                    "거래처마스터", os.path.basename(master_file_path)
                )

            # 거래처마스터 컬럼 검증
            DataValidator.validate_columns(
                df_customer, DataValidator.REQUIRED_MASTER_COLUMNS, "거래처마스터"
            )

            logger.log_info(f"거래처마스터 읽기 완료: {len(df_customer)}행")

        # STEP 4: 날짜 변환 및 필터링
        logger.log_info(f"STEP 4: 날짜 필터링 ({date})")
        today = datetime.strptime(date, "%Y-%m-%d")

        # 출고일 날짜 변환
        df["출고일"] = pd.to_datetime(df["출고일"], errors="coerce")

        # 2025-11-29 hoyeon.han: .copy() 추가로 SettingWithCopyWarning 방지
        df_sales_today = df[(df["출고일"] == today) & (df["계산서"] == "대상")].copy()

        # 데이터 존재 확인
        DataValidator.validate_date_data_exists(df_sales_today, date, len(df))

        logger.log_info(f"날짜 필터링 완료: {len(df_sales_today)}행")

        # STEP 5: 데이터 전처리
        logger.log_info("STEP 5: 데이터 전처리")

        # 2025-11-29 hoyeon.han: .copy() 이후 직접 할당 (pandas 3.0 대비)
        df_sales_today["특이사항"] = df_sales_today["특이사항"].fillna("")
        df_sales_today["상품매출"] = df_sales_today["상품매출"].fillna(0)
        df_sales_today["판매배송비"] = df_sales_today["판매배송비"].fillna(0)
        df_sales_today["도선료"] = df_sales_today["도선료"].fillna(0)

        # 숫자 변환
        df_sales_today["상품매출"] = to_num(df_sales_today["상품매출"])
        df_sales_today["수량"] = to_num(df_sales_today["수량"])

        # 데이터 필터링: 상품매출, 배송비, 도선료가 있는 것만
        df_sales_today = df_sales_today[
            (df_sales_today["상품매출"] != 0)
            | (df_sales_today["판매배송비"] != 0)
            | (df_sales_today["도선료"] != 0)
        ].copy()

        # 최종 데이터 확인
        if len(df_sales_today) == 0:
            raise NoDataForDateError(date, len(df))

        logger.log_info(f"유효 데이터: {len(df_sales_today)}행")

        # STEP 6: 비즈니스 로직
        logger.log_info("STEP 6: 비즈니스 로직 적용")

        # 반품유무 추가
        # 2025-02-03 hoyeon.han: 벡터화 적용
        df_sales_today["반품유무"] = np.where(df_sales_today["수량"] < 0, "Y", "N")

        # 이너바우어 통합
        df_sales_today.loc[
            df_sales_today["업체명"].str.startswith("이너바우어", na=False), "업체명"
        ] = "이너바우어"

        # 정렬
        df_sales_today = df_sales_today.sort_values(
            ["업체명", "특이사항", "제품", "수량"]
        )

        # STEP 7: 제품 데이터 집계
        logger.log_info("STEP 7: 제품 데이터 집계")

        df_1 = (
            df_sales_today.groupby(
                ["업체명", "특이사항", "제품", "과세구분", "반품유무"]
            )[["수량", "상품매출"]]
            .sum()
            .reset_index()
        )

        df_1["단가"] = df_1.apply(
            lambda x: 0 if x["수량"] == 0 else x["상품매출"] / x["수량"], axis=1
        )
        df_1["공급가"] = df_1.apply(
            lambda x: x["상품매출"]
            if x["과세구분"] == "면세"
            else round(x["상품매출"] / 1.1, 0),
            axis=1,
        )
        df_1["부가세"] = df_1.apply(
            lambda x: 0 if x["과세구분"] == "면세" else x["상품매출"] - x["공급가"],
            axis=1,
        )
        df_1 = df_1.rename(columns={"제품": "품목명"})

        # STEP 8: 배송비 집계
        logger.log_info("STEP 8: 배송비 집계")

        df_sales_today_delivery = df_sales_today[df_sales_today["판매배송비"] != 0]
        df_2 = (
            df_sales_today_delivery.groupby(
                ["업체명", "특이사항", "판매배송비", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_2["품목명"] = "택배비"
        df_2 = df_2.rename(columns={"판매배송비": "단가"})
        df_2["상품매출"] = df_2["단가"] * df_2["수량"]

        # 2025-02-03 hoyeon.han: 벡터화 적용
        mask_tax_free_2 = df_2["과세구분"] == "면세"
        df_2["공급가"] = np.where(
            mask_tax_free_2, df_2["상품매출"], (df_2["상품매출"] / 1.1).round(0)
        )
        df_2["부가세"] = np.where(mask_tax_free_2, 0, df_2["상품매출"] - df_2["공급가"])

        # STEP 9: 도선료 집계
        logger.log_info("STEP 9: 도선료 집계")

        df_sales_today_shipped = df_sales_today[df_sales_today["도선료"] != 0]
        df_3 = (
            df_sales_today_shipped.groupby(["업체명", "특이사항", "도선료", "과세구분"])
            .agg({"수량": "count"})
            .reset_index()
        )

        df_3["품목명"] = "도선료"
        df_3 = df_3.rename(columns={"도선료": "단가"})
        df_3["상품매출"] = df_3["단가"] * df_3["수량"]

        # 2025-02-03 hoyeon.han: 벡터화 적용
        mask_tax_free_3 = df_3["과세구분"] == "면세"
        df_3["공급가"] = np.where(
            mask_tax_free_3, df_3["상품매출"], (df_3["상품매출"] / 1.1).round(0)
        )
        df_3["부가세"] = np.where(mask_tax_free_3, 0, df_3["상품매출"] - df_3["공급가"])

        # STEP 10: 일괄등록 시트 생성
        logger.log_info("STEP 10: 일괄등록 시트 생성")

        df_5 = pd.concat([df_1, df_2, df_3], ignore_index=True)
        df_5["거래일자"] = date
        df_5["구분"] = "사업자"
        df_5["거래처명"] = df_5["업체명"]

        # 2025-02-03 hoyeon.han: 벡터화 적용
        df_5["부가세구분"] = np.where(df_5["과세구분"] == "과세", "포함", "없음")

        df_5["프로젝트/현장"] = ""
        df_5["창고"] = ""
        df_5["품목월일"] = datetime.strptime(date, "%Y-%m-%d").strftime("%m%d")
        df_5["품목코드"] = ""
        df_5["규격"] = ""
        df_5["단위"] = ""
        df_5 = df_5.rename(
            columns={"공급가": "공급가액", "부가세": "세액", "특이사항": "품목비고"}
        )
        df_5["입금액"] = ""
        df_5["인수자"] = ""
        df_5["공통메모"] = ""

        # STEP 11: 마스터 데이터 조인
        logger.log_info("STEP 11: 마스터 데이터 조인")

        df_10 = pd.merge(
            left=df_5,
            right=df_customer,
            how="left",
            left_on="거래처명",
            right_on="거래처명_솔루미랩",
        ).reindex(
            [
                "거래일자",
                "구분",
                "거래처명",
                "사업자번호",
                "부가세구분",
                "프로젝트/현장",
                "창고",
                "품목월일",
                "품목코드",
                "품목명",
                "규격",
                "수량",
                "단위",
                "단가",
                "공급가액",
                "세액",
                "품목비고",
                "입금액",
                "인수자",
                "공통메모",
            ],
            axis=1,
        )

        df_10 = df_10.sort_values(["거래처명", "부가세구분", "품목비고", "품목명"])

        # 중복 행 처리
        df_10.loc[
            df_10.duplicated(["사업자번호", "거래처명", "부가세구분", "품목비고"]),
            [
                "거래일자",
                "구분",
                "거래처명",
                "사업자번호",
                "부가세구분",
                "프로젝트/현장",
                "창고",
            ],
        ] = ""

        # STEP 12: 검증 및 경고
        logger.log_info("STEP 12: 최종 검증")

        warnings = DataValidator.validate_master_data_join(df_10, len(df_sales_today))
        for warning in warnings:
            logger.log_warning(f"매출 데이터 경고: {warning}")

        # 성능 로그
        duration = (datetime.now() - start_time).total_seconds()
        logger.log_performance("매출 데이터 처리", duration, len(df_10))

        logger.log_info(f"매출 데이터 처리 완료: {len(df_10)}행, {duration:.2f}초")

        return df_10

    except SollumeBaseException:
        # 커스텀 예외는 그대로 전파
        raise

    except Exception as e:
        # 예상치 못한 오류는 ProcessingError로 래핑
        duration = (datetime.now() - start_time).total_seconds()
        logger.log_error(f"매출 데이터 처리 중 예외 발생", error=e)
        raise ProcessingError("매출 데이터 처리", e)


def get_purchase_daily(
    file_path: str,
    date: str,
    master_file_path: str = "거래처마스터.xlsx",
    use_db: bool = True,
    db_path: str = "database/customer_master.db",
) -> pd.DataFrame:
    """
    매입 데이터 처리 함수 (개선 버전)

    2025-11-29 hoyeon.han: Phase 2 개선
    - 오류 처리 및 검증 추가
    - 단계별 로깅
    - SettingWithCopyWarning 해결

    2025-12-16 hoyeon.han: Phase 5 개선
    - DB 사용 옵션 추가 (use_db 파라미터)
    - Excel과 DB를 선택적으로 사용 가능

    Args:
        file_path: 발주내역 파일 경로
        date: 처리 날짜 (YYYY-MM-DD)
        master_file_path: 거래처마스터 Excel 파일 경로 (use_db=False일 때)
        use_db: DB 사용 여부 (기본값: True)
        db_path: 거래처마스터 DB 파일 경로 (use_db=True일 때)

    Returns:
        경리나라 일괄등록 형식의 데이터프레임

    Raises:
        MasterFileNotFoundError: 거래처마스터 파일 없음
        SheetNotFoundError: 필수 시트 없음
        ColumnNotFoundError: 필수 컬럼 없음
        NoDataForDateError: 해당 날짜 데이터 없음
        ProcessingError: 처리 중 오류
    """
    logger = get_logger()
    sheet_name = "(누적)2025년 발주내역"
    start_time = datetime.now()

    try:
        logger.log_info(f"매입 데이터 처리 시작: {file_path}, {date}")

        # STEP 1-3: 파일 읽기 및 검증 (매출과 동일)
        logger.log_info("STEP 1: 발주내역 파일 읽기")
        try:
            DataValidator.validate_file_size(file_path)
            df = pd.read_excel(
                file_path, engine="openpyxl", sheet_name=sheet_name, header=3
            )
        except ValueError as e:
            if "Worksheet" in str(e):
                raise SheetNotFoundError(sheet_name, os.path.basename(file_path))
            raise ProcessingError("발주내역 파일 읽기", e)

        logger.log_info(f"발주내역 시트 읽기 완료: {len(df)}행")

        # 필수 컬럼 검증
        DataValidator.validate_columns(
            df, DataValidator.REQUIRED_COLUMNS_PURCHASE, sheet_name
        )

        # 거래처마스터 읽기
        # 2025-12-16 hoyeon.han: DB 또는 Excel에서 거래처마스터 읽기
        if use_db and DB_AVAILABLE:
            logger.log_info(f"STEP 2: 거래처마스터 DB 읽기 ({db_path})")
            if not os.path.exists(db_path):
                raise MasterFileNotFoundError(db_path)

            db = CustomerMasterDB(db_path)
            df_customer = db.get_all_customers()

            # 컬럼명 변환 (DB → Excel 형식)
            df_customer = df_customer.rename(
                columns={
                    "발주내역_거래처명": "거래처명_솔루미랩",
                    "경리나라_거래처명": "거래처명_경리나라",
                }
            )

            logger.log_info(f"거래처마스터 DB 읽기 완료: {len(df_customer)}행")
        else:
            logger.log_info("STEP 2: 거래처마스터 파일 읽기")
            if not os.path.exists(master_file_path):
                raise MasterFileNotFoundError(master_file_path)

            try:
                df_customer = pd.read_excel(
                    master_file_path,
                    engine="openpyxl",
                    sheet_name="거래처마스터",
                    header=0,
                )
            except ValueError as e:
                raise SheetNotFoundError(
                    "거래처마스터", os.path.basename(master_file_path)
                )

            DataValidator.validate_columns(
                df_customer, DataValidator.REQUIRED_MASTER_COLUMNS, "거래처마스터"
            )

            logger.log_info(f"거래처마스터 읽기 완료: {len(df_customer)}행")

        # STEP 4: 날짜 변환 및 필터링
        logger.log_info(f"STEP 3: 날짜 필터링 ({date})")
        today = datetime.strptime(date, "%Y-%m-%d")

        df["출고일"] = pd.to_datetime(df["출고일"], errors="coerce")

        # 2025-11-29 hoyeon.han: .copy() 추가로 SettingWithCopyWarning 방지
        df_buy_today = df[
            (df["출고일"] == today)
            & (df["특이사항"] != "솔루미재고")
            & (df["매입처"] != "당사재고")
            & (df["매입처"] != "솔루미랩")
        ].copy()

        # 컬럼 이름 변경
        df_buy_today = df_buy_today.rename(columns={"도선료.1": "매입도선료"})

        # 타입 변환
        df_buy_today = df_buy_today.astype(
            {"매입배송비": "float64", "매입도선료": "float64"}
        )

        # 데이터 존재 확인
        DataValidator.validate_date_data_exists(df_buy_today, date, len(df))

        logger.log_info(f"날짜 필터링 완료: {len(df_buy_today)}행")

        # STEP 5: 데이터 전처리
        logger.log_info("STEP 4: 데이터 전처리")

        df_buy_today["특이사항"] = df_buy_today["특이사항"].fillna("")
        df_buy_today["상품매입"] = df_buy_today["상품매입"].fillna(0)
        df_buy_today["매입배송비"] = df_buy_today["매입배송비"].fillna(0)
        df_buy_today["매입도선료"] = df_buy_today["매입도선료"].fillna(0)

        # 숫자 변환
        df_buy_today["상품매입"] = to_num(df_buy_today["상품매입"])
        df_buy_today["수량"] = to_num(df_buy_today["수량"])

        # 데이터 필터링
        df_buy_today = df_buy_today[
            (df_buy_today["상품매입"] != 0)
            | (df_buy_today["매입배송비"] != 0)
            | (df_buy_today["매입도선료"] != 0)
        ].copy()

        if len(df_buy_today) == 0:
            raise NoDataForDateError(date, len(df))

        logger.log_info(f"유효 데이터: {len(df_buy_today)}행")

        # STEP 6: 업무 로직 (업체별 특수 처리)
        logger.log_info("STEP 5: 업무 로직 적용 (업체별 특수 처리)")

        # 지앤제이: 매입배송비, 매입도선료 0 처리
        df_buy_today.loc[df_buy_today["매입처"] == "지앤제이", "매입배송비"] = 0
        df_buy_today.loc[df_buy_today["매입처"] == "지앤제이", "매입도선료"] = 0
        df_buy_today.loc[
            (df_buy_today["매입처"] == "지앤제이")
            & (df_buy_today["업체명"] == "빅웨이브즈"),
            "특이사항",
        ] = "빅웨이브즈"

        # 유스랩: 매입배송비, 매입도선료 0 처리
        df_buy_today.loc[df_buy_today["매입처"] == "유스랩", "매입배송비"] = 0
        df_buy_today.loc[df_buy_today["매입처"] == "유스랩", "매입도선료"] = 0
        df_buy_today.loc[
            (df_buy_today["매입처"] == "유스랩")
            & (df_buy_today["업체명"] == "빅웨이브즈"),
            "특이사항",
        ] = "빅웨이브즈"

        # 유라이크: 매입도선료 0 처리
        df_buy_today.loc[df_buy_today["매입처"] == "유라이크", "매입도선료"] = 0

        # 반품유무 추가
        # 2025-02-03 hoyeon.han: 벡터화 적용
        df_buy_today["반품유무"] = np.where(df_buy_today["수량"] < 0, "Y", "N")

        # 정렬
        df_buy_today = df_buy_today.sort_values(["매입처", "특이사항", "제품", "수량"])

        # STEP 7-9: 집계 (매출과 유사)
        logger.log_info("STEP 6: 제품 데이터 집계")

        df_11 = (
            df_buy_today.groupby(
                ["매입처", "특이사항", "제품", "과세구분", "반품유무"]
            )[["수량", "상품매입"]]
            .sum()
            .reset_index()
        )

        # 2025-02-03 hoyeon.han: 벡터화 적용
        df_11["단가"] = np.where(
            df_11["수량"] == 0, 0, df_11["상품매입"] / df_11["수량"]
        )

        mask_tax_free_11 = df_11["과세구분"] == "면세"
        df_11["공급가"] = np.where(
            mask_tax_free_11, df_11["상품매입"], (df_11["상품매입"] / 1.1).round(0)
        )
        df_11["부가세"] = np.where(
            mask_tax_free_11, 0, df_11["상품매입"] - df_11["공급가"]
        )

        df_11 = df_11.rename(columns={"제품": "품목명"})

        # 배송비 집계
        logger.log_info("STEP 7: 배송비 집계")

        df_buy_today_delivery = df_buy_today[df_buy_today["매입배송비"] > 0]
        df_12 = (
            df_buy_today_delivery.groupby(
                ["매입처", "특이사항", "매입배송비", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_12["품목명"] = "택배비"
        df_12 = df_12.rename(columns={"매입배송비": "단가"})
        df_12["상품매입"] = df_12["단가"] * df_12["수량"]

        # 2025-02-03 hoyeon.han: 벡터화 적용
        mask_tax_free_12 = df_12["과세구분"] == "면세"
        df_12["공급가"] = np.where(
            mask_tax_free_12, df_12["상품매입"], (df_12["상품매입"] / 1.1).round(0)
        )
        df_12["부가세"] = np.where(
            mask_tax_free_12, 0, df_12["상품매입"] - df_12["공급가"]
        )

        # 도선료 집계
        logger.log_info("STEP 8: 도선료 집계")

        df_buy_today_shipped = df_buy_today[df_buy_today["매입도선료"] > 0]
        df_13 = (
            df_buy_today_shipped.groupby(
                ["매입처", "특이사항", "매입도선료", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_13["품목명"] = "도선료"
        df_13 = df_13.rename(columns={"매입도선료": "단가"})
        df_13["상품매입"] = df_13["단가"] * df_13["수량"]

        # 2025-02-03 hoyeon.han: 벡터화 적용
        mask_tax_free_13 = df_13["과세구분"] == "면세"
        df_13["공급가"] = np.where(
            mask_tax_free_13, df_13["상품매입"], (df_13["상품매입"] / 1.1).round(0)
        )
        df_13["부가세"] = np.where(
            mask_tax_free_13, 0, df_13["상품매입"] - df_13["공급가"]
        )

        # STEP 10: 일괄등록 시트 생성
        logger.log_info("STEP 9: 일괄등록 시트 생성")

        df_15 = pd.concat([df_11, df_12, df_13], ignore_index=True)
        df_15["거래일자"] = date
        df_15["구분"] = "사업자"
        df_15["거래처명"] = df_15["매입처"]

        # 2025-02-03 hoyeon.han: 벡터화 적용
        df_15["부가세구분"] = np.where(df_15["과세구분"] == "과세", "포함", "없음")

        df_15["프로젝트/현장"] = ""
        df_15["창고"] = ""
        df_15["품목월일"] = datetime.strptime(date, "%Y-%m-%d").strftime("%m%d")
        df_15["품목코드"] = ""
        df_15["규격"] = ""
        df_15["단위"] = ""
        df_15 = df_15.rename(
            columns={"공급가": "공급가액", "부가세": "세액", "특이사항": "품목비고"}
        )
        df_15["입금액"] = ""
        df_15["인수자"] = ""
        df_15["공통메모"] = ""

        # STEP 11: 마스터 데이터 조인
        logger.log_info("STEP 10: 마스터 데이터 조인")

        df_20 = pd.merge(
            left=df_15,
            right=df_customer,
            how="left",
            left_on="거래처명",
            right_on="거래처명_솔루미랩",
        ).reindex(
            [
                "거래일자",
                "구분",
                "거래처명",
                "사업자번호",
                "부가세구분",
                "프로젝트/현장",
                "창고",
                "품목월일",
                "품목코드",
                "품목명",
                "규격",
                "수량",
                "단위",
                "단가",
                "공급가액",
                "세액",
                "품목비고",
                "입금액",
                "인수자",
                "공통메모",
            ],
            axis=1,
        )

        df_20 = df_20.sort_values(["거래처명", "부가세구분", "품목비고", "품목명"])

        df_20.loc[
            df_20.duplicated(["사업자번호", "거래처명", "부가세구분", "품목비고"]),
            [
                "거래일자",
                "구분",
                "거래처명",
                "사업자번호",
                "부가세구분",
                "프로젝트/현장",
                "창고",
            ],
        ] = ""

        # STEP 12: 검증 및 경고
        logger.log_info("STEP 11: 최종 검증")

        warnings = DataValidator.validate_master_data_join(df_20, len(df_buy_today))
        for warning in warnings:
            logger.log_warning(f"매입 데이터 경고: {warning}")

        # 성능 로그
        duration = (datetime.now() - start_time).total_seconds()
        logger.log_performance("매입 데이터 처리", duration, len(df_20))

        logger.log_info(f"매입 데이터 처리 완료: {len(df_20)}행, {duration:.2f}초")

        return df_20

    except SollumeBaseException:
        raise

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.log_error(f"매입 데이터 처리 중 예외 발생", error=e)
        raise ProcessingError("매입 데이터 처리", e)


def get_sales_by_period_vendor(
    file_path: str,
    start_date: str,
    end_date: str,
    vendor_name: str,
    sheet_name: str = "(누적)2025년 발주내역",
    master_file_path: str = "거래처마스터.xlsx",
    use_db: bool = True,
    db_path: str = "database/customer_master.db",
) -> pd.DataFrame:
    """
    기간별/업체별 매출 데이터 처리 함수

    Args:
        file_path: 발주내역 파일 경로
        start_date: 시작일 (YYYY-MM-DD)
        end_date: 종료일 (YYYY-MM-DD)
        vendor_name: 업체명
        sheet_name: 발주내역 시트명
        master_file_path: 거래처마스터 Excel 파일 경로 (use_db=False일 때)
        use_db: DB 사용 여부 (기본값: True)
        db_path: 거래처마스터 DB 파일 경로 (use_db=True일 때)

    Returns:
        경리나라 일괄등록 형식의 데이터프레임
        - 데이터가 없으면 빈 데이터프레임 반환
    """
    # 2026-04-08 hoyeon.han: 기간별/업체별 매출 전표 생성 함수 추가
    logger = get_logger()
    start_time = datetime.now()

    output_columns = [
        "거래일자",
        "구분",
        "거래처명",
        "사업자번호",
        "부가세구분",
        "프로젝트/현장",
        "창고",
        "품목월일",
        "품목코드",
        "품목명",
        "규격",
        "수량",
        "단위",
        "단가",
        "공급가액",
        "세액",
        "품목비고",
        "입금액",
        "인수자",
        "공통메모",
    ]

    try:
        logger.log_info(
            f"기간별/업체별 매출 데이터 처리 시작: {file_path}, {start_date}~{end_date}, {vendor_name}"
        )

        # STEP 1: 파일 읽기
        logger.log_info("STEP 1: 발주내역 파일 읽기")
        try:
            DataValidator.validate_file_size(file_path)
            df = pd.read_excel(
                file_path, engine="openpyxl", sheet_name=sheet_name, header=3
            )
        except ValueError as e:
            if "Worksheet" in str(e):
                raise SheetNotFoundError(sheet_name, os.path.basename(file_path))
            raise ProcessingError("발주내역 파일 읽기", e)

        logger.log_info(f"발주내역 시트 읽기 완료: {len(df)}행")

        # STEP 2: 필수 컬럼 검증
        logger.log_info("STEP 2: 필수 컬럼 검증")
        DataValidator.validate_columns(
            df, DataValidator.REQUIRED_COLUMNS_SALES, sheet_name
        )

        # STEP 3: 거래처마스터 읽기
        if use_db and DB_AVAILABLE:
            logger.log_info(f"STEP 3: 거래처마스터 DB 읽기 ({db_path})")
            if not os.path.exists(db_path):
                raise MasterFileNotFoundError(db_path)

            db = CustomerMasterDB(db_path)
            df_customer = db.get_all_customers()
            df_customer = df_customer.rename(
                columns={
                    "발주내역_거래처명": "거래처명_솔루미랩",
                    "경리나라_거래처명": "거래처명_경리나라",
                }
            )
            logger.log_info(f"거래처마스터 DB 읽기 완료: {len(df_customer)}행")
        else:
            logger.log_info("STEP 3: 거래처마스터 파일 읽기")
            if not os.path.exists(master_file_path):
                raise MasterFileNotFoundError(master_file_path)

            try:
                df_customer = pd.read_excel(
                    master_file_path,
                    engine="openpyxl",
                    sheet_name="거래처마스터",
                    header=0,
                )
            except ValueError:
                raise SheetNotFoundError(
                    "거래처마스터", os.path.basename(master_file_path)
                )

            DataValidator.validate_columns(
                df_customer, DataValidator.REQUIRED_MASTER_COLUMNS, "거래처마스터"
            )
            logger.log_info(f"거래처마스터 읽기 완료: {len(df_customer)}행")

        # STEP 4: 날짜/업체 필터링
        logger.log_info(
            f"STEP 4: 날짜/업체 필터링 ({start_date}~{end_date}, 업체: {vendor_name})"
        )
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        df["출고일"] = pd.to_datetime(df["출고일"], errors="coerce")
        df_sales_today = df[
            (df["출고일"] >= start_dt)
            & (df["출고일"] <= end_dt)
            & (df["계산서"] == "대상")
            & (df["업체명"] == vendor_name)
        ].copy()

        if len(df_sales_today) == 0:
            logger.log_info("필터링 결과 데이터 없음 - 빈 데이터프레임 반환")
            return pd.DataFrame(columns=output_columns)

        logger.log_info(f"날짜/업체 필터링 완료: {len(df_sales_today)}행")

        # STEP 5: 데이터 전처리
        logger.log_info("STEP 5: 데이터 전처리")
        df_sales_today["특이사항"] = df_sales_today["특이사항"].fillna("")
        df_sales_today["상품매출"] = df_sales_today["상품매출"].fillna(0)
        df_sales_today["판매배송비"] = df_sales_today["판매배송비"].fillna(0)
        df_sales_today["도선료"] = df_sales_today["도선료"].fillna(0)

        df_sales_today["상품매출"] = to_num(df_sales_today["상품매출"])
        df_sales_today["수량"] = to_num(df_sales_today["수량"])

        df_sales_today = df_sales_today[
            (df_sales_today["상품매출"] != 0)
            | (df_sales_today["판매배송비"] != 0)
            | (df_sales_today["도선료"] != 0)
        ].copy()

        if len(df_sales_today) == 0:
            logger.log_info("유효 데이터 없음 - 빈 데이터프레임 반환")
            return pd.DataFrame(columns=output_columns)

        logger.log_info(f"유효 데이터: {len(df_sales_today)}행")

        # STEP 6: 비즈니스 로직
        logger.log_info("STEP 6: 비즈니스 로직 적용")
        df_sales_today["반품유무"] = np.where(df_sales_today["수량"] < 0, "Y", "N")
        df_sales_today.loc[
            df_sales_today["업체명"].str.startswith("이너바우어", na=False), "업체명"
        ] = "이너바우어"
        df_sales_today = df_sales_today.sort_values(
            ["업체명", "특이사항", "제품", "수량"]
        )

        # STEP 7: 제품 데이터 집계
        logger.log_info("STEP 7: 제품 데이터 집계")
        df_1 = (
            df_sales_today.groupby(
                ["출고일", "업체명", "특이사항", "제품", "과세구분", "반품유무"]
            )[["수량", "상품매출"]]
            .sum()
            .reset_index()
        )

        df_1["단가"] = df_1.apply(
            lambda x: 0 if x["수량"] == 0 else x["상품매출"] / x["수량"], axis=1
        )
        df_1["공급가"] = df_1.apply(
            lambda x: x["상품매출"]
            if x["과세구분"] == "면세"
            else round(x["상품매출"] / 1.1, 0),
            axis=1,
        )
        df_1["부가세"] = df_1.apply(
            lambda x: 0 if x["과세구분"] == "면세" else x["상품매출"] - x["공급가"],
            axis=1,
        )
        df_1 = df_1.rename(columns={"제품": "품목명"})

        # STEP 8: 배송비 집계
        logger.log_info("STEP 8: 배송비 집계")
        df_sales_today_delivery = df_sales_today[df_sales_today["판매배송비"] != 0]
        df_2 = (
            df_sales_today_delivery.groupby(
                ["출고일", "업체명", "특이사항", "판매배송비", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_2["품목명"] = "택배비"
        df_2 = df_2.rename(columns={"판매배송비": "단가"})
        df_2["상품매출"] = df_2["단가"] * df_2["수량"]
        mask_tax_free_2 = df_2["과세구분"] == "면세"
        df_2["공급가"] = np.where(
            mask_tax_free_2, df_2["상품매출"], (df_2["상품매출"] / 1.1).round(0)
        )
        df_2["부가세"] = np.where(mask_tax_free_2, 0, df_2["상품매출"] - df_2["공급가"])

        # STEP 9: 도선료 집계
        logger.log_info("STEP 9: 도선료 집계")
        df_sales_today_shipped = df_sales_today[df_sales_today["도선료"] != 0]
        df_3 = (
            df_sales_today_shipped.groupby(
                ["출고일", "업체명", "특이사항", "도선료", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_3["품목명"] = "도선료"
        df_3 = df_3.rename(columns={"도선료": "단가"})
        df_3["상품매출"] = df_3["단가"] * df_3["수량"]
        mask_tax_free_3 = df_3["과세구분"] == "면세"
        df_3["공급가"] = np.where(
            mask_tax_free_3, df_3["상품매출"], (df_3["상품매출"] / 1.1).round(0)
        )
        df_3["부가세"] = np.where(mask_tax_free_3, 0, df_3["상품매출"] - df_3["공급가"])

        # STEP 10: 일괄등록 시트 생성
        logger.log_info("STEP 10: 일괄등록 시트 생성")
        df_5 = pd.concat([df_1, df_2, df_3], ignore_index=True)
        df_5["거래일자"] = df_5["출고일"].dt.strftime("%Y-%m-%d")
        df_5["구분"] = "사업자"
        df_5["거래처명"] = df_5["업체명"]
        df_5["부가세구분"] = np.where(df_5["과세구분"] == "과세", "포함", "없음")
        df_5["프로젝트/현장"] = ""
        df_5["창고"] = ""
        df_5["품목월일"] = df_5["출고일"].dt.strftime("%m%d")
        df_5["품목코드"] = ""
        df_5["규격"] = ""
        df_5["단위"] = ""
        df_5 = df_5.rename(
            columns={"공급가": "공급가액", "부가세": "세액", "특이사항": "품목비고"}
        )
        df_5["입금액"] = ""
        df_5["인수자"] = ""
        df_5["공통메모"] = ""

        # STEP 11: 마스터 데이터 조인
        logger.log_info("STEP 11: 마스터 데이터 조인")
        df_10 = pd.merge(
            left=df_5,
            right=df_customer,
            how="left",
            left_on="거래처명",
            right_on="거래처명_솔루미랩",
        ).reindex(output_columns, axis=1)

        # 2026-04-08 hoyeon.han: 모든 행에 헤더 정보 입력하도록 수정
        df_10 = df_10.sort_values(
            ["거래처명", "부가세구분", "품목비고", "품목월일", "품목명"]
        )

        # 2026-04-08 hoyeon.han: 품목비고+품목월일 그룹의 첫 행에만 헤더 정보 입력
        df_10.loc[
            df_10.duplicated(
                ["사업자번호", "거래처명", "부가세구분", "품목비고", "품목월일"]
            ),
            [
                "거래일자",
                "구분",
                "거래처명",
                "사업자번호",
                "부가세구분",
                "프로젝트/현장",
                "창고",
            ],
        ] = ""

        # STEP 12: 검증 및 경고
        logger.log_info("STEP 12: 최종 검증")
        warnings = DataValidator.validate_master_data_join(df_10, len(df_sales_today))
        for warning in warnings:
            logger.log_warning(f"기간별/업체별 매출 데이터 경고: {warning}")

        duration = (datetime.now() - start_time).total_seconds()
        logger.log_performance("기간별/업체별 매출 데이터 처리", duration, len(df_10))
        logger.log_info(
            f"기간별/업체별 매출 데이터 처리 완료: {len(df_10)}행, {duration:.2f}초"
        )

        return df_10

    except SollumeBaseException:
        raise

    except Exception as e:
        logger.log_error("기간별/업체별 매출 데이터 처리 중 예외 발생", error=e)
        raise ProcessingError("기간별/업체별 매출 데이터 처리", e)


def get_purchase_by_period_vendor(
    file_path: str,
    start_date: str,
    end_date: str,
    vendor_name: str,
    sheet_name: str = "(누적)2025년 발주내역",
    master_file_path: str = "거래처마스터.xlsx",
    use_db: bool = True,
    db_path: str = "database/customer_master.db",
) -> pd.DataFrame:
    """
    기간별/업체별 매입 데이터 처리 함수

    Args:
        file_path: 발주내역 파일 경로
        start_date: 시작일 (YYYY-MM-DD)
        end_date: 종료일 (YYYY-MM-DD)
        vendor_name: 매입처명
        sheet_name: 발주내역 시트명
        master_file_path: 거래처마스터 Excel 파일 경로 (use_db=False일 때)
        use_db: DB 사용 여부 (기본값: True)
        db_path: 거래처마스터 DB 파일 경로 (use_db=True일 때)

    Returns:
        경리나라 일괄등록 형식의 데이터프레임
        - 데이터가 없으면 빈 데이터프레임 반환
    """
    # 2026-04-08 hoyeon.han: 기간별/업체별 매입 전표 생성 함수 추가
    logger = get_logger()
    start_time = datetime.now()

    output_columns = [
        "거래일자",
        "구분",
        "거래처명",
        "사업자번호",
        "부가세구분",
        "프로젝트/현장",
        "창고",
        "품목월일",
        "품목코드",
        "품목명",
        "규격",
        "수량",
        "단위",
        "단가",
        "공급가액",
        "세액",
        "품목비고",
        "입금액",
        "인수자",
        "공통메모",
    ]

    try:
        logger.log_info(
            f"기간별/업체별 매입 데이터 처리 시작: {file_path}, {start_date}~{end_date}, {vendor_name}"
        )

        # STEP 1: 파일 읽기
        logger.log_info("STEP 1: 발주내역 파일 읽기")
        try:
            DataValidator.validate_file_size(file_path)
            df = pd.read_excel(
                file_path, engine="openpyxl", sheet_name=sheet_name, header=3
            )
        except ValueError as e:
            if "Worksheet" in str(e):
                raise SheetNotFoundError(sheet_name, os.path.basename(file_path))
            raise ProcessingError("발주내역 파일 읽기", e)

        logger.log_info(f"발주내역 시트 읽기 완료: {len(df)}행")

        # STEP 2: 필수 컬럼 검증
        logger.log_info("STEP 2: 필수 컬럼 검증")
        DataValidator.validate_columns(
            df, DataValidator.REQUIRED_COLUMNS_PURCHASE, sheet_name
        )

        # STEP 3: 거래처마스터 읽기
        if use_db and DB_AVAILABLE:
            logger.log_info(f"STEP 3: 거래처마스터 DB 읽기 ({db_path})")
            if not os.path.exists(db_path):
                raise MasterFileNotFoundError(db_path)

            db = CustomerMasterDB(db_path)
            df_customer = db.get_all_customers()
            df_customer = df_customer.rename(
                columns={
                    "발주내역_거래처명": "거래처명_솔루미랩",
                    "경리나라_거래처명": "거래처명_경리나라",
                }
            )
            logger.log_info(f"거래처마스터 DB 읽기 완료: {len(df_customer)}행")
        else:
            logger.log_info("STEP 3: 거래처마스터 파일 읽기")
            if not os.path.exists(master_file_path):
                raise MasterFileNotFoundError(master_file_path)

            try:
                df_customer = pd.read_excel(
                    master_file_path,
                    engine="openpyxl",
                    sheet_name="거래처마스터",
                    header=0,
                )
            except ValueError:
                raise SheetNotFoundError(
                    "거래처마스터", os.path.basename(master_file_path)
                )

            DataValidator.validate_columns(
                df_customer, DataValidator.REQUIRED_MASTER_COLUMNS, "거래처마스터"
            )
            logger.log_info(f"거래처마스터 읽기 완료: {len(df_customer)}행")

        # STEP 4: 날짜/매입처 필터링
        logger.log_info(
            f"STEP 4: 날짜/매입처 필터링 ({start_date}~{end_date}, 매입처: {vendor_name})"
        )
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        df["출고일"] = pd.to_datetime(df["출고일"], errors="coerce")
        df_buy_today = df[
            (df["출고일"] >= start_dt)
            & (df["출고일"] <= end_dt)
            & (df["매입처"] == vendor_name)
            & (df["특이사항"] != "솔루미재고")
            & (df["매입처"] != "당사재고")
            & (df["매입처"] != "솔루미랩")
        ].copy()

        if len(df_buy_today) == 0:
            logger.log_info("필터링 결과 데이터 없음 - 빈 데이터프레임 반환")
            return pd.DataFrame(columns=output_columns)

        logger.log_info(f"날짜/매입처 필터링 완료: {len(df_buy_today)}행")

        # 컬럼 이름 변경
        df_buy_today = df_buy_today.rename(columns={"도선료.1": "매입도선료"})

        # 타입 변환
        df_buy_today = df_buy_today.astype(
            {"매입배송비": "float64", "매입도선료": "float64"}
        )

        # STEP 5: 데이터 전처리
        logger.log_info("STEP 5: 데이터 전처리")
        df_buy_today["특이사항"] = df_buy_today["특이사항"].fillna("")
        df_buy_today["상품매입"] = df_buy_today["상품매입"].fillna(0)
        df_buy_today["매입배송비"] = df_buy_today["매입배송비"].fillna(0)
        df_buy_today["매입도선료"] = df_buy_today["매입도선료"].fillna(0)

        df_buy_today["상품매입"] = to_num(df_buy_today["상품매입"])
        df_buy_today["수량"] = to_num(df_buy_today["수량"])

        df_buy_today = df_buy_today[
            (df_buy_today["상품매입"] != 0)
            | (df_buy_today["매입배송비"] != 0)
            | (df_buy_today["매입도선료"] != 0)
        ].copy()

        if len(df_buy_today) == 0:
            logger.log_info("유효 데이터 없음 - 빈 데이터프레임 반환")
            return pd.DataFrame(columns=output_columns)

        logger.log_info(f"유효 데이터: {len(df_buy_today)}행")

        # STEP 6: 업무 로직 (업체별 특수 처리)
        logger.log_info("STEP 6: 업무 로직 적용 (업체별 특수 처리)")

        # 지앤제이: 매입배송비, 매입도선료 0 처리
        df_buy_today.loc[df_buy_today["매입처"] == "지앤제이", "매입배송비"] = 0
        df_buy_today.loc[df_buy_today["매입처"] == "지앤제이", "매입도선료"] = 0

        # 유스랩: 매입배송비, 매입도선료 0 처리
        df_buy_today.loc[df_buy_today["매입처"] == "유스랩", "매입배송비"] = 0
        df_buy_today.loc[df_buy_today["매입처"] == "유스랩", "매입도선료"] = 0

        # 2026-04-13 hoyeon.han: 빅웨이브즈 특이사항 설정 추가 (get_purchase_daily와 동기화)
        # 지앤제이 + 빅웨이브즈인 경우 특이사항 설정
        df_buy_today.loc[
            (df_buy_today["매입처"] == "지앤제이")
            & (df_buy_today["업체명"] == "빅웨이브즈"),
            "특이사항",
        ] = "빅웨이브즈"

        # 유스랩 + 빅웨이브즈인 경우 특이사항 설정
        df_buy_today.loc[
            (df_buy_today["매입처"] == "유스랩")
            & (df_buy_today["업체명"] == "빅웨이브즈"),
            "특이사항",
        ] = "빅웨이브즈"

        # 유라이크: 매입도선료 0 처리
        df_buy_today.loc[df_buy_today["매입처"] == "유라이크", "매입도선료"] = 0

        df_buy_today["반품유무"] = np.where(df_buy_today["수량"] < 0, "Y", "N")
        df_buy_today = df_buy_today.sort_values(["매입처", "특이사항", "제품", "수량"])

        # STEP 7: 제품 데이터 집계
        logger.log_info("STEP 7: 제품 데이터 집계")
        df_11 = (
            df_buy_today.groupby(
                ["출고일", "매입처", "특이사항", "제품", "과세구분", "반품유무"]
            )[["수량", "상품매입"]]
            .sum()
            .reset_index()
        )

        df_11["단가"] = np.where(
            df_11["수량"] == 0, 0, df_11["상품매입"] / df_11["수량"]
        )
        mask_tax_free_11 = df_11["과세구분"] == "면세"
        df_11["공급가"] = np.where(
            mask_tax_free_11, df_11["상품매입"], (df_11["상품매입"] / 1.1).round(0)
        )
        df_11["부가세"] = np.where(
            mask_tax_free_11, 0, df_11["상품매입"] - df_11["공급가"]
        )
        df_11 = df_11.rename(columns={"제품": "품목명"})

        # STEP 8: 배송비 집계
        logger.log_info("STEP 8: 배송비 집계")
        df_buy_today_delivery = df_buy_today[df_buy_today["매입배송비"] > 0]
        df_12 = (
            df_buy_today_delivery.groupby(
                ["출고일", "매입처", "특이사항", "매입배송비", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_12["품목명"] = "택배비"
        df_12 = df_12.rename(columns={"매입배송비": "단가"})
        df_12["상품매입"] = df_12["단가"] * df_12["수량"]
        mask_tax_free_12 = df_12["과세구분"] == "면세"
        df_12["공급가"] = np.where(
            mask_tax_free_12, df_12["상품매입"], (df_12["상품매입"] / 1.1).round(0)
        )
        df_12["부가세"] = np.where(
            mask_tax_free_12, 0, df_12["상품매입"] - df_12["공급가"]
        )

        # STEP 9: 도선료 집계
        logger.log_info("STEP 9: 도선료 집계")
        df_buy_today_shipped = df_buy_today[df_buy_today["매입도선료"] > 0]
        df_13 = (
            df_buy_today_shipped.groupby(
                ["출고일", "매입처", "특이사항", "매입도선료", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_13["품목명"] = "도선료"
        df_13 = df_13.rename(columns={"매입도선료": "단가"})
        df_13["상품매입"] = df_13["단가"] * df_13["수량"]
        mask_tax_free_13 = df_13["과세구분"] == "면세"
        df_13["공급가"] = np.where(
            mask_tax_free_13, df_13["상품매입"], (df_13["상품매입"] / 1.1).round(0)
        )
        df_13["부가세"] = np.where(
            mask_tax_free_13, 0, df_13["상품매입"] - df_13["공급가"]
        )

        # STEP 10: 일괄등록 시트 생성
        logger.log_info("STEP 10: 일괄등록 시트 생성")
        df_15 = pd.concat([df_11, df_12, df_13], ignore_index=True)
        # 2026-04-08 hoyeon.han: 원본 출고일 기반 거래일자 유지
        df_15["거래일자"] = df_15["출고일"].dt.strftime("%Y-%m-%d")
        df_15["구분"] = "사업자"
        df_15["거래처명"] = df_15["매입처"]
        df_15["부가세구분"] = np.where(df_15["과세구분"] == "과세", "포함", "없음")
        df_15["프로젝트/현장"] = ""
        df_15["창고"] = ""
        df_15["품목월일"] = df_15["출고일"].dt.strftime("%m%d")
        df_15["품목코드"] = ""
        df_15["규격"] = ""
        df_15["단위"] = ""
        df_15 = df_15.rename(
            columns={"공급가": "공급가액", "부가세": "세액", "특이사항": "품목비고"}
        )
        df_15["입금액"] = ""
        df_15["인수자"] = ""
        df_15["공통메모"] = ""

        # STEP 11: 마스터 데이터 조인
        logger.log_info("STEP 11: 마스터 데이터 조인")
        df_20 = pd.merge(
            left=df_15,
            right=df_customer,
            how="left",
            left_on="거래처명",
            right_on="거래처명_솔루미랩",
        ).reindex(output_columns, axis=1)

        # 2026-04-08 hoyeon.han: 모든 행에 헤더 정보 입력하도록 수정
        df_20 = df_20.sort_values(
            ["거래처명", "부가세구분", "품목비고", "품목월일", "품목명"]
        )

        # 2026-04-08 hoyeon.han: 품목비고+품목월일 그룹의 첫 행에만 헤더 정보 입력
        df_20.loc[
            df_20.duplicated(
                ["사업자번호", "거래처명", "부가세구분", "품목비고", "품목월일"]
            ),
            [
                "거래일자",
                "구분",
                "거래처명",
                "사업자번호",
                "부가세구분",
                "프로젝트/현장",
                "창고",
            ],
        ] = ""

        # STEP 12: 검증 및 경고
        logger.log_info("STEP 12: 최종 검증")
        warnings = DataValidator.validate_master_data_join(df_20, len(df_buy_today))
        for warning in warnings:
            logger.log_warning(f"기간별/업체별 매입 데이터 경고: {warning}")

        duration = (datetime.now() - start_time).total_seconds()
        logger.log_performance("기간별/업체별 매입 데이터 처리", duration, len(df_20))
        logger.log_info(
            f"기간별/업체별 매입 데이터 처리 완료: {len(df_20)}행, {duration:.2f}초"
        )

        return df_20

    except SollumeBaseException:
        raise

    except Exception as e:
        logger.log_error("기간별/업체별 매입 데이터 처리 중 예외 발생", error=e)
        raise ProcessingError("기간별/업체별 매입 데이터 처리", e)


# 2026-04-09 hoyeon.han: 기간 통합 매입 전표 생성 함수 추가
def get_purchase_by_period(
    file_path,
    start_date,
    end_date,
    sheet_name="(누적)2025년 발주내역",
    master_file_path="거래처마스터.xlsx",
    use_db=True,
    db_path="database/customer_master.db",
    # 2026-07-13 hoyeon.han: 개별 날짜 목록 / 업체(매입처) 다중 선택 지원 인자 추가
    dates=None,  # list[date|str] | None — 주면 기간 대신 이 날짜들만 처리(isin)
    vendor_names=None,  # list[str] | None — 주면 해당 업체(매입처)만, None/빈값이면 전체
) -> pd.DataFrame:
    """
    기간별 매입 데이터 처리 함수

    # 2026-04-09 hoyeon.han: 기간 통합 매입 전표 생성 함수 추가

    Args:
        file_path: 발주내역 파일 경로
        start_date: 시작일 (YYYY-MM-DD)
        end_date: 종료일 (YYYY-MM-DD)
        sheet_name: 발주내역 시트명
        master_file_path: 거래처마스터 Excel 파일 경로 (use_db=False일 때)
        use_db: DB 사용 여부 (기본값: True)
        db_path: 거래처마스터 DB 파일 경로 (use_db=True일 때)

    Returns:
        경리나라 일괄등록 형식의 데이터프레임
        - 데이터가 없으면 빈 데이터프레임 반환
    """
    logger = get_logger()
    start_time = datetime.now()

    output_columns = [
        "거래일자",
        "구분",
        "거래처명",
        "사업자번호",
        "부가세구분",
        "프로젝트/현장",
        "창고",
        "품목월일",
        "품목코드",
        "품목명",
        "규격",
        "수량",
        "단위",
        "단가",
        "공급가액",
        "세액",
        "품목비고",
        "입금액",
        "인수자",
        "공통메모",
    ]

    try:
        logger.log_info(
            f"기간별 매입 데이터 처리 시작: {file_path}, {start_date}~{end_date}"
        )

        # STEP 1: 파일 읽기
        logger.log_info("STEP 1: 발주내역 파일 읽기")
        try:
            DataValidator.validate_file_size(file_path)
            df = pd.read_excel(
                file_path, engine="openpyxl", sheet_name=sheet_name, header=3
            )
        except ValueError as e:
            if "Worksheet" in str(e):
                raise SheetNotFoundError(sheet_name, os.path.basename(file_path))
            raise ProcessingError("발주내역 파일 읽기", e)

        logger.log_info(f"발주내역 시트 읽기 완료: {len(df)}행")

        # STEP 2: 필수 컬럼 검증
        logger.log_info("STEP 2: 필수 컬럼 검증")
        DataValidator.validate_columns(
            df, DataValidator.REQUIRED_COLUMNS_PURCHASE, sheet_name
        )

        # STEP 3: 거래처마스터 읽기
        if use_db and DB_AVAILABLE:
            logger.log_info(f"STEP 3: 거래처마스터 DB 읽기 ({db_path})")
            if not os.path.exists(db_path):
                raise MasterFileNotFoundError(db_path)

            db = CustomerMasterDB(db_path)
            df_customer = db.get_all_customers()
            df_customer = df_customer.rename(
                columns={
                    "발주내역_거래처명": "거래처명_솔루미랩",
                    "경리나라_거래처명": "거래처명_경리나라",
                }
            )
            logger.log_info(f"거래처마스터 DB 읽기 완료: {len(df_customer)}행")
        else:
            logger.log_info("STEP 3: 거래처마스터 파일 읽기")
            if not os.path.exists(master_file_path):
                raise MasterFileNotFoundError(master_file_path)

            try:
                df_customer = pd.read_excel(
                    master_file_path,
                    engine="openpyxl",
                    sheet_name="거래처마스터",
                    header=0,
                )
            except ValueError:
                raise SheetNotFoundError(
                    "거래처마스터", os.path.basename(master_file_path)
                )

            DataValidator.validate_columns(
                df_customer, DataValidator.REQUIRED_MASTER_COLUMNS, "거래처마스터"
            )
            logger.log_info(f"거래처마스터 읽기 완료: {len(df_customer)}행")

        # STEP 4: 날짜/매입처 필터링
        logger.log_info(f"STEP 4: 날짜 필터링 ({start_date}~{end_date})")
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        df["출고일"] = pd.to_datetime(df["출고일"], errors="coerce")
        # --- 기존 코드 (주석 처리) 2026-07-13 hoyeon.han ---
        # df_buy_today = df[
        #     (df["출고일"] >= start_dt)
        #     & (df["출고일"] <= end_dt)
        #     & (df["특이사항"] != "솔루미재고")
        #     & (df["매입처"] != "당사재고")
        #     & (df["매입처"] != "솔루미랩")
        # ].copy()
        # --- 기존 코드 끝 ---
        # 2026-07-13 hoyeon.han: 개별 날짜(dates) 지정 시 isin, 아니면 기간 범위
        if dates:
            _wanted = pd.to_datetime(list(dates)).normalize()
            _date_mask = df["출고일"].dt.normalize().isin(_wanted)
        else:
            _date_mask = (df["출고일"] >= start_dt) & (df["출고일"] <= end_dt)
        _mask = (
            _date_mask
            & (df["특이사항"] != "솔루미재고")
            & (df["매입처"] != "당사재고")
            & (df["매입처"] != "솔루미랩")
        )
        # 2026-07-13 hoyeon.han: 업체(매입처) 다중 선택 필터 (미지정=전체)
        if vendor_names:
            _mask &= df["매입처"].isin(list(vendor_names))
        df_buy_today = df[_mask].copy()

        if len(df_buy_today) == 0:
            logger.log_info("필터링 결과 데이터 없음 - 빈 데이터프레임 반환")
            return pd.DataFrame(columns=output_columns)

        logger.log_info(f"날짜 필터링 완료: {len(df_buy_today)}행")

        # 컬럼 이름 변경
        df_buy_today = df_buy_today.rename(columns={"도선료.1": "매입도선료"})

        # 타입 변환
        df_buy_today = df_buy_today.astype(
            {"매입배송비": "float64", "매입도선료": "float64"}
        )

        # STEP 5: 데이터 전처리
        logger.log_info("STEP 5: 데이터 전처리")
        df_buy_today["특이사항"] = df_buy_today["특이사항"].fillna("")
        df_buy_today["상품매입"] = df_buy_today["상품매입"].fillna(0)
        df_buy_today["매입배송비"] = df_buy_today["매입배송비"].fillna(0)
        df_buy_today["매입도선료"] = df_buy_today["매입도선료"].fillna(0)

        df_buy_today["상품매입"] = to_num(df_buy_today["상품매입"])
        df_buy_today["수량"] = to_num(df_buy_today["수량"])

        df_buy_today = df_buy_today[
            (df_buy_today["상품매입"] != 0)
            | (df_buy_today["매입배송비"] != 0)
            | (df_buy_today["매입도선료"] != 0)
        ].copy()

        if len(df_buy_today) == 0:
            logger.log_info("유효 데이터 없음 - 빈 데이터프레임 반환")
            return pd.DataFrame(columns=output_columns)

        logger.log_info(f"유효 데이터: {len(df_buy_today)}행")

        # STEP 6: 업무 로직 (업체별 특수 처리)
        logger.log_info("STEP 6: 업무 로직 적용 (업체별 특수 처리)")

        # 지앤제이: 매입배송비, 매입도선료 0 처리
        df_buy_today.loc[df_buy_today["매입처"] == "지앤제이", "매입배송비"] = 0
        df_buy_today.loc[df_buy_today["매입처"] == "지앤제이", "매입도선료"] = 0

        # 유스랩: 매입배송비, 매입도선료 0 처리
        df_buy_today.loc[df_buy_today["매입처"] == "유스랩", "매입배송비"] = 0
        df_buy_today.loc[df_buy_today["매입처"] == "유스랩", "매입도선료"] = 0

        # 2026-04-13 hoyeon.han: 빅웨이브즈 특이사항 설정 추가 (get_purchase_daily와 동기화)
        # 지앤제이 + 빅웨이브즈인 경우 특이사항 설정
        df_buy_today.loc[
            (df_buy_today["매입처"] == "지앤제이")
            & (df_buy_today["업체명"] == "빅웨이브즈"),
            "특이사항",
        ] = "빅웨이브즈"

        # 유스랩 + 빅웨이브즈인 경우 특이사항 설정
        df_buy_today.loc[
            (df_buy_today["매입처"] == "유스랩")
            & (df_buy_today["업체명"] == "빅웨이브즈"),
            "특이사항",
        ] = "빅웨이브즈"

        # 유라이크: 매입도선료 0 처리
        df_buy_today.loc[df_buy_today["매입처"] == "유라이크", "매입도선료"] = 0

        df_buy_today["반품유무"] = np.where(df_buy_today["수량"] < 0, "Y", "N")
        df_buy_today = df_buy_today.sort_values(["매입처", "특이사항", "제품", "수량"])

        # STEP 7: 제품 데이터 집계
        logger.log_info("STEP 7: 제품 데이터 집계")
        df_11 = (
            df_buy_today.groupby(
                ["출고일", "매입처", "특이사항", "제품", "과세구분", "반품유무"]
            )[["수량", "상품매입"]]
            .sum()
            .reset_index()
        )

        df_11["단가"] = np.where(
            df_11["수량"] == 0, 0, df_11["상품매입"] / df_11["수량"]
        )
        mask_tax_free_11 = df_11["과세구분"] == "면세"
        df_11["공급가"] = np.where(
            mask_tax_free_11, df_11["상품매입"], (df_11["상품매입"] / 1.1).round(0)
        )
        df_11["부가세"] = np.where(
            mask_tax_free_11, 0, df_11["상품매입"] - df_11["공급가"]
        )
        df_11 = df_11.rename(columns={"제품": "품목명"})

        # STEP 8: 배송비 집계
        logger.log_info("STEP 8: 배송비 집계")
        df_buy_today_delivery = df_buy_today[df_buy_today["매입배송비"] > 0]
        df_12 = (
            df_buy_today_delivery.groupby(
                ["출고일", "매입처", "특이사항", "매입배송비", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_12["품목명"] = "택배비"
        df_12 = df_12.rename(columns={"매입배송비": "단가"})
        df_12["상품매입"] = df_12["단가"] * df_12["수량"]
        mask_tax_free_12 = df_12["과세구분"] == "면세"
        df_12["공급가"] = np.where(
            mask_tax_free_12, df_12["상품매입"], (df_12["상품매입"] / 1.1).round(0)
        )
        df_12["부가세"] = np.where(
            mask_tax_free_12, 0, df_12["상품매입"] - df_12["공급가"]
        )

        # STEP 9: 도선료 집계
        logger.log_info("STEP 9: 도선료 집계")
        df_buy_today_shipped = df_buy_today[df_buy_today["매입도선료"] > 0]
        df_13 = (
            df_buy_today_shipped.groupby(
                ["출고일", "매입처", "특이사항", "매입도선료", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_13["품목명"] = "도선료"
        df_13 = df_13.rename(columns={"매입도선료": "단가"})
        df_13["상품매입"] = df_13["단가"] * df_13["수량"]
        mask_tax_free_13 = df_13["과세구분"] == "면세"
        df_13["공급가"] = np.where(
            mask_tax_free_13, df_13["상품매입"], (df_13["상품매입"] / 1.1).round(0)
        )
        df_13["부가세"] = np.where(
            mask_tax_free_13, 0, df_13["상품매입"] - df_13["공급가"]
        )

        # STEP 10: 일괄등록 시트 생성
        logger.log_info("STEP 10: 일괄등록 시트 생성")
        df_15 = pd.concat([df_11, df_12, df_13], ignore_index=True)
        # 2026-04-09 hoyeon.han: 원본 출고일 기반 거래일자 유지
        df_15["거래일자"] = df_15["출고일"].dt.strftime("%Y-%m-%d")
        df_15["구분"] = "사업자"
        df_15["거래처명"] = df_15["매입처"]
        df_15["부가세구분"] = np.where(df_15["과세구분"] == "과세", "포함", "없음")
        df_15["프로젝트/현장"] = ""
        df_15["창고"] = ""
        df_15["품목월일"] = df_15["출고일"].dt.strftime("%m%d")
        df_15["품목코드"] = ""
        df_15["규격"] = ""
        df_15["단위"] = ""
        df_15 = df_15.rename(
            columns={"공급가": "공급가액", "부가세": "세액", "특이사항": "품목비고"}
        )
        df_15["입금액"] = ""
        df_15["인수자"] = ""
        df_15["공통메모"] = ""

        # STEP 11: 마스터 데이터 조인
        logger.log_info("STEP 11: 마스터 데이터 조인")
        df_20 = pd.merge(
            left=df_15,
            right=df_customer,
            how="left",
            left_on="거래처명",
            right_on="거래처명_솔루미랩",
        ).reindex(output_columns, axis=1)

        # 2026-04-09 hoyeon.han: 모든 행에 헤더 정보 입력하도록 수정
        df_20 = df_20.sort_values(
            ["거래처명", "부가세구분", "품목비고", "품목월일", "품목명"]
        )

        # 2026-04-09 hoyeon.han: 품목비고+품목월일 그룹의 첫 행에만 헤더 정보 입력
        df_20.loc[
            df_20.duplicated(
                ["사업자번호", "거래처명", "부가세구분", "품목비고", "품목월일"]
            ),
            [
                "거래일자",
                "구분",
                "거래처명",
                "사업자번호",
                "부가세구분",
                "프로젝트/현장",
                "창고",
            ],
        ] = ""

        # STEP 12: 검증 및 경고
        logger.log_info("STEP 12: 최종 검증")
        warnings = DataValidator.validate_master_data_join(df_20, len(df_buy_today))
        for warning in warnings:
            logger.log_warning(f"기간별 매입 데이터 경고: {warning}")

        duration = (datetime.now() - start_time).total_seconds()
        logger.log_performance("기간별 매입 데이터 처리", duration, len(df_20))
        logger.log_info(
            f"기간별 매입 데이터 처리 완료: {len(df_20)}행, {duration:.2f}초"
        )

        return df_20

    except SollumeBaseException:
        raise

    except Exception as e:
        logger.log_error("기간별 매입 데이터 처리 중 예외 발생", error=e)
        raise ProcessingError("기간별 매입 데이터 처리", e)


def get_sales_by_period(
    file_path: str,
    start_date: str,
    end_date: str,
    sheet_name: str = "(누적)2025년 발주내역",
    master_file_path: str = "거래처마스터.xlsx",
    use_db: bool = True,
    db_path: str = "database/customer_master.db",
    # 2026-07-13 hoyeon.han: 개별 날짜 목록 / 업체(업체명) 다중 선택 지원 인자 추가
    dates=None,  # list[date|str] | None — 주면 기간 대신 이 날짜들만 처리(isin)
    vendor_names=None,  # list[str] | None — 주면 해당 업체(업체명)만, None/빈값이면 전체
) -> pd.DataFrame:
    """
    # 2026-04-09 hoyeon.han: 기간 통합 매출 전표 생성 함수 추가

    기간별 매출 데이터 처리 함수

    Args:
        file_path: 발주내역 파일 경로
        start_date: 시작일 (YYYY-MM-DD)
        end_date: 종료일 (YYYY-MM-DD)
        sheet_name: 발주내역 시트명
        master_file_path: 거래처마스터 Excel 파일 경로 (use_db=False일 때)
        use_db: DB 사용 여부 (기본값: True)
        db_path: 거래처마스터 DB 파일 경로 (use_db=True일 때)

    Returns:
        경리나라 일괄등록 형식의 데이터프레임
        - 데이터가 없으면 빈 데이터프레임 반환
    """
    # 2026-04-09 hoyeon.han: 기간 통합 매출 전표 생성 함수 추가
    logger = get_logger()
    start_time = datetime.now()

    output_columns = [
        "거래일자",
        "구분",
        "거래처명",
        "사업자번호",
        "부가세구분",
        "프로젝트/현장",
        "창고",
        "품목월일",
        "품목코드",
        "품목명",
        "규격",
        "수량",
        "단위",
        "단가",
        "공급가액",
        "세액",
        "품목비고",
        "입금액",
        "인수자",
        "공통메모",
    ]

    try:
        logger.log_info(
            f"기간 통합 매출 데이터 처리 시작: {file_path}, {start_date}~{end_date}"
        )

        # STEP 1: 파일 읽기
        logger.log_info("STEP 1: 발주내역 파일 읽기")
        try:
            DataValidator.validate_file_size(file_path)
            df = pd.read_excel(
                file_path, engine="openpyxl", sheet_name=sheet_name, header=3
            )
        except ValueError as e:
            if "Worksheet" in str(e):
                raise SheetNotFoundError(sheet_name, os.path.basename(file_path))
            raise ProcessingError("발주내역 파일 읽기", e)

        logger.log_info(f"발주내역 시트 읽기 완료: {len(df)}행")

        # STEP 2: 필수 컬럼 검증
        logger.log_info("STEP 2: 필수 컬럼 검증")
        DataValidator.validate_columns(
            df, DataValidator.REQUIRED_COLUMNS_SALES, sheet_name
        )

        # STEP 3: 거래처마스터 읽기
        if use_db and DB_AVAILABLE:
            logger.log_info(f"STEP 3: 거래처마스터 DB 읽기 ({db_path})")
            if not os.path.exists(db_path):
                raise MasterFileNotFoundError(db_path)

            db = CustomerMasterDB(db_path)
            df_customer = db.get_all_customers()
            df_customer = df_customer.rename(
                columns={
                    "발주내역_거래처명": "거래처명_솔루미랩",
                    "경리나라_거래처명": "거래처명_경리나라",
                }
            )
            logger.log_info(f"거래처마스터 DB 읽기 완료: {len(df_customer)}행")
        else:
            logger.log_info("STEP 3: 거래처마스터 파일 읽기")
            if not os.path.exists(master_file_path):
                raise MasterFileNotFoundError(master_file_path)

            try:
                df_customer = pd.read_excel(
                    master_file_path,
                    engine="openpyxl",
                    sheet_name="거래처마스터",
                    header=0,
                )
            except ValueError:
                raise SheetNotFoundError(
                    "거래처마스터", os.path.basename(master_file_path)
                )

            DataValidator.validate_columns(
                df_customer, DataValidator.REQUIRED_MASTER_COLUMNS, "거래처마스터"
            )
            logger.log_info(f"거래처마스터 읽기 완료: {len(df_customer)}행")

        # STEP 4: 날짜/계산서 필터링
        logger.log_info(f"STEP 4: 날짜/계산서 필터링 ({start_date}~{end_date})")
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        df["출고일"] = pd.to_datetime(df["출고일"], errors="coerce")
        # --- 기존 코드 (주석 처리) 2026-07-13 hoyeon.han ---
        # df_sales_today = df[
        #     (df["출고일"] >= start_dt)
        #     & (df["출고일"] <= end_dt)
        #     & (df["계산서"] == "대상")
        # ].copy()
        # --- 기존 코드 끝 ---
        # 2026-07-13 hoyeon.han: 개별 날짜(dates) 지정 시 isin, 아니면 기간 범위
        if dates:
            _wanted = pd.to_datetime(list(dates)).normalize()
            _date_mask = df["출고일"].dt.normalize().isin(_wanted)
        else:
            _date_mask = (df["출고일"] >= start_dt) & (df["출고일"] <= end_dt)
        _mask = _date_mask & (df["계산서"] == "대상")
        # 2026-07-13 hoyeon.han: 업체(업체명) 다중 선택 필터 (미지정=전체)
        if vendor_names:
            _mask &= df["업체명"].isin(list(vendor_names))
        df_sales_today = df[_mask].copy()

        if len(df_sales_today) == 0:
            logger.log_info("필터링 결과 데이터 없음 - 빈 데이터프레임 반환")
            return pd.DataFrame(columns=output_columns)

        logger.log_info(f"날짜/계산서 필터링 완료: {len(df_sales_today)}행")

        # STEP 5: 데이터 전처리
        logger.log_info("STEP 5: 데이터 전처리")
        df_sales_today["특이사항"] = df_sales_today["특이사항"].fillna("")
        df_sales_today["상품매출"] = df_sales_today["상품매출"].fillna(0)
        df_sales_today["판매배송비"] = df_sales_today["판매배송비"].fillna(0)
        df_sales_today["도선료"] = df_sales_today["도선료"].fillna(0)

        df_sales_today["상품매출"] = to_num(df_sales_today["상품매출"])
        df_sales_today["수량"] = to_num(df_sales_today["수량"])

        df_sales_today = df_sales_today[
            (df_sales_today["상품매출"] != 0)
            | (df_sales_today["판매배송비"] != 0)
            | (df_sales_today["도선료"] != 0)
        ].copy()

        if len(df_sales_today) == 0:
            logger.log_info("유효 데이터 없음 - 빈 데이터프레임 반환")
            return pd.DataFrame(columns=output_columns)

        logger.log_info(f"유효 데이터: {len(df_sales_today)}행")

        # STEP 6: 비즈니스 로직
        logger.log_info("STEP 6: 비즈니스 로직 적용")
        df_sales_today["반품유무"] = np.where(df_sales_today["수량"] < 0, "Y", "N")
        df_sales_today.loc[
            df_sales_today["업체명"].str.startswith("이너바우어", na=False), "업체명"
        ] = "이너바우어"
        df_sales_today = df_sales_today.sort_values(
            ["업체명", "특이사항", "제품", "수량"]
        )

        # STEP 7: 제품 데이터 집계
        logger.log_info("STEP 7: 제품 데이터 집계")
        df_1 = (
            df_sales_today.groupby(
                ["출고일", "업체명", "특이사항", "제품", "과세구분", "반품유무"]
            )[["수량", "상품매출"]]
            .sum()
            .reset_index()
        )

        df_1["단가"] = df_1.apply(
            lambda x: 0 if x["수량"] == 0 else x["상품매출"] / x["수량"], axis=1
        )
        df_1["공급가"] = df_1.apply(
            lambda x: x["상품매출"]
            if x["과세구분"] == "면세"
            else round(x["상품매출"] / 1.1, 0),
            axis=1,
        )
        df_1["부가세"] = df_1.apply(
            lambda x: 0 if x["과세구분"] == "면세" else x["상품매출"] - x["공급가"],
            axis=1,
        )
        df_1 = df_1.rename(columns={"제품": "품목명"})

        # STEP 8: 배송비 집계
        logger.log_info("STEP 8: 배송비 집계")
        df_sales_today_delivery = df_sales_today[df_sales_today["판매배송비"] != 0]
        df_2 = (
            df_sales_today_delivery.groupby(
                ["출고일", "업체명", "특이사항", "판매배송비", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_2["품목명"] = "택배비"
        df_2 = df_2.rename(columns={"판매배송비": "단가"})
        df_2["상품매출"] = df_2["단가"] * df_2["수량"]
        mask_tax_free_2 = df_2["과세구분"] == "면세"
        df_2["공급가"] = np.where(
            mask_tax_free_2, df_2["상품매출"], (df_2["상품매출"] / 1.1).round(0)
        )
        df_2["부가세"] = np.where(mask_tax_free_2, 0, df_2["상품매출"] - df_2["공급가"])

        # STEP 9: 도선료 집계
        logger.log_info("STEP 9: 도선료 집계")
        df_sales_today_shipped = df_sales_today[df_sales_today["도선료"] != 0]
        df_3 = (
            df_sales_today_shipped.groupby(
                ["출고일", "업체명", "특이사항", "도선료", "과세구분"]
            )
            .agg({"수량": "count"})
            .reset_index()
        )

        df_3["품목명"] = "도선료"
        df_3 = df_3.rename(columns={"도선료": "단가"})
        df_3["상품매출"] = df_3["단가"] * df_3["수량"]
        mask_tax_free_3 = df_3["과세구분"] == "면세"
        df_3["공급가"] = np.where(
            mask_tax_free_3, df_3["상품매출"], (df_3["상품매출"] / 1.1).round(0)
        )
        df_3["부가세"] = np.where(mask_tax_free_3, 0, df_3["상품매출"] - df_3["공급가"])

        # STEP 10: 일괄등록 시트 생성
        logger.log_info("STEP 10: 일괄등록 시트 생성")
        df_5 = pd.concat([df_1, df_2, df_3], ignore_index=True)
        df_5["거래일자"] = df_5["출고일"].dt.strftime("%Y-%m-%d")
        df_5["구분"] = "사업자"
        df_5["거래처명"] = df_5["업체명"]
        df_5["부가세구분"] = np.where(df_5["과세구분"] == "과세", "포함", "없음")
        df_5["프로젝트/현장"] = ""
        df_5["창고"] = ""
        df_5["품목월일"] = df_5["출고일"].dt.strftime("%m%d")
        df_5["품목코드"] = ""
        df_5["규격"] = ""
        df_5["단위"] = ""
        df_5 = df_5.rename(
            columns={"공급가": "공급가액", "부가세": "세액", "특이사항": "품목비고"}
        )
        df_5["입금액"] = ""
        df_5["인수자"] = ""
        df_5["공통메모"] = ""

        # STEP 11: 마스터 데이터 조인
        logger.log_info("STEP 11: 마스터 데이터 조인")
        df_10 = pd.merge(
            left=df_5,
            right=df_customer,
            how="left",
            left_on="거래처명",
            right_on="거래처명_솔루미랩",
        ).reindex(output_columns, axis=1)

        # 2026-04-09 hoyeon.han: 모든 행에 헤더 정보 입력하도록 유지
        df_10 = df_10.sort_values(
            ["거래처명", "부가세구분", "품목비고", "품목월일", "품목명"]
        )

        # 2026-04-09 hoyeon.han: 품목비고+품목월일 그룹의 첫 행에만 헤더 정보 입력
        df_10.loc[
            df_10.duplicated(
                ["사업자번호", "거래처명", "부가세구분", "품목비고", "품목월일"]
            ),
            [
                "거래일자",
                "구분",
                "거래처명",
                "사업자번호",
                "부가세구분",
                "프로젝트/현장",
                "창고",
            ],
        ] = ""

        # STEP 12: 검증 및 경고
        logger.log_info("STEP 12: 최종 검증")
        warnings = DataValidator.validate_master_data_join(df_10, len(df_sales_today))
        for warning in warnings:
            logger.log_warning(f"기간 통합 매출 데이터 경고: {warning}")

        duration = (datetime.now() - start_time).total_seconds()
        logger.log_performance("기간 통합 매출 데이터 처리", duration, len(df_10))
        logger.log_info(
            f"기간 통합 매출 데이터 처리 완료: {len(df_10)}행, {duration:.2f}초"
        )

        return df_10

    except SollumeBaseException:
        raise

    except Exception as e:
        logger.log_error("기간 통합 매출 데이터 처리 중 예외 발생", error=e)
        raise ProcessingError("기간 통합 매출 데이터 처리", e)
