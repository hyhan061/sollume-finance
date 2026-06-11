# api_server.py
# 2026-06-11 hoyeon.han: 외부 자동화 에이전트(OpenClaw 등)용 발주내역 파일 제공 API (신규)
#
# Streamlit 은 사람용 화면 전용이라 프로그램 간(HTTP) 인터페이스를 제공할 수 없다.
# 서버에 저장된 최신 발주내역(order_data/current.xlsm)을 외부 시스템이 받아갈 수
# 있도록 경량 Flask API 를 별도 프로세스(포트 8502)로 제공한다.
# nginx 리버스 프록시 뒤에서 /api/ 경로로만 외부에 노출되는 것을 전제로 한다.
#
# 실행 방법:
#   로컬 개발: ORDER_API_KEY=<키> python Src/api_server.py
#   운영(docker): gunicorn --bind 0.0.0.0:8502 --pythonpath /app/Src api_server:app
#
# 인증:
#   /api/order-file* 엔드포인트는 X-API-Key 헤더 필수 (환경변수 ORDER_API_KEY 와 비교).
#   키 생성: python -c "import secrets; print(secrets.token_urlsafe(32))"
#
# 엔드포인트:
#   GET /health                생존 확인 (인증 불필요, 컨테이너 헬스체크용)
#   GET /api/health            생존 확인 (인증 불필요, nginx 경유 확인용)
#   GET /api/order-file        최신 발주내역 원본(.xlsm) 다운로드
#   GET /api/order-file/meta   파일 메타데이터 JSON (원본명/업로드시각/시트목록 등)
#   GET /api/order-file/data   시트 내용을 행 단위 JSON 으로 반환
#                              ?sheet=시트명 (기본: 추천 시트) &offset=N &limit=N

import hmac
import json
import logging
import os
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, request, send_file

# pages/ 와 동일한 import 방식 (Src/ 디렉토리를 경로에 두고 모듈 직접 import)
from order_file_store import OrderFileStore

# ==============================================================================
# 설정
# ==============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ORDER_DATA_DIR = os.environ.get("ORDER_DATA_DIR", str(PROJECT_ROOT / "order_data"))
API_KEY_ENV = "ORDER_API_KEY"
DEFAULT_PORT = 8502
HEADER_ROW = 3  # 발주내역 시트의 제목 행 위치 (processing.py 의 read_excel 과 동일 규칙)
XLSM_MIME = "application/vnd.ms-excel.sheet.macroEnabled.12"

# ==============================================================================
# 로깅 (logs/api_server.log, 5MB x 3개 로테이션)
# ==============================================================================

logger = logging.getLogger("api_server")
logger.setLevel(logging.INFO)
if not logger.handlers:
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    _fh = RotatingFileHandler(
        log_dir / "api_server.log", maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8",
    )
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    logger.addHandler(_fh)
    logger.addHandler(_sh)

# ==============================================================================
# Flask 앱
# ==============================================================================

app = Flask(__name__)
app.json.ensure_ascii = False  # 한글 에러 메시지를 \uXXXX 로 깨지 않고 그대로 반환

store = OrderFileStore(store_dir=ORDER_DATA_DIR)


