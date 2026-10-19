<!-- 2026-10-15 hoyeon.han: 실제 실행 이미지와 최신 업무자료를 보존하는 운영 복구 절차 -->
# Oracle 운영 롤백

이 문서는 실행 절차이며 운영 서버에서 자동 실행되지 않습니다. 구현·검증은 로컬 임시 환경에서만 수행합니다. 복구 대상은 현재 시스템의 **호스트 Nginx + docker-compose.cloud.yml** 구성입니다. Docker Nginx 구성이나 다른 시스템으로 임의 적용하지 않습니다.

<!-- 2026-10-19 hoyeon.han: 완료한 압축 백업을 사용하는 최초 전환 절차를 우선 안내한다. -->
## 완료한 압축 백업 사용 — 최초 인증 전환

2026-10-19 운영자가 만든 아래 세 파일을 그대로 사용합니다. `capture`를 다시 실행하거나 이미지를 다시 저장할 필요는 없습니다.

| 파일 | 용도 |
|---|---|
| `application.tar.gz` | 기존 사용자·거래처 DB, 설정, 업무파일과 사전에 복사한 Nginx 설정 |
| `images.tar` | 실제 실행하던 이미지. 태그가 아닌 저장된 이미지 ID로 복구 |
| `containers.json` | 실제 명령·환경·마운트·CPU·메모리·원래 프로젝트와 경로 |

이 방식은 **인증 도입 전 앱·API 두 서비스의 백업**을 지원합니다. 보안 버전 간 복구는 아래의 전용 snapshot 절차를 사용합니다. 원본 압축 파일은 수정하지 않으며, 운영 폴더에 전체 압축을 덮어풀지 않습니다. 업무자료는 현재 것을 유지하고 필요한 사용자 DB와 실행 설정만 선택하여 처리합니다.

