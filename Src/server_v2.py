# 수정이력
# 2025-02-25 일괄등록 시트 생성 시 업체이름별로 구분되도록 수정
# 2025-10-21 숫자 변환 함수 추가

import pandas as pd
from flask import Flask, request, send_file, render_template_string, jsonify
from flask_cors import CORS
import sys
from datetime import datetime, timedelta
import re
import os
import xlwt

app = Flask(__name__)
CORS(app)  # Next.js와 CORS 문제 해결
UPLOAD_FOLDER = "uploads"
PROCESSED_FOLDER = "processed"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

def to_num(s: pd.Series) -> pd.Series:
    # 콤마/공백/숫자·소수점·부호 외 문자 제거 → 숫자 변환
    return pd.to_numeric(
        s.astype(str)
         .str.strip()
         .str.replace(',', '', regex=False)
         .str.replace(r'[^0-9.\-]', '', regex=True),
        errors='coerce'
    )

def groupby_sum_sales(x):
    return x['상품매출'] + x['판매배송비'] + x['도선료']

# dataframe을 xls 파일로 저장
def save_dataframe_to_xls(df, xls_file):
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

def get_sales_daily(file_path, date):
    fileName = file_path
    _day = date

    # 3번째 헤더부터 읽어야 함
    df = pd.read_excel(fileName, engine='openpyxl', sheet_name='(누적)2025년 발주내역', header=3)

    # 지정일을 datetime으로 변환
    date_day = datetime.strptime(_day, '%Y-%m-%d')
    today = datetime.strptime(_day, '%Y-%m-%d')

    # 거래처 마스터 엑셀 읽기
    df_customer = pd.read_excel("거래처마스터.xlsx", engine='openpyxl', sheet_name='거래처마스터', header=0)

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
    #df_sales_today.to_excel(excelWriter, sheet_name='원본_' + _day)

    ########## 마스터데이터 조회
    df_0 = df_sales_today.groupby(['업체명', '특이사항', '과세구분']).agg({'상품매출':'sum', '판매배송비':'sum', '도선료':'sum'}).reset_index()
    df_0['합계'] = df_0['상품매출'] + df_0['판매배송비'] + df_0['도선료']
    #df_0.to_excel(excelWriter, sheet_name='마스터_' + _day)

    ########## 제품데이터 조회
    # 업체명-특이사항-제품명 별로 수량, 상품매출 합계 구하기
    df_1 = df_sales_today.groupby(['업체명', '특이사항', '제품', '과세구분', '반품유무'])[['수량', '상품매출']].sum().reset_index()
    df_1['단가'] = df_1.apply(lambda x: 0 if x['수량'] == 0 else x['상품매출'] / x['수량'], axis=1)
    df_1['공급가'] = df_1.apply(lambda x : x['상품매출'] if x['과세구분'] == "면세" else round(x['상품매출'] / 1.1, 0), axis=1)
    df_1['부가세'] = df_1.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매출'] - x['공급가'], axis=1)
    df_1.rename(columns={'제품':'품목명'}, inplace=True)      # 제품 -> 품목명으로 변경
    #df_1.to_excel(excelWriter, sheet_name='상품_' + _day)

    ########## 배송비 조회
    # 업체명-특이사항-판매배송비 별로 개수 구하기
    df_sales_today_delivery = df_sales_today[df_sales_today['판매배송비'] != 0]
    # df_2 = df_sales_today_delivery.groupby(['업체명', '특이사항', '판매배송비']).agg({"수량":"count"}).reset_index()
    df_2 = df_sales_today_delivery.groupby(['업체명', '특이사항', '판매배송비', '과세구분']).agg({"수량":"count"}).reset_index()
    df_2['품목명'] = '택배비'
    df_2.rename(columns={'판매배송비':'단가'}, inplace=True)      # 판매배송비 -> 단가로 변경
    df_2['상품매출'] = df_2['단가'] * df_2['수량']
    # df_2['공급가'] = round(df_2['상품매출'] / 1.1, 0)
    df_2['공급가'] = df_2.apply(lambda x : x['상품매출'] if x['과세구분'] == "면세" else round(x['상품매출'] / 1.1, 0), axis=1)
    # df_2['부가세'] = df_2['상품매출'] - df_2['공급가']
    df_2['부가세'] = df_2.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매출'] - x['공급가'], axis=1)
    #df_2.to_excel(excelWriter, sheet_name='택배비_' + _day)
    # print(tabulate(df_2, headers='keys', tablefmt='psql', showindex=False))

    ########## 도선료 조회
    # 업체명-특이사항-도선료 별로 개수 구하기
    df_sales_today_shipped = df_sales_today[df_sales_today['도선료'] != 0]
    # df_3 = df_sales_today_delivery.groupby(['업체명', '특이사항', '도선료']).agg({"수량":"count"}).reset_index()
    df_3 = df_sales_today_shipped.groupby(['업체명', '특이사항', '도선료', '과세구분']).agg({"수량":"count"}).reset_index()
    df_3['품목명'] = '도선료'
    df_3.rename(columns={'도선료':'단가'}, inplace=True)      # 도선료 -> 단가로 변경
    df_3['상품매출'] = df_3['단가'] * df_3['수량']
    df_3['공급가'] = df_3.apply(lambda x : x['상품매출'] if x['과세구분'] == "면세" else round(x['상품매출'] / 1.1, 0), axis=1)
    df_3['부가세'] = df_3.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매출'] - x['공급가'], axis=1)
    #df_3.to_excel(excelWriter, sheet_name='도선료_' + _day)

    ########## 일괄등록시트 생성
    # 컬럼 : 거래일자	구분	거래처명	사업자번호	부가세구분	프로젝트/현장	창고	품목월일	품목코드	품목명	규격	수량	단위	단가	공급가액	세액	품목비고	입금액	인수자	공통메모
    #excelWriter = pd.ExcelWriter('솔루미랩_일괄등록_매출_' + _day + '.xlsx', engine='xlsxwriter')   # 매출 엑셀 별도 생성
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

