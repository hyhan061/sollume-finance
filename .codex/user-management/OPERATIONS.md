<!-- 2026-10-14 hoyeon.han: 사내 직원 전용 필수 MFA·화면 권한·다운로드 보호 운영 안내 -->
# 사용자관리 운영 안내

이 구성은 현재 회계 시스템 전용입니다. 외부 진입점은 `https://sollumeesthe.com`의 Nginx이고, 회계앱(8501), 발주내역 자동화 API(8502), 인증 서버(8503)는 직접 인터넷에 공개하지 않습니다. 로컬 개발은 별도의 시작 스크립트로 두 프로그램을 가상환경과 루프백 주소에서 실행합니다.

## 적용 전 확인

- 운영 서버에서 기존 `database/users.db`, `database/customer_master.db`, `order_data/`, `uploads/`, `processed/`를 유지합니다. 새 배포 폴더에 빈 DB를 만드는 방식으로 교체하지 않습니다.
- 실행 중인 SQLite는 단순 복사 대신 SQLite `backup`으로 일관된 백업을 만듭니다. 인증 마이그레이션은 기존 사용자 표에 열과 별도 보안 표를 추가하며, 사용자 ID·기존 비밀번호 해시·이름·이메일·기존 로그인 이력을 보존합니다. 최초 전환 전에 `users.db.pre-security.bak`도 한 번 생성합니다.
- 기존 계정은 최초 전환 후에도 기존 아이디·비밀번호로 등록을 시작합니다. 비밀번호만으로 업무에 접속할 수는 없습니다. 관리자가 발급한 단회 등록 코드, 새 비밀번호, 실제 인증 앱 번호가 필요합니다.
- Cloud 구성은 기존 `./거래처마스터.xlsx`의 읽기 전용 fallback 마운트도 보존합니다. 기존 파일을 유지하고, 현재 업무의 거래처 원본은 영속 `customer_master.db`를 사용합니다.
- 기존 일반 직원의 업무 화면 권한은 호환을 위해 초기 유지합니다. 시스템 관리·사용자관리는 관리자만 접근합니다. **공개 전에 관리자가 모든 기존 직원의 허용 화면을 명시적으로 검토하세요.** 새 직원의 기본 화면 권한은 없음입니다.
- 운영 키 `AUTH_ENCRYPTION_KEY`는 DB와 분리하여 비공개 보관·백업합니다. 다른 키로 임의 교체하면 기존 MFA 암호문을 읽을 수 없습니다. 키 분실 시 서버 운영자가 본인을 확인하고 MFA 등록을 초기화해야 합니다.
- 이 문서의 운영 명령은 운영자가 검토하고 실행하는 절차입니다. 개발·테스트 과정에서 실제 운영 DB, `.env`, 계정, 서버 또는 DNS를 변경하지 않습니다.

## 공통 환경 설정

`.env.example`을 `.env`로 복사하여 다음 값을 채웁니다. 기존 `ORDER_API_KEY`는 유지합니다. 키를 채운 `.env`나 Docker의 전체 설정 출력은 Git·채팅·로그에 남기지 않습니다.

```dotenv
AUTH_PUBLIC_ORIGIN=https://sollumeesthe.com
AUTH_ENCRYPTION_KEY=<별도로 생성한 Fernet 키>
ORDER_API_KEY=<기존 발주내역 API 키>
```

개발 PC에서는 가상환경에서 다음 명령으로 새 운영 키를 생성할 수 있습니다. 터미널에 표시된 키를 비공개 설정에 저장한 뒤 터미널 출력의 보관·공유에 주의하세요. 이것은 운영자가 직접 실행하는 생성 명령이며, 자동 생성되는 운영 기본 키는 없습니다.

