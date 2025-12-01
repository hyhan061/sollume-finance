#!/bin/bash

# Oracle Cloud Ubuntu 서버 초기 설정 스크립트
# 서버에서 실행: ssh ubuntu@server-ip < oracle-setup.sh
# 작성일: 2025-11-30
# 작성자: hoyeon.han

set -e

echo "================================================"
echo "  Oracle Cloud 서버 초기 설정"
echo "  Ubuntu 24.04 / ARM64"
echo "================================================"
echo ""

# 서버 정보 표시
echo "📊 서버 정보:"
echo "  - OS: $(lsb_release -d | cut -f2)"
echo "  - 아키텍처: $(uname -m)"
echo "  - CPU 코어: $(nproc)"
echo "  - 메모리: $(free -h | awk '/^Mem:/ {print $2}')"
echo ""

# 시스템 업데이트
echo "📦 시스템 패키지 업데이트..."
sudo apt-get update
sudo apt-get upgrade -y
echo "✅ 업데이트 완료"
echo ""

# Docker 설치
echo "🐳 Docker 설치 확인..."
if ! command -v docker &> /dev/null; then
    echo "Docker 설치 중..."

    # Docker 공식 설치 스크립트
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh

    # 현재 사용자를 docker 그룹에 추가
    sudo usermod -aG docker $USER

    echo "✅ Docker 설치 완료"
    echo "⚠️  로그아웃 후 재로그인하여 docker 그룹 적용 필요"
else
    echo "✅ Docker가 이미 설치되어 있습니다: $(docker --version)"
fi
echo ""

# Docker Compose 설치
echo "🐳 Docker Compose 설치 확인..."
if ! command -v docker-compose &> /dev/null; then
    echo "Docker Compose 설치 중..."

    # Docker Compose v2 (플러그인 방식)
    sudo apt-get install -y docker-compose-plugin

    echo "✅ Docker Compose 설치 완료"
else
    echo "✅ Docker Compose가 이미 설치되어 있습니다: $(docker compose version)"
fi
echo ""

# 필수 유틸리티 설치
echo "🔧 필수 유틸리티 설치..."
sudo apt-get install -y \
    curl \
    wget \
    git \
    vim \
    htop \
    net-tools \
    ufw

echo "✅ 유틸리티 설치 완료"
echo ""

# 방화벽 설정
echo "🔥 방화벽 설정..."
sudo ufw --force enable
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 8501/tcp  # Streamlit
sudo ufw allow 80/tcp    # HTTP (향후 Nginx용)
sudo ufw allow 443/tcp   # HTTPS (향후 Nginx용)
sudo ufw status
echo "✅ 방화벽 설정 완료"
echo ""

# 애플리케이션 디렉토리 생성
echo "📁 애플리케이션 디렉토리 생성..."
mkdir -p ~/sollume-finance/{logs,processed,uploads}
cd ~/sollume-finance
echo "✅ 디렉토리 생성 완료: $(pwd)"
echo ""

# 시스템 설정 최적화
echo "⚙️  시스템 설정 최적화..."

# 파일 디스크립터 제한 증가
sudo tee -a /etc/security/limits.conf > /dev/null <<EOF
* soft nofile 65536
* hard nofile 65536
EOF

# 스왑 메모리 설정 (24GB RAM이므로 필수는 아니지만 안전장치)
if [ ! -f /swapfile ]; then
    echo "스왑 파일 생성 중 (4GB)..."
    sudo fallocate -l 4G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "✅ 스왑 설정 완료"
fi
echo ""

# 자동 업데이트 비활성화 (선택사항)
echo "🔄 자동 업데이트 설정..."
sudo systemctl disable apt-daily.timer
sudo systemctl disable apt-daily-upgrade.timer
echo "✅ 자동 업데이트 비활성화 (수동 관리)"
echo ""

# 타임존 설정
echo "🕐 타임존 설정..."
sudo timedatectl set-timezone Asia/Seoul
echo "✅ 타임존: $(timedatectl | grep 'Time zone')"
echo ""

# Docker 서비스 시작
echo "🚀 Docker 서비스 시작..."
sudo systemctl enable docker
sudo systemctl start docker
sudo docker info > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✅ Docker 서비스 정상 동작"
else
    echo "⚠️  Docker 서비스 시작 실패 - 재로그인 필요"
fi
echo ""

# 완료 메시지
echo "================================================"
echo "  ✅ 서버 초기 설정 완료!"
echo "================================================"
echo ""
echo "📋 다음 단계:"
echo "  1. 로그아웃 후 재로그인 (docker 그룹 적용)"
echo "  2. 애플리케이션 배포:"
echo "     cd ~/sollume-finance"
echo "     wget https://raw.githubusercontent.com/your-repo/docker-compose.cloud.yml"
echo "     docker compose -f docker-compose.cloud.yml up -d"
echo ""
echo "  또는 간편 배포 스크립트 실행:"
echo "     curl -sSL https://your-domain/deploy.sh | bash"
echo ""
echo "🌐 서버 접속 URL:"
echo "  http://$(curl -s ifconfig.me):8501"
echo ""
echo "⚠️  주의사항:"
echo "  - 재로그인하여 docker 명령어가 sudo 없이 실행되는지 확인"
echo "  - Oracle Cloud 콘솔에서 8501 포트가 열려있는지 확인"
echo "  - 방화벽 규칙: Ingress Rules → 0.0.0.0/0 → TCP 8501"
echo ""
