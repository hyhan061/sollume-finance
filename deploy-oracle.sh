#!/usr/bin/env bash
# 2026-10-14 hoyeon.han: 이전 무인증 배포 코드 보존(실행되지 않음)
# #!/bin/bash
#
# # Oracle Cloud 자동 배포 스크립트
# # 서버에서 실행: curl -sSL https://your-domain/deploy-oracle.sh | bash
# # 2026-06-11 hoyeon.han: 실제 raw 주소로 갱신 (스크립트 자체도 항상 최신으로 실행 가능)
# #   curl -sSL https://raw.githubusercontent.com/hyhan061/sollume-finance/main/deploy-oracle.sh | bash
# # 또는: ssh ubuntu@server-ip < deploy-oracle.sh
# # 작성일: 2025-11-30
# # 작성자: hoyeon.han
#
# set -e
#
# echo "================================================"
# echo "  솔루미랩 Oracle Cloud 자동 배포"
# echo "================================================"
# echo ""
#
# # 설정
# DOCKER_IMAGE="hoyeonhan/sollume-lab:latest"
# APP_DIR="$HOME/sollume-finance"
# COMPOSE_FILE="docker-compose.cloud.yml"
# # 2026-06-11 hoyeon.han: compose 자동 다운로드용 GitHub raw 주소 (public repo, main 기준)
# RAW_BASE="https://raw.githubusercontent.com/hyhan061/sollume-finance/main"
#
# # 애플리케이션 디렉토리 생성
# echo "📁 애플리케이션 디렉토리 생성..."
# # 2025-12-16 hoyeon.han: database 디렉토리 추가
# # mkdir -p ${APP_DIR}/{logs,processed,uploads,database}
# # 2026-06-11 hoyeon.han: order_data(발주내역 저장소) 디렉토리 추가
# mkdir -p ${APP_DIR}/{logs,processed,uploads,database,order_data}
# cd ${APP_DIR}
# echo "✅ 디렉토리: $(pwd)"
# echo ""
#
# # Docker Compose 파일 다운로드 (또는 복사)
# # 2026-06-11 hoyeon.han: 실행 시마다 GitHub(main) 최신 compose 를 다운로드해 검증 후 적용
# # - 다운로드 + docker compose config 검증 통과 시에만 교체 (수동 scp 불필요)
# # - 실패 시: 서버의 기존 파일이 있으면 그대로 사용, 없으면 내장 fallback 생성
# echo "📥 최신 Compose 파일 다운로드 (GitHub main)..."
# if curl -fsSL "${RAW_BASE}/docker-compose.cloud.yml" -o "${COMPOSE_FILE}.tmp" \
#    && ORDER_API_KEY="${ORDER_API_KEY:-dummy}" docker compose -f "${COMPOSE_FILE}.tmp" config --quiet 2>/dev/null; then
#     # 2026-06-11 hoyeon.han: 교체 전 기존 compose 백업 (이전 운영 설정 추적/복구용)
#     if [ -f "${COMPOSE_FILE}" ]; then
#         BACKUP_FILE="${COMPOSE_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
#         cp "${COMPOSE_FILE}" "${BACKUP_FILE}"
#         echo "   (기존 파일 백업: ${BACKUP_FILE})"
#     fi
#     mv "${COMPOSE_FILE}.tmp" "${COMPOSE_FILE}"
#     echo "✅ 최신 Compose 파일 적용 완료"
# elif [ -f "${COMPOSE_FILE}" ]; then
#     rm -f "${COMPOSE_FILE}.tmp"
#     echo "⚠️  다운로드/검증 실패 - 서버의 기존 Compose 파일로 계속 진행합니다"
# else
#     rm -f "${COMPOSE_FILE}.tmp"
#     echo "⚠️  다운로드 실패 - 내장 기본 Compose 파일을 생성합니다"
#     # (발주내역 API sollume-api 추가, order_data/거래처마스터 볼륨 반영. 이전 내용은 git 이력 참조)
#     cat > ${COMPOSE_FILE} <<'COMPOSE_EOF'
# services:
#   sollume-app:
#     image: hoyeonhan/sollume-lab:latest
#     container_name: sollume-finance-app
#     ports:
#       - "8501:8501"
#     volumes:
#       - ./logs:/app/logs
#       - ./processed:/app/processed
#       - ./uploads:/app/uploads
#       - ./database:/app/database
#       - ./order_data:/app/order_data
#       - ./거래처마스터.xlsx:/app/Src/거래처마스터.xlsx:ro
#     environment:
#       - TZ=Asia/Seoul
#       - PYTHONUNBUFFERED=1
#       - STREAMLIT_SERVER_HEADLESS=true
#       - STREAMLIT_SERVER_FILE_WATCHER_TYPE=none
#       - STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
#     restart: unless-stopped
#     healthcheck:
#       test: ["CMD", "curl", "-f", "http://localhost:8501/_stcore/health"]
#       interval: 30s
#       timeout: 10s
#       retries: 3
#       start_period: 10s
#     deploy:
#       resources:
#         limits:
#           cpus: '4'
#           memory: 20G
#         reservations:
#           cpus: '2'
#           memory: 4G
#     logging:
#       driver: "json-file"
#       options:
#         max-size: "50m"
#         max-file: "5"
#     networks:
#       - sollume-network
#     security_opt:
#       - no-new-privileges:true
#
#   # 발주내역 API (OpenClaw 등 외부 에이전트 연동용)
#   # 호스트 nginx 가 /api/ → 127.0.0.1:8502 로 프록시한다
#   sollume-api:
#     image: hoyeonhan/sollume-lab:latest
#     container_name: sollume-finance-api
#     command: gunicorn --bind 0.0.0.0:8502 --workers 2 --timeout 120 --pythonpath /app/Src api_server:app
#     ports:
#       - "127.0.0.1:8502:8502"
#     volumes:
#       - ./logs:/app/logs
#       - ./order_data:/app/order_data:ro
#     environment:
#       - TZ=Asia/Seoul
#       - PYTHONUNBUFFERED=1
#       - ORDER_API_KEY=${ORDER_API_KEY}
#     restart: unless-stopped
#     healthcheck:
#       test: ["CMD", "curl", "-f", "http://localhost:8502/health"]
#       interval: 30s
#       timeout: 10s
#       retries: 3
#       start_period: 10s
#     deploy:
#       resources:
#         limits:
#           cpus: '1'
#           memory: 2G
#     logging:
#       driver: "json-file"
#       options:
#         max-size: "20m"
#         max-file: "3"
#     networks:
#       - sollume-network
#     security_opt:
#       - no-new-privileges:true
#     read_only: true
#     tmpfs:
#       - /tmp:size=256M
#
# networks:
#   sollume-network:
#     driver: bridge
# COMPOSE_EOF
#     echo "✅ Compose 파일 생성 완료"
# fi
# # 2026-06-11 hoyeon.han: 자동 다운로드 도입으로 기존 수동 scp 안내는 제거
# # else
# #     echo "✅ Compose 파일 존재"
# #     echo "   ⚠️  repo 의 docker-compose.cloud.yml 이 변경된 경우 이 파일을 직접 교체하세요:"
# #     echo "      scp docker-compose.cloud.yml ubuntu@서버IP:~/sollume-finance/"
# echo ""
#
# # 2025-12-16 hoyeon.han: 거래처 DB 파일 확인
# if [ ! -f "database/customer_master.db" ]; then
#     echo "⚠️  경고: database/customer_master.db 파일이 없습니다!"
#     echo "   이 파일을 서버로 복사해야 합니다:"
#     echo "   scp database/customer_master.db ubuntu@server-ip:~/sollume-finance/database/"
#     echo ""
#     read -p "계속하시겠습니까? (y/N): " -n 1 -r
#     echo
#     if [[ ! $REPLY =~ ^[Yy]$ ]]; then
#         exit 1
#     fi
# fi
#
# # 2026-06-11 hoyeon.han: 발주내역 API 인증 키(.env) 확인
# # 키가 없으면 API 가 모든 요청을 503 으로 거부한다 (Streamlit 화면은 영향 없음)
# if [ ! -f ".env" ] || ! grep -q "^ORDER_API_KEY=" .env; then
#     echo "⚠️  경고: .env 파일(ORDER_API_KEY)이 없습니다!"
#     echo "   발주내역 API 인증이 동작하지 않습니다. 다음 명령으로 생성하세요:"
#     echo "   python3 -c \"import secrets; print('ORDER_API_KEY=' + secrets.token_urlsafe(32))\" > .env"
#     echo ""
# fi
#
# # 기존 컨테이너 중지
# echo "🛑 기존 컨테이너 확인 및 중지..."
# if docker ps -a | grep -q sollume-finance-app; then
#     docker compose -f ${COMPOSE_FILE} down
#     echo "✅ 기존 컨테이너 중지 완료"
# fi
# echo ""
#
# # 최신 이미지 풀
# echo "📥 최신 Docker 이미지 다운로드..."
# docker pull ${DOCKER_IMAGE}
# echo "✅ 이미지 다운로드 완료"
# echo ""
#
# # 컨테이너 시작
# echo "🚀 컨테이너 시작..."
# docker compose -f ${COMPOSE_FILE} up -d
#
# # 상태 확인
# echo ""
# echo "⏳ 컨테이너 시작 대기 (10초)..."
# sleep 10
#
# echo ""
# echo "📊 컨테이너 상태:"
# docker compose -f ${COMPOSE_FILE} ps
# echo ""
#
# # 헬스체크
# echo "🏥 헬스체크..."
# if curl -f http://localhost:8501/_stcore/health > /dev/null 2>&1; then
#     echo "✅ 헬스체크 통과"
# else
#     echo "⚠️  헬스체크 실패 - 로그를 확인하세요"
#     echo "   docker compose -f ${COMPOSE_FILE} logs"
# fi
#
# # 2026-06-11 hoyeon.han: 발주내역 API 헬스체크 추가
# if curl -f http://localhost:8502/health > /dev/null 2>&1; then
#     echo "✅ 발주내역 API 헬스체크 통과 (127.0.0.1:8502)"
# else
#     echo "⚠️  발주내역 API 헬스체크 실패 - 로그를 확인하세요"
#     echo "   docker compose -f ${COMPOSE_FILE} logs sollume-api"
# fi
# echo ""
#
# # 완료 메시지
# echo "================================================"
# echo "  ✅ 배포 완료!"
# echo "================================================"
# echo ""
# echo "🌐 접속 URL:"
# PUBLIC_IP=$(curl -s ifconfig.me || echo "unknown")
# echo "  http://${PUBLIC_IP}:8501"
# echo ""
# echo "📋 유용한 명령어:"
# echo "  # 로그 확인"
# echo "  docker compose -f ${COMPOSE_FILE} logs -f"
# echo ""
# echo "  # 컨테이너 재시작"
# echo "  docker compose -f ${COMPOSE_FILE} restart"
# echo ""
# echo "  # 컨테이너 중지"
# echo "  docker compose -f ${COMPOSE_FILE} down"
# echo ""
# echo "  # 최신 버전 업데이트"
# echo "  docker compose -f ${COMPOSE_FILE} pull"
# echo "  docker compose -f ${COMPOSE_FILE} up -d"
# echo ""
# echo "⚠️  중요사항:"
# echo "  - Oracle Cloud 콘솔에서 8501 포트가 열려있는지 확인"
# echo "  - Ingress Rules → 0.0.0.0/0 → TCP 8501 추가"
# echo "  - database/customer_master.db 파일 복사 확인"
# # 2026-06-11 hoyeon.han: 발주내역 API 안내 추가
# echo "  - 발주내역 API(8502)는 127.0.0.1 전용이라 Ingress 개방 불필요"
# echo "  - 호스트 nginx 에 /api/ 프록시 설정 필요 (nginx-host-api.conf.example 참고)"
# echo "  - API 호출 확인: curl http://localhost/api/health"
# echo ""

