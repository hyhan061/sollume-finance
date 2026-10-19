<!-- 2026-10-14 hoyeon.han: 사내 직원 전용 필수 MFA·화면 권한·다운로드 보호 운영 안내 -->
# 사용자관리 운영 안내

<!-- 2026-10-19 hoyeon.han: 확정 전 공개 주소 설명을 보존한다.
이 구성은 현재 회계 시스템 전용입니다. 외부 진입점은 `https://sollumeesthe.com`의 Nginx이고, 회계앱(8501), 발주내역 자동화 API(8502), 인증 서버(8503)는 직접 인터넷에 공개하지 않습니다. 로컬 개발은 별도의 시작 스크립트로 두 프로그램을 가상환경과 루프백 주소에서 실행합니다.
-->
이 구성은 현재 회계 시스템 전용입니다. 확정한 외부 진입점은 `https://office1.sollumeesthe.com`입니다. 새 인증 구성에서는 회계앱(8501), 발주내역 자동화 API(8502), 인증 서버(8503)를 직접 인터넷에 공개하지 않습니다. 루트 도메인 `sollumeesthe.com`은 다른 서버의 기존 사이트이므로 변경하지 않습니다. 로컬 개발은 별도의 시작 스크립트로 두 프로그램을 가상환경과 루프백 주소에서 실행합니다.

<!-- 2026-10-19 hoyeon.han: 운영자가 완료한 압축 백업과 현재 서버의 최초 전환 경계를 명시한다. -->
## 2026-10-19 최초 전환 준비