```bash
source .venv311/bin/activate
python -m pip install -r requirements.txt
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

`AUTH_ENV=production`은 운영 Compose에서 지정합니다. 운영 `AUTH_PUBLIC_ORIGIN`은 HTTPS 주소여야 하며, 현재 Nginx 설정의 `sollumeesthe.com`과 일치해야 합니다. 별도 `AUTH_SIGNING_KEY`를 설정하지 않으면 인증 암호화 키에서 CSRF 쿠키 전용 서명 키를 용도를 구분하여 파생합니다.

회계앱과 인증 서버는 다음 설정·마운트를 공유합니다.

| 항목 | 운영 값 |
|---|---|
| 사용자 DB | `/app/database/users.db` ← 기존 `./database` |
| 비공개 다운로드 | `/app/processed/secure_downloads` ← `./processed` |
| 암호화 키·공개 주소 | 두 서비스에 동일하게 전달 |
| 신뢰 프록시 | Docker Nginx `172.30.0.10/32` 또는 호스트 Nginx 경유 `172.30.0.1/32`, 서비스 내부 상태 검사용 `127.0.0.1/32` |

Compose는 Docker 내부 네트워크를 `172.30.0.0/24`로 지정합니다. 기존 VPN·다른 Docker 네트워크와 충돌하면 네트워크 대역·게이트웨이·Nginx 고정 IP·신뢰 프록시 설정을 함께 수정해야 합니다. 실제 연결 대역을 확인하지 않고 모든 IP를 신뢰하도록 바꾸지 않습니다.

## HTTPS 및 포트

두 가지 운영 배치를 선택할 수 있습니다. 동시에 두 Nginx가 같은 80·443 포트를 사용하지 않습니다.

| 배치 | 구성 |
|---|---|
| Docker Nginx | `docker-compose.yml`, `nginx.conf`. Nginx만 80·443을 게시하고 내부 서비스는 `expose`만 사용 |
| Oracle 호스트 Nginx | `docker-compose.cloud.yml`, `nginx-host-api.conf.example`. 내부 서비스는 모두 `127.0.0.1`에만 게시 |

Docker Nginx의 실제 TLS 인증서는 `./ssl/fullchain.pem`, `./ssl/privkey.pem`으로 준비합니다. 호스트 Nginx 예시는 `/etc/letsencrypt/live/sollumeesthe.com/`의 실제 인증서를 사용합니다. 인증서 준비·갱신은 기존 운영 인증서 발급 절차를 따릅니다. 인증서가 없으면 HTTPS Nginx 시작을 중단하며 HTTP 업무 접속으로 폴백하지 않습니다. 80 포트는 HTTPS 이동만 제공합니다. 인증서 갱신에 HTTP-01 방식이 필요하다면 인증서 발급 도구의 전용 경로 설정을 별도로 검토해야 합니다.

호스트 Nginx 예시는 **전체 사이트 설정**입니다. 이전의 무인증 `location /`에 일부 경로만 덧붙이지 않습니다. 기존 설정을 백업하고, 동일 도메인의 기존 80·443 server와 중복하지 않게 적용합니다.

```bash
sudo nginx -V
sudo nginx -t
sudo systemctl reload nginx
```

`nginx -V`에서 `http_auth_request_module` 지원을 확인합니다. 문법·인증서 검사를 통과한 경우에만 재적용합니다. Cloud 배포 스크립트는 기본적으로 `/etc/nginx/sites-enabled/sollume-finance`를 검사합니다. 실제 전용 파일 경로가 다르면 `SOLLUME_NGINX_SITE_CONFIG`에 그 경로를 지정합니다.

서버 방화벽·Cloud Ingress에서는 HTTPS 443과 필요한 HTTP 80만 업무 접속에 사용합니다. 8501·8502·8503에 대한 `0.0.0.0/0` 허용 규칙은 제거합니다. 운영자 SSH 접속은 별도 기존 정책으로 제한합니다. 서버 외부에서 직접 포트 접속이 실패하는지도 확인합니다.

## 기존 관리자와 첫 등록

새 이미지에 인증 코드·템플릿·의존성이 포함되어야 합니다. 기존 `latest` 이미지가 인증 기능을 포함하는지 먼저 확인하고 새 버전을 빌드·게시합니다. 기존 DB를 삭제하거나 초기 사용자 데이터를 이미지에 넣지 않습니다.

<!-- 2026-10-14 hoyeon.han: Docker 가상환경 및 운영 CLI의 Python 경로 설명 -->
수정된 Dockerfile로 이미지를 빌드하면 `/opt/venv` 가상환경에 의존성을 설치하고 `VIRTUAL_ENV`와 `PATH`를 설정합니다. 회계앱·인증 서버·자동화 API·관리 CLI의 `python`, `pip`, `streamlit`, `gunicorn`은 이 가상환경을 사용합니다. 아래의 기존 `--entrypoint python` 명령도 `/opt/venv/bin/python`을 실행하여 CLI의 가상환경 검사를 통과합니다.

다음 명령은 사용자 DB를 보존하여 필요한 스키마만 준비합니다. 기존 활성 관리자가 있으면 새 관리자·기본 계정을 만들지 않습니다.

```bash
docker compose -f docker-compose.cloud.yml run --rm --no-deps --entrypoint python sollume-auth scripts/init_users_db.py
docker compose -f docker-compose.cloud.yml run --rm --no-deps --entrypoint python sollume-auth scripts/manage_users.py --list
```

기존 관리자에게 등록 코드를 발급합니다. 아래 `관리자아이디`는 실제 기존 아이디로 바꿉니다. 명령은 확인을 받은 후 기존 로그인·MFA 등록을 폐기하고 새 코드를 표시합니다. 이 명령은 서버 운영자 전용이며 인터넷 API로 공개하지 않습니다.

```bash
docker compose -f docker-compose.cloud.yml run --rm --no-deps --entrypoint python sollume-auth scripts/manage_users.py --enroll 관리자아이디
```

기존 계정이 전혀 없는 설치만 `init_users_db.py`에서 입력한 새 관리자를 만듭니다. 비밀번호는 숨김 입력이며 기본 비밀번호가 없습니다. 등록 코드는 24시간 유효하고 1회만 사용할 수 있으므로 본인을 확인한 비공개 채널로 전달합니다.

관리자는 HTTPS 로그인 화면에서 기존 비밀번호를 입력하고, 등록 코드를 확인한 뒤 인증 앱으로 QR을 스캔합니다. 12자 이상의 새 비밀번호와 인증 앱의 6자리 번호를 입력하여 최초 등록을 마칩니다. QR과 인증 비밀키는 서버 내부에서 생성되며 외부 QR 생성 서비스로 전달하지 않습니다. 이후에는 아이디·비밀번호와 인증 앱 번호가 모두 필요합니다.

## 직원 생성·화면 권한

관리자만 사용자관리 화면을 열 수 있습니다. 계정 생성, 활성 상태·관리자 역할 변경, 화면 권한 설정, 비밀번호 초기화, MFA 초기화, 잠금 해제, 변경 이력 조회를 제공합니다. 중요한 변경 직전에 최근 인증이 없으면 현재 비밀번호와 새로운 인증 번호로 재확인합니다.

일반 직원에게 선택할 수 있는 업무 화면은 일별 전표·기간 전표·특정업체 전표·정산서·셀러 정산서·이카운트 정산서·요약·비교·거래처 관리입니다. 홈·본인 계정관리는 로그인한 직원에게 제공하고 시스템 관리·사용자관리는 관리자 전용입니다. 일반 직원에게 관리자 전용 화면을 직접 선택해 부여할 수 없습니다. 마지막 활성 관리자는 정지하거나 직원으로 변경할 수 없습니다.

권한은 메뉴뿐 아니라 페이지 실행과 저장·삭제·다운로드 작업 직전에 서버에서 검사합니다. 계정 정지·역할 변경·화면 권한 변경·비밀번호 초기화·MFA 초기화 시 기존 로그인과 미완료 로그인 도전을 폐기합니다. 재로그인이 필요합니다. 공유 발주내역·거래처 데이터·과거 결과 파일 자체는 계정 정지 시 삭제하지 않습니다.

페이지 단위 권한은 한 업무 화면에 대한 권한입니다. 예를 들어 거래처 관리 화면을 허용하면 그 화면의 관리 작업도 허용됩니다. 이 구현은 업체별 행 제한이나 거래처 조회와 수정의 별도 권한까지 제공하는 설계가 아닙니다.

## 세션·파일·복구

- 로그인 세션은 30분 미사용 또는 로그인 후 최대 8시간에 만료됩니다. 상태 확인만 하는 호출은 미사용 시간을 연장하지 않습니다. 로그인 쿠키는 운영에서 `__Host-` 이름·Secure·HttpOnly·SameSite·Path `/`를 적용하며 비밀번호·인증키를 담지 않습니다.
- 비밀번호 또는 MFA를 반복 실패하면 계정과 요청 IP 단위로 제한합니다. 제한은 DB에 저장되어 새 브라우저·서비스 재시작으로 사라지지 않습니다. 인증 앱 번호는 동일한 시간 구간에서 재사용할 수 없습니다. 휴대전화와 서버 시간이 맞아야 합니다.
- 다운로드는 원래 로그인한 사용자·정확한 로그인 세션·관련 화면 권한·파일 만료를 재검사합니다. 생성한 다운로드 권한은 15분 동안 유효합니다. 다른 직원이나 같은 직원의 다른 세션에도 전달되지 않습니다. 이전 `/media` 경로는 Nginx에서 403으로 막습니다.
- 인증 서버 장애·세션 만료·계정 정지·권한 폐기 시 다음 요청부터 업무 접근과 다운로드를 막습니다. 열려 있는 화면은 주기적으로 상태를 확인합니다. 이미 화면에 표시됐거나 PC에 내려받은 자료까지 회수하는 것은 아닙니다.
- 직원이 휴대전화를 분실하면 관리자가 본인 확인 후 MFA 등록을 초기화합니다. 새 코드를 받아 다시 인증 앱을 등록해야 하며 기존 로그인은 폐기됩니다. 관리자도 인증 기기를 잃어 로그인할 수 없다면 서버 운영자만 CLI의 `--enroll` 절차로 복구합니다.
- 비밀번호를 잃어버린 경우 서버 운영자 CLI 또는 사용자관리 화면에서 임시 비밀번호를 설정하고 본인에게 비공개 전달합니다. 다음 로그인 시 직원이 비밀번호를 다시 변경합니다. 비밀번호와 인증키는 조회할 수 없습니다.

## 로컬 개발과 종료

```bash
./start.sh
```

Windows는 `.venv311\Scripts\python.exe`가 준비된 뒤 `start.bat`을 실행합니다. 두 스크립트는 `scripts/run_local.py`를 호출하여 인증 서버와 `Home.py`를 같은 가상환경에서 실행합니다. 인증은 `http://localhost:8503`, 회계앱은 `http://localhost:8501`이며 둘 다 `127.0.0.1`에서만 수신합니다. 인증 서버가 준비되지 않으면 회계앱을 시작하지 않습니다. 어느 한 프로그램이 종료되거나 Ctrl+C를 누르면 두 프로그램을 정리합니다.