# 2026-10-14 hoyeon.han: 운영 적용 전 인증·HTTPS·DB 보존을 검증한다.
set -euo pipefail
# 2026-10-19 hoyeon.han: 실행 설정과 추가 DB 백업을 기본 0600/0700으로 작성한다.
umask 077

APP_DIR="${SOLLUME_APP_DIR:-$HOME/sollume-finance}"
RAW_BASE="https://raw.githubusercontent.com/hyhan061/sollume-finance/main"
COMPOSE_FILE="docker-compose.cloud.yml"
NGINX_SITE_CONFIG="${SOLLUME_NGINX_SITE_CONFIG:-/etc/nginx/sites-enabled/sollume-finance}"
# 2026-10-15 hoyeon.han: 복구 도구는 호스트의 운영 전용 가상환경에서 실행한다.
OPS_PYTHON="${SOLLUME_OPS_PYTHON:-$APP_DIR/.venv-ops/bin/python}"
ROLLBACK_HELPER="$APP_DIR/scripts/release_snapshot.py"
ROLLBACK_RELEASE=""

fail() { echo "배포 중단: $*" >&2; exit 1; }
# 2026-10-19 hoyeon.han: 완료한 압축 백업을 명시적으로 지정하면 재캡처 대신 검증하여 사용한다.
MANUAL_BACKUP_DIR=""
NGINX_CONFIG_ARGS=()
while test "$#" -gt 0; do
    case "$1" in
        --backup-dir)
            test "$#" -ge 2 && test -n "$2" || fail "--backup-dir에 압축 백업의 절대 경로를 지정하세요."
            MANUAL_BACKUP_DIR="$2"
            shift 2
            ;;
        --nginx-config)
            test "$#" -ge 2 && test -n "$2" || fail "--nginx-config에 회계 사이트 설정의 절대 경로를 지정하세요."
            if test "${#NGINX_CONFIG_ARGS[@]}" -eq 0; then NGINX_SITE_CONFIG="$2"; fi
            NGINX_CONFIG_ARGS+=(--nginx-config "$2")
            shift 2
            ;;
        -h|--help)
            echo "사용법: deploy-oracle.sh [--backup-dir 절대백업경로] [--nginx-config 인증사이트] [--nginx-config 기존회계사이트 ...]"
            echo "실제 배포 명령입니다. 수동 백업 점검만 할 때는 rollback-oracle.sh --backup-dir 경로를 사용하세요."
            exit 0
            ;;
        *) fail "지원하지 않는 인자입니다. --help를 확인하세요." ;;
    esac
