"""
특정날짜 범위 매출/매입 총금액 확인
수정이력
2024-08-30 매입에 매출처 추가
v5 : 매입에서 솔루미재고는 제외함. 매입금액은 0, 배송비는 있으나 입력하지 않음
v6 : 유스랩도 지앤제이 처럼 매입배송비, 도선료 0처리함. 빅웨이브즈 비고에 입력
"""
def groupby_sum_sales(x):
    return x['상품매출'] + x['판매배송비'] + x['도선료']

import pandas as pd
import sys
from datetime import datetime, timedelta

fileName = sys.argv[1]
_from = sys.argv[2]
_to = sys.argv[3]

# 3번째 헤더부터 읽어야 함
df = pd.read_excel(fileName, engine='openpyxl', sheet_name='(누적)2024년 발주내역', header=3)

# 시작일, 종료일을 datetime으로 변환
date_from = datetime.strptime(_from, '%Y-%m-%d')
date_to = datetime.strptime(_to, '%Y-%m-%d')

# 엑셀 writer
excelWriter = pd.ExcelWriter('솔루미랩_' + _from + '_' + _to + '.xlsx', engine='xlsxwriter')

# 누적 매출/매입
acc_sales = 0
acc_buy = 0

# 업체별 매출/매입 dataframe
df_sales_acc = pd.DataFrame()
df_buy_acc = pd.DataFrame()

