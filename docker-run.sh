#!/bin/bash

# Docker 컨테이너 실행 스크립트

echo "======================================"
echo "  솔루미랩 Docker 컨테이너 실행"
echo "======================================"
echo ""

# 필수 디렉토리 생성
echo "📁 필요한 디렉토리를 생성합니다..."
mkdir -p logs processed uploads

# Docker Compose로 실행
echo "🚀 컨테이너를 시작합니다..."
docker-compose up -d

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 컨테이너가 시작되었습니다!"
    echo ""
    echo "🌐 브라우저에서 다음 주소로 접속하세요:"
    echo "   http://localhost:8501"
    echo ""
    echo "📋 유용한 명령어:"
    echo "   docker-compose logs -f          # 로그 확인"
    echo "   docker-compose ps               # 상태 확인"
    echo "   docker-compose down             # 컨테이너 종료"
    echo "   docker-compose restart          # 재시작"
    echo ""

    # 로그 따라가기 옵션
    read -p "로그를 실시간으로 보시겠습니까? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "Ctrl+C를 눌러 종료할 수 있습니다 (컨테이너는 계속 실행됨)"
        echo ""
        docker-compose logs -f
    fi
else
    echo ""
    echo "❌ 컨테이너 시작 실패!"
    echo "docker-compose logs를 확인하세요."
    exit 1
fi
