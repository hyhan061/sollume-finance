# office1 도메인 전환 로컬 검증

2026-10-19 hoyeon.han

공개 주소는 `https://office1.sollumeesthe.com`이며, 이번 변경과 검증은 로컬에서만 수행했다. 운영 앱 배포·운영 서버 접속·원격 push는 하지 않았다.

## 변경 범위

- 환경 예시, 두 Compose, 두 Nginx, 배포·복구 도구와 검증·운영 문서의 활성 도메인을 office1로 일치시켰다.
- 호스트 Nginx는 기본 서버를 지정하지 않고 office1 전용 map·제한 영역을 사용한다.
- 정상 보안 구성과 비공개 503 복구 모두 office1의 고정 HTTP ACME 경로를 유지한다.
- 루트 도메인은 복구 대상에서 제외하며, 기존 계정·업무자료·CPU/메모리 제한을 유지한다.

## 직접 실행한 검증

| 항목 | 결과 |
|---|---|
| 보안·회계·배포·복구 pytest | 294 통과, 12 제외(별도 Docker 실행 항목) |
| 실제 수동 압축 복구 | 37개 통과 |
| 실제 전용 snapshot 복구 | 68개 통과 |
| 실제 Docker 관리자 CLI·MFA 최초 등록 | 35개 통과 |
| 정상·실패503·재시도·구버전 복구의 ACME | HTTP200 및 본문 일치 |
| 인증·다운로드 차단 및 타 도메인·canary | 통과 |
| 원본 데이터 | 9개 파일 SHA-256 불변 |
| Python AST / Bash 문법 / CRLF | 11개 / 2개 / 3개 통과 |
| 테스트 자원 정리 | 완료 |

직접 실행한 pytest 근거는 [JUnit 결과](office1-pytest.xml), 실제 리허설은 [수동 압축 복구](office1-manual-results.md)와 [전용 snapshot 복구](office1-rollback-results.md), [관리자 CLI·MFA 등록](office1-cli-results.md)을 참조한다. 합산 근거·제약은 [검증 JSON](office1-validation.json)에 기록했다. 하위 리허설 JSON의 이전 parent_regression 참고값은 이번 부모 회귀 실행 결과가 아니다.

## 운영 배포 전에 남은 필수 작업

현재 배포의 `manual-prepare --check-current`는 백업·현재 런타임·계정 대조이며, 인자로 넘긴 Nginx 사이트 전체의 누락 또는 기존 DuckDNS 무인증 프록시 차단까지 보장하지 않는다. 전체 진입점 검사는 복구 경로에 있다.

운영 배포 전에 기존 두 DuckDNS의 회계 접속을 office1 리다이렉트 또는 차단 정책으로 전환·검증하고, 배포 공통 사전검사에서 누락·비활성 파일·무인증 프록시를 거절하도록 보강해야 한다. 새 이미지를 배포하거나 8501 외부 포트를 변경하는 작업은 아직 수행하지 않았다.

## 운영자가 확인한 인증서 스케줄

기존 3개 DuckDNS 인증서는 nginx 인증·설치 플러그인이고, office1은 webroot와 전용 deploy hook을 사용한다. 타이머는 하나를 공유한다. 실제 서비스는 `/usr/bin/certbot -q renew --no-random-sleep-on-renew`로 모든 인증서의 갱신 필요 여부를 확인하며, office1 후속 작업도 활성 상태다.

타이머는 한국시간 0시·12시를 기준으로 최대 43200초(12시간)의 무작위 지연을 적용하고, 중단 중 누락된 예약은 Persistent 설정으로 보완한다. 새 타이머나 cron을 추가하지 않았다.
