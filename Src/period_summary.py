"""
발주내역 기간별 요약 처리 모듈
select_sum_v8.py의 기능을 함수화하여 Streamlit에서 호출 가능하도록 구현

주요 기능:
1. 특정 기간(시작일~종료일) 동안의 발주내역 처리
2. 일자별 매출/매입 데이터 집계
3. 업체별 합계 계산
4. Excel 파일로 결과 저장

작성일: 2025-12-10
작성자: hoyeon.han
"""

# =============================================================================
# 라이브러리 임포트 (Import)
# =============================================================================

# pandas: 데이터프레임(표 형태 데이터) 처리를 위한 라이브러리
import pandas as pd

# numpy: 수치 연산을 위한 라이브러리
import numpy as np

# datetime, timedelta: 날짜 계산을 위한 라이브러리
from datetime import datetime, timedelta

# typing: 함수의 입력/출력 타입을 명시하기 위한 라이브러리
# Dict = 딕셔너리(사전) 타입, Any = 모든 타입, Optional = 값이 있거나 None일 수 있음, Callable = 함수 타입
from typing import Dict, Any, Optional, Callable

# logging: 로그(실행 기록) 출력을 위한 라이브러리
import logging

# os: 운영체제 관련 기능 (파일 경로 등)
import os


# =============================================================================
# 로거 설정
# 로거(Logger)란? 프로그램 실행 중 발생하는 정보를 기록하는 도구
# =============================================================================
logger = logging.getLogger(__name__)  # __name__은 현재 모듈명 (Src.period_summary)


# =============================================================================
# 보조 함수: 문자열을 숫자로 변환
# =============================================================================
def to_num(s: pd.Series) -> pd.Series:
    """
    pandas Series(컬럼)의 문자열 데이터를 숫자로 변환하는 함수

    처리 과정:
    1. 콤마(,) 제거: "1,000" → "1000"
    2. 숫자·소수점·부호 외 문자 제거: "1000원" → "1000"
    3. 숫자로 변환: "1000" → 1000 (정수/실수)
    4. 변환 실패 시 NaN(Not a Number)으로 처리

    Args:
        s (pd.Series): 변환할 pandas Series (데이터프레임의 한 컬럼)

    Returns:
        pd.Series: 숫자로 변환된 Series

    Example:
        >>> data = pd.Series(["1,000", "2,500원", "3000"])
        >>> to_num(data)
        0    1000.0
        1    2500.0
        2    3000.0
        dtype: float64

    2025-12-10 hoyeon.han: select_sum_v8.py의 to_num 함수 이식
    """
    return pd.to_numeric(
        # astype(str): 모든 값을 문자열로 변환
        s.astype(str)
         # .str.strip(): 앞뒤 공백 제거
         .str.strip()
         # .str.replace(',', '', regex=False): 콤마 제거 (정규식 사용 안 함)
         .str.replace(',', '', regex=False)
         # .str.replace(r'[^0-9.\-]', '', regex=True): 숫자, 소수점(.), 마이너스(-) 외 모두 제거
         .str.replace(r'[^0-9.\-]', '', regex=True),
        # errors='coerce': 변환 실패 시 NaN으로 처리 (에러 발생하지 않음)
        errors='coerce'
    )


