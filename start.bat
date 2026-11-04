@echo off
REM 2026-10-14 hoyeon.han: 이전 시작 스크립트 보존(실행되지 않음)
REM @echo off
REM REM 솔루미랩 경리나라 전표 생성 앱 시작 스크립트 (Windows)
REM
REM echo ======================================
REM echo   솔루미랩 경리나라 전표 생성 앱
REM echo ======================================
REM echo.
REM
REM REM 가상환경 활성화
REM echo 가상환경 활성화 중...
REM call .\Scripts\activate.bat
REM
REM REM Streamlit 설치 확인
REM pip show streamlit >nul 2>&1
REM if errorlevel 1 (
REM     echo Streamlit이 설치되어 있지 않습니다.
REM     echo 필요한 패키지를 설치합니다...
REM     pip install -r requirements.txt
REM )
REM
REM echo.
REM echo 앱을 시작합니다...
REM echo 브라우저가 자동으로 열립니다.
REM echo.
REM echo 종료하려면 Ctrl+C를 누르세요.
REM echo.
REM
REM REM Streamlit 앱 실행
REM streamlit run app.py --server.port 8501 --server.address localhost --browser.gatherUsageStats false
REM
REM pause

REM 2026-10-14 hoyeon.han: Windows도 Home.py와 인증 서버를 가상환경에서 함께 실행
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv311\Scripts\python.exe" (
    echo 가상환경이 없습니다. py -3.11 -m venv .venv311 후 의존성을 설치하세요.
    exit /b 1
)
call .venv311\Scripts\activate.bat
python -c "import streamlit, flask, pyotp, cryptography, argon2, qrcode" >nul 2>&1
if errorlevel 1 (
    python -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
)
python scripts/run_local.py
exit /b %errorlevel%
