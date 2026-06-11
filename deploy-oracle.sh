#!/bin/bash

# Oracle Cloud 자동 배포 스크립트
# 서버에서 실행: curl -sSL https://your-domain/deploy-oracle.sh | bash
# 또는: ssh ubuntu@server-ip < deploy-oracle.sh
# 작성일: 2025-11-30
# 작성자: hoyeon.han

set -e

echo "================================================"
echo "  솔루미랩 Oracle Cloud 자동 배포"
echo "================================================"
echo ""

# 설정
DOCKER_IMAGE="hoyeonhan/sollume-lab:latest"
APP_DIR="$HOME/sollume-finance"
COMPOSE_FILE="docker-compose.cloud.yml"

# 애플리케이션 디렉토리 생성
echo "📁 애플리케이션 디렉토리 생성..."
# 2025-12-16 hoyeon.han: database 디렉토리 추가
# mkdir -p ${APP_DIR}/{logs,processed,uploads,database}
# 2026-06-11 hoyeon.han: order_data(발주내역 저장소) 디렉토리 추가
mkdir -p ${APP_DIR}/{logs,processed,uploads,database,order_data}
cd ${APP_DIR}
echo "✅ 디렉토리: $(pwd)"
echo ""

# Docker Compose 파일 다운로드 (또는 복사)
if [ ! -f "${COMPOSE_FILE}" ]; then
    echo "📥 Docker Compose 파일 다운로드..."
    # GitHub raw URL로 변경하거나 직접 생성
    # 2026-06-11 hoyeon.han: 내장 compose 를 repo 의 docker-compose.cloud.yml 와 동기화
    # (발주내역 API sollume-api 추가, order_data/거래처마스터 볼륨 반영. 이전 내용은 git 이력 참조)
    cat > ${COMPOSE_FILE} <<'COMPOSE_EOF'
services:
  sollume-app:
    image: hoyeonhan/sollume-lab:latest
    container_name: sollume-finance-app
    ports:
      - "8501:8501"
    volumes:
      - ./logs:/app/logs
      - ./processed:/app/processed
      - ./uploads:/app/uploads
      - ./database:/app/database
      - ./order_data:/app/order_data
      - ./거래처마스터.xlsx:/app/Src/거래처마스터.xlsx:ro
    environment:
      - TZ=Asia/Seoul
      - PYTHONUNBUFFERED=1
      - STREAMLIT_SERVER_HEADLESS=true
      - STREAMLIT_SERVER_FILE_WATCHER_TYPE=none
      - STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8501/_stcore/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 20G
        reservations:
          cpus: '2'
          memory: 4G
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
    networks:
      - sollume-network
    security_opt:
      - no-new-privileges:true

  # 발주내역 API (OpenClaw 등 외부 에이전트 연동용)
  # 호스트 nginx 가 /api/ → 127.0.0.1:8502 로 프록시한다
  sollume-api:
    image: hoyeonhan/sollume-lab:latest
    container_name: sollume-finance-api
    command: gunicorn --bind 0.0.0.0:8502 --workers 2 --timeout 120 --pythonpath /app/Src api_server:app
    ports:
      - "127.0.0.1:8502:8502"
    volumes:
      - ./logs:/app/logs
      - ./order_data:/app/order_data:ro
    environment:
      - TZ=Asia/Seoul
      - PYTHONUNBUFFERED=1
      - ORDER_API_KEY=${ORDER_API_KEY}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8502/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 2G
    logging:
      driver: "json-file"
      options:
        max-size: "20m"
        max-file: "3"
    networks:
      - sollume-network
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:size=256M

networks:
  sollume-network:
    driver: bridge
COMPOSE_EOF
    echo "✅ Compose 파일 생성 완료"
else
    echo "✅ Compose 파일 존재"
    # 2026-06-11 hoyeon.han: 기존 파일은 자동 갱신되지 않으므로 변경 시 수동 교체 안내
    echo "   ⚠️  repo 의 docker-compose.cloud.yml 이 변경된 경우 이 파일을 직접 교체하세요:"
    echo "      scp docker-compose.cloud.yml ubuntu@서버IP:~/sollume-finance/"
fi
echo ""