# =============================================================================
# 보조 함수: 매입처별 특수 규칙 적용
# =============================================================================
def _apply_vendor_rules(df_buy: pd.DataFrame) -> pd.DataFrame:
    """
    특정 매입처에 대한 규칙을 적용하는 함수

    규칙:
    1. 지앤제이: 매입배송비=0, 도선료=0, 빅웨이브즈 주문은 특이사항에 표시
    2. 유스랩: 매입배송비=0, 도선료=0, 빅웨이브즈 주문은 특이사항에 표시
    3. 유라이크: 도선료=0

    Args:
        df_buy (pd.DataFrame): 매입 데이터프레임

    Returns:
        pd.DataFrame: 규칙이 적용된 데이터프레임

    Note:
        원본 데이터를 직접 수정함 (in-place modification)

    2025-12-10 hoyeon.han: select_sum_v8.py 라인 155-165 로직 이식
    """
    # .loc[조건, 컬럼]: 조건에 맞는 행의 특정 컬럼 값을 수정
    # 지앤제이 규칙
    df_buy.loc[df_buy['매입처'] == '지앤제이', '매입배송비'] = 0
    df_buy.loc[df_buy['매입처'] == '지앤제이', '도선료.1'] = 0
    # &는 AND 연산자 (두 조건 모두 만족)
    df_buy.loc[(df_buy['매입처'] == '지앤제이') & (df_buy['업체명'] == '빅웨이브즈'), '특이사항'] = '빅웨이브즈'

    # 유스랩 규칙
    df_buy.loc[df_buy['매입처'] == '유스랩', '매입배송비'] = 0
    df_buy.loc[df_buy['매입처'] == '유스랩', '도선료.1'] = 0
    df_buy.loc[(df_buy['매입처'] == '유스랩') & (df_buy['업체명'] == '빅웨이브즈'), '특이사항'] = '빅웨이브즈'

    # 유라이크 규칙
    df_buy.loc[df_buy['매입처'] == '유라이크', '도선료.1'] = 0

    return df_buy


# =============================================================================
# 보조 함수: 특정 날짜의 매출 데이터 처리
# =============================================================================
def _process_sales_daily(
    df: pd.DataFrame,
    target_date: datetime
) -> tuple:
    """
    특정 날짜의 매출 데이터를 처리하는 함수

    처리 단계:
    1. 해당 날짜, 계산서='대상', 수량≠0인 데이터 필터링
    2. NaN(빈 값) 처리 및 숫자 변환
    3. 단가 계산 (상품매출 / 수량)
    4. 업체별 합계 계산
    5. 정렬

    Args:
        df (pd.DataFrame): 전체 발주내역 데이터프레임
        target_date (datetime): 처리할 날짜

    Returns:
        tuple: (상세 데이터, 업체별 합계, 총액)
            - df_sales_today (pd.DataFrame): 해당 날짜의 매출 상세 데이터
            - df_sales_sum (pd.DataFrame): 업체별 합계
            - sum_sales (float): 총 매출 금액

    2025-12-10 hoyeon.han: select_sum_v8.py 라인 64-113 로직 이식
    """
    # 1. 데이터 필터링
    # | 는 OR 연산자 (하나라도 만족하면 True)
    # & 는 AND 연산자 (모두 만족해야 True)
    # .copy(): 원본 데이터를 복사 (원본 수정 방지, SettingWithCopyWarning 방지)
    df_sales_today = df[
        (df['출고일'] == target_date) &  # 출고일이 대상 날짜와 같고
        (df['계산서'] == '대상') &  # 계산서가 '대상'이고
        (df['수량'] != 0) &  # 수량이 0이 아니고
        (  # 아래 조건 중 하나라도 만족 (금액이 있는 것)
            (df['상품매출'] != 0) |
            (df['판매배송비'] != 0) |
            (df['도선료'] != 0)
        )
    ].copy()

    # 데이터가 없으면 빈 결과 반환
    if len(df_sales_today) == 0:
        # pd.DataFrame(): 빈 데이터프레임 생성
        return pd.DataFrame(), pd.DataFrame(), 0.0

    # 2. NaN(빈 값) 처리
    # .fillna(값): NaN을 특정 값으로 채우기
    df_sales_today['특이사항'] = df_sales_today['특이사항'].fillna('')  # 빈 문자열로
    df_sales_today['상품매출'] = df_sales_today['상품매출'].fillna(0)  # 0으로
    df_sales_today['판매배송비'] = df_sales_today['판매배송비'].fillna(0)
    df_sales_today['도선료'] = df_sales_today['도선료'].fillna(0)

    # 3. 소수점 제거 및 숫자 변환
    # np.floor(): 내림 함수 (1.9 → 1)
    # .apply(): 각 값에 함수를 적용
    df_sales_today['상품매출'] = df_sales_today['상품매출'].apply(np.floor)
    df_sales_today['상품매출'] = to_num(df_sales_today['상품매출'])
    df_sales_today['수량'] = to_num(df_sales_today['수량'])

    # 4. 단가 계산
    # 단가 = 상품매출 / 수량
    df_sales_today['단가'] = df_sales_today['상품매출'] / df_sales_today['수량']

    # 5. 정렬
    # sort_values([컬럼들]): 여러 컬럼 기준으로 정렬 (오름차순)
    df_sales_today = df_sales_today.sort_values(['업체명', '특이사항', '제품', '수량'])

    # 6. 업체별 합계 계산
    # .groupby([컬럼들]): 지정한 컬럼들로 그룹화
    # [[컬럼들]].sum(): 특정 컬럼들의 합계 계산
    # .reset_index(): 인덱스를 일반 컬럼으로 변환
    df_sales_sum = df_sales_today.groupby(['출고일', '업체명', '특이사항'])[
        ['상품매출', '판매배송비', '도선료']
    ].sum().reset_index()

    # 업체별합계 = 상품매출 + 판매배송비 + 도선료
    df_sales_sum['업체별합계'] = (
        df_sales_sum['상품매출'] +
        df_sales_sum['판매배송비'] +
        df_sales_sum['도선료']
    )

    # 업체별 합계와 상세 데이터 병합 (merge)
    # merge(): 두 데이터프레임을 특정 컬럼 기준으로 합치기 (SQL의 JOIN과 유사)
    # on=[컬럼들]: 병합 기준이 되는 컬럼들
    # 병합 전에 중복 컬럼 제거
    df_sales_sum_for_merge = df_sales_sum.drop(['상품매출', '판매배송비', '도선료'], axis=1)
    df_sales_today = pd.merge(
        left=df_sales_today,
        right=df_sales_sum_for_merge,
        on=['출고일', '업체명', '특이사항']
    )

    # 7. 총 매출 금액 계산
    # .sum().sum(): 첫 번째 sum()은 컬럼별 합계, 두 번째 sum()은 전체 합계
    # float(): 실수형으로 변환
    sum_sales = float(df_sales_today[['상품매출', '판매배송비', '도선료']].sum().sum())

    return df_sales_today, df_sales_sum, sum_sales


