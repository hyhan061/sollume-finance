#!/bin/bash

# 2025-12-09 hoyeon.han: 솔루미랩 경리나라 전표 생성 앱 시작 스크립트 (Mac/Linux)
# 개선 사항: 에러 처리 강화, 필수 디렉토리 생성, 가상환경 체크

echo "======================================"
echo "  솔루미랩 경리나라 전표 생성 앱"
echo "======================================"
echo ""

# =============================================================================
# 2025-12-09 hoyeon.han: 필수 디렉토리 생성
# logs, uploads, processed 폴더가 없으면 앱 실행 시 오류 발생
# =============================================================================
echo "📁 필수 디렉토리 확인 중..."
mkdir -p logs uploads processed
echo "   ✓ logs, uploads, processed 디렉토리 준비 완료"
echo ""

# =============================================================================
# 2025-12-09 hoyeon.han: 가상환경 존재 여부 확인
# bin/activate 파일이 없으면 가상환경이 설정되지 않은 것
# =============================================================================
if [ ! -f ".venv311/bin/activate" ]; then
    echo "❌ 가상환경이 설정되어 있지 않습니다."
    echo ""
    echo "다음 명령으로 가상환경을 생성하세요:"
    echo "  python3 -m venv ."
    echo "  source bin/activate"
    echo "  pip install -r requirements.txt"
    echo ""
    exit 1
fi

# =============================================================================
# 2025-12-09 hoyeon.han: 가상환경 활성화
# =============================================================================
echo "🔧 가상환경 활성화 중..."
source .venv311/bin/activate

if [ $? -ne 0 ]; then
    echo "❌ 가상환경 활성화 실패!"
    exit 1
fi
echo "   ✓ 가상환경 활성화 완료"
echo ""

# =============================================================================
# 2025-12-09 hoyeon.han: 필수 파일 확인
# =============================================================================
echo "📋 필수 파일 확인 중..."

if [ ! -f "app.py" ]; then
    echo "❌ app.py 파일이 없습니다!"
    exit 1
fi
echo "   ✓ app.py 존재"

if [ ! -f "Src/거래처마스터.xlsx" ]; then
    echo "⚠️  경고: Src/거래처마스터.xlsx 파일이 없습니다."
    echo "   앱 실행 시 오류가 발생할 수 있습니다."
else
    echo "   ✓ 거래처마스터.xlsx 존재"
fi
echo ""

# =============================================================================
# 2025-12-09 hoyeon.han: Streamlit 및 필수 패키지 설치 확인
# =============================================================================
echo "📦 필수 패키지 확인 중..."
if ! pip show streamlit > /dev/null 2>&1; then
    echo "   Streamlit이 설치되어 있지 않습니다."
    echo "   필요한 패키지를 설치합니다..."
    pip install -r requirements.txt

    if [ $? -ne 0 ]; then
        echo "❌ 패키지 설치 실패!"
        exit 1
    fi
else
    echo "   ✓ Streamlit 설치됨"
fi
echo ""

# =============================================================================
# 2025-12-09 hoyeon.han: Streamlit 앱 실행
# =============================================================================
echo "🚀 앱을 시작합니다..."
echo ""
echo "✨ 브라우저가 자동으로 열립니다."
echo "📍 수동 접속: http://localhost:8501"
echo ""
echo "⚠️  종료하려면 Ctrl+C를 누르세요."
echo "======================================"
echo ""

# Streamlit 앱 실행
# --server.port 8501: 포트 번호
# --server.address localhost: 로컬에서만 접근 가능
# --browser.gatherUsageStats false: 사용 통계 수집 안함
streamlit run app.py --server.port 8501 --server.address localhost --browser.gatherUsageStats false
