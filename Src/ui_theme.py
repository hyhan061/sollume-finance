"""
UI 테마/디자인 시스템 모듈
2026-07-09 hoyeon.han: 디자인 개선 신규 생성
  - 밝은 핀테크(Stripe 계열) 톤 + Pretendard 폰트 + 콘텐츠 폭 사용자 설정
  - 참고: .claude/plans (디자인 개선 계획), .claude/design/stripe_DESIGN.md

제공 기능 (Streamlit 호출 포함, 순수 함수 아님):
  - inject_global_css()   : 전역 CSS 1회 주입 (폰트/색/타이포/컴포넌트/콘텐츠 폭)
  - render_page_header()  : 페이지 상단 통일 헤더
  - render_width_setting(): 사이드바 콘텐츠 폭 설정 셀렉터
  - get_content_width()   : 현재 선택된 본문 최대 폭(px, 0이면 캡 해제)

디자인 토큰과 폭 프리셋은 이 파일의 상수(TOKENS, WIDTH_PRESETS)가 단일 소스이다.
발주내역 양식/비즈니스 로직과 무관한 순수 프레젠테이션 레이어.
"""

import json
import os

import streamlit as st

# ---------------------------------------------------------------------------
# 디자인 토큰 (단일 소스) — Stripe 계열 밝은 핀테크
# ---------------------------------------------------------------------------
TOKENS = {
    "primary": "#533afd",       # 인디고 (버튼/링크/포커스/포인트)
    "primary_deep": "#4434d4",  # hover/press
    "primary_soft": "#eff0ff",  # 연한 강조 배경
    "canvas": "#ffffff",
    "canvas_soft": "#f6f9fc",   # 카드/보조배경/사이드바
    "ink": "#0d253d",           # 본문 텍스트 (딥네이비)
    "ink_mute": "#64748d",      # 라벨/캡션
    "hairline": "#e3e8ee",      # 테두리/구분선
    "success": "#12805c",
    "success_bg": "#e7f4ec",
    "warning": "#9a6a00",
    "warning_bg": "#fdf3e2",
    "error": "#cd3d64",
    "error_bg": "#fbe9ef",
    "font": (
        "'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, "
        "'Apple SD Gothic Neo', 'Malgun Gothic', 'Segoe UI', sans-serif"
    ),
}

# ---------------------------------------------------------------------------
# 콘텐츠 폭 프리셋 (사용자 설정) — 값은 본문 최대 폭(px), 0이면 캡 해제(전체 폭)
# ---------------------------------------------------------------------------
WIDTH_PRESETS = {
    "좁게": 960,
    "중간": 1120,
    "넓게": 1320,
    "꽉 참": 0,
}
DEFAULT_WIDTH_LABEL = "중간"

_PREFS_PATH = "config/ui_prefs.json"
_WIDTH_KEY = "ui_content_width"  # session_state 키 (라벨 저장)

# Pretendard 웹폰트 (CDN). 사용자 브라우저가 인터넷 접근 가능할 때 로드되며,
# 실패 시 TOKENS['font']의 시스템 폴백(Apple SD Gothic Neo / Malgun Gothic)으로 렌더된다.
_PRETENDARD_CDN = (
    "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/"
    "dist/web/variable/pretendardvariable-dynamic-subset.min.css"
)


