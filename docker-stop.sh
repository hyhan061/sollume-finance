#!/bin/bash

# Docker 컨테이너 종료 스크립트

echo "======================================"
echo "  솔루미랩 Docker 컨테이너 종료"
echo "======================================"
echo ""

echo "🛑 컨테이너를 종료합니다..."
docker-compose down

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 컨테이너가 종료되었습니다."
    echo ""
    echo "💡 데이터는 다음 위치에 보존됩니다:"
    echo "   - logs/"
    echo "   - processed/"
    echo "   - uploads/"
else
    echo ""
    echo "❌ 종료 실패!"
    exit 1
fi
