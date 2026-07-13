"""
UI 공통 컴포넌트 모듈
2025-12-22 hoyeon.han: Quick Win #4 - 사이드바 로고 및 공통 컴포넌트

재사용 가능한 UI 컴포넌트를 제공합니다.
"""

import streamlit as st
from datetime import datetime
import os


def _logo_data_uri():
    """현재 테마에 맞는 로고 PNG를 data URI로 반환 (라이트=검정 logo_dark / 다크=흰색 logo_white).
    2026-07-13 hoyeon.han: 신규 - 커스텀 <a> 사이드바 로고와 홈 중앙 로고에서 공용.
    """
    import base64

    assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
    try:
        is_dark = st.context.theme.type == "dark"
    except Exception:
        is_dark = False
    fname = "logo_white.png" if is_dark else "logo_dark.png"
    try:
        with open(os.path.join(assets_dir, fname), "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except Exception:
        return None


def _home_url():
    """앱 홈(기본 페이지) URL — 같은 탭 이동용.
    2026-07-13 hoyeon.han: 루트 서빙 기준(scheme://host/). baseUrlPath 사용 시 이 부분 조정 필요.
    """
    try:
        from urllib.parse import urlparse

        u = urlparse(st.context.url)
        return f"{u.scheme}://{u.netloc}/"
    except Exception:
        return "/"


def render_sidebar_logo():
    """사이드바 최상단 로고 — 클릭 시 같은 탭에서 홈으로 이동.

    2026-07-13 hoyeon.han: 디자인 개선 - st.logo(link=)는 새 탭(target=_blank)이라,
      커스텀 <a target="_self"> + data URI 이미지로 '같은 탭 홈 이동'을 구현. 테마별 공식
      PNG(라이트=검정/다크=흰색). st.navigation(position="hidden") 커스텀 네비 전제
      — 자동 네비가 없으므로 이 마크다운이 사이드바 최상단에 위치한다.
    """
    uri = _logo_data_uri()
    with st.sidebar:
        if uri:
            st.markdown(
                f'<a href="{_home_url()}" target="_self" title="홈으로" '
                f'style="display:block;text-align:center;padding:12px 0 6px;">'
                f'<img src="{uri}" alt="SOLLUME ESTHÉ" style="width:78%;max-width:190px;"/></a>',
                unsafe_allow_html=True,
            )


def render_home_logo():
    """홈(기본 페이지) 중앙 큰 로고 — 심플 랜딩(로고만 가운데).
    2026-07-13 hoyeon.han: 디자인 개선 - 기존 환영/기능카드/사용법/시스템정보 랜딩을 대체.
    """
    uri = _logo_data_uri()
    if uri:
        st.markdown(
            f'<div style="display:flex;justify-content:center;align-items:center;min-height:62vh;">'
            f'<img src="{uri}" alt="SOLLUME ESTHÉ" style="width:55%;max-width:440px;"/></div>',
            unsafe_allow_html=True,
        )
    else:
        st.title("SollumeLab 회계 시스템")


def render_sidebar_user_simple():
    """사이드바 간소화 사용자 블록 — 아바타 + 이름/역할 + 로그아웃.
    2026-07-10 hoyeon.han: 디자인 개선 - 기존 auth.show_user_info_sidebar()의
      제목/로그인시각/세션만료를 덜어낸 심플 버전. 세션·로그아웃 로직은 auth 재사용.
    """
    import auth  # 로컬 import (세션 기반)

    with st.sidebar:
        if not auth.is_session_valid():
            return
        user = auth.get_current_user() or {}
        name = user.get("full_name") or user.get("username") or "사용자"
        role = "관리자" if user.get("is_admin") else "사용자"
        initial = name.strip()[0] if name.strip() else "·"

        st.divider()
        st.markdown(
            f'<div class="sl-user"><div class="sl-avatar">{initial}</div>'
            f'<div><div class="sl-uname">{name}</div>'
            f'<div class="sl-urole">{role}</div></div></div>',
            unsafe_allow_html=True,
        )
        if st.button("⏻ 로그아웃", use_container_width=True, key="sidebar_logout_btn"):
            auth.logout()
            st.rerun()


def render_sidebar_user_info():
    """
    사이드바 사용자 정보 표시
    """
    with st.sidebar:
        # 사용자 정보 (인증 시스템 연동)
        if "user" in st.session_state:
            user = st.session_state.user

            st.markdown(
                f"""
            <div style="
                background: #F5F7FA;
                border-radius: 8px;
                padding: 1rem;
                margin: 1rem 0;
            ">
                <div style="font-weight: bold; margin-bottom: 0.5rem; color: #2C3E50;">
                    👤 {user.get("name", "사용자")}
                </div>
                <div style="font-size: 0.875rem; color: #718096;">
                    {user.get("department", "")} {" | " if user.get("department") else ""} {user.get("role", "")}
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

            st.divider()


def render_sidebar_quick_actions():
    """
    사이드바 퀵 액션 버튼
    """
    with st.sidebar:
        st.markdown("### ⚡ 빠른 작업")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("📝 신규\n전표", use_container_width=True, key="quick_new"):
                st.switch_page("pages/1_📝_전표생성.py")

        with col2:
            if st.button(
                "📊 발주\n요약", use_container_width=True, key="quick_summary"
            ):
                st.switch_page("pages/2_📊_발주내역요약.py")

        st.divider()


def get_recent_files(folder="processed", limit=5):
    """
    최근 생성된 파일 목록 조회

    Args:
        folder: 폴터 경로
        limit: 조회할 파일 수

    Returns:
        파일 정보 리스트 [{"name": ..., "date": ..., "type": ..., "path": ...}]
    """
    if not os.path.exists(folder):
        return []

    files = []
    for filename in os.listdir(folder):
        if filename.endswith(".xls"):
            filepath = os.path.join(folder, filename)
            try:
                stat = os.stat(filepath)
                # 날짜 추출 (매출_2025-01-15.xls -> 2025-01-15)
                date_part = (
                    filename.split("_")[1].replace(".xls", "")
                    if "_" in filename
                    else ""
                )
                file_type = (
                    "매출"
                    if "매출" in filename
                    else "매입"
                    if "매입" in filename
                    else "기타"
                )

                files.append(
                    {
                        "name": filename,
                        "date": date_part,
                        "type": file_type,
                        "path": filepath,
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                    }
                )
            except:
                continue

    # 수정 시간 기준 정렬 (최신순)
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files[:limit]


def render_sidebar_recent_files():
    """
    사이드바 최근 파일 목록 표시
    2025-04-13 hoyeon.han: 신규 추가
    """
    with st.sidebar:
        st.markdown("### 📁 최근 파일")

        recent_files = get_recent_files("processed", limit=5)

        if recent_files:
            for f in recent_files:
                file_icon = "💰" if f["type"] == "매출" else "🛒"
                st.caption(f"{file_icon} {f['date']} - {f['type']}")
        else:
            st.caption("📂 파일 없음")

        # 전체 보기 버튼
        if st.button(
            "📂 전체 파일 보기", use_container_width=True, key="sidebar_all_files"
        ):
            st.switch_page("pages/6_⚙️_시스템관리.py")

        st.divider()


def render_sidebar_system_status():
    """
    사이드바 시스템 상태 표시
    """
    with st.sidebar:
        st.markdown("### 📡 시스템 상태")

        # DB 연결 체크
        db_path = "database/customer_master.db"
        if os.path.exists(db_path):
            st.success("✅ DB 정상", icon="✅")
        else:
            st.error("❌ DB 오류", icon="❌")

        # 파일 개수 (간단 버전)
        try:
            processed_dir = "processed"
            if os.path.exists(processed_dir):
                file_count = len(
                    [f for f in os.listdir(processed_dir) if f.endswith(".xls")]
                )
                st.info(f"📦 전표 파일: {file_count}개", icon="📦")
            else:
                st.info("📦 전표 파일: 0개", icon="📦")
        except:
            pass

        st.divider()

        # 로그 다운로드 버튼 (2025-04-13 hoyeon.han: 신규 추가)
        if os.path.exists("logs/app.log"):
            with open("logs/app.log", "rb") as f:
                st.download_button(
                    label="🐛 로그 다운로드",
                    data=f.read(),
                    file_name=f"app_log_{datetime.now().strftime('%Y%m%d')}.log",
                    mime="text/plain",
                    use_container_width=True,
                )
        else:
            st.button(
                "🐛 로그 없음",
                disabled=True,
                use_container_width=True,
            )

        st.divider()

        # 버전 정보
        st.caption("v3.0.2 | 2025-04-13")


def render_custom_sidebar():
    """
    통합 사이드바 렌더링
    모든 페이지에서 이 함수를 호출하면 됩니다.

    사용 예시:
    ```python
    from Src.ui_components import render_custom_sidebar
    render_custom_sidebar()
    ```
    """
    render_sidebar_logo()
    # 2026-07-09 hoyeon.han: 디자인 개선 - 사이드바 간결화
    #   빠른작업/최근파일/시스템상태는 pages/6(시스템관리)에 더 나은 버전이 있어 사이드바에서 제거,
    #   화면 폭 설정은 pages/6 상단 popover로 이전.
    #   죽은 사용자정보 카드(render_sidebar_user_info: session_state["user"]를 읽으나 실제 저장은 user_info)
    #   대신 실제 세션을 읽고 로그아웃까지 있는 auth.show_user_info_sidebar()로 교체(Home/2/3과 통일).
    # render_sidebar_user_info()
    # render_sidebar_quick_actions()
    # render_sidebar_recent_files()  # 2025-04-13 hoyeon.han: 최근 파일 위젯 추가
    # render_sidebar_system_status()
    # from ui_theme import render_width_setting
    # render_width_setting()
    # 2026-07-10 hoyeon.han: 디자인 개선 - 사용자 블록을 심플 버전(아바타+이름/역할+로그아웃)으로 교체
    # import auth
    # auth.show_user_info_sidebar()
    render_sidebar_user_simple()


def card(title, content, status="info"):
    """
    재사용 가능한 카드 컴포넌트

    Args:
        title: 카드 제목
        content: 카드 내용 (HTML 또는 텍스트)
        status: 카드 상태 ("info", "success", "warning", "error")

    사용 예시:
    ```python
    from Src.ui_components import card

    card(
        title="처리 완료",
        content="매출 152건, 매입 89건이 처리되었습니다.",
        status="success"
    )
    ```
    """
    status_colors = {
        "info": "#0066FF",
        "success": "#4CAF50",
        "warning": "#FF9800",
        "error": "#F44336",
    }

    color = status_colors.get(status, "#0066FF")

    st.markdown(
        f"""
    <div style="
        background: white;
        border-left: 4px solid {color};
        border-radius: 8px;
        padding: 1.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.08);
        margin: 1rem 0;
    ">
        <h3 style="margin: 0 0 0.5rem 0; color: {color}; font-size: 1.25rem;">
            {title}
        </h3>
        <div style="color: #2C3E50;">
            {content}
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def alert(message, alert_type="info", icon=None):
    """
    알림 메시지 컴포넌트

    Args:
        message: 알림 메시지
        alert_type: 알림 타입 ("info", "success", "warning", "error")
        icon: 커스텀 아이콘 (선택)

    사용 예시:
    ```python
    from Src.ui_components import alert

    alert("파일이 성공적으로 업로드되었습니다.", "success", "✅")
    ```
    """
    alert_config = {
        "info": {"bg": "#D1ECF1", "border": "#17A2B8", "text": "#0C5460", "icon": "ℹ️"},
        "success": {
            "bg": "#D4EDDA",
            "border": "#28A745",
            "text": "#155724",
            "icon": "✅",
        },
        "warning": {
            "bg": "#FFF3CD",
            "border": "#FFC107",
            "text": "#856404",
            "icon": "⚠️",
        },
        "error": {
            "bg": "#F8D7DA",
            "border": "#DC3545",
            "text": "#721C24",
            "icon": "❌",
        },
    }

    config = alert_config.get(alert_type, alert_config["info"])
    display_icon = icon if icon else config["icon"]

    st.markdown(
        f"""
    <div style="
        background-color: {config["bg"]};
        border-left: 4px solid {config["border"]};
        border-radius: 4px;
        padding: 1rem;
        margin: 1rem 0;
        color: {config["text"]};
    ">
        <span style="font-size: 1.25rem; margin-right: 0.5rem;">{display_icon}</span>
        <span>{message}</span>
    </div>
    """,
        unsafe_allow_html=True,
    )


def metric_card(label, value, delta=None, delta_color="normal", help_text=None):
    """
    커스텀 메트릭 카드 (st.metric 확장 버전)

    Args:
        label: 라벨
        value: 값
        delta: 변화량 (선택)
        delta_color: 변화량 색상 ("normal", "inverse", "off")
        help_text: 도움말 (선택)
    """
    # Streamlit 기본 st.metric 사용 (추후 커스터마이징 가능)
    st.metric(
        label=label, value=value, delta=delta, delta_color=delta_color, help=help_text
    )


def workflow_steps(steps, current_step):
    """
    워크플로우 스텝 표시

    Args:
        steps: 단계 리스트 [{"number": 1, "icon": "📤", "label": "파일 선택"}, ...]
        current_step: 현재 단계 번호

    사용 예시:
    ```python
    from Src.ui_components import workflow_steps

    steps = [
        {"number": 1, "icon": "📤", "label": "파일 선택"},
        {"number": 2, "icon": "🔍", "label": "데이터 검증"},
        {"number": 3, "icon": "⚙️", "label": "전표 생성"},
        {"number": 4, "icon": "✅", "label": "결과 확인"}
    ]

    workflow_steps(steps, current_step=2)
    ```
    """
    cols = st.columns(len(steps))

    for i, col in enumerate(cols):
        with col:
            step = steps[i]
            is_active = step["number"] == current_step
            is_completed = step["number"] < current_step

            # 색상 결정
            if is_completed:
                color = "#4CAF50"  # 초록
            elif is_active:
                color = "#0066FF"  # 파란
            else:
                color = "#E0E0E0"  # 회색

            st.markdown(
                f"""
            <div style="text-align: center;">
                <div style="
                    width: 60px;
                    height: 60px;
                    line-height: 60px;
                    border-radius: 50%;
                    background: {color};
                    color: white;
                    font-size: 2rem;
                    margin: 0 auto 0.5rem;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                ">
                    {step["icon"]}
                </div>
                <div style="
                    font-weight: {"bold" if is_active else "normal"};
                    color: {color if (is_active or is_completed) else "#718096"};
                    font-size: 0.875rem;
                ">
                    {step["label"]}
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )


# 2026-06-03 hoyeon.han: 발주내역 파일 서버 저장/재사용 공통 컴포넌트
def render_order_file_selector(key_prefix, sheet_select=False):
    """발주내역 파일 소스 선택 공통 컴포넌트

    '서버에 저장된 파일 사용' 또는 '새 파일 업로드'를 선택하는 UI를 렌더링한다.
    새 파일을 업로드하면 즉시 서버에 저장(덮어쓰기=1버전 유지)하고, 어느 경우든
    처리 함수에 그대로 넘길 파일 경로를 반환한다.

    Args:
        key_prefix: 페이지별 위젯 key 충돌 방지용 접두사 (예: "period", "daily")
        sheet_select: True면 시트 선택 드롭다운을 표시한다
                      (sheet_name 인자를 받는 처리 함수용).

    Returns:
        준비 완료 시 dict:
          {"file_path": str,           # 처리 함수에 넘길 경로 (order_data/current.xlsm)
           "sheet_name": str | None,   # sheet_select=True 일 때만 값
           "source": "stored" | "uploaded",
           "display_name": str}        # 원본 파일명 (UI/결과 메타 표기용)
        파일 미선택/미저장 시 None
    """
    # 지역 import (ui_components 가 무거운 의존성을 전역으로 끌어오지 않도록)
    import pandas as pd
    from order_file_store import OrderFileStore

    store = OrderFileStore()
    has_stored = store.exists()

    # 소스 선택: 저장된 파일이 없으면 '새 파일 업로드'만 노출
    options = (
        ["서버에 저장된 파일 사용", "새 파일 업로드"]
        if has_stored
        else ["새 파일 업로드"]
    )
    mode = st.radio(
        "발주내역 파일 소스",
        options=options,
        horizontal=True,
        key=f"{key_prefix}_file_source_mode",
    )

    # ----------------------------------------------------------------------
    # (A) 서버에 저장된 파일 사용
    # ----------------------------------------------------------------------
    if mode == "서버에 저장된 파일 사용":
        meta = store.get_metadata() or {}
        original_name = meta.get("original_name", "current.xlsm")
        uploaded_at = meta.get("uploaded_at", "")
        st.success(
            f"📎 저장된 발주내역 사용: **{original_name}**"
            + (f"  (업로드: {uploaded_at})" if uploaded_at else "")
        )

        sheet_name = None
        if sheet_select:
            sheet_names = meta.get("sheet_names", [])
            if sheet_names:
                recommended = meta.get("recommended_sheet")
                default_index = (
                    sheet_names.index(recommended)
                    if recommended in sheet_names
                    else 0
                )
                sheet_name = st.selectbox(
                    "📋 처리할 시트 선택",
                    options=sheet_names,
                    index=default_index,
                    key=f"{key_prefix}_stored_sheet_selector",
                )
            else:
                st.warning("저장된 파일의 시트 목록을 읽을 수 없습니다.")

        return {
            "file_path": store.get_path(),
            "sheet_name": sheet_name,
            "source": "stored",
            "display_name": original_name,
        }

    # ----------------------------------------------------------------------
    # (B) 새 파일 업로드 → 즉시 서버 저장 (덮어쓰기 = 1버전 유지)
    # ----------------------------------------------------------------------
    uploaded_file = st.file_uploader(
        "발주내역 Excel 파일을 선택하세요 (.xlsm/.xlsx)",
        type=["xlsm", "xlsx"],
        key=f"{key_prefix}_uploader",
    )

    if uploaded_file is None:
        return None

    # 같은 파일이 재실행마다 중복 저장되지 않도록 시그니처로 가드
    sig = (uploaded_file.name, uploaded_file.size)
    saved_sig_key = f"{key_prefix}_saved_sig"
    if st.session_state.get(saved_sig_key) != sig:
        success, message = store.save(uploaded_file.getvalue(), uploaded_file.name)
        if not success:
            st.error(message)
            return None
        st.session_state[saved_sig_key] = sig

    st.success(
        f"✅ 파일: {uploaded_file.name} "
        f"({uploaded_file.size / 1024 / 1024:.2f} MB) — 서버에 저장되어 다음에 재사용할 수 있습니다."
    )

    sheet_name = None
    if sheet_select:
        try:
            excel_file = pd.ExcelFile(uploaded_file)
            sheet_names = excel_file.sheet_names

            default_index = 0
            current_year = datetime.now().year
            for i, sheet in enumerate(sheet_names):
                if "발주내역" in sheet and str(current_year) in sheet:
                    default_index = i
                    break

            sheet_name = st.selectbox(
                "📋 처리할 시트 선택",
                options=sheet_names,
                index=default_index,
                key=f"{key_prefix}_upload_sheet_selector",
                help='"발주내역" + 현재 연도 포함 시트를 우선 선택합니다.',
            )

            with st.expander("🔍 시트 미리보기 (상위 5행)"):
                try:
                    preview_df = pd.read_excel(
                        uploaded_file, sheet_name=sheet_name, header=3, nrows=5
                    )
                    st.dataframe(preview_df, use_container_width=True)
                except Exception as e:
                    st.warning(f"시트 미리보기를 불러올 수 없습니다: {str(e)}")
        except Exception as e:
            st.error(f"시트 목록을 읽을 수 없습니다: {str(e)}")
            return None

    return {
        "file_path": store.get_path(),
        "sheet_name": sheet_name,
        "source": "uploaded",
        "display_name": uploaded_file.name,
    }