def require_api_key(f):
    """X-API-Key 헤더를 환경변수 ORDER_API_KEY 와 비교하는 인증 데코레이터."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        expected = os.environ.get(API_KEY_ENV, "")
        if not expected:
            # 키 미설정은 서버 설정 오류. 안전을 위해 모든 요청을 거부한다.
            logger.error(f"{API_KEY_ENV} 환경변수가 설정되지 않았습니다")
            return jsonify(
                {"error": "서버에 API 키가 설정되지 않았습니다. 관리자에게 문의하세요."}
            ), 503
        provided = request.headers.get("X-API-Key", "")
        # 상수 시간 비교 (타이밍 공격 방지)
        if not hmac.compare_digest(expected, provided):
            logger.warning(f"인증 실패: {request.remote_addr} → {request.path}")
            return jsonify(
                {"error": "인증에 실패했습니다. X-API-Key 헤더를 확인하세요."}
            ), 401
        return f(*args, **kwargs)

    return wrapper


# ==============================================================================
# 엔드포인트
# ==============================================================================


@app.get("/health")
@app.get("/api/health")
def health():
    """생존 확인. 인증 불필요 (docker 헬스체크 / 외부 연결 점검용)."""
    return jsonify({"status": "ok"})


@app.get("/api/order-file")
@require_api_key
def download_order_file():
    """저장된 최신 발주내역 원본(.xlsm)을 그대로 내려준다."""
    if not store.exists():
        return jsonify(
            {"error": "저장된 발주내역 파일이 없습니다. 먼저 화면에서 파일을 업로드하세요."}
        ), 404

    meta = store.get_metadata() or {}
    download_name = meta.get("original_name", "발주내역.xlsm")
    logger.info(f"파일 다운로드: {download_name} → {request.remote_addr}")
    # send_file 이 한글 파일명을 RFC 5987(filename*) 형식으로 처리한다
    return send_file(
        store.get_path(),
        as_attachment=True,
        download_name=download_name,
        mimetype=XLSM_MIME,
    )


@app.get("/api/order-file/meta")
@require_api_key
def order_file_meta():
    """파일 메타데이터를 반환한다.

    파일이 없어도 200 + {"exists": false} 를 반환한다.
    (에이전트가 에러 처리 없이 존재 여부를 폴링할 수 있도록)
    """
    return jsonify(store.get_stats())


@app.get("/api/order-file/data")
@require_api_key
def order_file_data():
    """발주내역 시트를 행 단위 JSON 으로 반환한다.

    쿼리 파라미터:
        sheet:  읽을 시트명 (생략 시 메타데이터의 추천 시트)
        offset: 건너뛸 행 수 (기본 0)
        limit:  최대 반환 행 수 (생략 시 전체)
    """
    if not store.exists():
        return jsonify(
            {"error": "저장된 발주내역 파일이 없습니다. 먼저 화면에서 파일을 업로드하세요."}
        ), 404

    stats = store.get_stats()
    sheet = request.args.get("sheet") or stats.get("recommended_sheet")
    if not sheet:
        return jsonify(
            {"error": "조회할 시트를 결정할 수 없습니다. ?sheet= 파라미터를 지정하세요."}
        ), 400
    if stats.get("sheet_names") and sheet not in stats["sheet_names"]:
        return jsonify(
            {
                "error": f"시트를 찾을 수 없습니다: {sheet}",
                "available_sheets": stats["sheet_names"],
            }
        ), 404

    try:
        offset = int(request.args.get("offset", 0))
        limit_raw = request.args.get("limit")
        limit = int(limit_raw) if limit_raw is not None else None
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError
    except ValueError:
        return jsonify({"error": "offset/limit 은 0 이상의 정수여야 합니다."}), 400

    try:
        df = pd.read_excel(
            store.get_path(), engine="openpyxl", sheet_name=sheet, header=HEADER_ROW
        )
    except Exception as e:
        logger.error(f"시트 읽기 실패: {sheet} - {e}", exc_info=True)
        return jsonify({"error": f"시트를 읽는 중 오류가 발생했습니다: {e}"}), 500

    total_rows = len(df)
    if offset:
        df = df.iloc[offset:]
    if limit is not None:
        df = df.iloc[:limit]

    # JSON 규격에는 NaN/날짜형이 없으므로 pandas 의 to_json 으로
    # NaN → null, 날짜 → ISO 문자열로 변환한 뒤 dict 로 되돌린다
    rows = json.loads(
        df.to_json(orient="records", force_ascii=False, date_format="iso")
    )

    logger.info(
        f"데이터 조회: 시트={sheet}, 전체={total_rows}행, "
        f"반환={len(rows)}행 → {request.remote_addr}"
    )
    return jsonify(
        {
            "sheet": sheet,
            "total_rows": total_rows,
            "offset": offset,
            "returned_rows": len(rows),
            "columns": [str(c) for c in df.columns],
            "rows": rows,
        }
    )


# ==============================================================================
# 공통 에러 처리 (모든 응답을 JSON 으로 통일)
# ==============================================================================


@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "존재하지 않는 주소입니다."}), 404


@app.errorhandler(405)
def method_not_allowed(_e):
    return jsonify({"error": "허용되지 않은 HTTP 메서드입니다."}), 405


@app.errorhandler(Exception)
def internal_error(e):
    logger.error(f"처리되지 않은 오류: {e}", exc_info=True)
    return jsonify({"error": "서버 내부 오류가 발생했습니다. 로그를 확인하세요."}), 500


# ==============================================================================
# 로컬 개발용 실행 (운영에서는 gunicorn 사용)
# ==============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("ORDER_API_PORT", DEFAULT_PORT))
    logger.info(f"발주내역 API 서버 시작: 포트 {port}, 저장소 {ORDER_DATA_DIR}")
    app.run(host="0.0.0.0", port=port)
