@echo off
REM 솔루미랩 경리나라 전표 생성 앱 시작 스크립트 (Windows)

echo ======================================
echo   솔루미랩 경리나라 전표 생성 앱
echo ======================================
echo.

REM 가상환경 활성화
echo 가상환경 활성화 중...
call .\Scripts\activate.bat

REM Streamlit 설치 확인
pip show streamlit >nul 2>&1
if errorlevel 1 (
    echo Streamlit이 설치되어 있지 않습니다.
    echo 필요한 패키지를 설치합니다...
    pip install -r requirements.txt
)

echo.
echo 앱을 시작합니다...
echo 브라우저가 자동으로 열립니다.
echo.
echo 종료하려면 Ctrl+C를 누르세요.
echo.

REM Streamlit 앱 실행
streamlit run app.py --server.port 8501 --server.address localhost --browser.gatherUsageStats false

pause