개발 암호화 키는 Git에서 제외된 `database/auth-development.key`에 한 번 생성하여 보존합니다. 운영 모드나 공개 주소로 로컬 실행을 바꾸지 않습니다. 운영 MFA를 등록한 DB를 다른 개발 키로 열면 기존 MFA를 검증할 수 없으므로 테스트는 임시 DB를 사용합니다.

로컬 최초 관리자 준비·기존 관리자 등록 코드는 동일 개발 키를 사용하도록 다음 명령에 `--development`를 지정합니다.

```bash
source .venv311/bin/activate
python scripts/init_users_db.py --development
python scripts/manage_users.py --development --enroll 관리자아이디
```

## 검증과 배포

자동 검증은 `.Codex/tests/`에서 임시 DB와 가짜 시험 계정을 사용합니다. 기존 DB의 스키마와 계정 보존, 비밀번호만으로 접근 차단, 인증 등록 코드·실제 TOTP, 재사용·실패 제한, 관리자·직원 권한, 정지·권한 변경의 기존 세션 폐기, 세션과 파일 만료, 소유자와 세션별 파일 제한, CSRF·HTTPS·Host 보호, 운영 포트 제한과 로컬 종료를 확인합니다.

```bash
source .venv311/bin/activate
python -m pytest -q .Codex/tests --confcutdir=.Codex -o norecursedirs=
docker compose -f docker-compose.cloud.yml config --quiet
bash -n start.sh
bash -n deploy-oracle.sh
```

