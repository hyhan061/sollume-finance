#!/bin/bash

# Synology NAS 배포 스크립트

echo "======================================"
echo "  Synology NAS 배포"
echo "======================================"
echo ""

# 설정
read -p "NAS IP 주소 또는 도메인 입력 (예: 192.168.1.100): " NAS_HOST
read -p "NAS 사용자명 입력 (기본: admin): " NAS_USER
NAS_USER=${NAS_USER:-admin}
NAS_PATH="/volume1/docker/sollume-finance"

echo ""
echo "📋 배포 정보:"
echo "   NAS 주소: $NAS_HOST"
echo "   사용자명: $NAS_USER"
echo "   배포 경로: $NAS_PATH"
echo ""

read -p "계속하시겠습니까? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "배포를 취소했습니다."
    exit 0
fi

# 1. NAS에 디렉토리 생성
echo ""
echo "📁 NAS에 디렉토리 생성 중..."
ssh ${NAS_USER}@${NAS_HOST} "mkdir -p ${NAS_PATH}/{logs,processed,uploads,Src,.streamlit}"

if [ $? -ne 0 ]; then
    echo "❌ SSH 연결 실패. NAS 주소와 사용자명을 확인하세요."
    exit 1
fi

# 2. 필수 파일 복사
echo ""
echo "📤 파일을 NAS로 전송 중..."

# 애플리케이션 파일
scp app.py ${NAS_USER}@${NAS_HOST}:${NAS_PATH}/
scp Dockerfile ${NAS_USER}@${NAS_HOST}:${NAS_PATH}/
scp docker-compose.yml ${NAS_USER}@${NAS_HOST}:${NAS_PATH}/
scp requirements.txt ${NAS_USER}@${NAS_HOST}:${NAS_PATH}/
scp .dockerignore ${NAS_USER}@${NAS_HOST}:${NAS_PATH}/

# Src 디렉토리
scp Src/processing.py ${NAS_USER}@${NAS_HOST}:${NAS_PATH}/Src/
scp "Src/거래처마스터.xlsx" ${NAS_USER}@${NAS_HOST}:${NAS_PATH}/Src/

# Streamlit 설정
scp .streamlit/config.toml ${NAS_USER}@${NAS_HOST}:${NAS_PATH}/.streamlit/

if [ $? -ne 0 ]; then
    echo "❌ 파일 전송 실패!"
    exit 1
fi

echo "✅ 파일 전송 완료!"

# 3. NAS에서 Docker 컨테이너 실행
echo ""
echo "🚀 NAS에서 Docker 컨테이너를 시작합니다..."

ssh ${NAS_USER}@${NAS_HOST} << 'EOF'
cd /volume1/docker/sollume-finance

# 기존 컨테이너 중지 및 삭제
docker-compose down

# 새 이미지 빌드
docker-compose build

# 컨테이너 시작
docker-compose up -d

# 상태 확인
echo ""
echo "📊 컨테이너 상태:"
docker-compose ps

echo ""
echo "📋 최근 로그:"
docker-compose logs --tail=20
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 배포 완료!"
    echo ""
    echo "🌐 다음 주소로 접속할 수 있습니다:"
    echo "   http://${NAS_HOST}:8501"
    echo ""
    echo "📋 유용한 명령어 (NAS에서 실행):"
    echo "   ssh ${NAS_USER}@${NAS_HOST}"
    echo "   cd ${NAS_PATH}"
    echo "   docker-compose logs -f          # 로그 확인"
    echo "   docker-compose restart          # 재시작"
    echo "   docker-compose down             # 종료"
else
    echo ""
    echo "❌ 배포 실패!"
    echo "NAS에 SSH 접속해서 로그를 확인하세요:"
    echo "   ssh ${NAS_USER}@${NAS_HOST}"
    echo "   cd ${NAS_PATH}"
    echo "   docker-compose logs"
    exit 1
fi
