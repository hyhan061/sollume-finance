"""
솔루미랩 거래처 관리 페이지
거래처 검색, 등록, 수정, 삭제 및 Excel 가져오기/내보내기 기능
2025-12-16 hoyeon.han: 거래처 관리 페이지 생성
2025-12-17 hoyeon.han: 로그인 인증 추가
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import os
import sys
from pathlib import Path
import re
import logging

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정 (Streamlit 명령 중 가장 먼저 실행되어야 함)
st.set_page_config(page_title="거래처 관리", page_icon="🏢", layout="wide")

# 2025-12-17 hoyeon.han: 인증 체크 (Src/__init__.py 우회)
import importlib.util

spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent.parent / "Src" / "auth.py"
)
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
auth.require_auth()
auth.show_user_info_sidebar()

# 거래처 마스터 DB 클래스
from customer_master_db import CustomerMasterDB

# 디렉토리 생성
os.makedirs("logs", exist_ok=True)
os.makedirs("database", exist_ok=True)
os.makedirs("database/backups", exist_ok=True)
os.makedirs("processed", exist_ok=True)
os.makedirs("uploads", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/customer_management.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# =============================================================================
# 2025-12-16 hoyeon.han: CSS 스타일 정의
# =============================================================================

st.markdown(
    """