# ---------------------------------------------------------------------------
# 콘텐츠 폭 설정 (저장/조회)
# ---------------------------------------------------------------------------
def _load_prefs():
    """UI 설정 JSON 로드 (없으면 빈 dict)."""
    try:
        with open(_PREFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_width_label(label):
    """선택한 폭 라벨을 JSON에 저장 (재시작 후에도 유지)."""
    try:
        os.makedirs(os.path.dirname(_PREFS_PATH), exist_ok=True)
        prefs = _load_prefs()
        prefs["content_width"] = label
        with open(_PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)
    except Exception:
        # 저장 실패는 치명적이지 않음 (세션 내에서는 정상 동작)
        pass


def get_width_label():
    """현재 폭 라벨. 우선순위: 세션 > 저장값 > 기본."""
    if _WIDTH_KEY in st.session_state:
        label = st.session_state[_WIDTH_KEY]
    else:
        label = _load_prefs().get("content_width", DEFAULT_WIDTH_LABEL)
    return label if label in WIDTH_PRESETS else DEFAULT_WIDTH_LABEL


def get_content_width():
    """현재 본문 최대 폭(px). 0이면 캡 해제(전체 폭)."""
    return WIDTH_PRESETS.get(get_width_label(), WIDTH_PRESETS[DEFAULT_WIDTH_LABEL])


def render_width_setting():
    """콘텐츠 폭 설정 위젯 (호출한 컨테이너에 그대로 렌더).

    2026-07-09 hoyeon.han: 사이드바 전용 → 컨테이너 비의존 위젯으로 변경.
      (시스템관리 pages/6 상단 popover에서 호출) 값 변경 시 세션+JSON 저장,
      inject_global_css()가 이 값을 읽어 본문 최대 폭을 적용한다.
    """
    labels = list(WIDTH_PRESETS.keys())
    kwargs = {}
    # 위젯이 아직 세션에 없을 때만 초기값(저장값) 지정
    if _WIDTH_KEY not in st.session_state:
        kwargs["index"] = labels.index(get_width_label())
    choice = st.radio(
        "본문 최대 폭",
        options=labels,
        key=_WIDTH_KEY,
        horizontal=True,
        help="와이드 모니터에서 본문이 너무 퍼지면 좁게, 표가 많으면 넓게 선택하세요.",
        **kwargs,
    )
    # 저장값과 다르면 JSON 갱신
    if choice != _load_prefs().get("content_width", DEFAULT_WIDTH_LABEL):
        _save_width_label(choice)


# ---------------------------------------------------------------------------
# 전역 CSS 주입
# ---------------------------------------------------------------------------
def _root_vars():
    t = TOKENS
    return (
        ":root{"
        f"--sl-primary:{t['primary']};"
        f"--sl-primary-deep:{t['primary_deep']};"
        f"--sl-primary-soft:{t['primary_soft']};"
        f"--sl-canvas-soft:{t['canvas_soft']};"
        f"--sl-ink:{t['ink']};"
        f"--sl-ink-mute:{t['ink_mute']};"
        f"--sl-line:{t['hairline']};"
        f"--sl-ok:{t['success']};--sl-ok-bg:{t['success_bg']};"
        f"--sl-warn:{t['warning']};--sl-warn-bg:{t['warning_bg']};"
        f"--sl-err:{t['error']};--sl-err-bg:{t['error_bg']};"
        f"--sl-font:{t['font']};"
        "}"
    )


# var(--sl-*) 만 사용하는 정적 CSS (f-string 아님 — 중괄호 이스케이프 불필요)
_CSS_BODY = """
html, body, .stApp, [data-testid="stSidebar"], [data-testid="stMarkdownContainer"],
input, textarea, button, select, [data-baseweb] {
  font-family: var(--sl-font) !important;
}
.stApp { color: var(--sl-ink); }
h1, h2, h3 { color: var(--sl-ink); font-weight: 700; letter-spacing: -0.02em; }
h1 { font-size: 1.55rem; }
h2 { font-size: 1.25rem; }
h3 { font-size: 1.08rem; }

.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 8px; font-weight: 600;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {
  background: var(--sl-primary); border-color: var(--sl-primary);
}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primary"]:hover {
  background: var(--sl-primary-deep); border-color: var(--sl-primary-deep);
}

[data-baseweb="input"], [data-baseweb="select"] > div, .stTextArea textarea,
.stNumberInput div[data-baseweb="input"] { border-radius: 8px; }

/* 2026-07-09 hoyeon.han: 폼 컨트롤 측정폭(measure) - 단독 배치 시 본문 폭 전체로 퍼지지 않게 */
[data-testid="stSelectbox"], [data-testid="stTextInput"],
[data-testid="stDateInput"], [data-testid="stNumberInput"] { max-width: 480px; }
[data-testid="stMultiSelect"] { max-width: 640px; }
.stTextArea textarea { max-width: 720px; }
/* st.columns 안에서는 컬럼 비율이 폭을 지배하도록 캡 해제(의도된 레이아웃 존중) */
[data-testid="stHorizontalBlock"] [data-testid="stSelectbox"],
[data-testid="stHorizontalBlock"] [data-testid="stTextInput"],
[data-testid="stHorizontalBlock"] [data-testid="stDateInput"],
[data-testid="stHorizontalBlock"] [data-testid="stNumberInput"],
[data-testid="stHorizontalBlock"] [data-testid="stMultiSelect"] { max-width: none; }

[data-testid="stMetric"] {
  background: var(--sl-canvas-soft);
  border: 1px solid var(--sl-line);
  border-radius: 12px;
  padding: 14px 16px;
  overflow: visible;
}
/* 2026-07-09 hoyeon.han: 긴 값('YYYY-MM-DD ~ YYYY-MM-DD' 등) 잘림('…') 방지 - 폰트 축소 + 공백 줄바꿈 허용 */
[data-testid="stMetricValue"] {
  font-size: 1.5rem;
  line-height: 1.25;
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}
[data-testid="stMetricValue"] > * { white-space: inherit; overflow: visible; }
[data-testid="stMetricLabel"] { color: var(--sl-ink-mute); }

[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }

[data-testid="stSidebar"] {
  background: var(--sl-canvas-soft);
  border-right: 1px solid var(--sl-line);
}

[data-baseweb="tab-list"] { gap: 4px; overflow-x: auto; }

[data-testid="stExpander"] { border-radius: 8px; }
[data-testid="stExpander"] > details { border-radius: 8px; border-color: var(--sl-line); }

.sl-page-header { margin: 0 0 0.25rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--sl-line); }
.sl-ph-title { font-size: 1.55rem; font-weight: 700; color: var(--sl-ink); letter-spacing: -0.02em; line-height: 1.2; }
.sl-ph-sub { font-size: 0.9rem; color: var(--sl-ink-mute); margin-top: 0.3rem; }

.main-header { font-size: 1.55rem; font-weight: 700; color: var(--sl-ink); margin-bottom: 0.5rem; letter-spacing: -0.02em; }
.section-header { font-size: 1.2rem; font-weight: 700; color: var(--sl-ink); margin: 1.5rem 0 0.75rem; border-bottom: 2px solid var(--sl-primary); padding-bottom: 0.4rem; }
.section-box { padding: 1.25rem; background: var(--sl-canvas-soft); border: 1px solid var(--sl-line); border-radius: 12px; margin: 1rem 0; }
.card-box { padding: 1.25rem; background: var(--sl-canvas-soft); border: 1px solid var(--sl-line); border-left: 4px solid var(--sl-primary); border-radius: 8px; margin: 0.75rem 0; }
.section-title { font-size: 1.1rem; font-weight: 700; color: var(--sl-ink); margin-bottom: 0.4rem; }
.section-desc { color: var(--sl-ink-mute); font-size: 0.92rem; line-height: 1.6; }
.feature-list { margin-left: 1.2rem; color: var(--sl-ink-mute); }
.success-box { padding: 1rem; background: var(--sl-ok-bg); border-left: 4px solid var(--sl-ok); border-radius: 8px; margin: 1rem 0; color: var(--sl-ok); }
.info-box { padding: 1rem; background: var(--sl-primary-soft); border-left: 4px solid var(--sl-primary); border-radius: 8px; margin: 1rem 0; color: var(--sl-primary-deep); }
.warning-box { padding: 1rem; background: var(--sl-warn-bg); border-left: 4px solid var(--sl-warn); border-radius: 8px; margin: 1rem 0; color: var(--sl-warn); }
.error-box { padding: 1rem; background: var(--sl-err-bg); border-left: 4px solid var(--sl-err); border-radius: 8px; margin: 1rem 0; color: var(--sl-err); }
"""


def inject_global_css():
    """전역 CSS를 1회 주입한다. 각 페이지 상단(사이드바 렌더 후)에서 호출한다."""
    width = get_content_width()
    if width and width > 0:
        width_css = (
            ".block-container{"
            f"max-width:{width}px;"
            "padding-top:3rem;padding-left:2rem;padding-right:2rem;"
            "margin-left:auto;margin-right:auto;}"
        )
    else:
        # '꽉 참' — 폭 캡 해제 (Streamlit 기본 wide 동작)
        width_css = ".block-container{padding-top:3rem;padding-left:2rem;padding-right:2rem;}"

    css = (
        "<style>"
        f"@import url('{_PRETENDARD_CDN}');"
        + _root_vars()
        + _CSS_BODY
        + width_css
        + "</style>"
    )
    st.markdown(css, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 페이지 헤더 (통일)
# ---------------------------------------------------------------------------
def render_page_header(title, subtitle=None, icon=None):
    """페이지 상단 통일 헤더.

    기존 페이지별 `st.title` / HTML `.main-header` 혼용을 대체한다.

    Args:
        title: 제목 텍스트
        subtitle: 부제(선택)
        icon: 제목 앞 이모지/아이콘(선택)
    """
    icon_html = f"{icon} " if icon else ""
    sub_html = f'<div class="sl-ph-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="sl-page-header">'
        f'<div class="sl-ph-title">{icon_html}{title}</div>'
        f"{sub_html}"
        f"</div>",
        unsafe_allow_html=True,
    )
