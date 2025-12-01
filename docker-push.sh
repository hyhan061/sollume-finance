#!/bin/bash

# Docker Hub에 이미지 푸시 스크립트
# 작성일: 2025-11-30
# 작성자: hoyeon.han

set -e  # 오류 발생 시 즉시 종료

echo "================================================"
echo "  솔루미랩 Docker Hub 배포"
echo "================================================"
echo ""

# 설정
DOCKER_USERNAME="hoyeonhan"
DOCKER_REPO="sollume-lab"
IMAGE_NAME="${DOCKER_USERNAME}/${DOCKER_REPO}"

# Git 태그로부터 버전 가져오기 (없으면 latest)
VERSION=$(git describe --tags --always 2>/dev/null || echo "latest")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

echo "📦 빌드 정보:"
echo "  - 이미지: ${IMAGE_NAME}"
echo "  - 버전: ${VERSION}"
echo "  - 커밋: ${GIT_COMMIT}"
echo ""

# Docker 로그인 확인
echo "🔐 Docker Hub 로그인 확인..."
if ! docker info | grep -q "Username: ${DOCKER_USERNAME}"; then
    echo "Docker Hub에 로그인이 필요합니다."
    docker login
    if [ $? -ne 0 ]; then
        echo "❌ Docker Hub 로그인 실패!"
        exit 1
    fi
fi
echo "✅ Docker Hub 로그인 완료"
echo ""

# 멀티 플랫폼 빌드 확인 (Oracle Cloud는 ARM64)
echo "🏗️  멀티 플랫폼 빌더 설정 확인..."
if ! docker buildx ls | grep -q "sollume-builder"; then
    echo "멀티 플랫폼 빌더 생성 중..."
    docker buildx create --name sollume-builder --use
    docker buildx inspect --bootstrap
fi
echo "✅ 빌더 준비 완료"
echo ""

# 이미지 빌드 (AMD64 + ARM64)
echo "🔨 Docker 이미지 빌드 중..."
echo "  플랫폼: linux/amd64, linux/arm64"
echo ""

docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --tag ${IMAGE_NAME}:${VERSION} \
    --tag ${IMAGE_NAME}:latest \
    --tag ${IMAGE_NAME}:${GIT_COMMIT} \
    --push \
    --progress=plain \
    .

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 이미지 푸시 완료!"
    echo ""
    echo "📋 생성된 태그:"
    echo "  - ${IMAGE_NAME}:${VERSION}"
    echo "  - ${IMAGE_NAME}:latest"
    echo "  - ${IMAGE_NAME}:${GIT_COMMIT}"
    echo ""
    echo "🌐 Docker Hub에서 확인:"
    echo "  https://hub.docker.com/r/${DOCKER_USERNAME}/${DOCKER_REPO}"
    echo ""
    echo "🚀 Oracle Cloud에서 실행:"
    echo "  docker pull ${IMAGE_NAME}:latest"
    echo "  docker run -d -p 8501:8501 ${IMAGE_NAME}:latest"
    echo ""
else
    echo ""
    echo "❌ 이미지 푸시 실패!"
    exit 1
fi

# 로컬 이미지 정리 (선택)
read -p "로컬 빌드 캐시를 정리하시겠습니까? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🧹 빌드 캐시 정리 중..."
    docker buildx prune -f
    echo "✅ 정리 완료"
fi

echo ""
echo "🎉 배포 준비 완료!"
