"""
솔루미랩 시스템 관리 페이지
DB 상태, 파일 관리, 로그 뷰어, 데이터 정리 기능 제공
2025-04-13 hoyeon.han: 신규 생성 (전표생성 페이지에서 분리)
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import os
import sys
from pathlib import Path

# Src 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "Src"))

# 페이지 설정 (Streamlit 명령 중 가장 먼저 실행되어야 함)
# 2026-07-10 hoyeon.han: st.navigation 라우터(Home.py)로 이전 - 진입점에서 처리
# st.set_page_config(page_title="시스템 관리", page_icon="⚙️", layout="wide")

# 인증 체크
import importlib.util

spec = importlib.util.spec_from_file_location(
    "auth", Path(__file__).parent.parent / "Src" / "auth.py"
)
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
# auth.require_auth()

# 커스텀 사이드바
from ui_components import render_custom_sidebar

# 2026-07-09 hoyeon.han: 디자인 개선 - 공통 테마 CSS/헤더/화면폭 설정 모듈
from ui_theme import inject_global_css, render_page_header, render_width_setting

# render_custom_sidebar()
# 2026-07-09 hoyeon.han: 사이드바 이후 전역 CSS 주입(.section-header 등 공통 클래스 포함)
# inject_global_css()

# =============================================================================
# CSS 스타일
# =============================================================================

# 2026-07-09 hoyeon.han: 디자인 개선 - 로컬 <style>(구 팔레트 #1f77b4/#3498db) 제거
#   .main-header/.section-header 는 Src/ui_theme.py inject_global_css()가 새 인디고 테마로 제공,
#   .metric-card 는 미사용. (페이지 헤더는 render_page_header 로 대체)
# st.markdown(
#     """
# <style>
#     .main-header { font-size: 2rem; font-weight: bold; color: #1f77b4; margin-bottom: 1rem; }
#     .section-header { font-size: 1.5rem; font-weight: bold; color: #2c3e50; margin-top: 2rem;
#                       margin-bottom: 1rem; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; }
#     .metric-card { background-color: #f8f9fa; border-radius: 8px; padding: 1rem; border-left: 4px solid #3498db; }
# </style>
# """,
#     unsafe_allow_html=True,
# )

# =============================================================================
# 페이지 타이틀
# =============================================================================

# 2026-07-09 hoyeon.han: 디자인 개선 - 통일 페이지 헤더로 교체
# st.markdown('<div class="main-header">⚙️ 시스템 관리</div>', unsafe_allow_html=True)
# st.caption("시스템 상태 모니터링, 파일 관리, 로그 확인, 데이터 정리 기능을 제공합니다.")
# st.divider()
render_page_header(
    "시스템 관리",
    "시스템 상태·파일·로그·데이터 정리와 화면 표시 설정을 제공합니다.",
    icon="⚙️",
)

# 2026-07-09 hoyeon.han: 디자인 개선 - 화면 폭 설정을 사이드바에서 이곳 상단 popover로 이전
with st.popover("🖥️ 화면 표시 설정"):
    st.caption("본문 최대 폭을 선택하세요. 테마가 적용된 화면에 반영되고 재접속 후에도 유지됩니다.")
    render_width_setting()

# =============================================================================
# 탭 구성
# =============================================================================

# 2026-06-03 hoyeon.han: '발주내역 파일' 관리 탭 추가 (4개 → 5개)
# --- 기존 코드 (주석 처리) ---
# tab1, tab2, tab3, tab4 = st.tabs(
#     ["📊 시스템 상태", "📁 파일 관리", "🔍 로그 뷰어", "🧹 데이터 정리"]
# )
# --- 기존 코드 끝 ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📊 시스템 상태", "📁 파일 관리", "📥 발주내역 파일", "🔍 로그 뷰어", "🧹 데이터 정리"]
)

# =============================================================================
# 탭 1: 시스템 상태
# =============================================================================

