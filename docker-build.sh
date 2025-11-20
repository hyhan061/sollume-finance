#!/bin/bash

# Docker 이미지 빌드 스크립트

echo "======================================"
echo "  솔루미랩 Docker 이미지 빌드"
echo "======================================"
echo ""

# 필수 파일 확인
if [ ! -f "Dockerfile" ]; then
    echo "❌ Dockerfile이 없습니다."
    exit 1
fi

if [ ! -f "docker-compose.yml" ]; then
    echo "❌ docker-compose.yml이 없습니다."
    exit 1
fi

if [ ! -f "Src/거래처마스터.xlsx" ]; then
    echo "⚠️  경고: Src/거래처마스터.xlsx 파일이 없습니다."
    echo "   앱 실행 시 오류가 발생할 수 있습니다."
fi

echo "📦 Docker 이미지를 빌드합니다..."
echo ""

# 이전 이미지 및 컨테이너 정리 (선택사항)
read -p "기존 컨테이너를 정리하시겠습니까? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🧹 기존 컨테이너 정리 중..."
    docker-compose down
fi

# 빌드
docker-compose build

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 빌드 완료!"
    echo ""
    echo "다음 명령으로 실행할 수 있습니다:"
    echo "  ./docker-run.sh"
    echo "  또는"
    echo "  docker-compose up -d"
else
    echo ""
    echo "❌ 빌드 실패!"
    exit 1
fi