while date_from <= date_to:
    today = date_from.strftime('%Y-%m-%d')

    #################### 매출 데이터 조회 ####################

    # 한방에 데이터 필터링 (특정날짜, 계산서대상, 매출/배송비/도선료 있는것만)
    df_sales_today = df[ (df['출고일'] == today) & (df['계산서'] == '대상') & ((df['상품매출'] != 0) | (df['판매배송비'] != 0) | (df['도선료'] != 0)) ]

    # 특이사항 NaN을 공란으로 수정
    df_sales_today.loc[:, '특이사항'] = df_sales_today['특이사항'].fillna('')
    df_sales_today.loc[:, '상품매출'] = df_sales_today['상품매출'].fillna(0)
    df_sales_today.loc[:, '판매배송비'] = df_sales_today['판매배송비'].fillna(0)
    df_sales_today.loc[:, '도선료'] = df_sales_today['도선료'].fillna(0)

    # 업체명-특이사항-제품-수량 순으로 정렬
    df_sales_today = df_sales_today.sort_values(['업체명', '특이사항', '제품', '수량'])

    # 출고일-업체명-특이사항 별로 각각 상품매출/판매배송비/도선료 합계 구하기
    df_sales_today_sum_per_seller = df_sales_today.groupby(['출고일', '업체명', '특이사항'])[['상품매출', '판매배송비', '도선료']].sum().reset_index()
    # 업체별합계 = 상품매출 + 판매배송비 + 도선료
    df_sales_today_sum_per_seller['업체별합계'] = df_sales_today_sum_per_seller['상품매출'] + df_sales_today_sum_per_seller['판매배송비'] + df_sales_today_sum_per_seller['도선료']
    # 열 삭제 : 상품매출, 판매배송비, 도선료 // merge 후 열 이름 중복
    df_sales_today_sum_per_seller = df_sales_today_sum_per_seller.drop(['상품매출', '판매배송비', '도선료'], axis=1)
    # df_sales_today와 merge
    df_sales_today = pd.merge(left=df_sales_today, right=df_sales_today_sum_per_seller, on=['출고일', '업체명', '특이사항'])

    # 업체별합계 매출 누적 구하기
    df_sales_acc = pd.concat([df_sales_acc, df_sales_today_sum_per_seller], axis=0)

    # 인덱스 초기화
    df_sales_today.reset_index()

    # 중복제거 수량 합계 구하기 // 금액 확인 문제 때문에 사용하지 않음
    # df_sales_today.groupby(['출고일', '업체명', '특이사항', '제품'])['수량'].sum()

    # 매출 금액 합계
    sum_sales = float(df_sales_today[['상품매출','판매배송비','도선료']].sum().sum())    
    acc_sales += sum_sales

    if len(df_sales_today) > 0:
        # 특정 열만 선택
        # df_sales_today.loc[:, ['출고일', '업체명', '특이사항', '제품', '수량', '과세구분', '계산서', '상품매출', '판매배송비', '도선료']].to_excel('솔루미랩_매출_' + today + '.xlsx')
        df_sales_today.loc[:, ['출고일', '업체명', '특이사항', '제품', '수량', '상품매출', '판매배송비', '도선료', '업체별합계', '과세구분', '계산서', '구분']].to_excel(excelWriter, sheet_name='매출_' + today)
        print(today, "매출 금액 합계 : ", sum_sales)

    #################### 매입 데이터 조회 ####################
    # 한방에 데이터 필터링 (특정날짜, 당사재고아닌것, 매입/배송비/도선료 있는것만)
    df_buy_today = df[ (df['출고일'] == today) & (df['특이사항'] != '솔루미재고') & (df['매입처'] != '당사재고') & (df['매입처'] != '솔루미랩') & ((df['상품매입'] != 0) | (df['매입배송비'] != 0) | (df['도선료.1'] != 0)) ]

    # 매입배송비, 도선료.1 int64 -> float64로 변경
    df_buy_today = df_buy_today.astype({'매입배송비':'float64', '도선료.1': 'float64'})

    # 특이사항 NaN을 공란으로 수정
    df_buy_today.loc[:, '특이사항'] = df_buy_today['특이사항'].fillna('')
    df_buy_today.loc[:, '상품매입'] = df_buy_today['상품매입'].fillna(0)
    df_buy_today.loc[:, '매입배송비'] = df_buy_today['매입배송비'].fillna(0)
    df_buy_today.loc[:, '도선료.1'] = df_buy_today['도선료.1'].fillna(0)                # 매입도선료는 도선료.1로 들어옴

    # '매입처' 지앤제이 '매입배송비', 도선료 0 처리
    df_buy_today.loc[df_buy_today['매입처'] == '지앤제이', '매입배송비'] = 0
    df_buy_today.loc[df_buy_today['매입처'] == '지앤제이', '도선료.1'] = 0
    df_buy_today.loc[(df_buy_today['매입처'] == '지앤제이') & (df_buy_today['업체명'] == '빅웨이브즈'), '특이사항'] = '빅웨이브즈' 
    # '매입처' 유스랩 '매입배송비', 도선료 0 처리. 2024-10-30 추가
    df_buy_today.loc[df_buy_today['매입처'] == '유스랩', '매입배송비'] = 0
    df_buy_today.loc[df_buy_today['매입처'] == '유스랩', '도선료.1'] = 0
    df_buy_today.loc[(df_buy_today['매입처'] == '유스랩') & (df_buy_today['업체명'] == '빅웨이브즈'), '특이사항'] = '빅웨이브즈'    
    # df_buy_today.loc[(df_buy_today['매입처'] == '지앤제이') & (df_buy_today['업체명'] == '빅웨이브즈'), '추가1'] = '빅웨이브즈'

    # 출고일-매입처-특이사항 별로 각각 상품매입/매입배송비/도선료.1 합계 구하기
    df_buy_today_sum_per_seller = df_buy_today.groupby(['출고일', '매입처', '특이사항'])[['상품매입', '매입배송비', '도선료.1']].sum().reset_index()
    # 업체별합계 = 상품매입 + 매입배송비 + 도선료.1
    df_buy_today_sum_per_seller['업체별합계'] = df_buy_today_sum_per_seller['상품매입'] + df_buy_today_sum_per_seller['매입배송비'] + df_buy_today_sum_per_seller['도선료.1']
    # 열 삭제 : 상품매입, 매입배송비, 도선료.1 // merge 후 열 이름 중복
    df_buy_today_sum_per_seller = df_buy_today_sum_per_seller.drop(['상품매입', '매입배송비', '도선료.1'], axis=1)
    # df_buy_today와 merge
    df_buy_today = pd.merge(left=df_buy_today, right=df_buy_today_sum_per_seller, on=['출고일', '매입처', '특이사항'])

    # 업체별합계 매입 누적 구하기
    df_buy_acc = pd.concat([df_buy_acc, df_buy_today_sum_per_seller], axis=0)

    # 업체명-특이사항-제품-수량 순으로 정렬
    df_buy_today = df_buy_today.sort_values(['매입처', '특이사항', '제품', '수량'])

    # 매입 금액 합계
    sum_buy = float(df_buy_today[['상품매입','매입배송비','도선료.1']].sum().sum())    
    acc_buy += sum_buy

    if len(df_buy_today) > 0:
        # 특정 열만 선택
        # df_buy_today.loc[:, ['출고일', '매입처', '특이사항', '제품', '수량', '과세구분', '상품매입', '매입배송비', '도선료']].to_excel('솔루미랩_매입_' + today + '.xlsx')
        df_buy_today.loc[:, ['출고일', '매입처', '특이사항', '제품', '수량', '상품매입', '매입배송비', '도선료.1', '업체별합계', '과세구분', '구분', '업체명']].to_excel(excelWriter, sheet_name='매입_' + today)
        print(today, "매입 금액 합계 : ", sum_buy)

    # 다음날
    date_from += timedelta(days=1)

df_sales_acc.groupby(['업체명','특이사항'])[['업체별합계']].sum().sort_values(['업체명','특이사항']).reset_index().to_excel(excelWriter, sheet_name='매출_업체별합계')
df_buy_acc.groupby(['매입처','특이사항'])[['업체별합계']].sum().sort_values(['매입처','특이사항']).reset_index().to_excel(excelWriter, sheet_name='매입_업체별합계')

# 엑셀파일 저장
excelWriter.close()

# 누적 매출/매입 출력
print(_from, _to, "누적 매출 금액 : ", acc_sales)
print(_from, _to, "누적 매입 금액 : ", acc_buy)