def get_purchase_daily(file_path, date):
    fileName = file_path
    _day = date

    # 3번째 헤더부터 읽어야 함
    df = pd.read_excel(fileName, engine='openpyxl', sheet_name='(누적)2025년 발주내역', header=3)

    # 지정일을 datetime으로 변환
    date_day = datetime.strptime(_day, '%Y-%m-%d')
    today = datetime.strptime(_day, '%Y-%m-%d')

    # 거래처 마스터 엑셀 읽기
    df_customer = pd.read_excel("거래처마스터.xlsx", engine='openpyxl', sheet_name='거래처마스터', header=0)
    
    #################### 매입 데이터 조회 ####################
    # 데이터 필터링 (특정날짜, 당사재고아닌것, 매입/배송비/도선료 있는것만)
    # df_buy_today = df[ (df['출고일'] == today) & (df['특이사항'] != '솔루미재고') & (df['매입처'] != '당사재고') & (df['매입처'] != '솔루미랩') & ((df['상품매입'] != 0) | (df['매입배송비'] != 0) | (df['도선료.1'] != 0)) ]
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
    #df_buy_today.to_excel(excelWriter, sheet_name='원본_' + _day)

    ########## 마스터데이터 조회
    df_10 = df_buy_today.groupby(['매입처', '특이사항', '과세구분']).agg({'상품매입':'sum', '매입배송비':'sum', '매입도선료':'sum'}).reset_index()
    df_10['합계'] = df_10['상품매입'] + df_10['매입배송비'] + df_10['매입도선료']
    #df_10.to_excel(excelWriter, sheet_name='마스터_' + _day)

    ########## 제품데이터 조회 df_11
    # 매입처-특이사항-제품명-반품유무 별로 수량, 상품매입 합계 구하기
    df_11 = df_buy_today.groupby(['매입처', '특이사항', '제품', '과세구분', '반품유무'])[['수량', '상품매입']].sum().reset_index()
    # df_11['단가'] = df_11['상품매입'] / df_11['수량']
    df_11['단가'] = df_11.apply(lambda x: 0 if x['수량'] == 0 else x['상품매입'] / x['수량'], axis=1)
    df_11['공급가'] = df_11.apply(lambda x : x['상품매입'] if x['과세구분'] == "면세" else round(x['상품매입'] / 1.1, 0), axis=1)
    df_11['부가세'] = df_11.apply(lambda x : 0 if x['과세구분'] == "면세" else x['상품매입'] - x['공급가'], axis=1)
    df_11.rename(columns={'제품':'품목명'}, inplace=True)      # 제품 -> 품목명으로 변경
    #df_11.to_excel(excelWriter, sheet_name='상품_' + _day)     # 테스트

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
    #df_12.to_excel(excelWriter, sheet_name='택배비_' + _day)

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
    #df_13.to_excel(excelWriter, sheet_name='도선료_' + _day)

    ########## 일괄등록시트 생성
    # 컬럼 : 거래일자	구분	거래처명	등록번호	부가세구분	프로젝트/현장	창고	품목월일	품목코드	품목명	규격	수량	단위	단가	공급가액	세액	품목비고	입금액	인수자	공통메모
    #excelWriter = pd.ExcelWriter('솔루미랩_일괄등록_매입_' + _day + '.xlsx', engine='xlsxwriter')   # 매출 엑셀 별도 생성
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
    #df_20.rename(columns={'사업자번호':'등록번호'}, inplace=True)
    df_20 = df_20.sort_values(['거래처명', '부가세구분', '품목비고', '품목명'])
    df_20.loc[df_20.duplicated(['사업자번호', '거래처명', '부가세구분', '품목비고']), ['거래일자','구분','거래처명','사업자번호','부가세구분','프로젝트/현장','창고']] = ''

    return df_20