<style>
    .main-header {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .section-header {
        font-size: 1.5rem;
        font-weight: bold;
        color: #2c3e50;
        margin-top: 2rem;
        margin-bottom: 1rem;
        border-bottom: 2px solid #3498db;
        padding-bottom: 0.5rem;
    }
    .success-box {
        padding: 1rem;
        background-color: #d4edda;
        border-left: 4px solid #28a745;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .error-box {
        padding: 1rem;
        background-color: #f8d7da;
        border-left: 4px solid #dc3545;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .info-box {
        padding: 1rem;
        background-color: #d1ecf1;
        border-left: 4px solid #17a2b8;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .warning-box {
        padding: 1rem;
        background-color: #fff3cd;
        border-left: 4px solid #ffc107;
        border-radius: 4px;
        margin: 1rem 0;
    }
    .card-box {
        padding: 1.5rem;
        background-color: #f8f9fa;
        border-radius: 10px;
        border-left: 4px solid #3498db;
        margin: 1rem 0;
    }
</style>
""",
    unsafe_allow_html=True,
)

# =============================================================================
# 2025-12-16 hoyeon.han: Session State 초기화
# =============================================================================

if "search_results" not in st.session_state:
    st.session_state.search_results = pd.DataFrame()

if "selected_customer" not in st.session_state:
    st.session_state.selected_customer = None

if "show_add_form" not in st.session_state:
    st.session_state.show_add_form = False

if "show_edit_form" not in st.session_state:
    st.session_state.show_edit_form = False

# =============================================================================
# 2025-12-16 hoyeon.han: 유틸리티 함수
# =============================================================================


def is_business_number_format(business_number: str) -> bool:
    """사업자번호 형식 검증 (000-00-00000)

    Args:
        business_number: 사업자번호 문자열

    Returns:
        형식이 올바르면 True, 아니면 False
    """
    # 정규식 패턴: 숫자3자리-숫자2자리-숫자5자리
    pattern = r"^\d{3}-\d{2}-\d{5}$"
    return bool(re.match(pattern, business_number))


def format_business_number(business_number: str) -> str:
    """사업자번호 형식 자동 변환 (하이픈 추가)

    Args:
        business_number: 사업자번호 (하이픈 있거나 없거나)

    Returns:
        형식화된 사업자번호 (000-00-00000)
    """
    # 하이픈 제거
    cleaned = business_number.replace("-", "").replace(" ", "")

    # 숫자만 남김
    numbers = "".join(filter(str.isdigit, cleaned))

    # 10자리가 아니면 원본 반환
    if len(numbers) != 10:
        return business_number

    # 형식화: 000-00-00000
    return f"{numbers[:3]}-{numbers[3:5]}-{numbers[5:]}"


# =============================================================================
# 2025-12-16 hoyeon.han: 거래처 검색 기능
# =============================================================================


def show_search_section(db: CustomerMasterDB):
    """거래처 검색 섹션"""

    st.markdown(
        '<div class="section-header">🔍 거래처 검색</div>', unsafe_allow_html=True
    )

    col1, col2, col3 = st.columns([3, 1, 1])

    with col1:
        search_query = st.text_input(
            "거래처명 또는 사업자번호 검색",
            placeholder="거래처명 일부 또는 사업자번호를 입력하세요",
            key="search_query",
        )

    with col2:
        search_btn = st.button("🔍 검색", type="primary", use_container_width=True)

    with col3:
        show_all_btn = st.button("📋 전체 조회", use_container_width=True)

    # 검색 실행
    if search_btn and search_query:
        try:
            with st.spinner("검색 중..."):
                results = db.search_customers(search_query)
                st.session_state.search_results = results

                if len(results) == 0:
                    st.warning(f"'{search_query}'에 대한 검색 결과가 없습니다.")
                    st.info(
                        "신규 거래처를 등록하시겠습니까? 아래 '신규 등록' 버튼을 클릭하세요."
                    )
                    st.session_state.show_add_form = True
                else:
                    st.success(f"검색 결과: {len(results)}건")
                    st.session_state.show_add_form = False

        except Exception as e:
            logger.error(f"검색 실패: {e}", exc_info=True)
            st.error(f"검색 중 오류가 발생했습니다: {str(e)}")

    # 전체 조회
    elif show_all_btn:
        try:
            with st.spinner("전체 거래처 조회 중..."):
                results = db.get_all_customers()
                st.session_state.search_results = results
                st.success(f"전체 거래처: {len(results)}건")
                st.session_state.show_add_form = False

        except Exception as e:
            logger.error(f"전체 조회 실패: {e}", exc_info=True)
            st.error(f"조회 중 오류가 발생했습니다: {str(e)}")


# =============================================================================
# 2025-12-16 hoyeon.han: 검색 결과 표시
# =============================================================================


def show_search_results():
    """검색 결과 테이블 표시"""

    if st.session_state.search_results.empty:
        return

    st.markdown(
        '<div class="section-header">📊 검색 결과</div>', unsafe_allow_html=True
    )

    # DataFrame 표시 (타임스탬프 컬럼 제외)
    display_df = st.session_state.search_results[
        ["사업자번호", "발주내역_거래처명", "경리나라_거래처명", "대표자명"]
    ].copy()

    # 인덱스를 1부터 시작
    display_df.index = range(1, len(display_df) + 1)

    st.dataframe(
        display_df,
        use_container_width=True,
        height=min(400, (len(display_df) + 1) * 35 + 3),
    )

    # 거래처 선택 (수정/삭제용)
    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        # 2026-05-24 hoyeon.han: 스키마 id PK 마이그레이션 대응 - 사업자번호 단독 식별 불가, id 기반 선택으로 변경
        # # 사업자번호 선택
        # business_numbers = st.session_state.search_results["사업자번호"].tolist()
        # customer_names = st.session_state.search_results["발주내역_거래처명"].tolist()
        #
        # # 선택 옵션: "사업자번호 - 거래처명"
        # options = [f"{bn} - {cn}" for bn, cn in zip(business_numbers, customer_names)]
        #
        # selected_option = st.selectbox(
        #     "수정/삭제할 거래처 선택",
        #     options=["선택하세요"] + options,
        #     key="selected_customer_option",
        # )

        # 2026-05-24 hoyeon.han: id 컬럼이 있을 때만 식별자 기반 선택 활성화
        if "id" in st.session_state.search_results.columns:
            ids = st.session_state.search_results["id"].tolist()
            business_numbers = st.session_state.search_results["사업자번호"].tolist()
            customer_names = st.session_state.search_results[
                "발주내역_거래처명"
            ].tolist()

            # 옵션 값은 id, 라벨은 "사업자번호 - 거래처명"
            id_to_label = {
                int(cid): f"{bn} - {cn}"
                for cid, bn, cn in zip(ids, business_numbers, customer_names)
            }
            options = [None] + list(id_to_label.keys())

            selected_id = st.selectbox(
                "수정/삭제할 거래처 선택",
                options=options,
                format_func=lambda x: "선택하세요" if x is None else id_to_label[x],
                key="selected_customer_option",
            )
        else:
            # 구버전 스키마 호환: id 컬럼이 없으면 수정/삭제 비활성화
            selected_id = None
            st.warning(
                "현재 DB 스키마에 id 컬럼이 없어 수정/삭제가 비활성화되어 있습니다. "
                "DB 마이그레이션이 필요합니다."
            )

    with col2:
        st.write("")  # 여백
        st.write("")  # 여백

        col2_1, col2_2 = st.columns(2)

        with col2_1:
            edit_btn = st.button("✏️ 수정", type="secondary", use_container_width=True)

        with col2_2:
            delete_btn = st.button("🗑️ 삭제", type="secondary", use_container_width=True)

    # 거래처 선택 처리
    # 2026-05-24 hoyeon.han: 스키마 id PK 마이그레이션 대응 - id 기반으로 selected_customer 저장
    if selected_id is not None:
        st.session_state.selected_customer = int(selected_id)

        # 수정 버튼 클릭
        if edit_btn:
            st.session_state.show_edit_form = True
            st.session_state.show_add_form = False
            st.rerun()

        # 삭제 버튼 클릭
        if delete_btn:
            show_delete_confirmation(int(selected_id))


# =============================================================================
# 2025-12-16 hoyeon.han: 신규 거래처 등록 폼
# =============================================================================


def show_add_customer_form(db: CustomerMasterDB):
    """신규 거래처 등록 폼"""

    st.markdown(
        '<div class="section-header">➕ 신규 거래처 등록</div>', unsafe_allow_html=True
    )

    with st.form("add_customer_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            business_number_input = st.text_input(
                "사업자번호 *",
                placeholder="000-00-00000 또는 0000000000",
                help="하이픈 포함 또는 미포함 10자리",
            )

            order_name = st.text_input(
                "발주내역 거래처명 *", placeholder="발주내역 엑셀에 표시되는 거래처명"
            )

        with col2:
            accounting_name = st.text_input(
                "경리나라 거래처명 *", placeholder="경리나라 프로그램에 등록된 거래처명"
            )

            representative = st.text_input(
                "대표자명", placeholder="대표자 성함 (선택사항)"
            )

        st.markdown("**필수 항목**")

        col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 1])

        with col_btn2:
            submit_btn = st.form_submit_button(
                "💾 등록", type="primary", use_container_width=True
            )

        with col_btn3:
            cancel_btn = st.form_submit_button("❌ 취소", use_container_width=True)

    # 취소 버튼
    if cancel_btn:
        st.session_state.show_add_form = False
        st.rerun()

    # 등록 처리
    if submit_btn:
        # 입력 검증
        if not business_number_input or not order_name or not accounting_name:
            st.error(
                "필수 항목을 모두 입력해주세요 (사업자번호, 발주내역 거래처명, 경리나라 거래처명)"
            )
            return

        # 사업자번호 형식 변환
        business_number = format_business_number(business_number_input)

        # 형식 검증
        if not is_business_number_format(business_number):
            st.error(
                f"사업자번호 형식이 올바르지 않습니다: {business_number_input}\n올바른 형식: 000-00-00000 (하이픈 포함 10자리)"
            )
            return

        # DB에 등록
        try:
            with st.spinner("거래처 등록 중..."):
                success, message = db.add_customer(
                    business_number=business_number,
                    order_name=order_name.strip(),
                    accounting_name=accounting_name.strip(),
                    representative=representative.strip() if representative else None,
                )

            if success:
                st.success(message)
                logger.info(f"거래처 등록 성공: {business_number} - {order_name}")

                # 폼 닫기
                st.session_state.show_add_form = False

                # 검색 결과 갱신
                st.session_state.search_results = db.search_customers(order_name)

                st.balloons()
                st.rerun()
            else:
                st.error(message)
                logger.warning(f"거래처 등록 실패: {message}")

        except Exception as e:
            logger.error(f"거래처 등록 오류: {e}", exc_info=True)
            st.error(f"거래처 등록 중 오류가 발생했습니다: {str(e)}")


# =============================================================================
# 2025-12-16 hoyeon.han: 거래처 수정 폼
# =============================================================================


# 2026-05-24 hoyeon.han: 스키마 id PK 마이그레이션 대응 - 식별자 business_number → customer_id 로 변경
# def show_edit_customer_form(db: CustomerMasterDB, business_number: str):
#     """거래처 수정 폼"""
#
#     st.markdown(
#         '<div class="section-header">✏️ 거래처 정보 수정</div>', unsafe_allow_html=True
#     )
#
#     # 기존 정보 조회
#     customer = db.get_customer(business_number)
#
#     if not customer:
#         st.error(f"거래처를 찾을 수 없습니다: {business_number}")
#         st.session_state.show_edit_form = False
#         return
def show_edit_customer_form(db: CustomerMasterDB, customer_id: int):
    """거래처 수정 폼

    2026-05-24 hoyeon.han: 스키마 id PK 마이그레이션 대응
    - 인자: business_number(str) → customer_id(int)
    - 조회: get_customer(List[dict] 반환) → get_customer_by_id(단일 dict 반환)
    """

    st.markdown(
        '<div class="section-header">✏️ 거래처 정보 수정</div>', unsafe_allow_html=True
    )

    # 기존 정보 조회
    customer = db.get_customer_by_id(customer_id)

    if not customer:
        st.error(f"거래처를 찾을 수 없습니다: ID {customer_id}")
        st.session_state.show_edit_form = False
        return

    # 정보 표시
    st.info(
        f"**수정 대상:** {customer['발주내역_거래처명']} ({customer['사업자번호']})"
    )

    with st.form("edit_customer_form"):
        # 사업자번호는 변경 불가 (PK)
        st.text_input(
            "사업자번호 (변경 불가)",
            value=customer["사업자번호"],
            disabled=True,
            help="사업자번호는 수정할 수 없습니다",
        )

        col1, col2 = st.columns(2)

        with col1:
            order_name = st.text_input(
                "발주내역 거래처명 *", value=customer["발주내역_거래처명"]
            )

        with col2:
            accounting_name = st.text_input(
                "경리나라 거래처명 *", value=customer["경리나라_거래처명"]
            )

        representative = st.text_input(
            "대표자명", value=customer["대표자명"] if customer["대표자명"] else ""
        )

        col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 1])

        with col_btn2:
            submit_btn = st.form_submit_button(
                "💾 수정 완료", type="primary", use_container_width=True
            )

        with col_btn3:
            cancel_btn = st.form_submit_button("❌ 취소", use_container_width=True)

    # 취소 버튼
    if cancel_btn:
        st.session_state.show_edit_form = False
        st.session_state.selected_customer = None
        st.rerun()

    # 수정 처리
    if submit_btn:
        # 입력 검증
        if not order_name or not accounting_name:
            st.error(
                "필수 항목을 모두 입력해주세요 (발주내역 거래처명, 경리나라 거래처명)"
            )
            return

        # DB 업데이트
        # 2026-05-24 hoyeon.han: 스키마 id PK 마이그레이션 대응 - customer_id를 첫 인자로 전달
        # try:
        #     with st.spinner("거래처 정보 수정 중..."):
        #         success, message = db.update_customer(
        #             business_number=business_number,
        #             order_name=order_name.strip(),
        #             accounting_name=accounting_name.strip(),
        #             representative=representative.strip() if representative else None,
        #         )
        #
        #     if success:
        #         st.success(message)
        #         logger.info(f"거래처 수정 성공: {business_number}")
        try:
            with st.spinner("거래처 정보 수정 중..."):
                success, message = db.update_customer(
                    customer_id=customer_id,
                    order_name=order_name.strip(),
                    accounting_name=accounting_name.strip(),
                    representative=representative.strip() if representative else None,
                )

            if success:
                st.success(message)
                logger.info(f"거래처 수정 성공: ID {customer_id}")

                # 폼 닫기
                st.session_state.show_edit_form = False
                st.session_state.selected_customer = None

                # 검색 결과 갱신
                st.session_state.search_results = db.search_customers(order_name)

                st.rerun()
            else:
                st.error(message)
                logger.warning(f"거래처 수정 실패: {message}")

        except Exception as e:
            logger.error(f"거래처 수정 오류: {e}", exc_info=True)
            st.error(f"거래처 수정 중 오류가 발생했습니다: {str(e)}")


# =============================================================================
# 2025-12-16 hoyeon.han: 거래처 삭제 확인
# =============================================================================


# 2026-05-24 hoyeon.han: 스키마 id PK 마이그레이션 대응 - 식별자 business_number → customer_id 로 변경
# def show_delete_confirmation(business_number: str):
#     """거래처 삭제 확인 다이얼로그"""
#
#     # DB 인스턴스 생성
#     db = CustomerMasterDB()
#
#     # 거래처 정보 조회
#     customer = db.get_customer(business_number)
#
#     if not customer:
#         st.error(f"거래처를 찾을 수 없습니다: {business_number}")
#         return
#
#     # 확인 다이얼로그
#     st.markdown('<div class="warning-box">', unsafe_allow_html=True)
#     st.warning("⚠️ **거래처 삭제 확인**")
#     st.write(f"**거래처명:** {customer['발주내역_거래처명']}")
#     st.write(f"**사업자번호:** {customer['사업자번호']}")
#     st.write(f"**경리나라 거래처명:** {customer['경리나라_거래처명']}")
#     st.markdown("</div>", unsafe_allow_html=True)
#
#     st.error("**정말로 이 거래처를 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.**")
#
#     col1, col2, col3 = st.columns([2, 1, 1])
#
#     with col2:
#         confirm_btn = st.button("🗑️ 삭제 확인", type="primary", use_container_width=True)
#
#     with col3:
#         cancel_delete_btn = st.button("❌ 취소", use_container_width=True)
#
#     # 삭제 확인
#     if confirm_btn:
#         try:
#             with st.spinner("거래처 삭제 중..."):
#                 success, message = db.delete_customer(business_number)
#
#             if success:
#                 st.success(message)
#                 logger.info(f"거래처 삭제 성공: {business_number}")
#
#                 # 검색 결과에서 제거
#                 st.session_state.search_results = st.session_state.search_results[
#                     st.session_state.search_results["사업자번호"] != business_number
#                 ]
#
#                 st.session_state.selected_customer = None
#                 st.rerun()
#             else:
#                 st.error(message)
#                 logger.warning(f"거래처 삭제 실패: {message}")
#
#         except Exception as e:
#             logger.error(f"거래처 삭제 오류: {e}", exc_info=True)
#             st.error(f"거래처 삭제 중 오류가 발생했습니다: {str(e)}")
#
#     # 취소
#     if cancel_delete_btn:
#         st.session_state.selected_customer = None
#         st.rerun()
def show_delete_confirmation(customer_id: int):
    """거래처 삭제 확인 다이얼로그

    2026-05-24 hoyeon.han: 스키마 id PK 마이그레이션 대응
    - 인자: business_number(str) → customer_id(int)
    - 조회/삭제: get_customer_by_id, delete_customer(customer_id)
    - 검색 결과 필터: 사업자번호 비교 → id 비교
    """

    # DB 인스턴스 생성
    db = CustomerMasterDB()

    # 거래처 정보 조회
    customer = db.get_customer_by_id(customer_id)

    if not customer:
        st.error(f"거래처를 찾을 수 없습니다: ID {customer_id}")
        return

    # 확인 다이얼로그
    st.markdown('<div class="warning-box">', unsafe_allow_html=True)
    st.warning("⚠️ **거래처 삭제 확인**")
    st.write(f"**거래처명:** {customer['발주내역_거래처명']}")
    st.write(f"**사업자번호:** {customer['사업자번호']}")
    st.write(f"**경리나라 거래처명:** {customer['경리나라_거래처명']}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.error("**정말로 이 거래처를 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.**")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col2:
        confirm_btn = st.button("🗑️ 삭제 확인", type="primary", use_container_width=True)

    with col3:
        cancel_delete_btn = st.button("❌ 취소", use_container_width=True)

    # 삭제 확인
    if confirm_btn:
        try:
            with st.spinner("거래처 삭제 중..."):
                success, message = db.delete_customer(customer_id)

            if success:
                st.success(message)
                logger.info(f"거래처 삭제 성공: ID {customer_id}")

                # 검색 결과에서 제거 (id 기준)
                if "id" in st.session_state.search_results.columns:
                    st.session_state.search_results = st.session_state.search_results[
                        st.session_state.search_results["id"] != customer_id
                    ]

                st.session_state.selected_customer = None
                st.rerun()
            else:
                st.error(message)
                logger.warning(f"거래처 삭제 실패: {message}")

        except Exception as e:
            logger.error(f"거래처 삭제 오류: {e}", exc_info=True)
            st.error(f"거래처 삭제 중 오류가 발생했습니다: {str(e)}")

    # 취소
    if cancel_delete_btn:
        st.session_state.selected_customer = None
        st.rerun()


# =============================================================================
# 2025-12-16 hoyeon.han: Excel 가져오기/내보내기
# =============================================================================


def show_data_management(db: CustomerMasterDB):
    """데이터 관리 섹션 (Excel 가져오기/내보내기, DB 백업)"""

    st.markdown(
        '<div class="section-header">🔄 데이터 관리</div>', unsafe_allow_html=True
    )

    col1, col2, col3 = st.columns(3)

    # Excel 가져오기
    with col1:
        with st.expander("📥 Excel 가져오기", expanded=False):
            st.info("""
            **Excel 파일 형식:**
            - 시트명: `거래처마스터`
            - 필수 컬럼:
              - 거래처명_경리나라
              - 거래처명_솔루미랩
              - 사업자번호
              - 대표자명 (선택)
            """)

            uploaded_file = st.file_uploader(
                "Excel 파일 선택", type=["xlsx", "xls"], key="import_excel"
            )

            if uploaded_file:
                if st.button(
                    "📥 가져오기 실행", type="primary", use_container_width=True
                ):
                    try:
                        # 임시 파일로 저장
                        temp_path = f"uploads/temp_master_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

                        with open(temp_path, "wb") as f:
                            f.write(uploaded_file.getvalue())

                        with st.spinner("Excel 데이터 가져오는 중..."):
                            success, message = db.import_from_excel(temp_path)

                        # 임시 파일 삭제
                        if os.path.exists(temp_path):
                            os.remove(temp_path)

                        if success:
                            st.success(message)
                            logger.info(f"Excel 가져오기 성공")

                            # 검색 결과 갱신
                            st.session_state.search_results = db.get_all_customers()
                        else:
                            st.error(message)
                            logger.warning(f"Excel 가져오기 실패: {message}")

                    except Exception as e:
                        logger.error(f"Excel 가져오기 오류: {e}", exc_info=True)
                        st.error(f"Excel 가져오기 중 오류가 발생했습니다: {str(e)}")

    # Excel 내보내기
    with col2:
        with st.expander("📤 Excel 내보내기", expanded=False):
            st.info("현재 DB의 모든 거래처 데이터를 Excel 파일로 다운로드합니다.")

            if st.button("📤 내보내기 실행", type="primary", use_container_width=True):
                try:
                    # 파일명 생성
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    export_path = f"processed/거래처마스터_{timestamp}.xlsx"

                    with st.spinner("Excel 파일 생성 중..."):
                        success, message = db.export_to_excel(export_path)

                    if success:
                        st.success(message)
                        logger.info(f"Excel 내보내기 성공: {export_path}")

                        # 다운로드 버튼
                        with open(export_path, "rb") as f:
                            st.download_button(
                                label="💾 Excel 파일 다운로드",
                                data=f.read(),
                                file_name=f"거래처마스터_{timestamp}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True,
                            )
                    else:
                        st.error(message)
                        logger.warning(f"Excel 내보내기 실패: {message}")

                except Exception as e:
                    logger.error(f"Excel 내보내기 오류: {e}", exc_info=True)
                    st.error(f"Excel 내보내기 중 오류가 발생했습니다: {str(e)}")

    # DB 백업
    with col3:
        with st.expander("💾 DB 백업", expanded=False):
            st.info(
                "데이터베이스를 백업합니다. 백업 파일은 `database/backups/` 폴더에 저장됩니다."
            )

            if st.button("💾 백업 실행", type="primary", use_container_width=True):
                try:
                    with st.spinner("데이터베이스 백업 중..."):
                        backup_file = db.backup_db()

                    st.success(f"백업 완료!\n파일: {backup_file}")
                    logger.info(f"DB 백업 성공: {backup_file}")

                    # 백업 파일 정보
                    backup_path = Path(backup_file)
                    file_size = backup_path.stat().st_size / 1024  # KB

                    st.caption(f"백업 파일 크기: {file_size:.2f} KB")
                    st.caption(
                        f"백업 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )

                except Exception as e:
                    logger.error(f"DB 백업 오류: {e}", exc_info=True)
                    st.error(f"백업 중 오류가 발생했습니다: {str(e)}")


# =============================================================================
# 2025-12-16 hoyeon.han: 통계 정보 표시
# =============================================================================


def show_statistics(db: CustomerMasterDB):
    """DB 통계 정보 표시"""

    try:
        stats = db.get_stats()

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("총 거래처 수", f"{stats.get('total_customers', 0)}건")

        with col2:
            latest_created = stats.get("latest_created")
            if latest_created:
                created_date = datetime.strptime(
                    latest_created, "%Y-%m-%d %H:%M:%S"
                ).strftime("%Y-%m-%d")
                st.metric("최근 등록일", created_date)
            else:
                st.metric("최근 등록일", "N/A")

        with col3:
            latest_updated = stats.get("latest_updated")
            if latest_updated:
                updated_date = datetime.strptime(
                    latest_updated, "%Y-%m-%d %H:%M:%S"
                ).strftime("%Y-%m-%d")
                st.metric("최근 수정일", updated_date)
            else:
                st.metric("최근 수정일", "N/A")

    except Exception as e:
        logger.error(f"통계 조회 오류: {e}", exc_info=True)
        st.error(f"통계 정보를 가져올 수 없습니다: {str(e)}")


# =============================================================================
# 2025-12-16 hoyeon.han: 메인 페이지
# =============================================================================


def main():
    """메인 페이지"""

    # 페이지 헤더
    st.markdown('<div class="main-header">🏢 거래처 관리</div>', unsafe_allow_html=True)

    st.markdown("""
    거래처 정보를 조회, 등록, 수정, 삭제할 수 있습니다.
    Excel 파일로 가져오기/내보내기도 가능합니다.
    """)

    st.divider()

    # DB 인스턴스 생성
    try:
        db = CustomerMasterDB()
    except Exception as e:
        logger.error(f"DB 연결 실패: {e}", exc_info=True)
        st.error(f"데이터베이스 연결에 실패했습니다: {str(e)}")
        st.stop()

    # 통계 정보
    show_statistics(db)

    st.divider()

    # 거래처 검색
    show_search_section(db)

    st.divider()

    # 검색 결과 표시
    if not st.session_state.search_results.empty:
        show_search_results()
        st.divider()

    # 신규 등록 버튼 (검색 결과가 없거나 명시적으로 추가 버튼 클릭)
    if st.session_state.search_results.empty or st.button(
        "➕ 신규 거래처 등록", type="secondary"
    ):
        st.session_state.show_add_form = True

    # 신규 등록 폼
    if st.session_state.show_add_form:
        show_add_customer_form(db)
        st.divider()

    # 수정 폼
    # 2026-05-24 hoyeon.han: selected_customer는 이제 customer_id(int) 를 담음
    if st.session_state.show_edit_form and st.session_state.selected_customer:
        show_edit_customer_form(db, int(st.session_state.selected_customer))
        st.divider()

    # 데이터 관리
    show_data_management(db)

    # Footer
    st.divider()
    st.caption("© 2025 솔루미랩 | v3.0.0")
    st.caption("작성자: hoyeon.han | 작성일: 2025-12-16")


# =============================================================================
# 2025-12-16 hoyeon.han: 실행
# =============================================================================

if __name__ == "__main__":
    main()