<!-- 2026-10-19 hoyeon.han: 환경값을 재해석하지 않는 Compose raw env_file 지원 버전을 기록한다. -->
복구 Compose는 실제 환경값의 `$`·따옴표를 보존하기 위해 `env_file`의 `format: raw`를 사용합니다. Docker Compose 2.30.0 이상이 필요하며, 운영자가 확인한 서버 버전은 5.0.0입니다. 실제 실행 전 Compose 렌더 검사를 통과해야 합니다. [Docker 공식 설명](https://docs.docker.com/reference/compose-file/services/#format)

### 1. 변경 없는 백업 점검

새 `scripts/release_snapshot.py`와 `rollback-oracle.sh`를 운영에 가져가는 것은 별도 운영 일정에 수행합니다. 아래는 나중에 사용할 명령이며 지금 운영 배포를 지시하는 명령이 아닙니다. `실제백업폴더명`은 이미 완료한 폴더명으로 바꿉니다.

<!-- 2026-10-19 hoyeon.han: 검사 전 운영 Compose를 새 파일로 미리 교체하는 실수를 방지한다. -->
운영 반영 시에는 검토한 `scripts/release_snapshot.py`, `rollback-oracle.sh`, `deploy-oracle.sh`만 선택적으로 가져옵니다. 기존 `docker-compose.cloud.yml`과 `.env`의 API 키·DB·업무파일을 새 체크아웃으로 덮어쓰지 않습니다. Compose는 배포 스크립트가 검증·백업 후 교체합니다. 인증 설정은 기존 `.env`의 API 키를 유지하면서 추가합니다.

```bash
cd /home/ubuntu/sollume-finance
SOLLUME_BACKUP_DIR="$PWD/database/backups/releases/실제백업폴더명"

./rollback-oracle.sh \
  --app-dir "$PWD" \
  --backup-dir "$SOLLUME_BACKUP_DIR"
```

기본 실행은 계획만 확인하며 DB·컨테이너·Nginx를 변경하지 않습니다. 필요한 DB와 부속 WAL을 임시 폴더에서 검사하고, 실제 컨테이너 설정과 저장 이미지의 관계, 압축 경로·필수 파일·손상 여부를 확인합니다. `.venv`의 정상 심볼릭 링크 등 선택하지 않는 항목은 추출하지 않습니다. 계정·키·전체 inspect 내용은 출력하지 않습니다.

### 2. 배포 직전 준비 — 승인된 배포 일정에만 실행

배포 스크립트에는 백업 폴더와 **모든 회계 Nginx 사이트**를 지정합니다. 첫 사이트는 새 인증 정책을 설치할 사이트입니다. 현재 알려진 두 사이트는 `sollume-finance`, `sol-fin`입니다. 새 도메인을 별도 사이트에 구성했다면 그 경로를 첫 번째로 지정하고 기존 두 경로를 뒤에 추가합니다. DNS·실제 TLS 인증서·기존 주소 처리·외부 직접 포트 차단은 먼저 준비해야 합니다.

```bash
./deploy-oracle.sh \
  --backup-dir "$SOLLUME_BACKUP_DIR" \
  --nginx-config /etc/nginx/sites-enabled/sollume-finance \
  --nginx-config /etc/nginx/sites-enabled/sol-fin
```

이 명령은 **실제 배포 명령**입니다. 백업 점검용으로 실행하지 않습니다. 내부 `manual-prepare --check-current`가 원본 세 파일과 현재 실제 이미지·명령·데이터 마운트·자원 제한·계정 상태를 대조한 뒤 비공개 복구 정보를 작성합니다. 현재 설정이 백업과 다르면 이미지 pull과 서비스 교체 전에 멈춥니다. 원래 Compose의 문자열·빈 명령 표현을 실제 명령과 단순 비교하던 `capture`는 이 경로에서 실행하지 않습니다.

추가 DB 백업은 Ubuntu가 쓰도록 준비된 `database/backups/releases/` 아래에만 만듭니다. 상위 `database/backups`의 root 소유권과 기존 백업을 변경하지 않습니다. `sudo -v` 대신 실제 필요한 관리자 명령의 비대화식 권한을 사용하며, 비밀번호가 필요하면 서비스 변경 전에 중단합니다. 보관 원본 세 파일이 바뀌면 준비 정보를 그대로 재사용하지 않습니다.

### 3. 문제가 생겼을 때 구버전 복구

먼저 같은 백업과 모든 회계 사이트를 지정하여 계획을 확인합니다.

```bash
./rollback-oracle.sh \
  --app-dir "$PWD" --backup-dir "$SOLLUME_BACKUP_DIR" \
  --nginx-config /etc/nginx/sites-enabled/sollume-finance \
  --nginx-config /etc/nginx/sites-enabled/sol-fin \
  --legacy-private --restore-users
```

실제 복구가 승인된 경우에만 같은 명령에 `--apply`를 추가하고 Nginx 설정을 쓸 수 있는 운영자 권한으로 실행합니다. 다음은 실제 변경 명령입니다.

```bash
sudo -n ./rollback-oracle.sh \
  --app-dir "$PWD" --backup-dir "$SOLLUME_BACKUP_DIR" \
  --nginx-config /etc/nginx/sites-enabled/sollume-finance \
  --nginx-config /etc/nginx/sites-enabled/sol-fin \
  --legacy-private --restore-users --apply
```

복구는 모든 회계 사이트의 503 차단을 검증하고 정확한 회계앱·API·인증 컨테이너만 중지합니다. 최신 사용자 DB·현재 `.env`·인증키·설정은 비공개로 먼저 보관합니다. 최신 거래처 DB·발주내역·업로드·결과 파일은 복원하거나 삭제하지 않습니다. 저장 이미지의 실제 명령과 기존 CPU·메모리 정책으로 시작하되 포트는 루프백으로 제한하고 새 pull·build를 하지 않습니다. `n8n`, `goodsfoundry`의 컨테이너·사이트는 대상에 포함하지 않습니다.

구버전 사용자 DB에서 최근 정지·삭제·관리자 강등·비밀번호 변경을 되살리지 않습니다. 백업 이후 추가된 계정도 가능한 공통 계정정보를 보존하되, 구버전 비밀번호 호환을 확인할 수 없으면 비활성으로 두고 운영자 재설정을 요구합니다. 최신 MFA·권한·감사 이력 전체는 복구 직전 사용자 DB에 보관합니다. ID·아이디 충돌이나 검사 실패가 있으면 임의로 합치지 않고 중단합니다.

구버전은 MFA·화면 권한·다운로드 보호가 없으므로 **복구가 성공해도 외부 접속은 503으로 유지**합니다. SSH 터널로 운영자만 점검합니다. 전체 Nginx 설정에서 다른 회계 진입점이 발견되거나 외부 차단을 확인하지 못하면 공개 복구를 진행하지 않습니다. 실패 기록의 경로와 단계만 공유하고 DB·키·inspect 원문은 공유하지 않습니다.

### 4. 구버전 운영자 로그인 복구

인증 등록으로 비밀번호 해시가 바뀐 관리자는 구버전에서 비활성화될 수 있습니다. 완료된 비공개 복구 뒤, 현재도 유효한 기존 계정만 명시적으로 새 비밀번호를 설정할 수 있습니다. 먼저 `--apply` 없이 점검하고 실제 변경 시에만 추가합니다.

```bash
sudo -n .venv-ops/bin/python scripts/release_snapshot.py manual-password \
  --app-dir "$PWD" --backup-dir "$SOLLUME_BACKUP_DIR" \
  --nginx-config /etc/nginx/sites-enabled/sollume-finance \
  --nginx-config /etc/nginx/sites-enabled/sol-fin \
  --username 실제관리자아이디 --apply
```

터미널에서 새 비밀번호를 숨김 입력합니다. 이 명령은 서버 `ubuntu` 비밀번호 변경과 별개입니다. 최근 정지·삭제된 계정은 허용하지 않으며, 외부 503 차단과 저장 이미지가 맞는지 다시 검사합니다. SSH 키·OS 계정·다른 서비스는 변경하지 않습니다.

---

<!-- 2026-10-19 hoyeon.han: 아래 내용은 기존 전용 snapshot 형식에 대한 별도 지원 절차이다. -->
## 기존 전용 snapshot 형식

이하 `--release` 명령은 `capture`로 만든 전용 복구 지점에만 사용합니다. 위의 압축 백업에는 `--backup-dir`를 사용하세요. 두 형식의 manifest를 서로 대신 사용하지 않습니다.

## 복구 방식

| 대상 | 사용자·업무자료 | 공개 접속 |
|---|---|---|
| 필수 MFA를 포함한 호환 버전 | 최신 사용자 DB·현재 암호화 키·거래처 DB·발주내역·업로드·결과 파일을 유지. 로그인·등록 코드·다운로드 권한만 폐기 | 내부 상태와 미인증 접근 차단 검증 후 재개 |
| MFA 도입 전 버전 | 현재 사용자 DB를 먼저 보관하고, 지정한 구버전 복구 지점의 사용자 DB만 명시적으로 복원. 최신 거래처 DB와 업무 파일 유지 | **항상 503 점검 상태 유지. SSH 터널 등 운영자 접근만 사용** |

새 인증에서 등록·생성·비밀번호 변경을 완료한 계정은 Argon2를 사용하지만, 인증 도입 전 앱은 bcrypt만 지원합니다. 최신 사용자 DB를 구버전에 연결하거나 Argon2를 bcrypt로 역변환하는 방식은 지원하지 않습니다. 구버전은 MFA·화면별 권한·다운로드 보호를 제공하지 않으므로 공개 접속을 자동 재개하지 않습니다.

구버전 사용자 DB 복원 시 최근 정지·관리자 강등·삭제한 계정을 되살리지 않습니다. 현재와 과거의 ID·아이디가 일치하는 계정만 검토하며 활성·관리자 상태는 양쪽에서 허용하는 범위로 제한합니다. 비밀번호 해시가 달라진 계정도 정지하여 폐기한 옛 비밀번호가 다시 유효해지지 않게 합니다. 새 인증에서 추가한 계정·MFA·권한·감사 이력은 복구 직전 백업에 보존되며, 구버전 앱에서는 사용할 수 없습니다.

## 최초 준비 — 운영자가 나중에 실행

검토한 동일 버전의 다음 세 파일을 기존 운영 디렉토리에 설치합니다. 새 빈 디렉토리·빈 DB로 교체하지 않습니다.

- `deploy-oracle.sh`
- `rollback-oracle.sh`
- `scripts/release_snapshot.py`

```bash
cd "$HOME/sollume-finance"
python3 -m venv .venv-ops
chmod 700 rollback-oracle.sh scripts/release_snapshot.py
```

운영 도구는 표준 라이브러리만 사용하므로 별도 pip 설치가 필요하지 않습니다. sudo 복구 시에도 기존 Compose·사용자 DB·Nginx 파일의 소유자와 그룹을 교체 전에 보존합니다. `rollback-oracle.sh`는 가상환경 Python을 선택하고, Docker 이미지는 기존 앱·API·인증 서버가 실제 실행하던 것을 사용합니다. 다른 가상환경은 `SOLLUME_OPS_PYTHON`에 절대 경로를 지정합니다. `sudo`로 실행할 때도 `--app-dir`를 명시하여 root의 홈 디렉토리로 경로가 바뀌지 않게 합니다.

**첫 복구 지점은 Nginx·Compose·.env를 새 버전으로 바꾸기 전에 생성합니다.** 배포 스크립트가 만드는 자동 복구 지점은 실행 당시 파일 상태입니다. 이미 덮어쓴 설정을 과거 파일로 추정해 복원하지 않습니다.

```bash
.venv-ops/bin/python scripts/release_snapshot.py capture   --app-dir "$PWD"   --nginx-config /etc/nginx/sites-enabled/sollume-finance
```

실제 사이트 경로가 다르면 모든 명령에 동일한 `--nginx-config`를 지정합니다. 첫 캡처는 현재 실행 중인 기존 앱·API를 읽어 보관합니다. 컨테이너가 없거나 실행 상태와 Compose의 프로젝트·마운트가 다르면 임의로 추정하지 않고 중단합니다.

## 복구 지점의 내용

기본 보관 경로는 `database/backups/releases/<복구지점>/`입니다. 디렉토리 권한은 700, 개별 파일은 600으로 제한합니다.

- 서비스별 **실행 이미지 ID**, 아키텍처, Compose 프로젝트·서비스명·절대 마운트 경로·자원 제한
- 오프라인 복구용 Docker 이미지 묶음. 롤백에서 `latest`를 다시 다운로드하거나 이미지를 빌드하지 않음
- 이미지 ID를 고정하고 비밀값을 환경변수 참조로 분리한 Compose, Nginx 사이트와 링크 정보
- SQLite backup API로 만든 사용자·거래처 DB, 파일별 체크섬과 복구 기록
- 존재하는 경우 현재 발주 파일과 메타데이터 보관본. 일반 롤백은 이를 최신 업무 파일에 덮어쓰지 않음

암호화 키·API 키 등 비밀 설정은 DB 백업 디렉토리와 분리한 `database/.release-secrets/<복구지점>/.env`에 비공개 보관합니다. 이 파일은 원본 `.env`의 dotenv 원문입니다. 같은 비공개 디렉토리의 `.env.local`은 도구 전용 HMAC 키(바이너리), `.env.compose.local`은 캡처 당시 원본 Compose입니다. 이 두 파일은 셸에서 source하지 않습니다. 복구 지점과 비밀 디렉토리는 대응하는 쌍으로 보관합니다. HMAC 키가 없거나 파일이 변조되면 검사를 거절하며 새 키를 생성해 우회하지 않습니다. 기존 Git의 `.env` 제외 규칙과 Docker의 `database/*` 제외 규칙을 적용합니다. 백업은 외부에 공개하거나 Git에 추가하지 않습니다. 보고서·채팅에 키·전체 Compose 렌더링·원본 DB 내용을 붙여 넣지 않습니다.

일반 롤백에서는 **현재 .env를 그대로 사용**합니다. 보관한 과거 키로 자동 덮어쓰지 않습니다. 현재 DB의 MFA 암호문과 맞는 키가 있어야 합니다. 키를 잃었다면 임의로 새 키를 만들지 않습니다. 운영자는 복구할 사용자 DB와 같은 시점의 비공개 `.env` 보관본을 확인하고 비공개 편집기에서 현재 `.env`의 해당 키만 복구한 후 사전 점검을 다시 실행합니다. 과거 API 키나 다른 설정까지 자동으로 덮어쓰지 않습니다. 이번 도구는 키 회전을 자동 처리하지 않으며 보안 복구 지점의 키와 현재 키가 다르면 중단합니다. TLS 인증서도 현재 유효한 파일을 유지하며 과거 인증서로 덮어쓰지 않습니다.

## 배포 시 자동 보관

`deploy-oracle.sh`는 필수 설정·Nginx 검사 후, **새 이미지 pull 전에** 기존 실행 이미지와 설정·DB를 캡처합니다. 캡처가 실패하면 이미지 교체를 진행하지 않습니다. 기존 DB 백업 단계도 유지합니다.

배포 실패 시 복구 지점 경로를 표시합니다. 자동으로 구버전을 공개하지 않습니다. `rollback-oracle.sh`와 이 문서를 검토하여 복구 지점을 명시적으로 선택합니다. 배포와 롤백을 동시에 실행하지 않습니다. 각 복구 지점은 생성 당시 상태이며, 자동으로 최신화하지 않습니다.

## 일반 롤백 — 사전 점검이 기본

출력된 실제 복구 지점의 절대 경로를 사용합니다. 아래의 `<복구지점>`은 예시 자리표시자입니다.

```bash
./rollback-oracle.sh   --app-dir "$PWD"   --nginx-config /etc/nginx/sites-enabled/sollume-finance   --release "$PWD/database/backups/releases/<복구지점>"
```

`--apply`가 없으면 파일·DB·Nginx·컨테이너를 변경하지 않습니다. 체크섬, 앱 경로, 프로젝트, 영속 마운트, 스키마·보안 호환성, 현재 키 설정을 검사합니다. 잘못된 경로·손상된 백업·필수 설정 누락 시 적용 전에 중단합니다.

실제 복구는 사이트 파일 교체 권한을 가진 운영자가 실행합니다.

```bash
sudo ./rollback-oracle.sh   --app-dir "$PWD"   --nginx-config /etc/nginx/sites-enabled/sollume-finance   --release "$PWD/database/backups/releases/<복구지점>"   --apply
```

실행 순서는 다음과 같습니다.

1. 현재 상태를 별도의 복구 지점으로 추가 보관합니다.
2. Nginx에 HTTPS 503 점검 설정을 적용하고 실제 응답을 확인합니다. 현재 인증서 경로를 유지합니다.
3. 이전 서비스 전체를 중지하여 쓰기와 기존 WebSocket 연결을 끊습니다. 영속 볼륨은 삭제하지 않습니다.
4. 중지 직전까지의 사용자·거래처 DB를 다시 일관되게 백업합니다.
5. 저장한 이미지를 로드하고 ID·아키텍처를 확인합니다. 원래 프로젝트·절대 마운트·CPU·메모리 제한으로 시작합니다.
6. 일반 롤백에서는 사용자·거래처 DB와 업무 파일을 복원하지 않습니다. 비밀번호·MFA·계정 상태·화면 권한은 유지하고 기존 세션·미완료 로그인·등록 코드·다운로드 권한을 폐기합니다. 직원은 다시 로그인하고, 미등록 직원의 기존 등록 코드는 재발급합니다.
7. 503을 유지한 상태에서 내부 상태·인증/다운로드 거부와 승인된 사이트 정책을 확인합니다. 공개 재개 후 HTTPS 미인증 접근 401·기존 `/media` 경로 403을 이중 점검하고, 실패하면 즉시 503으로 복귀합니다.

저장된 보안 사이트는 승인된 `nginx-host-api.conf.example`의 고정 정책과 정확히 일치해야 합니다. 토큰 비교는 따옴표 안의 내용은 보존하고 주석·표현상 공백 및 TLS 인증서 경로 두 항목만 제외합니다. 인증 우회 경로·include·추가 server/location·헤더·proxy_pass가 바뀌면 사전 점검에서 거절합니다. 공개 직전 후보도 다시 검사하고, 503 상태에서 내부 인증·다운로드 거부를 먼저 확인합니다. 전역 Nginx 설정이나 다른 사이트까지 승인하는 도구는 아니며, 해당 설정은 기존 운영 통제 아래 유지해야 합니다.

완료·실패 기록에 대상 복구 지점과 실행 직전 추가 보관 경로가 남습니다. 실행 직전의 장애 상태 보관본은 `recoverable=false`로 표시하여 정상 운영 버전으로 오인해 자동 선택하지 못하게 합니다. 필요한 최신 사용자 DB·설정·이미지 정보는 이 보관본에서 운영자가 확인할 수 있습니다. `docker compose down -v`, 볼륨 삭제, 빈 DB 생성, 기본 관리자 생성은 복구 절차에 포함되지 않습니다.

## 인증 도입 전 버전으로 복구

기본 명령은 인증 도입 전 버전을 거절합니다. 아래 두 옵션을 **함께** 명시한 별도 복구만 허용합니다. 우선 `--apply` 없이 점검합니다.

```bash
./rollback-oracle.sh   --app-dir "$PWD"   --nginx-config /etc/nginx/sites-enabled/sollume-finance   --release "$PWD/database/backups/releases/<구버전복구지점>"   --legacy-private --restore-users
```

점검을 통과한 후 같은 명령에 `sudo`와 `--apply`를 추가하면 사용자 DB 복원을 수행합니다. 최신 계정 DB는 실행 직전 복구 지점에 보존합니다. 최신 거래처 DB·발주내역·업무 결과는 과거 시점으로 되돌리지 않습니다. SQLite 복원은 모든 쓰기를 중단한 후 수행하며 이전 WAL 파일과 복구 DB를 단순 혼합하지 않습니다.

복구 후 서비스 포트는 127.0.0.1에만 게시하고 공개 도메인은 계속 503으로 유지합니다. 운영자 SSH 터널은 별도 터미널에서 열 수 있습니다.

```bash
ssh -L 18501:127.0.0.1:8501 ubuntu@운영서버
```

운영자 PC에서 `http://localhost:18501`을 열어 제한된 점검을 합니다. 서버 8501 포트를 인터넷에 개방하지 않습니다. 최근 비밀번호 변경으로 정지된 계정은 아래 명시적 운영자 절차로만 복구합니다. 먼저 사전 점검을 실행합니다. `직원아이디`는 실제 복구할 기존 계정으로 바꿉니다.

```bash
.venv-ops/bin/python scripts/release_snapshot.py legacy-password \
  --app-dir "$PWD" \
  --nginx-config /etc/nginx/sites-enabled/sollume-finance \
  --release "$PWD/database/backups/releases/<적용한구버전복구지점>" \
  --username 직원아이디
```

신원을 확인한 운영자가 같은 명령을 `sudo .venv-ops/bin/python`으로 실행하고 `--apply`를 추가하면 터미널에서 새 비밀번호와 확인 값을 숨김 입력합니다. 비밀번호는 12자 이상·UTF-8 72바이트 이하로 입력합니다. 비밀번호는 명령 인자·환경변수·로그에 넣지 않습니다.

이 절차는 완료된 구버전 복구 기록과 실행 이미지·프로젝트·공개 503 상태를 검사합니다. 복구 직전 최신 계정 DB에 같은 ID·아이디로 존재하며 활성 상태였던 기존 계정만 재설정할 수 있습니다. 최근 정지·삭제한 계정은 거절하고 관리자 승격이나 새 계정 생성은 하지 않습니다. 과거 비밀번호 대신 새 bcrypt 비밀번호를 설정하며, 해당 계정만 운영자 접근에 사용할 수 있도록 합니다. 기존 writer·WebSocket 연결은 서비스를 중지·재생성하여 종료합니다. 공개 503은 계속 유지합니다.

이전 스크립트의 평문 비밀번호 입력이나 초기 관리자 생성 명령은 실행하지 않습니다.

## 실패·재시도

손상된 이미지·체크섬, 다른 앱 경로·프로젝트, 지원하지 않는 DB 스키마, 잘못된 비밀 설정은 사전 점검에서 거절합니다. 이미지 로드·컨테이너 준비·Nginx·접근 차단 검사에 실패하면 공개 차단을 유지하고 실패 기록을 남깁니다. 비밀이 포함될 수 있는 전체 Docker inspect/config 출력 대신 오류 종류와 기록 경로로 조사합니다.

현재 사용자 DB에 미반영 WAL이 있으면 조회 전용 점검은 이를 무시하지 않고 중단합니다. 정상 운영 절차로 writer를 안전하게 정리한 뒤 재점검합니다. 실제 변경 단계에서는 writer를 모두 중지하고 체크포인트·일관된 백업·스키마 호환성을 재검사합니다.

Ctrl+C와 SIGTERM은 변경 단계의 실패 정리 경로를 사용합니다. SIGKILL, 전원 차단, 디스크·Nginx 자체 장애까지 프로세스가 정리 동작을 보장할 수는 없습니다. 이런 경우 공개 접속을 수동 차단하고 실제 상태·마지막 기록부터 확인합니다.

실패 후 무조건 최신 배포를 반복하지 않습니다. 현재 실제 실행 상태와 남은 복구 지점을 확인하고 같은 사전 점검부터 다시 시작합니다. 인증 도입 전 버전으로 복구한 뒤 최신 MFA 사용자 DB를 되돌리는 작업은 일반 이미지 롤백과 구분해야 합니다. 보관된 최신 사용자 DB와 대응하는 키를 확인하여 운영자가 별도로 복원하고, 세션·등록 코드·다운로드 권한을 폐기한 뒤 보안 검증을 다시 수행합니다.

## 로컬 검증

원본 계정·자료를 마운트하지 않은 임시 DB·설정·컨테이너로 검증합니다. 단위 테스트와 실제 Docker/Compose/Nginx 리허설 결과를 구분하여 기록합니다. 운영 도메인·운영 인증서·운영 서버·실제 키는 변경하지 않습니다.

```bash
.venv311/bin/python -m pytest -q .codex/tests/test_rollback.py
```

<!-- 2026-10-15 hoyeon.han: 실제 리허설은 명시적으로 선택하고 준비된 로컬 이미지만 사용합니다. -->
위 기본 명령은 단위 검사만 수행하며 실제 Docker 검사는 건너뜁니다. Docker Desktop이 실행 중이고 `.venv311`에 프로젝트 의존성과 pytest가 설치된 개발 환경에서는 다음 명령으로 실제 복구 리허설을 선택합니다.

```bash
SOLLUME_ROLLBACK_INTEGRATION=1 .venv311/bin/python -m pytest -q .codex/tests/test_rollback.py -p no:cacheprovider --tb=short
```

리허설은 로컬에 준비된 `sollume-finance-security:venv-test`(현 인증 이미지), `sollume-finance-sollume-app:latest`(인증 도입 전 이미지), `nginx:alpine` 이미지를 사용합니다. 실행 전에 각 태그가 의도한 검증 이미지인지 확인합니다. 도구가 운영 이미지를 다운로드하거나 운영 서버에 접속하지 않습니다. 테스트는 합성 DB와 비밀값·자체 서명 TLS·별도 Compose 프로젝트·임시 루프백 포트를 만들고 종료 시 정리합니다. Docker Desktop의 `host.docker.internal`을 사용하는 시험 구성으로, Linux 운영 호스트의 systemd·방화벽·실제 인증서는 검증 범위에 포함하지 않습니다.

실제 Docker 리허설의 명령·결과·한계는 [롤백 검증 기록](ROLLBACK_VALIDATION.md)을 참고합니다. 로컬 ARM64 이미지의 성공을 다른 아키텍처나 실제 운영 배포 성공으로 간주하지 않습니다.