운영자가 회계앱·API만 중지하여 `application.tar.gz`, `images.tar`, `containers.json`을 보관하고 같은 컨테이너의 정상 응답·healthy 상태를 확인했습니다. 이 백업을 사용하는 배포에는 `deploy-oracle.sh --backup-dir 절대경로`를 사용하며, 이미지와 프로젝트 폴더를 다시 저장하지 않습니다. 기본 백업 검증은 `rollback-oracle.sh --app-dir 원래절대경로 --backup-dir 절대경로`이고 서비스를 변경하지 않습니다. 자세한 순서와 실제 변경 명령은 [압축 백업 기반 복구](ROLLBACK.md#완료한-압축-백업-사용--최초-인증-전환)를 따릅니다.

압축 내용이 읽힌다는 사실과 실제 복구 성공은 다릅니다. 로컬 합성 자료 복구 시험은 실제 운영 계정·자료·인증서·방화벽을 검증하지 않습니다. 기존 운영 백업 세 파일의 내용·키·전체 inspect는 Git이나 채팅으로 옮기지 않습니다. 백업 폴더 자체는 Ubuntu 소유 0700이며, 상위 root 소유 `database/backups`를 재귀 변경하지 않습니다. 추가 배포 DB 백업은 준비된 `database/backups/releases` 아래에 생성합니다.

<!-- 2026-10-19 hoyeon.han: DNS·인증서 준비 전 설명을 보존한다.
아직 서버에 새 인증 구성을 설치한 상태는 아닙니다. 현재 알려진 `sol-fin.duckdns.org`, `sollume-finance.duckdns.org`의 회계앱 경로와 자동화 API 사용처를 확인하고, 새 `sollumeesthe.com`의 DNS·TLS와 함께 적용 계획을 확정해야 합니다. 새 도메인의 설정 하나만 바꾸고 기존 주소의 앱 프록시를 남기지 않습니다. 새 예시의 `default_server`가 기존 Nginx 사이트와 충돌하지 않는지도 확인합니다. `n8n`·`goodsfoundry`의 컨테이너·Nginx 설정·게시 포트는 이번 배포/복구 대상이 아닙니다.
-->
서버에 새 인증 앱은 아직 배포하지 않았습니다. 운영자는 `office1.sollumeesthe.com`의 DNS·HTTPS·자동 갱신 시험을 완료했다고 보고했습니다. 기존 `sol-fin.duckdns.org`, `sollume-finance.duckdns.org`는 현재 서비스 중이며, 최초 배포에서는 새 주소와 기존 두 회계 진입점을 함께 관리해야 합니다. 새 주소만 보호한 채 기존 주소의 무인증 앱 프록시를 남기지 않습니다. 호스트 Nginx 예시에는 `default_server`를 지정하지 않으며 office1 전용 변수·제한 영역 이름으로 다른 사이트와의 충돌을 줄입니다. `n8n`·`goodsfoundry`의 컨테이너·Nginx 설정·게시 포트와 루트 도메인은 이번 배포/복구 대상이 아닙니다. 외부 API 프로그램의 연동 시험은 사용자의 요청으로 이번 준비 범위에서 제외합니다.

`--backup-dir` 경로에서는 원래 Compose 명령과 실제 명령을 단순 비교하던 자동 캡처를 대신해 저장된 inspect의 실제 명령·이미지·마운트·CPU/메모리 설정을 검증합니다. 백업과 현재 실행 상태가 다르거나 비공개 복구 준비가 실패하면 pull·서비스 교체 전에 중단합니다. 구버전 복구는 외부 503 차단을 유지하며 운영자 SSH 터널 점검만 허용합니다.

<!-- 2026-10-19 hoyeon.han: 운영자가 직접 완료했다고 보고한 도메인 준비와 인증서 갱신 구성을 기록한다. -->
## office1 도메인·인증서 준비 상태

다음은 운영자의 실행 결과에 근거한 상태입니다. 개발 환경에서 운영 서버에 접속해 재검증한 결과는 아닙니다.

| 항목 | 준비된 값·상태 |
|---|---|
| 공개 주소 | `https://office1.sollumeesthe.com` |
| DNS A | `152.69.227.107`, Cloudflare·Google 리졸버에서 확인 |
| 설정 원본 | `/etc/nginx/sites-available/office1.sollumeesthe.com` |
| 활성화 링크 | `/etc/nginx/sites-enabled/zz-office1.sollumeesthe.com` |
| HTTP ACME 경로 | `/var/www/letsencrypt/.well-known/acme-challenge/` |
| 현재 일반 HTTP 접속 | 새 주소의 HTTPS로 301 이동 |
| 현재 HTTPS 접속 | 인증서 검증 성공, 업무 앱 대신 503 준비 응답 |
| 인증서·개인키 | `/etc/letsencrypt/live/office1.sollumeesthe.com/fullchain.pem`, 같은 폴더의 `privkey.pem` |
| 기존 서비스 | 두 회계 DuckDNS의 HTTPS 200 및 기존 컨테이너 정상 응답 보고 |
| 발급 방식 | Certbot `certonly --webroot`, webroot `/var/www/letsencrypt` |
| 갱신 시험 | office1 지정 `renew --dry-run --run-deploy-hooks -v` 성공 보고 |

### 기존 인증서와 공유하는 갱신 스케줄

<!-- 2026-10-19 hoyeon.han: 실제 갱신 설정을 조회하기 전 설명을 보존한다.
기존 `certbot.timer`가 활성 상태이며, 이 도메인 전용 타이머를 추가하지 않습니다. 타이머가 서비스를 실행하면 서비스에 지정된 Certbot 갱신 명령이 각 인증서의 저장된 갱신 설정과 갱신 필요 여부를 확인합니다. **기존 서비스의 실제 `ExecStart`와 인증서별 설정 파일은 아직 읽지 않았으므로** 실행 시각·옵션·기존 인증서의 발급/설치 방식을 단정하지 않습니다. 다음 명령은 필요할 때 운영자가 읽기 전용으로 확인합니다.

이번 준비에서 기존 타이머를 변경하거나 새 cron 작업을 만들지는 않았습니다. 일반적인 `certbot renew`는 보관된 인증서들을 확인하여 갱신이 필요한 인증서만 처리하지만, 실제 서비스가 `--cert-name`으로 특정 인증서만 선택하거나 `--no-directory-hooks`로 후속 작업을 제외할 수 있습니다. 따라서 office1의 수동 갱신 시험 성공과 예약 실행의 대상·hook 실행 여부는 구분하며, 실제 `ExecStart`를 확인한 뒤 예약까지 확정합니다.
-->
운영자가 전달한 실제 unit·갱신 설정 조회 결과에서 기존 `certbot.timer`를 네 인증서가 공유하는 것을 확인했습니다. office1 전용 타이머나 새 cron을 만들지 않았고 기존 예약도 수정하지 않았습니다.

| 실제 조회 항목 | 확인한 값과 의미 |
|---|---|
| 타이머 `OnCalendar` | `*-*-* 00,12:00:00`: 매일 00시·12시 기준 |
| `RandomizedDelaySec` | `43200`: 각 실행에 최대 12시간 지연을 분산 적용. 기준 시각에 정확히 실행되는 것은 아님 |
| `Persistent` | `true`: 타이머가 중단된 동안 놓친 calendar 실행을 재활성화 시 보완 |
| 서비스 `Type` | `oneshot`: 갱신 명령이 끝나면 해당 실행 종료 |
| 서비스 `ExecStart` | `/usr/bin/certbot -q renew --no-random-sleep-on-renew` |
| 서비스 `PrivateTmp` | `true`: 서비스에 분리된 임시 디렉토리 제공. office1 webroot는 `/var/www/letsencrypt`이므로 이 설정의 임시 경로가 아님 |

`-q`는 출력량을 줄이며, `--no-random-sleep-on-renew`는 Certbot 자체의 임의 대기를 끕니다. 실행 분산은 위 systemd 타이머가 담당합니다. `--cert-name`이 없으므로 기존 세 DuckDNS와 office1을 포함한 보관 인증서들의 갱신 필요 여부를 확인합니다. `--no-directory-hooks`도 없으므로 office1이 실제로 갱신되면 준비한 deploy hook도 대상입니다. 매번 인증서를 다시 발급하는 것은 아니며 갱신이 필요한 인증서만 처리합니다. 다음은 운영자가 이미 확인한 예약을 다시 조회할 때 사용할 명령입니다.

```bash
systemctl cat certbot.timer certbot.service
```

타이머의 시간 조건과 갱신 서비스의 `ExecStart`를 조회합니다.

```bash
sudo -n find /etc/letsencrypt/renewal -maxdepth 1 -type f -name '*.conf' -print
```

인증서별 갱신 설정의 파일 경로만 확인합니다. 실제 설정 확인 시에는 `authenticator`, `installer`, `webroot_path`와 `[webroot_map]` 등 필요한 항목만 조회하고 개인키 내용은 공유하지 않습니다.

office1은 HTTP의 `/.well-known/acme-challenge/`에서 파일을 제공하는 webroot 방식입니다. 인증서가 갱신되어 파일이 바뀌어도 실행 중인 Nginx는 재적용 전까지 이전 인증서를 사용할 수 있으므로 다음 deploy hook을 준비했습니다.

파일 경로:

```text
/etc/letsencrypt/renewal-hooks/deploy/50-office1-reload-nginx.sh
```

운영자가 저장하고 시험한 내용:

```sh
#!/bin/sh
# 2026-10-19 hoyeon.han: office1 인증서 갱신 성공 후 Nginx에 반영
set -e

case " ${RENEWED_DOMAINS:-} " in
    *" office1.sollumeesthe.com "*)
        /usr/sbin/nginx -t
        /usr/bin/systemctl reload nginx
        printf '%s\n' 'office1 인증서 반영: Nginx reload 완료'
        ;;
esac
```

<!-- 2026-10-19 hoyeon.han: 기존 플러그인 조회 전 설명 보존.
Certbot이 전달하는 `RENEWED_DOMAINS`에 office1이 있을 때만 설정 검사 후 reload합니다. 다른 인증서의 갱신에서는 이 hook의 동작이 없습니다. 기존 인증서가 Nginx 설치 플러그인이나 별도 후속 작업으로 반영되는지는 해당 갱신 설정을 읽은 뒤 판단합니다. hook 파일은 `root:root`, 0755로 준비됐습니다. 이 reload는 공유 Nginx 데몬의 전체 설정을 다시 읽으며 office1만 별도로 재시작하는 명령이 아닙니다. Docker 컨테이너를 재시작하지는 않습니다.

배포와 구버전 503 복구 중에도 office1의 HTTP ACME 경로를 유지해야 합니다. 이 경로는 업무자료·로그인·다운로드로 연결하지 않습니다. 기존 DuckDNS 인증서 갱신까지 자동 보장한 것은 아니므로 해당 인증서의 실제 갱신 방식은 별도로 확인합니다.
-->
기존 `sol-fin.duckdns.org`, `sollume-finance.duckdns.org`, `sollume-n8n.duckdns.org`의 갱신 설정은 모두 `authenticator=nginx`, `installer=nginx`로 확인됐습니다. 기존 인증서는 Nginx 플러그인이 도메인 확인과 갱신 후 서버 반영을 담당합니다. office1은 `authenticator=webroot`이며 installer가 없어 준비한 파일 경로로 확인하고 별도의 deploy hook으로 Nginx에 반영합니다.

Certbot이 전달하는 `RENEWED_DOMAINS`에 office1이 있을 때만 이 hook이 설정 검사 후 reload합니다. 다른 인증서의 갱신에서는 이 hook이 추가 동작을 하지 않습니다. hook 파일은 `root:root`, 0755로 준비됐습니다. 이 reload는 공유 Nginx 데몬의 전체 설정을 다시 읽으며 office1만 별도로 재시작하는 명령이 아닙니다. Docker 컨테이너를 재시작하지는 않습니다.

배포와 구버전 503 복구 중에도 office1의 HTTP ACME 경로를 유지해야 합니다. 이 경로는 업무자료·로그인·다운로드로 연결하지 않습니다. 기존 인증서의 실제 갱신 방식과 공유 예약을 확인한 사실이 앞으로 모든 갱신의 성공을 보장하는 것은 아니므로, 회계 사이트 전환 후에도 각 인증서의 갱신 결과를 확인합니다.

<!-- 2026-10-19 hoyeon.han: 현재 배포 코드의 진입점 검증 범위를 명시하고 다음 필수 작업을 기록한다. -->
## 운영 배포 전 남은 진입점 전환·검사

현재 `deploy-oracle.sh`의 `manual-prepare --check-current`는 압축 백업과 실제 이미지·명령·마운트·자원 제한·계정의 대조를 수행합니다. 세 Nginx 사이트를 인자로 전달했다고 해서 누락된 회계 진입점을 찾거나 기존 DuckDNS의 무인증 프록시가 차단됐는지까지 검사하지는 않습니다. `_blocked_sites(False)`를 통한 기존 진입점 차단 검사는 실제 롤백 경로에 있으며 배포 사전 검사와 구분해야 합니다. 따라서 현재 배포 명령의 성공만으로 이전 주소 차단이 보장되지는 않습니다.

운영 배포 전 다음 작업이 필요합니다. 기존 두 회계 DuckDNS의 무인증 회계 프록시를 새 주소로 이동시키거나 차단하도록 전환하고 외부에서 결과를 확인해야 합니다. 또한 배포 전에 모든 회계 진입점을 검사하는 공통 사전 검사 기능을 보강하고 별도로 검증해야 합니다. 이 문서 수정과 office1 도메인 변경 검증에서는 해당 기능을 구현하거나 운영 사이트를 전환하지 않았습니다. 운영 배포는 아직 진행하지 않습니다.

## 적용 전 확인

- 운영 서버에서 기존 `database/users.db`, `database/customer_master.db`, `order_data/`, `uploads/`, `processed/`를 유지합니다. 새 배포 폴더에 빈 DB를 만드는 방식으로 교체하지 않습니다.
- 실행 중인 SQLite는 단순 복사 대신 SQLite `backup`으로 일관된 백업을 만듭니다. 인증 마이그레이션은 기존 사용자 표에 열과 별도 보안 표를 추가하며, 사용자 ID·기존 비밀번호 해시·이름·이메일·기존 로그인 이력을 보존합니다. 최초 전환 전에 `users.db.pre-security.bak`도 한 번 생성합니다.
- 기존 계정은 최초 전환 후에도 기존 아이디·비밀번호로 등록을 시작합니다. 비밀번호만으로 업무에 접속할 수는 없습니다. 관리자가 발급한 단회 등록 코드, 새 비밀번호, 실제 인증 앱 번호가 필요합니다.
- Cloud 구성은 기존 `./거래처마스터.xlsx`의 읽기 전용 fallback 마운트도 보존합니다. 기존 파일을 유지하고, 현재 업무의 거래처 원본은 영속 `customer_master.db`를 사용합니다.
- 기존 일반 직원의 업무 화면 권한은 호환을 위해 초기 유지합니다. 시스템 관리·사용자관리는 관리자만 접근합니다. **공개 전에 관리자가 모든 기존 직원의 허용 화면을 명시적으로 검토하세요.** 새 직원의 기본 화면 권한은 없음입니다.
- 운영 키 `AUTH_ENCRYPTION_KEY`는 DB와 분리하여 비공개 보관·백업합니다. 다른 키로 임의 교체하면 기존 MFA 암호문을 읽을 수 없습니다. 키 분실 시 서버 운영자가 본인을 확인하고 MFA 등록을 초기화해야 합니다.
- 이 문서의 운영 명령은 운영자가 검토하고 실행하는 절차입니다. 개발·테스트 과정에서 실제 운영 DB, `.env`, 계정, 서버 또는 DNS를 변경하지 않습니다.

## 공통 환경 설정

<!-- 2026-10-19 hoyeon.han: 신규 설치용 복사 안내를 보존하고 기존 운영 설정의 덮어쓰기를 방지한다.
`.env.example`을 `.env`로 복사하여 다음 값을 채웁니다. 기존 `ORDER_API_KEY`는 유지합니다. 키를 채운 `.env`나 Docker의 전체 설정 출력은 Git·채팅·로그에 남기지 않습니다.
-->
현재 운영에서는 기존 `/home/ubuntu/sollume-finance/.env`를 편집하여 아래 인증 설정만 추가·수정합니다. `.env.example`을 기존 `.env`에 덮어쓰지 않으며 기존 `ORDER_API_KEY`와 다른 설정을 유지합니다. 키를 채운 `.env`나 Docker의 전체 설정 출력은 Git·채팅·로그에 남기지 않습니다.

```dotenv
# 2026-10-19 hoyeon.han: 확정 전 주소 보존
# AUTH_PUBLIC_ORIGIN=https://sollumeesthe.com
AUTH_PUBLIC_ORIGIN=https://office1.sollumeesthe.com
AUTH_ENCRYPTION_KEY=<별도로 생성한 Fernet 키>
ORDER_API_KEY=<기존 발주내역 API 키>
```

개발 PC에서는 가상환경에서 다음 명령으로 새 운영 키를 생성할 수 있습니다. 터미널에 표시된 키를 비공개 설정에 저장한 뒤 터미널 출력의 보관·공유에 주의하세요. 이것은 운영자가 직접 실행하는 생성 명령이며, 자동 생성되는 운영 기본 키는 없습니다.

```bash
source .venv311/bin/activate
python -m pip install -r requirements.txt
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

<!-- 2026-10-19 hoyeon.han: 확정 전 운영 origin 설명을 보존한다.
`AUTH_ENV=production`은 운영 Compose에서 지정합니다. 운영 `AUTH_PUBLIC_ORIGIN`은 HTTPS 주소여야 하며, 현재 Nginx 설정의 `sollumeesthe.com`과 일치해야 합니다. 별도 `AUTH_SIGNING_KEY`를 설정하지 않으면 인증 암호화 키에서 CSRF 쿠키 전용 서명 키를 용도를 구분하여 파생합니다.
-->
`AUTH_ENV=production`은 운영 Compose에서 지정합니다. 운영 `AUTH_PUBLIC_ORIGIN`은 `https://office1.sollumeesthe.com`이며 Nginx의 서버 이름·Origin 검사와 일치해야 합니다. 별도 `AUTH_SIGNING_KEY`를 설정하지 않으면 인증 암호화 키에서 CSRF 쿠키 전용 서명 키를 용도를 구분하여 파생합니다.

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

<!-- 2026-10-19 hoyeon.han: 도메인 확정·webroot 준비 전 설명을 보존한다.
Docker Nginx의 실제 TLS 인증서는 `./ssl/fullchain.pem`, `./ssl/privkey.pem`으로 준비합니다. 호스트 Nginx 예시는 `/etc/letsencrypt/live/sollumeesthe.com/`의 실제 인증서를 사용합니다. 인증서 준비·갱신은 기존 운영 인증서 발급 절차를 따릅니다. 인증서가 없으면 HTTPS Nginx 시작을 중단하며 HTTP 업무 접속으로 폴백하지 않습니다. 80 포트는 HTTPS 이동만 제공합니다. 인증서 갱신에 HTTP-01 방식이 필요하다면 인증서 발급 도구의 전용 경로 설정을 별도로 검토해야 합니다.
-->
Docker Nginx의 실제 TLS 인증서는 `./ssl/fullchain.pem`, `./ssl/privkey.pem`으로 준비합니다. 현재 Oracle 운영에서는 호스트 Nginx를 사용하며 office1 인증서 경로는 `/etc/letsencrypt/live/office1.sollumeesthe.com/`입니다. 인증서가 없으면 HTTPS Nginx 시작을 중단하며 HTTP 업무 접속으로 폴백하지 않습니다. 호스트의 80 포트는 office1의 HTTP ACME 경로만 정적 파일로 제공하고 나머지는 HTTPS로 이동시킵니다. Docker Nginx 예시의 인증서 갱신 배치는 별도 준비 대상이며 호스트의 webroot 준비가 Docker 배치를 검증한 것은 아닙니다.

호스트 Nginx 예시는 **전체 사이트 설정**입니다. 이전의 무인증 `location /`에 일부 경로만 덧붙이지 않습니다. 기존 설정을 백업하고, 동일 도메인의 기존 80·443 server와 중복하지 않게 적용합니다.

<!-- 2026-10-19 hoyeon.han: 기존 일괄 표시를 보존하고 실행 단계를 분리한다.
```bash
sudo nginx -V
sudo nginx -t
sudo systemctl reload nginx
```
-->
빌드 옵션을 조회합니다.

```bash
sudo -n nginx -V
```

설정 문법과 인증서 파일을 검사합니다.

```bash
sudo -n nginx -t
```

위 검사에 성공하고 운영 변경이 승인된 때에만 설정을 반영합니다.

```bash
sudo -n systemctl reload nginx
```

<!-- 2026-10-19 hoyeon.han: 이전 기본 사이트 설명을 보존한다.
`nginx -V`에서 `http_auth_request_module` 지원을 확인합니다. 문법·인증서 검사를 통과한 경우에만 재적용합니다. Cloud 배포 스크립트는 기본적으로 `/etc/nginx/sites-enabled/sollume-finance`를 검사합니다. 실제 전용 파일 경로가 다르면 `SOLLUME_NGINX_SITE_CONFIG`에 그 경로를 지정합니다.
-->
`nginx -V`에서 `http_auth_request_module` 지원을 확인합니다. 문법·인증서 검사를 통과한 경우에만 재적용합니다. Cloud 배포 스크립트의 기본 인증 사이트는 `/etc/nginx/sites-enabled/zz-office1.sollumeesthe.com`입니다. 실제 최초 전환에서는 기본 경로 하나에 의존하지 않고 `--nginx-config`를 반복 지정하여 office1, 기존 `sollume-finance`, 기존 `sol-fin` 세 사이트를 모두 포함합니다. 첫 번째 사이트가 새 인증 정책의 설치 대상입니다. 자세한 절대경로 명령은 [압축 백업 기반 복구](ROLLBACK.md#완료한-압축-백업-사용--최초-인증-전환)를 따릅니다.

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

<!-- 2026-10-19 hoyeon.han: 압축 백업 경로는 검증된 보관본을 사용하고 기존 자동 snapshot 경로는 별도로 유지한다. -->
`deploy-oracle.sh`는 최신 인증 Compose 다운로드·필수 환경변수·호스트 Nginx·이미지 내 인증 코드 확인을 통과한 뒤 SQLite 백업을 만들고 서비스를 적용합니다. `--backup-dir`를 지정하면 기존 압축 백업과 현재 실행 상태를 검증하여 복구 정보를 준비하고, 지정하지 않으면 기존 자동 snapshot 캡처를 수행합니다. 다운로드나 검증 실패 시 이전 무인증 Compose나 내장 무인증 설정으로 실행하지 않습니다. `docker compose --wait` 및 내부 상태 검사, 미인증 업무 401·기존 media 403 검사를 완료한 경우에만 배포 완료를 표시합니다. 실제 외부 방화벽과 직원별 권한 점검은 운영자가 완료해야 합니다.

문제가 발생해도 무인증 구성을 다시 공개하지 않습니다. 먼저 외부 업무 접속을 차단하고, 안전한 이전 인증 이미지·설정·DB 백업을 이용하여 복구합니다. 암호화 키를 맞추어 복구하고 기존 세션은 모두 폐기한 뒤 인증·권한·다운로드 차단을 다시 점검합니다.


<!-- 2026-10-15 hoyeon.han: 복구 지점과 일반/초기 구버전 롤백 절차 연결 -->
## 배포 전 복구 지점과 롤백

<!-- 2026-10-19 hoyeon.han: 완료한 압축 백업을 사용하는 경우의 재캡처 생략 조건을 반영한다. -->
배포 도구는 `.venv-ops`와 `scripts/release_snapshot.py`를 준비한 뒤 사용합니다. 최초 전환은 Nginx·Compose를 변경하기 전에 기존 압축 백업 또는 전용 snapshot을 준비합니다. 완료한 압축 백업을 `--backup-dir`로 지정하면 원본 해시·필수 파일·실제 실행 상태를 검증한 경우에만 재캡처를 생략합니다. 일반 롤백은 최신 계정·MFA·권한·업무자료를 유지하며, 인증 도입 전 복구는 공개 503 상태에서만 허용합니다. 명령과 데이터 처리, 실패 시 대응은 [롤백 운영 절차](ROLLBACK.md)를 따릅니다.
