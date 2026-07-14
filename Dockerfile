# Streamlit 앱을 위한 Dockerfile
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 필요한 패키지 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 파일 복사
COPY requirements.txt .

# Python 패키지 설치
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
# 2025-12-16 hoyeon.han: Multi-Page App 구조로 변경
# 2025-02-03 hoyeon.han: Scripts 폴더 추가 (사용자 관리용)
COPY Home.py .
COPY pages/ ./pages/
COPY Src/ ./Src/
COPY scripts/ ./scripts/

# Streamlit 설정 파일 복사
COPY .streamlit/ ./.streamlit/

# 2026-07-14 hoyeon.han: 브랜드 자산(로고/심볼 PNG) 복사 추가.
#   누락 시 사이드바 로고·홈 로고·파비콘이 폴백(빈 박스/텍스트/이모지)으로 표시됨.
#   코드가 /app/assets 참조 (Home.py:46, Src/ui_components.py:19).
COPY assets/ ./assets/

# 디렉토리 생성
# 2025-12-16 hoyeon.han: database 디렉토리 추가
RUN mkdir -p logs uploads processed database

# 포트 노출
# 2026-06-11 hoyeon.han: 8502 = 발주내역 API (Src/api_server.py, compose 에서 command 교체로 실행)
EXPOSE 8501 8502

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Streamlit 실행
# 2025-12-16 hoyeon.han: app.py → Home.py 변경
CMD ["streamlit", "run", "Home.py", "--server.port=8501", "--server.address=0.0.0.0", "--browser.gatherUsageStats=false"]
