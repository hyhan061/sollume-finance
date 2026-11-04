#!/usr/bin/env bash
# 2026-10-14 hoyeon.han: 기존 배포 스크립트 보존(실행되지 않음)
# #!/bin/bash
#
# # Docker 컨테이너 실행 스크립트
#
# echo "======================================"
# echo "  솔루미랩 Docker 컨테이너 실행"
# echo "======================================"
# echo ""
#
# # 필수 디렉토리 생성
# echo "📁 필요한 디렉토리를 생성합니다..."
# mkdir -p logs processed uploads
#
# # Docker Compose로 실행
# echo "🚀 컨테이너를 시작합니다..."
# docker-compose up -d
#
# if [ $? -eq 0 ]; then
#     echo ""
#     echo "✅ 컨테이너가 시작되었습니다!"
#     echo ""
#     echo "🌐 브라우저에서 다음 주소로 접속하세요:"
#     echo "   http://localhost:8501"
#     echo ""
#     echo "📋 유용한 명령어:"
#     echo "   docker-compose logs -f          # 로그 확인"
#     echo "   docker-compose ps               # 상태 확인"
#     echo "   docker-compose down             # 컨테이너 종료"
#     echo "   docker-compose restart          # 재시작"
#     echo ""
#
#     # 로그 따라가기 옵션
#     read -p "로그를 실시간으로 보시겠습니까? (y/N): " -n 1 -r
#     echo
#     if [[ $REPLY =~ ^[Yy]$ ]]; then
#         echo ""
#         echo "Ctrl+C를 눌러 종료할 수 있습니다 (컨테이너는 계속 실행됨)"
#         echo ""
#         docker-compose logs -f
#     fi
# else
#     echo ""
#     echo "❌ 컨테이너 시작 실패!"
#     echo "docker-compose logs를 확인하세요."
#     exit 1
# fi

# 2026-10-14 hoyeon.han: 인증·HTTPS 준비 후에만 Docker 서비스를 실행한다.
set -euo pipefail
cd "$(dirname "$0")"
if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose v2가 필요합니다. 설치 후 다시 실행하세요." >&2
    exit 1
fi
if [ ! -f .env ] || [ ! -f ssl/fullchain.pem ] || [ ! -f ssl/privkey.pem ]; then
    echo ".env의 운영 인증키·HTTPS 주소·API 키와 ssl의 실제 인증서를 준비하세요." >&2
    echo "안내: .Codex/user-management/OPERATIONS.md" >&2
    exit 1
fi
docker compose -f docker-compose.yml config --quiet
mkdir -p logs processed uploads database order_data
docker compose -f docker-compose.yml up -d --wait --wait-timeout 120
echo "서비스 준비 완료: https://sollumeesthe.com"
echo "최초 관리자 인증 앱 등록과 직원별 화면 권한은 운영 안내를 따라 설정하세요."
echo "8501·8502·8503 포트를 외부에 개방하지 않습니다."