with tab1:
    st.markdown(
        '<div class="section-header">데이터베이스 상태</div>', unsafe_allow_html=True
    )

    db_path = "database/customer_master.db"

    if os.path.exists(db_path):
        file_size = os.path.getsize(db_path) / 1024
        file_time = datetime.fromtimestamp(os.path.getmtime(db_path))

        try:
            from Src.customer_master_db import CustomerMasterDB

            db = CustomerMasterDB(db_path)
            customer_count = len(db.get_all_customers())

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📁 DB 파일 크기", f"{file_size:.1f} KB")
            with col2:
                st.metric("🏢 등록된 거래처", f"{customer_count}개")
            with col3:
                st.metric("🕐 최종 수정", file_time.strftime("%Y-%m-%d %H:%M"))

            st.success(f"✅ 데이터베이스 연결 정상: `{db_path}`")

        except Exception as e:
            st.warning(f"⚠️ DB 조회 중 오류: {str(e)}")
    else:
        st.error(f"❌ 데이터베이스가 존재하지 않습니다: `{db_path}`")
        st.info("💡 scripts/migrate_excel_to_db.py를 실행하여 마이그레이션하세요.")

    st.divider()

    st.markdown(
        '<div class="section-header">디스크 사용량</div>', unsafe_allow_html=True
    )

    def get_folder_size(folder):
        if not os.path.exists(folder):
            return 0
        total = 0
        for entry in os.scandir(folder):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_folder_size(entry.path)
        return total

    col1, col2, col3 = st.columns(3)

    with col1:
        uploads_size = get_folder_size("uploads") / 1024 / 1024
        st.metric("📤 업로드 폴터", f"{uploads_size:.2f} MB")

    with col2:
        processed_size = get_folder_size("processed") / 1024 / 1024
        st.metric("📦 처리 완료 폴터", f"{processed_size:.2f} MB")

    with col3:
        logs_size = get_folder_size("logs") / 1024 / 1024
        st.metric("📝 로그 폴터", f"{logs_size:.2f} MB")

    # 총계
    total_size = uploads_size + processed_size + logs_size
    st.info(f"💾 **총 사용량**: {total_size:.2f} MB")

    st.divider()

    st.markdown('<div class="section-header">시스템 정보</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**📁 디렉토리 상태**")
        dirs_status = {
            "로그 (logs)": Path("logs").exists(),
            "업로드 (uploads)": Path("uploads").exists(),
            "처리완료 (processed)": Path("processed").exists(),
            "데이터베이스 (database)": Path("database").exists(),
        }

        for dir_name, exists in dirs_status.items():
            status_icon = "✅" if exists else "❌"
            st.write(f"{status_icon} {dir_name}")

    with col2:
        st.markdown("**ℹ️ 앱 정보**")
        st.write("📊 버전: v3.0.0")
        st.write("🐍 Python: 3.11")
        st.write("🌐 Streamlit: 1.51.0")


# =============================================================================
# 탭 2: 파일 관리
# =============================================================================

with tab2:
    st.markdown(
        '<div class="section-header">저장된 전표 파일</div>', unsafe_allow_html=True
    )

    processed_files = (
        sorted(os.listdir("processed"), reverse=True)
        if os.path.exists("processed")
        else []
    )

    if processed_files:
        # 날짜별 그룹핑
        files_by_date = {}
        for filename in processed_files:
            try:
                date_part = filename.split("_")[1].replace(".xls", "")
                if date_part not in files_by_date:
                    files_by_date[date_part] = []
                files_by_date[date_part].append(filename)
            except:
                continue

        # 통계
        total_files = len(processed_files)
        sales_files = len([f for f in processed_files if f.startswith("매출_")])
        purchase_files = len([f for f in processed_files if f.startswith("매입_")])

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📦 총 파일 수", f"{total_files}개")
        with col2:
            st.metric("💰 매출 파일", f"{sales_files}개")
        with col3:
            st.metric("🛒 매입 파일", f"{purchase_files}개")

        st.divider()

        # 파일 목록
        for date, files in sorted(files_by_date.items(), reverse=True):
            with st.expander(f"📅 {date} ({len(files)}개 파일)", expanded=False):
                for filename in files:
                    filepath = os.path.join("processed", filename)
                    file_size = os.path.getsize(filepath) / 1024
                    file_time = datetime.fromtimestamp(os.path.getmtime(filepath))

                    col1, col2 = st.columns([4, 1])

                    with col1:
                        file_type = "💰 매출" if "매출" in filename else "🛒 매입"
                        st.write(f"**{file_type}**: {filename}")
                        st.caption(
                            f"{file_size:.1f} KB | {file_time.strftime('%Y-%m-%d %H:%M:%S')}"
                        )

                    with col2:
                        with open(filepath, "rb") as f:
                            st.download_button(
                                label="⬇️ 다운로드",
                                data=f.read(),
                                file_name=filename,
                                mime="application/vnd.ms-excel",
                                key=f"dl_{filename}_{date}",
                            )
    else:
        st.info("📂 저장된 파일이 없습니다.")

    st.divider()

    # 일괄 다운로드
    st.markdown(
        '<div class="section-header">일괄 다운로드</div>', unsafe_allow_html=True
    )

    if processed_files:
        import zipfile
        import io

        # 최근 7일 파일 압축
        recent_files = processed_files[:20]  # 최근 20개

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for filename in recent_files:
                filepath = os.path.join("processed", filename)
                zip_file.write(filepath, filename)

        zip_buffer.seek(0)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label=f"📦 최근 {len(recent_files)}개 파일 일괄 다운로드",
                data=zip_buffer,
                file_name=f"전표파일_일괄_{datetime.now().strftime('%Y%m%d')}.zip",
                mime="application/zip",
                use_container_width=True,
            )
    else:
        st.button(
            "📦 일괄 다운로드",
            disabled=True,
            use_container_width=True,
            help="파일이 없습니다",
        )