done
if test "${#NGINX_CONFIG_ARGS[@]}" -eq 0; then NGINX_CONFIG_ARGS=(--nginx-config "$NGINX_SITE_CONFIG"); fi
if test -n "$MANUAL_BACKUP_DIR"; then
    case "$MANUAL_BACKUP_DIR" in /*) ;; *) fail "압축 백업은 절대 경로로 지정하세요." ;; esac
fi
command -v docker >/dev/null || fail "Docker가 필요합니다."
# command -v python3 >/dev/null || fail "설정 검증과 SQLite 백업용 Python 3이 필요합니다."
# 2026-10-19 hoyeon.han: 호스트 Python 프로그램은 아래 검증한 운영 가상환경으로만 실행한다.
test -d "$APP_DIR" || fail "기존 운영 디렉토리를 확인하세요: $APP_DIR"
cd "$APP_DIR"
test -f .env || fail ".env에 인증 암호화 키·HTTPS 주소·기존 API 키를 설정하세요."
# 2026-10-15 hoyeon.han: 터미널 export가 보관한 .env보다 우선하여 다른 키로 배포되는 것을 막는다.
unset AUTH_ENCRYPTION_KEY AUTH_SIGNING_KEY AUTH_PUBLIC_ORIGIN ORDER_API_KEY
test -f database/users.db || fail "기존 사용자 DB가 없습니다. 자동으로 빈 DB를 만들지 않습니다."
test -f database/customer_master.db || fail "기존 거래처 DB가 없습니다. 원본을 복원하세요."
test -f "$NGINX_SITE_CONFIG" || fail "엄격한 호스트 Nginx 설정을 먼저 설치하세요. OPERATIONS.md를 참고하세요."
# 2026-10-15 hoyeon.han: 복구 지점 없이 이미지를 교체하지 않는다. 설치 절차는 ROLLBACK.md에 둔다.
test -f "$ROLLBACK_HELPER" || fail "scripts/release_snapshot.py를 먼저 설치하세요. ROLLBACK.md의 최초 준비 절차를 확인하세요."
test -x "$OPS_PYTHON" || fail ".venv-ops 가상환경이 필요합니다. python3 -m venv .venv-ops로 준비하세요."
"$OPS_PYTHON" -c 'import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)' \
    || fail "SOLLUME_OPS_PYTHON에는 가상환경 Python을 지정하세요."
# 2026-10-19 hoyeon.han: 상위 backups 소유권을 바꾸지 않고 기존 releases 쓰기 가능 여부를 먼저 검사한다.
test -d database/backups/releases && test -w database/backups/releases \
    || fail "Ubuntu 소유·0700인 database/backups/releases를 먼저 준비하세요. 상위 backups는 변경하지 않습니다."

# 기존 설정이나 내장 무인증 Compose로 폴백하면 접근 차단을 우회하므로 즉시 중단한다.
COMPOSE_STAGED=$(mktemp "${COMPOSE_FILE}.tmp.XXXXXX")
COMPOSE_RENDERED=$(mktemp "${COMPOSE_FILE}.validated.XXXXXX")
# 2026-10-15 hoyeon.han: 원래 정리 동작은 보존하고, 실패 시 복구 지점만 안내한다. 자동 롤백은 하지 않는다.
# trap 'rm -f "$COMPOSE_STAGED" "$COMPOSE_RENDERED"' EXIT
cleanup_deployment() {
    local result=$?
    rm -f "$COMPOSE_STAGED" "$COMPOSE_RENDERED"
    # 2026-10-19 hoyeon.han: 수동 백업 복구는 자동 snapshot과 다른 인자로 점검한다.
    # if test "$result" -ne 0 && test -n "$ROLLBACK_RELEASE" && test -f "$ROLLBACK_RELEASE/manifest.json"; then
    if test "$result" -ne 0 && test -n "$MANUAL_BACKUP_DIR" && test -n "$ROLLBACK_RELEASE"; then
        echo "배포가 완료되지 않았습니다. 보존한 압축 백업: $MANUAL_BACKUP_DIR" >&2
        echo "rollback-oracle.sh --backup-dir 백업경로 --app-dir 원래앱경로 --nginx-config 회계사이트(각각 지정) 로 점검하세요." >&2
        echo "복구는 자동 실행하지 않습니다. 구버전 복구 후 공개 접속은 차단 상태로 유지합니다." >&2
    elif test "$result" -ne 0 && test -n "$ROLLBACK_RELEASE" && test -f "$ROLLBACK_RELEASE/manifest.json"; then
        echo "배포가 완료되지 않았습니다. 복구 지점: $ROLLBACK_RELEASE" >&2
        echo "rollback-oracle.sh --release 복구지점 으로 사전 점검하세요. 실제 복구는 --apply를 명시합니다." >&2
        echo "인증 도입 전 버전은 외부 접속을 차단한 별도 복구 절차만 허용합니다. ROLLBACK.md를 확인하세요." >&2
    fi
}
trap cleanup_deployment EXIT
chmod 600 "$COMPOSE_STAGED" "$COMPOSE_RENDERED" .env
curl -fsSL --proto '=https' --tlsv1.2 "$RAW_BASE/$COMPOSE_FILE" -o "$COMPOSE_STAGED" \
    || fail "최신 인증 Compose 다운로드에 실패했습니다. 실행 중인 구성은 변경하지 않았습니다."
docker compose --env-file .env -f "$COMPOSE_STAGED" config --format json > "$COMPOSE_RENDERED" \
    || fail "인증 환경변수 또는 Compose 검증 실패. 실행 중인 구성은 변경하지 않았습니다."

# 출력 JSON에는 키가 포함되므로 화면·로그에 출력하지 않고 비공개 임시 파일에서만 검사한다.
# python3 - "$COMPOSE_RENDERED" "$NGINX_SITE_CONFIG" <<'PY'
# 2026-10-19 hoyeon.han: Compose·Nginx 검증도 운영 가상환경에서 실행한다.
"$OPS_PYTHON" - "$COMPOSE_RENDERED" "$NGINX_SITE_CONFIG" <<'PY'
import json, pathlib, sys
from urllib.parse import urlsplit
config = json.loads(pathlib.Path(sys.argv[1]).read_text())
services = config.get('services', {})
required = {'sollume-app':8501, 'sollume-api':8502, 'sollume-auth':8503}
for name, port in required.items():
    service = services.get(name)
    if not service:
        raise SystemExit(f'필수 서비스 누락: {name}. 인증 전 버전은 배포할 수 없습니다.')
    bindings = service.get('ports', [])
    if len(bindings) != 1 or bindings[0].get('host_ip') != '127.0.0.1' or bindings[0].get('target') != port:
        raise SystemExit(f'직접 외부 포트 노출을 차단해야 합니다: {name}')
    if name != 'sollume-api':
        env = service.get('environment', {})
        if env.get('AUTH_ENV') != 'production':
            raise SystemExit('운영 인증 모드가 필요합니다.')
        if env.get('AUTH_PUBLIC_ORIGIN') != 'https://sollumeesthe.com':
            raise SystemExit('운영 공개 주소와 Nginx 도메인이 일치해야 합니다.')
        if not env.get('AUTH_ENCRYPTION_KEY'):
            raise SystemExit('인증 암호화 키가 필요합니다.')
nginx = pathlib.Path(sys.argv[2]).read_text()
active = '\n'.join(line.split('#',1)[0] for line in nginx.splitlines())
for required_text in ('listen 443 ssl', 'ssl_certificate', 'auth_request /_auth_check;',
                      'location = /_auth_check', 'internal;', '/auth/check',
                      'location ^~ /media/', 'return 403;', 'location ^~ /downloads/'):
    if required_text not in active:
        raise SystemExit(f'Nginx 인증 설정 누락: {required_text}')
if active.count('auth_request /_auth_check;') < 2:
    raise SystemExit('업무 화면과 다운로드 모두 Nginx 인증 검사가 필요합니다.')
print('Compose의 내부 포트·운영 인증 설정 및 Nginx 필수 경로 검증 완료')
PY
# sudo nginx -t || fail "HTTPS 인증서 또는 Nginx 설정 검증 실패. 기존 컨테이너를 유지합니다."
# 2026-10-19 hoyeon.han: 비밀번호 프롬프트에서 배포가 멈추지 않도록 실제 명령 권한을 확인한다.
sudo -n nginx -t || fail "관리자 권한·HTTPS 인증서·Nginx 설정 검증 실패. 기존 컨테이너를 유지합니다."

# 2026-10-15 hoyeon.han: latest가 바뀌기 전에 실제 실행 이미지와 설정·DB를 오프라인 복구 지점으로 보관한다.
# ROLLBACK_RELEASE="$APP_DIR/database/backups/releases/before_deploy_$(date +%Y%m%d_%H%M%S)_$$"
# "$OPS_PYTHON" "$ROLLBACK_HELPER" capture --app-dir "$APP_DIR" \
#     --nginx-config "$NGINX_SITE_CONFIG" --release "$ROLLBACK_RELEASE" \
#     || fail "이전 실행 이미지·설정·DB의 복구 지점 생성에 실패했습니다. 서비스를 교체하지 않습니다."
# 2026-10-19 hoyeon.han: 압축 백업의 원본 3파일을 재저장하지 않고 현재 실행 상태와 대조한다.
if test -n "$MANUAL_BACKUP_DIR"; then
    MANUAL_PREPARE_RESULT=$("$OPS_PYTHON" "$ROLLBACK_HELPER" manual-prepare \
        --app-dir "$APP_DIR" --backup-dir "$MANUAL_BACKUP_DIR" \
        "${NGINX_CONFIG_ARGS[@]}" --check-current) \
        || fail "압축 백업 또는 현재 실행 상태 검증에 실패했습니다. 서비스를 교체하지 않습니다."
    ROLLBACK_RELEASE=$("$OPS_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["release"])' <<< "$MANUAL_PREPARE_RESULT") \
        || fail "압축 백업의 복구 준비 결과를 확인할 수 없습니다."
else
    ROLLBACK_RELEASE="$APP_DIR/database/backups/releases/before_deploy_$(date +%Y%m%d_%H%M%S)_$$"
    "$OPS_PYTHON" "$ROLLBACK_HELPER" capture --app-dir "$APP_DIR" \
        --nginx-config "$NGINX_SITE_CONFIG" --release "$ROLLBACK_RELEASE" \
        || fail "이전 실행 이미지·설정·DB의 복구 지점 생성에 실패했습니다. 서비스를 교체하지 않습니다."
fi
echo "배포 전 복구 지점 준비 완료: $ROLLBACK_RELEASE"

# 이미지 다운로드와 스키마 지원 검사가 끝나기 전 기존 컨테이너를 중지하지 않는다.
docker compose --env-file .env -f "$COMPOSE_STAGED" pull \
    || fail "이미지 다운로드 실패. 기존 컨테이너를 유지합니다."
# 2026-10-14 hoyeon.han: DB를 열지 않고 Docker 가상환경과 인증·관리 CLI 포함 여부를 검사한다.
# docker compose --env-file .env -f "$COMPOSE_STAGED" run --rm --no-deps --entrypoint python sollume-auth \
#     -c 'import sys; sys.path.insert(0,"/app/Src"); import auth_gateway, security_service, pyotp, cryptography, argon2, qrcode' \
#     || fail "이미지에 승인된 인증 모듈이 없습니다. 이미지를 먼저 빌드·게시하세요."
docker compose --env-file .env -f "$COMPOSE_STAGED" run --rm --no-deps --entrypoint python sollume-auth \
    -c 'import sys; assert sys.prefix != sys.base_prefix, "Docker Python 가상환경이 없습니다."; sys.path[:0] = ["/app/Src", "/app/scripts"]; import auth_gateway, security_service, pyotp, cryptography, argon2, qrcode, manage_users, init_users_db' \
    || fail "이미지의 가상환경 또는 인증·관리 CLI 검증에 실패했습니다. 수정된 Dockerfile과 필수 모듈을 포함해 이미지를 다시 빌드·게시하세요."

# BACKUP_DIR="database/backups/before_security_$(date +%Y%m%d_%H%M%S)"
# 2026-10-19 hoyeon.han: root 소유 backups를 변경하지 않고 준비된 releases 아래에 보관한다.
BACKUP_DIR="database/backups/releases/before_security_$(date +%Y%m%d_%H%M%S)_$$"
mkdir -p "$BACKUP_DIR" processed/secure_downloads
chmod 700 "$BACKUP_DIR" processed/secure_downloads
# python3 - "$BACKUP_DIR" <<'PY'
# 2026-10-19 hoyeon.han: DB 백업 연결을 명시적으로 닫고 운영 가상환경을 사용한다.
"$OPS_PYTHON" - "$BACKUP_DIR" <<'PY'
import pathlib, sqlite3, sys
from contextlib import closing
for name in ('users.db', 'customer_master.db'):
    # with sqlite3.connect(f'file:database/{name}?mode=ro', uri=True) as source:
    #     with sqlite3.connect(str(pathlib.Path(sys.argv[1])/name)) as destination:
    with closing(sqlite3.connect(f'file:database/{name}?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(str(pathlib.Path(sys.argv[1])/name))) as destination, destination:
            source.backup(destination)
print('기존 사용자·거래처 DB의 일관된 백업 완료')
PY
if test -f "$COMPOSE_FILE"; then cp "$COMPOSE_FILE" "$BACKUP_DIR/docker-compose.cloud.yml"; fi
mv "$COMPOSE_STAGED" "$COMPOSE_FILE"
docker compose --env-file .env -f "$COMPOSE_FILE" up -d --wait --wait-timeout 120 \
    || fail "서비스 준비 실패. 로그와 안전한 롤백 안내를 확인하세요."
# sudo systemctl reload nginx || fail "Nginx 적용 실패. 서비스 포트는 루프백 제한 상태입니다."
# 2026-10-19 hoyeon.han: 적용 단계에서도 비대화식 관리자 권한을 사용한다.
sudo -n systemctl reload nginx || fail "Nginx 적용 실패. 서비스 포트는 루프백 제한 상태입니다."

curl -fsS http://127.0.0.1:8501/_stcore/health >/dev/null || fail "회계앱 상태 검사 실패"
curl -fsS -H 'Host: sollumeesthe.com' http://127.0.0.1:8503/auth/health >/dev/null || fail "인증 서버 상태 검사 실패"
HTTP_STATUS=$(curl -sS -o /dev/null -w '%{http_code}' --resolve sollumeesthe.com:443:127.0.0.1 \
    -H 'Accept: application/json' https://sollumeesthe.com/)
test "$HTTP_STATUS" = 401 || fail "미인증 업무 접근이 차단되지 않았습니다(HTTP $HTTP_STATUS)."
MEDIA_STATUS=$(curl -sS -o /dev/null -w '%{http_code}' --resolve sollumeesthe.com:443:127.0.0.1 \
    https://sollumeesthe.com/media/blocked-test)
test "$MEDIA_STATUS" = 403 || fail "기존 media 다운로드 경로가 차단되지 않았습니다."
echo "배포 및 기본 접근 차단 검증 완료: https://sollumeesthe.com"
echo "초기 인증 등록·계정 권한·외부 포트 차단은 OPERATIONS.md의 운영 점검을 완료하세요."
echo "8501·8502·8503의 인터넷 Ingress는 열지 않습니다."
