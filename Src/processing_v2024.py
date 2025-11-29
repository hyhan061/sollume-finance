# 수정이력
# 2025-02-25 일괄등록 시트 생성 시 업체이름별로 구분되도록 수정
# 2025-10-21 숫자 변환 함수 추가
# 2024-11-15 Streamlit 전환을 위해 모듈 분리

import pandas as pd
from datetime import datetime
import xlwt
import os

def to_num(s: pd.Series) -> pd.Series:
    """콤마/공백/숫자·소수점·부호 외 문자 제거 → 숫자 변환"""
    return pd.to_numeric(
        s.astype(str)
         .str.strip()
         .str.replace(',', '', regex=False)
         .str.replace(r'[^0-9.\-]', '', regex=True),
        errors='coerce'
    )

def save_dataframe_to_xls(df, xls_file):
    """dataframe을 xls 파일로 저장"""
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

def get_sales_daily(file_path, date, master_file_path="거래처마스터.xlsx"):
    """매출 데이터 처리 함수"""
    fileName = file_path
    _day = date

    # 3번째 헤더부터 읽어야 함
    df = pd.read_excel(fileName, engine='openpyxl', sheet_name='(누적)2025년 발주내역', header=3)

    # 지정일을 datetime으로 변환
    today = datetime.strptime(_day, '%Y-%m-%d')

    # 거래처 마스터 엑셀 읽기
    if not os.path.exists(master_file_path):
        raise FileNotFoundError(f"거래처마스터 파일을 찾을 수 없습니다: {master_file_path}")

    df_customer = pd.read_excel(master_file_path, engine='openpyxl', sheet_name='거래처마스터', header=0)

    #################### 매출 데이터 조회 ####################
    # 출고일에 년월일만 남김. 시분초 삭제
    df['출고일'] = pd.to_datetime(df['출고일'], errors='coerce')
    # 데이터 필터링 : 특정날짜, 계산서대상만
    df_sales_today = df[ (df['출고일'] == today) & (df['계산서'] == '대상') ]

    # 특이사항 NaN을 공란으로 수정
    df_sales_today.loc[:, '특이사항'] = df_sales_today['특이사항'].fillna('')
    df_sales_today.loc[:, '상품매출'] = df_sales_today['상품매출'].fillna(0)
    df_sales_today.loc[:, '판매배송비'] = df_sales_today['판매배송비'].fillna(0)
    df_sales_today.loc[:, '도선료'] = df_sales_today['도선료'].fillna(0)
    # 숫자로 변환
    df_sales_today['상품매출'] = to_num(df_sales_today['상품매출'])
    df_sales_today['수량'] = to_num(df_sales_today['수량'])
    # 데이터 필터링 : 상품매출, 배송비, 도선료가 있는것만
    df_sales_today = df_sales_today[ ((df_sales_today['상품매출'] != 0) | (df_sales_today['판매배송비'] != 0) | (df_sales_today['도선료'] != 0)) ]
    # 반품유무 추가
    df_sales_today['반품유무'] = df_sales_today.apply(lambda x : 'Y' if (x['수량'] < 0) else 'N', axis=1)
    # 이너바우어 쿠팡, 올웨이즈 하나로 합치기
    df_sales_today.loc[df_sales_today['업체명'].str.startswith('이너바우어'), '업체명'] = '이너바우어'

    # 업체명-특이사항-제품-수량 순으로 정렬
    df_sales_today = df_sales_today.sort_values(['업체명', '특이사항', '제품', '수량'])

    ########## 마스터데이터 조회
    df_0 = df_sales_today.groupby(['업체명', '특이사항', '과세구분']).agg({'상품매출':'sum', '판매배송비':'sum', '도선료':'sum'}).reset_index()
    df_0['합계'] = df_0['상품매출'] + df_0['판매배송비'] + df_0['도선료']

    ########## 제품데이터 조회
    # 업체명-특이사항-제품명 별로 수량, 상품매출 합계 구하기
    df_1 = df_sales_today.groupby(['업체명', '특이사항', '제품', '과세구분', '반품유무'])[['수량', '상품매출']].sum().reset_index()
    df_1['단가'] = df_1.apply(lambda x: 0 if x['수량'] == 0 else x['상품매출'] / x['수량'], axis=1)
    df_1['공급가'] = df_1.apply(lambda x : x['상품매출'] if x['과세구분'] == "면세" else round(x['상품매출'] / 1.1, 0), axis=1)
    df_1['부가세'] = df_1.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매출'] - x['공급가'], axis=1)
    df_1.rename(columns={'제품':'품목명'}, inplace=True)      # 제품 -> 품목명으로 변경

    ########## 배송비 조회
    # 업체명-특이사항-판매배송비 별로 개수 구하기
    df_sales_today_delivery = df_sales_today[df_sales_today['판매배송비'] != 0]
    df_2 = df_sales_today_delivery.groupby(['업체명', '특이사항', '판매배송비', '과세구분']).agg({"수량":"count"}).reset_index()
    df_2['품목명'] = '택배비'
    df_2.rename(columns={'판매배송비':'단가'}, inplace=True)      # 판매배송비 -> 단가로 변경
    df_2['상품매출'] = df_2['단가'] * df_2['수량']
    df_2['공급가'] = df_2.apply(lambda x : x['상품매출'] if x['과세구분'] == "면세" else round(x['상품매출'] / 1.1, 0), axis=1)
    df_2['부가세'] = df_2.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매출'] - x['공급가'], axis=1)

    ########## 도선료 조회
    # 업체명-특이사항-도선료 별로 개수 구하기
    df_sales_today_shipped = df_sales_today[df_sales_today['도선료'] != 0]
    df_3 = df_sales_today_shipped.groupby(['업체명', '특이사항', '도선료', '과세구분']).agg({"수량":"count"}).reset_index()
    df_3['품목명'] = '도선료'
    df_3.rename(columns={'도선료':'단가'}, inplace=True)      # 도선료 -> 단가로 변경
    df_3['상품매출'] = df_3['단가'] * df_3['수량']
    df_3['공급가'] = df_3.apply(lambda x : x['상품매출'] if x['과세구분'] == "면세" else round(x['상품매출'] / 1.1, 0), axis=1)
    df_3['부가세'] = df_3.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매출'] - x['공급가'], axis=1)

    ########## 일괄등록시트 생성
    # 컬럼 : 거래일자	구분	거래처명	사업자번호	부가세구분	프로젝트/현장	창고	품목월일	품목코드	품목명	규격	수량	단위	단가	공급가액	세액	품목비고	입금액	인수자	공통메모
    df_5 = pd.concat([df_1, df_2, df_3])    # 행간 결합 (df_5)
    df_5['거래일자'] = _day
    df_5['구분'] = '사업자'
    df_5['거래처명'] = df_5['업체명']
    df_5['부가세구분'] = df_5.apply(lambda x : '포함' if x['과세구분'] == "과세" else "없음", axis=1)
    df_5['프로젝트/현장'] = ''
    df_5['창고'] = ''
    df_5['품목월일'] = datetime.strptime(_day, '%Y-%m-%d').strftime("%m%d")
    df_5['품목코드'] = ''
    df_5['규격'] = ''
    df_5['단위'] = ''
    df_5.rename(columns={'공급가':'공급가액'}, inplace=True)    # 공급가 -> 공급가액으로 변경
    df_5.rename(columns={'부가세':'세액'}, inplace=True)        # 부가세 -> 세액으로 변경
    df_5.rename(columns={'특이사항':'품목비고'}, inplace=True)        # 부가세 -> 세액으로 변경
    df_5['입금액'] = ''
    df_5['인수자'] = ''
    df_5['공통메모'] = ''
    df_10 = pd.merge(left=df_5, right=df_customer, how='left', left_on='거래처명', right_on='거래처명_솔루미랩').reindex(['거래일자','구분','거래처명','사업자번호','부가세구분','프로젝트/현장','창고','품목월일','품목코드','품목명','규격','수량','단위','단가','공급가액','세액','품목비고','입금액','인수자','공통메모'], axis=1)
    df_10 = df_10.sort_values(['거래처명', '부가세구분', '품목비고', '품목명'])
    df_10.loc[df_10.duplicated(['사업자번호', '거래처명', '부가세구분', '품목비고']), ['거래일자','구분','거래처명','사업자번호','부가세구분','프로젝트/현장','창고']] = ''

    return df_10