대소문자를 구분하지 않는 macOS에서는 기존 `.codex`와 `.Codex`가 같은 디렉토리이므로 pytest에 실제 디렉토리명 `.codex/tests`를 전달하거나 위처럼 `--confcutdir`를 지정할 수 있습니다. Docker 전체 설정을 화면에 출력하지 않습니다.

운영자는 별도로 다음 실제 동작을 확인합니다.

1. 미인증 HTML 화면은 로그인으로 이동하고 WebSocket·업로드·다운로드 호출은 401로 거부됩니다.
2. 인증 서버를 사용할 수 없으면 업무 요청이 실패하며 회계 자료를 제공하지 않습니다.
3. 직원에게 허용하지 않은 화면의 직접 주소와 저장·삭제 작업은 거부됩니다.
4. 다운로드 링크를 다른 직원과 다른 세션에 전달해도 403 또는 401로 거부됩니다.
5. 계정 정지·권한 해제 후 기존 로그인과 기존 다운로드 링크가 동작하지 않습니다.
6. `/media/...`는 로그인한 직원에게도 403이고, `/auth/check`, `/_auth_check`, `/auth/health`, `/_stcore/health`는 외부에 공개되지 않습니다. 기존 자동화의 `/api/health`는 자료를 포함하지 않는 상태 응답으로 유지합니다.
7. 다른 호스트에서 서버의 8501·8502·8503 직접 접속이 실패합니다.
8. 관리자 계정 복구 절차와 DB·암호화 키의 별도 백업이 준비되어 있습니다.

`deploy-oracle.sh`는 최신 인증 Compose 다운로드·필수 환경변수·호스트 Nginx·이미지 내 인증 코드 확인을 통과한 뒤 SQLite 백업을 만들고 서비스를 적용합니다. 다운로드나 검증 실패 시 이전 무인증 Compose나 내장 무인증 설정으로 실행하지 않습니다. `docker compose --wait` 및 내부 상태 검사, 미인증 업무 401·기존 media 403 검사를 완료한 경우에만 배포 완료를 표시합니다. 실제 외부 방화벽과 직원별 권한 점검은 운영자가 완료해야 합니다.

문제가 발생해도 무인증 구성을 다시 공개하지 않습니다. 먼저 외부 업무 접속을 차단하고, 안전한 이전 인증 이미지·설정·DB 백업을 이용하여 복구합니다. 암호화 키를 맞추어 복구하고 기존 세션은 모두 폐기한 뒤 인증·권한·다운로드 차단을 다시 점검합니다.