# =============================================================================
# 보조 함수: 특정 날짜의 매입 데이터 처리
# =============================================================================
def _process_buy_daily(
    df: pd.DataFrame,
    target_date: datetime
) -> tuple:
    """
    특정 날짜의 매입 데이터를 처리하는 함수

    처리 단계:
    1. 해당 날짜, 당사재고 제외, 수량≠0인 데이터 필터링
    2. NaN 처리 및 숫자 변환
    3. 단가 계산
    4. 매입처별 특수 규칙 적용
    5. 업체별 합계 계산
    6. 정렬

    Args:
        df (pd.DataFrame): 전체 발주내역 데이터프레임
        target_date (datetime): 처리할 날짜

    Returns:
        tuple: (상세 데이터, 업체별 합계, 총액)
            - df_buy_today (pd.DataFrame): 해당 날짜의 매입 상세 데이터
            - df_buy_sum (pd.DataFrame): 업체별 합계
            - sum_buy (float): 총 매입 금액

    2025-12-10 hoyeon.han: select_sum_v8.py 라인 134-200 로직 이식
    """
    # 1. 데이터 필터링
    df_buy_today = df[
        (df['출고일'] == target_date) &  # 출고일이 대상 날짜와 같고
        (df['특이사항'] != '솔루미재고') &  # 솔루미재고 제외
        (df['매입처'] != '당사재고') &  # 당사재고 제외
        (df['매입처'] != '솔루미랩') &  # 솔루미랩 제외
        (df['수량'] != 0) &  # 수량이 0이 아니고
        (  # 아래 조건 중 하나라도 만족 (금액이 있는 것)
            (df['상품매입'] != 0) |
            (df['매입배송비'] != 0) |
            (df['도선료.1'] != 0)  # 매입도선료는 '도선료.1' 컬럼
        )
    ].copy()

    # 데이터가 없으면 빈 결과 반환
    if len(df_buy_today) == 0:
        return pd.DataFrame(), pd.DataFrame(), 0.0

    # 2. 데이터 타입 변환
    # .astype(): 데이터 타입 변환
    # float64: 64비트 실수 (소수점 포함 숫자)
    df_buy_today = df_buy_today.astype({
        '매입배송비': 'float64',
        '도선료.1': 'float64'
    })

    # 3. NaN 처리
    df_buy_today['특이사항'] = df_buy_today['특이사항'].fillna('')
    df_buy_today['상품매입'] = df_buy_today['상품매입'].fillna(0)
    df_buy_today['매입배송비'] = df_buy_today['매입배송비'].fillna(0)
    df_buy_today['도선료.1'] = df_buy_today['도선료.1'].fillna(0)

    # 4. 숫자 변환
    df_buy_today['상품매입'] = to_num(df_buy_today['상품매입'])
    df_buy_today['수량'] = to_num(df_buy_today['수량'])

    # 5. 단가 계산
    df_buy_today['단가'] = df_buy_today['상품매입'] / df_buy_today['수량']

    # 6. 매입처별 특수 규칙 적용
    df_buy_today = _apply_vendor_rules(df_buy_today)

    # 7. 업체별 합계 계산
    df_buy_sum = df_buy_today.groupby(['출고일', '매입처', '특이사항'])[
        ['상품매입', '매입배송비', '도선료.1']
    ].sum().reset_index()

    # 업체별합계 = 상품매입 + 매입배송비 + 도선료.1
    df_buy_sum['업체별합계'] = (
        df_buy_sum['상품매입'] +
        df_buy_sum['매입배송비'] +
        df_buy_sum['도선료.1']
    )

    # 병합 전 중복 컬럼 제거
    df_buy_sum_for_merge = df_buy_sum.drop(['상품매입', '매입배송비', '도선료.1'], axis=1)
    df_buy_today = pd.merge(
        left=df_buy_today,
        right=df_buy_sum_for_merge,
        on=['출고일', '매입처', '특이사항']
    )

    # 8. 정렬
    df_buy_today = df_buy_today.sort_values(['매입처', '특이사항', '제품', '수량'])

    # 9. 총 매입 금액 계산
    sum_buy = float(df_buy_today[['상품매입', '매입배송비', '도선료.1']].sum().sum())

    return df_buy_today, df_buy_sum, sum_buy