@app.route("/upload", methods=["POST"])
def upload_and_process():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files["file"]
    date = request.form.get("date")
    if not date:
        return jsonify({"error": "No date provided"}), 400
    
    if file and file.filename.endswith(".xlsm"):
        filepath = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(filepath)
        
        # 엑셀 데이터 가공 처리
        df = get_sales_daily(filepath, date)
        
        #processed_filename = file.filename.replace(".xlsm", "_sales.xlsx")
        processed_filename = "매출_" + date + ".xls"
        processed_filepath = os.path.join(PROCESSED_FOLDER, processed_filename)
        save_dataframe_to_xls(df, processed_filepath)
        # df.to_excel(processed_filepath, index=False, engine="xlsxwriter")
        
        os.remove(filepath)
        return jsonify({"download_url": f"/download/{processed_filename}"})
    
    return jsonify({"error": "Invalid file format"}), 400

@app.route("/upload2", methods=["POST"])
def upload_and_process2():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files["file"]
    date = request.form.get("date")
    if not date:
        return jsonify({"error": "No date provided"}), 400
    
    if file and file.filename.endswith(".xlsm"):
        filepath = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(filepath)
        
        # 엑셀 데이터 가공 처리
        df = get_purchase_daily(filepath, date)
        
        #processed_filename = file.filename.replace(".xlsm", "_purchase.xlsx")
        processed_filename = "매입_" + date + ".xls"
        processed_filepath = os.path.join(PROCESSED_FOLDER, processed_filename)
        save_dataframe_to_xls(df, processed_filepath)
        # df.to_excel(processed_filepath, index=False, engine="xlsxwriter")
        
        os.remove(filepath)
        return jsonify({"download_url": f"/download/{processed_filename}"})
    
    return jsonify({"error": "Invalid file format"}), 400
    
@app.route("/download/<filename>")
def download_file(filename):
    return send_file(os.path.join(PROCESSED_FOLDER, filename), as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