def get_purchase_daily(file_path, date, master_file_path="거래처마스터.xlsx"):
    """매입 데이터 처리 함수"""
    fileName = file_path
    _day = date

    # 3번째 헤더부터 읽어야 함
    df = pd.read_excel(fileName, engine='openpyxl', sheet_name='(누적)2025년 발주내역', header=3)

    # 지정일을 datetime으로 변환
    today = datetime.strptime(_day, '%Y-%m-%d')

    # 거래처 마스터 엑셀 읽기
    if not os.path.exists(master_file_path):
        raise FileNotFoundError(f"거래처마스터 파일을 찾을 수 없습니다: {master_file_path}")

    df_customer = pd.read_excel(master_file_path, engine='openpyxl', sheet_name='거래처마스터', header=0)

    #################### 매입 데이터 조회 ####################
    # 출고일에 년월일만 남김. 시분초 삭제
    df['출고일'] = pd.to_datetime(df['출고일'], errors='coerce')
    df_buy_today = df[ (df['출고일'] == today) & (df['특이사항'] != '솔루미재고') & (df['매입처'] != '당사재고') & (df['매입처'] != '솔루미랩') ]
    df_buy_today = df_buy_today.rename(columns={'도선료.1':'매입도선료'}, inplace=False)      # 도선료.1 -> 매입도선료 로 변경, 출고 도선료와 이름이 같아 변경함

    # 매입배송비, 매입도선료 int64 -> float64로 변경
    df_buy_today = df_buy_today.astype({'매입배송비':'float64', '매입도선료': 'float64'})

    # 특이사항 NaN을 공란으로 수정
    df_buy_today.loc[:, '특이사항'] = df_buy_today['특이사항'].fillna('')
    df_buy_today.loc[:, '상품매입'] = df_buy_today['상품매입'].fillna(0)
    df_buy_today.loc[:, '매입배송비'] = df_buy_today['매입배송비'].fillna(0)
    df_buy_today.loc[:, '매입도선료'] = df_buy_today['매입도선료'].fillna(0)
    # 숫자로 변환
    df_buy_today['상품매입'] = to_num(df_buy_today['상품매입'])
    df_buy_today['수량'] = to_num(df_buy_today['수량'])
    # 데이터 필터링 : 상품매입, 매입배송비, 매입도선료가 있는것만
    df_buy_today = df_buy_today[ ((df_buy_today['상품매입'] != 0) | (df_buy_today['매입배송비'] != 0) | (df_buy_today['매입도선료'] != 0)) ]

    # 업무로직 : '매입처' 지앤제이 매입배송비, 매입도선료 0 처리
    df_buy_today.loc[df_buy_today['매입처'] == '지앤제이', '매입배송비'] = 0
    df_buy_today.loc[df_buy_today['매입처'] == '지앤제이', '매입도선료'] = 0
    # 업무로직 : 매입처가 지앤제이이고 출고업체가 빅웨이브즈이면 특이사항을 빅웨이브즈로 변경
    df_buy_today.loc[(df_buy_today['매입처'] == '지앤제이') & (df_buy_today['업체명'] == '빅웨이브즈'), '특이사항'] = '빅웨이브즈'

    # 업무로직 : '매입처' 유스랩 매입배송비, 매입도선료 0 처리
    df_buy_today.loc[df_buy_today['매입처'] == '유스랩', '매입배송비'] = 0
    df_buy_today.loc[df_buy_today['매입처'] == '유스랩', '매입도선료'] = 0
    # 업무로직 : 매입처가 유스랩이고 출고업체가 빅웨이브즈이면 특이사항을 빅웨이브즈로 변경
    df_buy_today.loc[(df_buy_today['매입처'] == '유스랩') & (df_buy_today['업체명'] == '빅웨이브즈'), '특이사항'] = '빅웨이브즈'
    # 업무로직 : 매입처가 유라이크이면 도선료 0처리. 2024-12-16 추가
    df_buy_today.loc[df_buy_today['매입처'] == '유라이크', '매입도선료'] = 0

    # 반품유무 추가
    df_buy_today['반품유무'] = df_buy_today.apply(lambda x : 'Y' if (x['수량'] < 0) else 'N', axis=1)

    # 매입처-특이사항-제품-수량 순으로 정렬
    df_buy_today = df_buy_today.sort_values(['매입처', '특이사항', '제품', '수량'])

    ########## 마스터데이터 조회
    df_10 = df_buy_today.groupby(['매입처', '특이사항', '과세구분']).agg({'상품매입':'sum', '매입배송비':'sum', '매입도선료':'sum'}).reset_index()
    df_10['합계'] = df_10['상품매입'] + df_10['매입배송비'] + df_10['매입도선료']

    ########## 제품데이터 조회 df_11
    # 매입처-특이사항-제품명-반품유무 별로 수량, 상품매입 합계 구하기
    df_11 = df_buy_today.groupby(['매입처', '특이사항', '제품', '과세구분', '반품유무'])[['수량', '상품매입']].sum().reset_index()
    df_11['단가'] = df_11.apply(lambda x: 0 if x['수량'] == 0 else x['상품매입'] / x['수량'], axis=1)
    df_11['공급가'] = df_11.apply(lambda x : x['상품매입'] if x['과세구분'] == "면세" else round(x['상품매입'] / 1.1, 0), axis=1)
    df_11['부가세'] = df_11.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매입'] - x['공급가'], axis=1)
    df_11.rename(columns={'제품':'품목명'}, inplace=True)      # 제품 -> 품목명으로 변경

    ########## 배송비 조회 df_12
    # 업체명-특이사항-판매배송비 별로 개수 구하기
    df_buy_today_delivery = df_buy_today[df_buy_today['매입배송비'] > 0]
    # 매입처, 특이사항, 매입배송비, 과세구분 별로 수량 조회 (별도 입력)
    df_12 = df_buy_today_delivery.groupby(['매입처', '특이사항', '매입배송비', '과세구분']).agg({"수량":"count"}).reset_index()
    df_12['품목명'] = '택배비'
    df_12.rename(columns={'매입배송비':'단가'}, inplace=True)      # 매입배송비 -> 단가로 변경
    df_12['상품매입'] = df_12['단가'] * df_12['수량']              # 택배비 유형별 총 금액
    df_12['공급가'] = df_12.apply(lambda x : x['상품매입'] if x['과세구분'] == "면세" else round(x['상품매입'] / 1.1, 0), axis=1)   # 택배비 유형별 공급가 구하기
    df_12['부가세'] = df_12.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매입'] - x['공급가'], axis=1)                 # 택배비 유형별 부가세 구하기

    ########## 매입도선료 조회 df_13
    # 업체명-특이사항-도선료 별로 개수 구하기
    df_buy_today_shipped = df_buy_today[df_buy_today['매입도선료'] > 0]
    # 매입처, 특이사항, 매입도선료, 과세구분 별로 수량 조회 (별도 입력)
    df_13 = df_buy_today_shipped.groupby(['매입처', '특이사항', '매입도선료', '과세구분']).agg({"수량":"count"}).reset_index()
    df_13['품목명'] = '도선료'
    df_13.rename(columns={'매입도선료':'단가'}, inplace=True)      # 매입도선료 -> 단가로 변경
    df_13['상품매입'] = df_13['단가'] * df_13['수량']
    df_13['공급가'] = df_13.apply(lambda x : x['상품매입'] if x['과세구분'] == "면세" else round(x['상품매입'] / 1.1, 0), axis=1)
    df_13['부가세'] = df_13.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매입'] - x['공급가'], axis=1)

    ########## 일괄등록시트 생성
    # 컬럼 : 거래일자	구분	거래처명	등록번호	부가세구분	프로젝트/현장	창고	품목월일	품목코드	품목명	규격	수량	단위	단가	공급가액	세액	품목비고	입금액	인수자	공통메모
    df_15 = pd.concat([df_11, df_12, df_13])    # 행간 결합
    df_15['거래일자'] = _day
    df_15['구분'] = '사업자'
    df_15['거래처명'] = df_15['매입처']
    df_15['부가세구분'] = df_15.apply(lambda x : '포함' if x['과세구분'] == "과세" else "없음", axis=1)
    df_15['프로젝트/현장'] = ''
    df_15['창고'] = ''
    df_15['품목월일'] = datetime.strptime(_day, '%Y-%m-%d').strftime("%m%d")
    df_15['품목코드'] = ''
    df_15['규격'] = ''
    df_15['단위'] = ''
    df_15.rename(columns={'공급가':'공급가액'}, inplace=True)    # 공급가 -> 공급가액으로 변경
    df_15.rename(columns={'부가세':'세액'}, inplace=True)        # 부가세 -> 세액으로 변경
    df_15.rename(columns={'특이사항':'품목비고'}, inplace=True)        # 부가세 -> 세액으로 변경
    df_15['입금액'] = ''
    df_15['인수자'] = ''
    df_15['공통메모'] = ''
    df_20 = pd.merge(left=df_15, right=df_customer, how='left', left_on='거래처명', right_on='거래처명_솔루미랩').reindex(['거래일자','구분','거래처명','사업자번호','부가세구분','프로젝트/현장','창고','품목월일','품목코드','품목명','규격','수량','단위','단가','공급가액','세액','품목비고','입금액','인수자','공통메모'], axis=1)
    df_20 = df_20.sort_values(['거래처명', '부가세구분', '품목비고', '품목명'])
    df_20.loc[df_20.duplicated(['사업자번호', '거래처명', '부가세구분', '품목비고']), ['거래일자','구분','거래처명','사업자번호','부가세구분','프로젝트/현장','창고']] = ''

    return df_20