# =============================================================================
# 탭 3: 발주내역 파일 (2026-06-03 hoyeon.han: 신규)
# =============================================================================

with tab3:
    st.markdown(
        '<div class="section-header">서버에 저장된 발주내역 파일</div>',
        unsafe_allow_html=True,
    )

    from order_file_store import OrderFileStore

    order_store = OrderFileStore()
    order_stats = order_store.get_stats()

    if order_stats.get("exists"):
        st.success(
            f"📄 현재 저장된 발주내역: **{order_stats['original_name']}**"
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🕐 업로드 시각", order_stats["uploaded_at"].replace("T", " "))
        with col2:
            st.metric("📦 파일 크기", f"{order_stats['size_kb']:.1f} KB")
        with col3:
            st.metric("📋 시트 수", f"{order_stats['sheet_count']}개")

        # 시트 목록 (추천 시트는 ⭐ 표시)
        sheet_names = order_stats.get("sheet_names", [])
        if sheet_names:
            with st.expander(f"📋 시트 목록 ({len(sheet_names)}개)", expanded=False):
                for s in sheet_names:
                    mark = "⭐ " if s == order_stats.get("recommended_sheet") else "• "
                    st.write(f"{mark}{s}")

        st.divider()

        col_dl, col_del = st.columns(2)
        with col_dl:
            # .xlsm 정확한 MIME 타입 사용
            st.download_button(
                label="⬇️ 발주내역 파일 다운로드",
                data=order_store.get_file_bytes(),
                file_name=order_stats["original_name"],
                mime="application/vnd.ms-excel.sheet.macroEnabled.12",
                use_container_width=True,
                key="download_order_file",
            )
        with col_del:
            # 2026-06-03 hoyeon.han: 실수 방지를 위해 확인 체크박스 후 삭제 활성화
            confirm_delete = st.checkbox("삭제 확인", key="confirm_delete_order_file")
            if st.button(
                "🗑️ 저장된 발주내역 삭제",
                type="secondary",
                disabled=not confirm_delete,
                use_container_width=True,
                key="delete_order_file",
            ):
                success, message = order_store.delete()
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)
    else:
        st.info(
            "📂 저장된 발주내역 파일이 없습니다. "
            "전표 생성 페이지에서 발주내역 파일을 업로드하면 여기에 표시됩니다."
        )


# =============================================================================
# 탭 4: 로그 뷰어
# =============================================================================

with tab4:
    st.markdown(
        '<div class="section-header">애플리케이션 로그</div>', unsafe_allow_html=True
    )

    log_file = "logs/app.log"

    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)

        # 로그 라인 수 선택
        line_options = [50, 100, 200, 500, "전체"]
        selected_lines = st.selectbox(
            "표시할 로그 라인 수",
            options=line_options,
            index=0,
        )

        if selected_lines == "전체":
            display_lines = all_lines
        else:
            display_lines = all_lines[-selected_lines:]

        # 로그 필터
        filter_text = st.text_input(
            "🔍 로그 필터",
            placeholder="검색어를 입력하세요 (예: ERROR, WARNING, 특정 파일명)",
        )

        if filter_text:
            display_lines = [line for line in display_lines if filter_text in line]

        # 로그 표시
        st.text_area(
            f"로그 내용 (총 {len(display_lines)}줄 / 전체 {total_lines}줄)",
            value="".join(display_lines),
            height=400,
            label_visibility="collapsed",
        )

        st.divider()

        # 다운로드 버튼들
        col1, col2 = st.columns(2)

        with col1:
            with open(log_file, "rb") as f:
                st.download_button(
                    label="📥 전체 로그 다운로드",
                    data=f.read(),
                    file_name=f"app_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
                    mime="text/plain",
                    use_container_width=True,
                )

        with col2:
            # JSON 로그 다운로드 (있는 경우)
            json_logs = [
                f
                for f in os.listdir("logs")
                if f.startswith("app_") and f.endswith(".json")
            ]
            if json_logs:
                latest_json = sorted(json_logs)[-1]
                json_path = os.path.join("logs", latest_json)
                with open(json_path, "rb") as f:
                    st.download_button(
                        label=f"📊 JSON 로그 다운로드",
                        data=f.read(),
                        file_name=latest_json,
                        mime="application/json",
                        use_container_width=True,
                    )
            else:
                st.button(
                    "📊 JSON 로그 없음",
                    disabled=True,
                    use_container_width=True,
                )

    else:
        st.info("📝 로그 파일이 없습니다.")
        st.caption("애플리케이션을 사용하면 자동으로 생성됩니다.")