# 2025-12-16 hoyeon.han: 거래처 DB 파일 확인
if [ ! -f "database/customer_master.db" ]; then
    echo "⚠️  경고: database/customer_master.db 파일이 없습니다!"
    echo "   이 파일을 서버로 복사해야 합니다:"
    echo "   scp database/customer_master.db ubuntu@server-ip:~/sollume-finance/database/"
    echo ""
    read -p "계속하시겠습니까? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 2026-06-11 hoyeon.han: 발주내역 API 인증 키(.env) 확인
# 키가 없으면 API 가 모든 요청을 503 으로 거부한다 (Streamlit 화면은 영향 없음)
if [ ! -f ".env" ] || ! grep -q "^ORDER_API_KEY=" .env; then
    echo "⚠️  경고: .env 파일(ORDER_API_KEY)이 없습니다!"
    echo "   발주내역 API 인증이 동작하지 않습니다. 다음 명령으로 생성하세요:"
    echo "   python3 -c \"import secrets; print('ORDER_API_KEY=' + secrets.token_urlsafe(32))\" > .env"
    echo ""
fi

# 기존 컨테이너 중지
echo "🛑 기존 컨테이너 확인 및 중지..."
if docker ps -a | grep -q sollume-finance-app; then
    docker compose -f ${COMPOSE_FILE} down
    echo "✅ 기존 컨테이너 중지 완료"
fi
echo ""

# 최신 이미지 풀
echo "📥 최신 Docker 이미지 다운로드..."
docker pull ${DOCKER_IMAGE}
echo "✅ 이미지 다운로드 완료"
echo ""

# 컨테이너 시작
echo "🚀 컨테이너 시작..."
docker compose -f ${COMPOSE_FILE} up -d

# 상태 확인
echo ""
echo "⏳ 컨테이너 시작 대기 (10초)..."
sleep 10

echo ""
echo "📊 컨테이너 상태:"
docker compose -f ${COMPOSE_FILE} ps
echo ""

# 헬스체크
echo "🏥 헬스체크..."
if curl -f http://localhost:8501/_stcore/health > /dev/null 2>&1; then
    echo "✅ 헬스체크 통과"
else
    echo "⚠️  헬스체크 실패 - 로그를 확인하세요"
    echo "   docker compose -f ${COMPOSE_FILE} logs"
fi

# 2026-06-11 hoyeon.han: 발주내역 API 헬스체크 추가
if curl -f http://localhost:8502/health > /dev/null 2>&1; then
    echo "✅ 발주내역 API 헬스체크 통과 (127.0.0.1:8502)"
else
    echo "⚠️  발주내역 API 헬스체크 실패 - 로그를 확인하세요"
    echo "   docker compose -f ${COMPOSE_FILE} logs sollume-api"
fi
echo ""

# 완료 메시지
echo "================================================"
echo "  ✅ 배포 완료!"
echo "================================================"
echo ""
echo "🌐 접속 URL:"
PUBLIC_IP=$(curl -s ifconfig.me || echo "unknown")
echo "  http://${PUBLIC_IP}:8501"
echo ""
echo "📋 유용한 명령어:"
echo "  # 로그 확인"
echo "  docker compose -f ${COMPOSE_FILE} logs -f"
echo ""
echo "  # 컨테이너 재시작"
echo "  docker compose -f ${COMPOSE_FILE} restart"
echo ""
echo "  # 컨테이너 중지"
echo "  docker compose -f ${COMPOSE_FILE} down"
echo ""
echo "  # 최신 버전 업데이트"
echo "  docker compose -f ${COMPOSE_FILE} pull"
echo "  docker compose -f ${COMPOSE_FILE} up -d"
echo ""
echo "⚠️  중요사항:"
echo "  - Oracle Cloud 콘솔에서 8501 포트가 열려있는지 확인"
echo "  - Ingress Rules → 0.0.0.0/0 → TCP 8501 추가"
echo "  - database/customer_master.db 파일 복사 확인"
# 2026-06-11 hoyeon.han: 발주내역 API 안내 추가
echo "  - 발주내역 API(8502)는 127.0.0.1 전용이라 Ingress 개방 불필요"
echo "  - 호스트 nginx 에 /api/ 프록시 설정 필요 (nginx-host-api.conf.example 참고)"
echo "  - API 호출 확인: curl http://localhost/api/health"
echo ""
