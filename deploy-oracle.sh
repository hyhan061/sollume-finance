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
mkdir -p ${APP_DIR}/{logs,processed,uploads,database}
cd ${APP_DIR}
echo "✅ 디렉토리: $(pwd)"
echo ""

# Docker Compose 파일 다운로드 (또는 복사)
if [ ! -f "${COMPOSE_FILE}" ]; then
    echo "📥 Docker Compose 파일 다운로드..."
    # GitHub raw URL로 변경하거나 직접 생성
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

networks:
  sollume-network:
    driver: bridge
COMPOSE_EOF
    echo "✅ Compose 파일 생성 완료"
else
    echo "✅ Compose 파일 존재"
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
echo ""