# =============================================================================
# 탭 5: 데이터 정리
# =============================================================================

with tab5:
    st.markdown('<div class="section-header">데이터 정리</div>', unsafe_allow_html=True)

    st.warning(
        "⚠️ **주의**: 아래 작업은 되돌릴 수 없습니다. 신중하게 선택하세요.",
        icon="⚠️",
    )

    st.divider()

    # 업로드 파일 삭제
    st.markdown("#### 📤 업로드 파일 삭제")
    st.caption("uploads 폴더의 모든 임시 파일을 삭제합니다.")

    upload_files = os.listdir("uploads") if os.path.exists("uploads") else []
    upload_count = len(upload_files)

    col1, col2 = st.columns([3, 1])
    with col1:
        st.write(f"현재 파일 수: **{upload_count}개**")
    with col2:
        if st.button(
            "🗑️ 삭제",
            type="secondary",
            key="del_uploads",
            disabled=upload_count == 0,
        ):
            deleted_count = 0
            for file in upload_files:
                try:
                    os.remove(os.path.join("uploads", file))
                    deleted_count += 1
                except FileNotFoundError:
                    pass
            st.success(f"✅ {deleted_count}개 파일 삭제 완료!")
            st.rerun()

    st.divider()

    # 처리된 파일 삭제
    st.markdown("#### 📦 처리된 파일 삭제")
    st.caption("processed 폴더의 모든 전표 파일을 삭제합니다.")

    processed_count = len(processed_files)

    col1, col2 = st.columns([3, 1])
    with col1:
        st.write(f"현재 파일 수: **{processed_count}개**")
    with col2:
        if st.button(
            "🗑️ 삭제",
            type="secondary",
            key="del_processed",
            disabled=processed_count == 0,
        ):
            deleted_count = 0
            for file in processed_files:
                try:
                    os.remove(os.path.join("processed", file))
                    deleted_count += 1
                except FileNotFoundError:
                    pass
            st.success(f"✅ {deleted_count}개 파일 삭제 완료!")
            st.rerun()

    st.divider()

    # 로그 파일 삭제
    st.markdown("#### 📝 로그 파일 삭제")
    st.caption("logs 폴더의 모든 로그 파일을 삭제합니다.")

    log_files = os.listdir("logs") if os.path.exists("logs") else []
    log_count = len(log_files)

    col1, col2 = st.columns([3, 1])
    with col1:
        st.write(f"현재 파일 수: **{log_count}개**")
    with col2:
        if st.button(
            "🗑️ 삭제",
            type="secondary",
            key="del_logs",
            disabled=log_count == 0,
        ):
            deleted_count = 0
            for file in log_files:
                try:
                    os.remove(os.path.join("logs", file))
                    deleted_count += 1
                except FileNotFoundError:
                    pass
            st.success(f"✅ {deleted_count}개 파일 삭제 완료!")
            st.rerun()

    st.divider()

    # 전체 초기화
    st.markdown("#### 🚨 전체 초기화")
    st.caption("모든 데이터(업로드, 처리, 로그)를 삭제합니다.")

    with st.expander("⚠️ 전체 초기화 실행 (주의!)", expanded=False):
        st.error("이 작업은 모든 데이터를 영구적으로 삭제합니다!")

        confirm_text = st.text_input(
            '확인을 위해 "초기화"를 입력하세요',
            placeholder="초기화",
        )

        if st.button(
            "🚨 전체 초기화 실행",
            type="primary",
            disabled=confirm_text != "초기화",
        ):
            total_deleted = 0

            # uploads 삭제
            if os.path.exists("uploads"):
                for file in os.listdir("uploads"):
                    try:
                        os.remove(os.path.join("uploads", file))
                        total_deleted += 1
                    except:
                        pass

            # processed 삭제
            if os.path.exists("processed"):
                for file in os.listdir("processed"):
                    try:
                        os.remove(os.path.join("processed", file))
                        total_deleted += 1
                    except:
                        pass

            # logs 삭제
            if os.path.exists("logs"):
                for file in os.listdir("logs"):
                    try:
                        os.remove(os.path.join("logs", file))
                        total_deleted += 1
                    except:
                        pass

            st.success(f"✅ 총 {total_deleted}개 파일 삭제 완료!")
            st.balloons()
            st.rerun()


# =============================================================================
# 푸터
# =============================================================================

st.divider()
st.caption("© 2025 솔루미랩 | 시스템 관리 페이지")
