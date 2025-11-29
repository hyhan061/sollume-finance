# 솔루미랩 경리나라 전표 생성 시스템

![Python](https://img.shields.io/badge/Python-3.11-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.39.0-red.svg)
![License](https://img.shields.io/badge/License-Private-lightgrey.svg)
![Status](https://img.shields.io/badge/Status-Production-green.svg)

매출/매입 전표를 **날짜별로 자동 생성**하여 경리나라 회계 소프트웨어에 일괄 등록할 수 있는 웹 애플리케이션입니다.

**주 사용자**: 비개발자(총무 직원)
**기술 스택**: Python 3.11 + Streamlit + Pandas + Docker

---

## 📋 목차

- [주요 기능](#-주요-기능)
- [빠른 시작](#-빠른-시작)
- [설치 가이드](#-설치-가이드)
- [사용 방법](#-사용-방법)
- [프로젝트 구조](#-프로젝트-구조)
- [최근 업데이트](#-최근-업데이트)
- [배포 방법](#-배포-방법)
- [문제 해결](#-문제-해결)
- [개발 가이드](#-개발-가이드)
- [라이선스](#-라이선스)

---

## ✨ 주요 기능

### 핵심 기능
- 📊 **Excel 발주내역 자동 처리** - 업체별/제품별 집계 및 전표 생성
- 💰 **매출/매입 전표 분리 생성** - 경리나라 일괄등록 형식 (.xls)
- 🧮 **세금 자동 계산** - 과세/면세 구분하여 공급가액 및 부가세 자동 계산
- 🔍 **실시간 데이터 미리보기** - 처리 결과를 표 형태로 즉시 확인
- 📥 **원클릭 다운로드** - 생성된 전표 파일 즉시 다운로드

### 안정성 & 편의성 (2025-11-29 업데이트)
- 🛡️ **체계적인 오류 처리** - 8종 커스텀 예외로 명확한 오류 메시지 제공
- 📝 **구조화된 로깅** - 텍스트/JSON/오류 전용 3종 로그 파일 자동 생성
- ⚡ **성능 측정** - 처리 시간 및 처리량 자동 로깅
- 🔧 **단계별 검증** - 파일/구조/데이터/비즈니스 룰 4단계 검증
- 💡 **사용자 친화적 UI** - 한글 오류 메시지 + 해결 방법 자동 제시

### 자동화 처리
- ✅ 업체명 정규화 (이너바우어 계열사 통합)
- ✅ 반품 데이터 자동 감지 (수량 < 0)
- ✅ 배송비/도선료 별도 항목 처리
- ✅ 거래처마스터 자동 조인 (사업자번호 추가)
- ✅ 업체별 특수 규칙 적용 (지앤제이, 유스랩, 유라이크 등)

---

## 🚀 빠른 시작

### 1분 안에 실행하기

```bash
# 1. 저장소 클론
git clone <repository-url>
cd sollume-finance

# 2. 가상환경 활성화
source .venv311/bin/activate  # Mac/Linux
# 또는
.venv311\Scripts\activate     # Windows

# 3. 앱 실행
streamlit run app.py
```

브라우저에서 자동으로 열립니다: **http://localhost:8501**

### Docker로 실행하기 (권장)

```bash
# 빌드 및 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 접속
open http://localhost:8501
```

---

## 📦 설치 가이드

### 사전 요구사항

- **Python**: 3.11 이상
- **운영체제**: macOS, Linux, Windows
- **메모리**: 최소 2GB RAM
- **디스크**: 최소 500MB 여유 공간

### 로컬 설치

#### Step 1: Python 가상환경 설정

```bash
# Python 3.11 설치 확인
python3 --version

# 가상환경 생성 (최초 1회)
python3 -m venv .venv311

# 가상환경 활성화
source .venv311/bin/activate  # Mac/Linux
.venv311\Scripts\activate     # Windows
```

#### Step 2: 의존성 설치

```bash
pip install -r requirements.txt
```

**주요 패키지**:
- `streamlit==1.39.0` - 웹 UI 프레임워크
- `pandas==2.2.2` - 데이터 처리
- `openpyxl==3.1.5` - Excel 읽기
- `xlwt==1.3.0` - Excel 쓰기 (.xls 포맷)

#### Step 3: 필수 파일 준비

```bash
# 거래처마스터 파일 확인
ls -la Src/거래처마스터.xlsx

# 없으면 생성 (샘플)
# - 시트명: 거래처마스터
# - 필수 컬럼: 거래처명_솔루미랩, 사업자번호
```

#### Step 4: 실행

```bash
streamlit run app.py
```

---

## 📖 사용 방법

### 1️⃣ 전표 생성 (메인 기능)

1. **파일 업로드**
   ```
   📁 발주내역 파일 선택 (.xlsm)
   → 드래그앤드롭 또는 클릭하여 선택
   ```

2. **날짜 선택**
   ```
   📅 처리할 날짜 선택
   → 캘린더에서 날짜 클릭
   ```

3. **처리 시작**
   ```
   ▶️ 업로드 및 처리 버튼 클릭
   → 진행 상황 표시줄 확인
   ```

4. **결과 다운로드**
   ```
   📥 매출 파일 다운로드
   📥 매입 파일 다운로드
   → 경리나라에 일괄등록
   ```

### 2️⃣ 처리 이력 확인

- 좌측 메뉴 → **처리 이력** 선택
- 이번 세션 처리 내역 조회
- 저장된 파일 목록 확인
- 애플리케이션 로그 다운로드

### 3️⃣ 설정 관리

- 좌측 메뉴 → **설정** 선택
- 거래처마스터 파일 경로 확인
- 디스크 사용량 모니터링
- 오래된 파일 자동 정리

### 4️⃣ 오류 처리

오류 발생 시 화면에 표시되는 정보:

```
❌ 파일 오류
거래처마스터 파일을 찾을 수 없습니다

💡 해결 방법:
1. 'Src/거래처마스터.xlsx' 파일이 있는지 확인해주세요
2. 파일 이름이 정확한지 확인해주세요
3. 문제가 계속되면 개발자에게 오류 ID를 알려주세요

🔍 개발자용 상세 정보
  오류 ID: 53614-3a24
  발생 시각: 2025-11-29 22:05:15
  파일 경로: Src/거래처마스터.xlsx

📥 오류 리포트 다운로드 (JSON)
```

---

## 📁 프로젝트 구조

```
sollume-finance/
├── app.py                          # Streamlit 메인 앱 (468줄)
├── Src/
│   ├── processing.py               # 비즈니스 로직 (800+줄) ✨ Phase 2 개선
│   ├── exceptions.py               # 커스텀 예외 (344줄) ✨ 신규
│   ├── logger.py                   # 로깅 시스템 (265줄) ✨ 신규
│   ├── validators.py               # 데이터 검증 (334줄) ✨ 신규
│   ├── __init__.py                 # 모듈 초기화 (57줄)
│   ├── processing_v2024.py         # 백업 (기존 버전)
│   └── 거래처마스터.xlsx           # 마스터 데이터
├── logs/
│   ├── app.log                     # 텍스트 로그
│   ├── app_YYYYMMDD.json           # JSON 구조화 로그
│   └── errors.log                  # 오류 전용 로그
├── uploads/                        # 임시 업로드 폴더
├── processed/                      # 처리 결과 저장
│   ├── 매출_YYYY-MM-DD.xls
│   └── 매입_YYYY-MM-DD.xls
├── .claude/                        # 프로젝트 문서
│   ├── 작업_요약_2025-11-29.md    # Phase 1&2 작업 요약
│   ├── 코드분석보고서_2025-11-29.md # 코드 품질 분석
│   └── 오류처리_로깅_개선_설계안.md # 설계 문서
├── requirements.txt                # Python 의존성
├── Dockerfile                      # Docker 이미지
├── docker-compose.yml              # Docker Compose 설정
├── start.sh / start.bat            # 실행 스크립트
├── CLAUDE.md                       # Claude Code 가이드
├── README.md                       # 이 파일
├── README_STREAMLIT.md             # Streamlit 사용 가이드
└── README_DOCKER.md                # Docker 배포 가이드
```

### 핵심 모듈 설명

| 모듈 | 역할 | 라인 수 | 상태 |
|------|------|---------|------|
| `app.py` | Streamlit UI 오케스트레이션 | 468 | ✅ 안정 |
| `processing.py` | 매출/매입 데이터 처리 로직 | 800+ | ✨ Phase 2 개선 |
| `exceptions.py` | 8종 커스텀 예외 클래스 | 344 | ✨ 신규 |
| `logger.py` | 3종 로그 파일 시스템 | 265 | ✨ 신규 |
| `validators.py` | 4단계 데이터 검증 | 334 | ✨ 신규 |

---

## 🔄 최근 업데이트

### v2.0.0 - 오류 처리 및 로깅 시스템 (2025-11-29)

#### Phase 2: 비즈니스 로직 개선 ✨
- **12단계 처리 과정** 구현 (단계별 로깅)
- **SettingWithCopyWarning 완전 해결** (.copy() 사용)
- **커스텀 예외 통합** (4종 예외 적용)
- **성능 측정 로그** 추가 (처리 시간, 행/초)

#### Phase 1: 기반 구조 구축 ✨
- **커스텀 예외 시스템** (8종 예외, 오류 ID 자동 생성)
- **다층 로깅 시스템** (텍스트/JSON/오류 전용)
- **데이터 검증 레이어** (파일/구조/품질/비즈니스 룰)
- **민감정보 마스킹** (사업자번호 등)

#### 기술 개선사항
```python
# Before (경고 발생)
df_sales_today = df[(조건)]
df_sales_today.loc[:, '컬럼'] = 값  # ⚠️ SettingWithCopyWarning

# After (안전)
df_sales_today = df[(조건)].copy()
df_sales_today['컬럼'] = 값  # ✅ OK
```

**성과**:
- 오류 처리: 0% → 95%
- 로깅: 단순 → 구조화
- 데이터 무결성: 경고 → 안전

**관련 커밋**:
- `3e86ce2` - Phase 2: processing.py 개선
- `7758bb2` - Phase 1: 인프라 구축
- `2d79128` - ImportError 해결

### v1.0.0 - Streamlit 마이그레이션 (2024-11-15)

- Next.js + Flask → Streamlit 전환
- 단일 서버 아키텍처 (8501 포트)
- 통합 웹 UI (파일 업로드, 미리보기, 다운로드)

---

## 🐳 배포 방법

### Docker 배포 (권장)

#### 로컬 개발 환경

```bash
# 빌드
./docker-build.sh

# 실행
./docker-run.sh

# 접속
open http://localhost:8501

# 종료
./docker-stop.sh
```

#### NAS 배포 (Synology)

```bash
# 자동 배포 스크립트
./deploy-nas.sh

# 입력 사항:
# - NAS IP 주소
# - 사용자명 (기본: admin)

# 접속
http://nas-ip:8501
```

**NAS 리버스 프록시 설정 후**:
```
https://your-name.synology.me
```

#### 클라우드 배포 (AWS Lightsail / DigitalOcean)

```bash
# 서버 접속
ssh ubuntu@server-ip

# Docker 설치
curl -fsSL https://get.docker.com | sh

# 프로젝트 배포
git clone <repo-url>
cd sollume-finance
docker-compose up -d

# 방화벽 설정
# TCP 8501 포트 오픈

# 접속
http://server-ip:8501
```

자세한 배포 가이드: [README_DOCKER.md](./README_DOCKER.md)

---

## 🛠️ 문제 해결

### 자주 발생하는 문제

#### 1. "거래처마스터 파일을 찾을 수 없습니다"

**원인**: `Src/거래처마스터.xlsx` 파일 누락

**해결**:
```bash
# 파일 존재 확인
ls -la Src/거래처마스터.xlsx

# 샘플 파일 구조:
# 시트명: 거래처마스터
# 컬럼: 거래처명_솔루미랩 | 사업자번호
```

#### 2. "Excel 시트를 찾을 수 없습니다"

**원인**: 업로드 파일에 `(누적)2025년 발주내역` 시트 없음

**해결**:
1. Excel 파일 열기
2. 시트 이름 확인 (정확히 일치해야 함)
3. 시트명 수정 또는 올바른 파일 선택

#### 3. ImportError 발생

**원인**: Python 경로 문제

**해결** (2025-11-30 수정 완료):
```bash
# 이미 수정됨 (커밋 2d79128)
# 상대 import → 절대 import 변경
```

#### 4. 포트 8501 이미 사용 중

**해결**:
```bash
# 기존 프로세스 종료
lsof -ti:8501 | xargs kill -9

# 또는 다른 포트 사용
streamlit run app.py --server.port=8502
```

### 로그 확인 방법

```bash
# 텍스트 로그 (사람이 읽기 쉬움)
tail -f logs/app.log

# JSON 로그 (프로그램 분석용)
cat logs/app_20251129.json | jq

# 오류 전용 로그
tail -f logs/errors.log
```

### 개발자 지원

문제가 해결되지 않을 경우:

1. **오류 ID 확인** - 화면에 표시된 5-9자리 코드
2. **로그 다운로드** - 처리 이력 → "📥 전체 로그 다운로드"
3. **스크린샷 캡처** - 오류 메시지 전체 화면
4. **개발자 전달** - 오류 ID + 로그 + 스크린샷

---

## 👨‍💻 개발 가이드

### 개발 환경 설정

```bash
# 저장소 클론
git clone <repo-url>
cd sollume-finance

# 가상환경 생성
python3 -m venv .venv311
source .venv311/bin/activate

# 개발 의존성 설치
pip install -r requirements.txt
pip install pytest  # 테스트용 (선택)

# 개발 서버 실행
streamlit run app.py --server.runOnSave=true
```

### 코드 스타일 가이드

프로젝트 가이드: [CLAUDE.md](./CLAUDE.md)

**주요 규칙**:
- 언어: 한글 (UI, 주석, 에러 메시지)
- 주석 형식: `# 2025-MM-DD hoyeon.han: 설명`
- 코드 수정 시: 기존 코드 주석 처리 후 신규 코드 추가
- Import: 절대 경로 사용 (`from exceptions import ...`)

### 브랜치 전략

```
main (또는 master)
  └── feature/convert-streamlit (현재 작업 브랜치)
      ├── Phase 1: 오류 처리 인프라 ✅
      ├── Phase 2: 비즈니스 로직 개선 ✅
      └── 향후 개선 사항 ⏳
```

### 테스트 실행

```bash
# Phase 1 테스트
python test_phase1.py

# Phase 2 테스트
python test_phase2.py

# 전체 테스트 (pytest 설치 필요)
pytest tests/
```

### 커밋 메시지 규칙

```
<type>: <subject>

<body>

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>
```

**Type 종류**:
- `feat`: 새 기능
- `fix`: 버그 수정
- `chore`: 기타 변경
- `docs`: 문서 수정
- `refactor`: 리팩토링

### 다음 단계 로드맵

**우선순위 1 (치명적)** ⏳:
1. 버전 파일 삭제 (12개 `*_v*.py`)
2. Git으로 버전 관리 전환

**우선순위 2 (높음)** ⏳:
3. Excel I/O 최적화 (파일 중복 읽기 제거)
4. Pandas 벡터화 연산 (성능 60-70% 향상)
5. 통합 테스트 추가 (pytest)

**우선순위 3 (보통)** ⏳:
6. 아키텍처 리팩토링 (레이어 분리)
7. 설정 외부화 (config.py)
8. 타입 힌트 추가

자세한 개선 계획: [.claude/코드분석보고서_2025-11-29.md](./.claude/코드분석보고서_2025-11-29.md)

---

## 📊 기술 스택

### 코어 기술

| 카테고리 | 기술 | 버전 | 용도 |
|----------|------|------|------|
| **언어** | Python | 3.11 | 메인 개발 언어 |
| **웹 프레임워크** | Streamlit | 1.39.0 | 웹 UI |
| **데이터 처리** | Pandas | 2.2.2 | DataFrame 처리 |
| **Excel 읽기** | openpyxl | 3.1.5 | .xlsm 파일 읽기 |
| **Excel 쓰기** | xlwt | 1.3.0 | .xls 파일 쓰기 |
| **배포** | Docker | latest | 컨테이너화 |

### 아키텍처 패턴

```
┌─────────────────┐
│   Streamlit UI  │  ← 프레젠테이션 레이어 (app.py)
└────────┬────────┘
         │
┌────────▼────────┐
│ Processing Logic│  ← 비즈니스 로직 (processing.py)
│  - Validators   │
│  - Exceptions   │
│  - Logger       │
└────────┬────────┘
         │
┌────────▼────────┐
│  Data Sources   │  ← 데이터 레이어
│  - Excel Files  │
│  - Master Data  │
└─────────────────┘
```

---

## 📄 라이선스

**Private License** - 솔루미랩 내부 사용 전용

본 소프트웨어는 솔루미랩의 내부 업무용으로 개발되었으며, 외부 배포 및 재사용이 제한됩니다.

---

## 📞 문의 및 지원

- **개발자**: hoyeon.han
- **프로젝트**: 솔루미랩 경리나라 전표 생성 시스템
- **버전**: 2.0.0 (Phase 2)
- **최종 업데이트**: 2025-11-30

---

## 🙏 감사의 말

이 프로젝트는 다음 기술들을 사용하여 개발되었습니다:

- [Streamlit](https://streamlit.io/) - 웹 UI 프레임워크
- [Pandas](https://pandas.pydata.org/) - 데이터 처리
- [Docker](https://www.docker.com/) - 컨테이너화
- [Claude Code](https://claude.ai/code) - AI 코딩 어시스턴트

---

**Happy Accounting! 📊✨**