# =============================================================================
# 메인 함수: 기간별 요약 처리
# =============================================================================
def process_period_summary(
    file_path: str,
    sheet_name: str,
    start_date: str,
    end_date: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Dict[str, Any]:
    """
    기간별 발주내역 요약을 처리하는 메인 함수

    전체 처리 흐름:
    1. Excel 파일 읽기
    2. 날짜 범위 계산
    3. 일자별 루프:
       - 매출 데이터 처리
       - 매입 데이터 처리
       - 누적 데이터 업데이트
       - 진행률 콜백 호출 (선택)
    4. 전체 기간 집계
    5. Excel 파일 저장
    6. 결과 반환

    Args:
        file_path (str): 발주내역 Excel 파일 경로
        sheet_name (str): 처리할 시트명 (예: "(누적)2025년 발주내역")
        start_date (str): 시작일 (YYYY-MM-DD 형식)
        end_date (str): 종료일 (YYYY-MM-DD 형식)
        progress_callback (Callable, optional): 진행률 콜백 함수
            함수 형태: callback(현재일수, 전체일수, 메시지)

    Returns:
        Dict[str, Any]: 처리 결과 딕셔너리
            {
                "output_file": str,           # 생성된 파일 경로
                "total_sales": float,         # 총 매출
                "total_buy": float,           # 총 매입
                "profit": float,              # 손익 (매출 - 매입)
                "period": str,                # 처리 기간 (시작일~종료일)
                "days_count": int,            # 처리 일수
                "sheets_created": List[str],  # 생성된 시트 목록
                "daily_summary": List[Dict]   # 일자별 요약
            }

    Raises:
        FileNotFoundError: 파일을 찾을 수 없을 때
        ValueError: 시트를 찾을 수 없거나 날짜 형식이 잘못되었을 때
        KeyError: 필수 컬럼이 없을 때

    Example:
        >>> result = process_period_summary(
        ...     file_path="발주내역.xlsm",
        ...     sheet_name="(누적)2025년 발주내역",
        ...     start_date="2025-10-01",
        ...     end_date="2025-10-31"
        ... )
        >>> print(f"총 매출: {result['total_sales']:,}원")

    2025-12-10 hoyeon.han: select_sum_v8.py 전체 로직을 함수화
    """
    # =========================================================================
    # 1. 입력 검증 및 초기화
    # =========================================================================
    logger.info(f"기간별 요약 처리 시작: {start_date} ~ {end_date}")

    # 날짜 문자열을 datetime 객체로 변환
    # strptime(): 문자열을 날짜로 파싱 (parse time)
    # %Y: 4자리 연도, %m: 2자리 월, %d: 2자리 일
    try:
        date_from = datetime.strptime(start_date, '%Y-%m-%d')
        date_to = datetime.strptime(end_date, '%Y-%m-%d')
    except ValueError as e:
        # raise: 예외를 발생시킴
        raise ValueError(f"날짜 형식이 잘못되었습니다 (YYYY-MM-DD): {e}")

    # 날짜 유효성 검증
    if date_from > date_to:
        raise ValueError("시작일이 종료일보다 늦습니다")

    # =========================================================================
    # 2. Excel 파일 읽기
    # =========================================================================
    logger.info(f"Excel 파일 읽기: {file_path}, 시트: {sheet_name}")

    try:
        # pd.read_excel(): Excel 파일을 pandas DataFrame으로 읽기
        # engine='openpyxl': .xlsm 파일을 읽기 위한 엔진
        # sheet_name: 읽을 시트 이름
        # header=3: 4번째 줄을 컬럼명으로 사용 (0부터 시작하므로 3=4번째)
        df = pd.read_excel(
            file_path,
            engine='openpyxl',
            sheet_name=sheet_name,
            header=3
        )
    except FileNotFoundError:
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")
    except ValueError as e:
        if "Worksheet" in str(e):
            raise ValueError(f"시트를 찾을 수 없습니다: {sheet_name}")
        raise

    # 출고일을 datetime 형식으로 변환
    # errors='coerce': 변환 실패 시 NaT(Not a Time)로 처리
    df['출고일'] = pd.to_datetime(df['출고일'], errors='coerce')

    # =========================================================================
    # 3. 출력 파일 설정
    # =========================================================================
    # 출력 디렉토리 생성 (없으면)
    # os.makedirs(): 디렉토리 생성
    # exist_ok=True: 이미 존재해도 에러 발생 안 함
    os.makedirs("processed", exist_ok=True)

    # 출력 파일명 생성
    output_filename = f"발주내역_요약_{start_date}_{end_date}.xlsx"
    output_path = os.path.join("processed", output_filename)

    # Excel writer 생성
    # pd.ExcelWriter(): Excel 파일에 여러 시트를 쓰기 위한 객체
    # engine='xlsxwriter': .xlsx 파일 생성 엔진
    excel_writer = pd.ExcelWriter(output_path, engine='xlsxwriter')

    # =========================================================================
    # 4. 누적 변수 초기화
    # =========================================================================
    # 누적 매출/매입 금액
    acc_sales = 0.0  # 0.0은 실수형 0
    acc_buy = 0.0

    # 업체별 누적 데이터를 저장할 빈 데이터프레임
    df_sales_acc = pd.DataFrame()
    df_buy_acc = pd.DataFrame()

    # 일자별 합계를 저장할 데이터프레임
    # columns=[]: 컬럼명 지정
    df_sales_daily = pd.DataFrame(columns=['매출일자', '합계금액'])
    df_buy_daily = pd.DataFrame(columns=['매입일자', '합계금액'])

    # 일자별 요약 정보를 저장할 리스트
    daily_summary = []  # [] = 빈 리스트

    # 생성된 시트 목록
    sheets_created = []

    # =========================================================================
    # 5. 일자별 처리 루프
    # =========================================================================
    # 전체 처리 일수 계산
    # .days: timedelta 객체에서 일수 추출
    total_days = (date_to - date_from).days + 1  # +1: 시작일과 종료일 포함
    current_day = 0  # 현재 처리 중인 일수 (진행률 계산용)

    # 현재 날짜를 date_from으로 초기화
    current_date = date_from

    # while 루프: 조건이 True인 동안 반복
    # <=: 작거나 같을 때 (종료일 포함)
    while current_date <= date_to:
        current_day += 1  # += : 자기 자신에 더하기 (current_day = current_day + 1)

        # 현재 날짜를 문자열로 변환 (YYYY-MM-DD)
        # strftime(): datetime을 문자열로 포맷팅 (format time)
        today_str = current_date.strftime('%Y-%m-%d')

        # 진행률 콜백 호출 (제공된 경우)
        # if 변수: 변수가 None이 아니면 True
        if progress_callback:
            progress_callback(current_day, total_days, f"{today_str} 처리 중...")

        # =====================================================================
        # 5-1. 매출 데이터 처리
        # =====================================================================
        df_sales_today, df_sales_sum, sum_sales = _process_sales_daily(df, current_date)

        # 데이터가 있으면 Excel 시트에 쓰기
        # len(): 길이 (행의 개수)
        # > 0: 0보다 크면 (데이터가 있으면)
        if len(df_sales_today) > 0:
            # 필요한 컬럼만 선택하여 Excel 시트로 저장
            # .loc[:, [컬럼들]]: 모든 행(:), 특정 컬럼들만 선택
            # .to_excel(): DataFrame을 Excel로 저장
            # sheet_name: 시트 이름
            # index=False: 인덱스(행 번호) 제외
            df_sales_today.loc[:, [
                '출고일', '업체명', '특이사항', '제품', '수량',
                '상품매출', '단가', '판매배송비', '도선료',
                '업체별합계', '과세구분', '계산서', '구분'
            ]].to_excel(excel_writer, sheet_name=f'매출_{today_str}', index=False)

            sheets_created.append(f'매출_{today_str}')

            # 업체별 합계를 누적 데이터에 추가
            # pd.concat(): 여러 DataFrame을 연결 (concatenate)
            # [df1, df2]: 연결할 DataFrame 리스트
            # axis=0: 세로 방향 연결 (행 추가), axis=1: 가로 방향 연결 (컬럼 추가)
            df_sales_acc = pd.concat([df_sales_acc, df_sales_sum], axis=0)

            # 일자별 합계 추가
            # pd.DataFrame({컬럼: [값]}): 딕셔너리로 DataFrame 생성
            new_sales_row = pd.DataFrame({
                '매출일자': [today_str],
                '합계금액': [sum_sales]
            })

            # 첫 데이터면 그대로 대입, 아니면 concat으로 추가
            # .empty: DataFrame이 비어있으면 True
            if df_sales_daily.empty:
                df_sales_daily = new_sales_row.copy()
            else:
                # ignore_index=True: 인덱스 재정렬 (0, 1, 2, ...)
                df_sales_daily = pd.concat([df_sales_daily, new_sales_row], ignore_index=True)

            # 누적 매출 금액 업데이트
            acc_sales += sum_sales

            logger.info(f"{today_str} 매출 금액 합계: {sum_sales:,}원")

        # =====================================================================
        # 5-2. 매입 데이터 처리
        # =====================================================================
        df_buy_today, df_buy_sum, sum_buy = _process_buy_daily(df, current_date)

        # 데이터가 있으면 Excel 시트에 쓰기
        if len(df_buy_today) > 0:
            df_buy_today.loc[:, [
                '출고일', '매입처', '특이사항', '제품', '수량',
                '상품매입', '단가', '매입배송비', '도선료.1',
                '업체별합계', '과세구분', '구분', '업체명'
            ]].to_excel(excel_writer, sheet_name=f'매입_{today_str}', index=False)

            sheets_created.append(f'매입_{today_str}')

            # 업체별 합계를 누적 데이터에 추가
            df_buy_acc = pd.concat([df_buy_acc, df_buy_sum], axis=0)

            # 일자별 합계 추가
            new_buy_row = pd.DataFrame({
                '매입일자': [today_str],
                '합계금액': [sum_buy]
            })

            if df_buy_daily.empty:
                df_buy_daily = new_buy_row.copy()
            else:
                df_buy_daily = pd.concat([df_buy_daily, new_buy_row], ignore_index=True)

            # 누적 매입 금액 업데이트
            acc_buy += sum_buy

            logger.info(f"{today_str} 매입 금액 합계: {sum_buy:,}원")

        # =====================================================================
        # 5-3. 일자별 요약 정보 저장
        # =====================================================================
        # .append(): 리스트에 항목 추가
        daily_summary.append({
            'date': today_str,
            'sales': sum_sales,
            'buy': sum_buy
        })

        # =====================================================================
        # 5-4. 다음 날짜로 이동
        # =====================================================================
        # timedelta(days=1): 1일을 나타내는 객체
        current_date += timedelta(days=1)

    # =========================================================================
    # 6. 전체 기간 집계 시트 작성
    # =========================================================================
    # 매출 업체별 합계
    if not df_sales_acc.empty:
        # groupby().sum(): 그룹별 합계
        # sort_values(): 정렬
        # reset_index(): 인덱스 초기화
        df_sales_acc_summary = (
            df_sales_acc
            .groupby(['업체명', '특이사항'])[['업체별합계']]
            .sum()
            .sort_values(['업체명', '특이사항'])
            .reset_index()
        )
        df_sales_acc_summary.to_excel(excel_writer, sheet_name='매출_업체별합계', index=False)
        sheets_created.append('매출_업체별합계')

    # 2026-05-11 hoyeon.han: 업체별 + 일자별 교차 시트 신규 추가
    if not df_sales_acc.empty:
        df_sales_acc_daily = (
            df_sales_acc
            .groupby(['출고일', '업체명', '특이사항'])[['업체별합계']]
            .sum()
            .sort_values(['업체명', '출고일', '특이사항'])
            .reset_index()
        )
        df_sales_acc_daily['출고일'] = df_sales_acc_daily['출고일'].dt.strftime('%Y-%m-%d')
        df_sales_acc_daily = df_sales_acc_daily[['출고일', '업체명', '특이사항', '업체별합계']]
        df_sales_acc_daily.to_excel(excel_writer, sheet_name='매출_업체_일자별', index=False)
        sheets_created.append('매출_업체_일자별')
        logger.info(f"매출_업체_일자별 시트 생성: {len(df_sales_acc_daily)}행")

    # 매입 업체별 합계
    if not df_buy_acc.empty:
        df_buy_acc_summary = (
            df_buy_acc
            .groupby(['매입처', '특이사항'])[['업체별합계']]
            .sum()
            .sort_values(['매입처', '특이사항'])
            .reset_index()
        )
        df_buy_acc_summary.to_excel(excel_writer, sheet_name='매입_업체별합계', index=False)
        sheets_created.append('매입_업체별합계')

    # 2026-05-11 hoyeon.han: 업체별 + 일자별 교차 시트 신규 추가
    if not df_buy_acc.empty:
        df_buy_acc_daily = (
            df_buy_acc
            .groupby(['출고일', '매입처', '특이사항'])[['업체별합계']]
            .sum()
            .sort_values(['매입처', '출고일', '특이사항'])
            .reset_index()
        )
        df_buy_acc_daily['출고일'] = df_buy_acc_daily['출고일'].dt.strftime('%Y-%m-%d')
        df_buy_acc_daily = df_buy_acc_daily[['출고일', '매입처', '특이사항', '업체별합계']]
        df_buy_acc_daily.to_excel(excel_writer, sheet_name='매입_업체_일자별', index=False)
        sheets_created.append('매입_업체_일자별')
        logger.info(f"매입_업체_일자별 시트 생성: {len(df_buy_acc_daily)}행")

    # 매출 일자별 합계
    if not df_sales_daily.empty:
        df_sales_daily.to_excel(excel_writer, sheet_name='매출_일자별합계', index=False)
        sheets_created.append('매출_일자별합계')

    # 매입 일자별 합계
    if not df_buy_daily.empty:
        df_buy_daily.to_excel(excel_writer, sheet_name='매입_일자별합계', index=False)
        sheets_created.append('매입_일자별합계')

    # =========================================================================
    # 7. Excel 파일 저장
    # =========================================================================
    # .close(): Excel writer 닫기 (파일 저장)
    excel_writer.close()

    logger.info(f"Excel 파일 저장 완료: {output_path}")
    logger.info(f"총 누적 매출: {acc_sales:,}원")
    logger.info(f"총 누적 매입: {acc_buy:,}원")

    # =========================================================================
    # 8. 결과 반환
    # =========================================================================
    # 딕셔너리 생성 및 반환
    # {키: 값, 키: 값, ...}
    return {
        "output_file": output_path,
        "total_sales": acc_sales,
        "total_buy": acc_buy,
        "profit": acc_sales - acc_buy,  # 손익 = 매출 - 매입
        "period": f"{start_date} ~ {end_date}",
        "days_count": total_days,
        "sheets_created": sheets_created,
        "daily_summary": daily_summary
    }


# =============================================================================
# 모듈 테스트용 코드 (직접 실행 시에만 동작)
# =============================================================================
# __name__ == "__main__": 이 파일이 직접 실행될 때만 True
# import되어 사용될 때는 False
if __name__ == "__main__":
    # 테스트 실행 예제
    print("=== 기간별 요약 처리 테스트 ===")

    # 테스트용 콜백 함수 정의
    # def: 함수 정의
    # current, total, msg: 매개변수 (파라미터)
    def test_callback(current, total, msg):
        # f-string: 문자열 안에 변수 삽입
        # {변수}: 변수 값 출력
        # {변수:.1f}: 소수점 1자리까지 출력
        # % 기호 출력을 위해 %%로 이스케이프
        progress_pct = (current / total) * 100
        print(f"[{current}/{total}] {progress_pct:.1f}% - {msg}")

    # 테스트 실행
    # try-except: 예외(에러) 처리
    try:
        result = process_period_summary(
            file_path="솔루미랩_발주내역_20251020.xlsm",
            sheet_name="(누적)2025년 발주내역",
            start_date="2025-10-01",
            end_date="2025-10-05",  # 테스트는 짧은 기간으로
            progress_callback=test_callback
        )

        # 결과 출력
        print("\n=== 처리 결과 ===")
        print(f"출력 파일: {result['output_file']}")
        print(f"처리 기간: {result['period']} ({result['days_count']}일)")
        print(f"총 매출: {result['total_sales']:,}원")
        print(f"총 매입: {result['total_buy']:,}원")
        print(f"손익: {result['profit']:,}원")
        print(f"생성된 시트 수: {len(result['sheets_created'])}개")

    # except: 예외가 발생했을 때 실행
    # Exception as e: 모든 예외를 e 변수에 저장
    except Exception as e:
        print(f"에러 발생: {e}")
        # import traceback: 상세 에러 정보 출력 모듈
        import traceback
        traceback.print_exc()
