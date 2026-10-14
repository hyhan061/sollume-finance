<!-- 2026-10-14 hoyeon.han: 기존 CPU·메모리 정책 복원 및 로컬 검증 기록 -->
# CPU·메모리 정책 복원

`codex/strict-user-management`의 `docker-compose.cloud.yml`에서 기존 main의 자원 정책을 복원했다.

| 서비스 | CPU 상한 | 메모리 상한 | CPU 예약 선언 | 메모리 예약 |
|---|---:|---:|---:|---:|
| 회계앱 | 4 | 20G | 2 | 4G |
| 발주내역 API | 1 | 2G | 기존에 없음 | 기존에 없음 |

인증 서비스의 정책은 이번 변경 대상에 포함하지 않았다. 기존 주석과 CRLF를 유지했고 자원 설정 15줄을 추가했다.

실제 Docker Compose 파서로 두 서비스의 전체 `deploy.resources`가 main과 동일함을 확인했다. CPU·메모리 값을 실제 숫자로 정규화하여 검사하는 회귀 테스트 2개를 추가했고, 기존 포트 제한·인증 설정 검사를 포함한 `test_security_config.py` 11개가 통과했다.

로컬 Docker Desktop에 설치된 Nginx 이미지를 사용하여 자원 설정만 담은 검증용 컨테이너 2개를 생성했다. 컨테이너는 한 번도 시작하지 않았으며 운영 경로 마운트·포트 게시 없이 네트워크를 `none`으로 지정했다. Docker HostConfig의 NanoCpus·Memory·MemoryReservation을 확인한 후 두 컨테이너를 제거했다.

CPU 예약은 기존 Compose 선언값 2를 보존했는지 검사했다. 실제 CPU 최소 할당이나 부하 성능을 검증한 것은 아니다. 운영 서버에는 연결하거나 배포하지 않았고 원본 사용자·거래처 DB 및 발주 파일 등 9개 SHA256이 변경되지 않았다. 기존 로컬 사용자 테스트 서버는 변경하지 않았다.

상세 검증 결과는 `resource-limits-validation-20261014.json`, 재실행 도구는 `verify_resource_limits.py`에 저장했다. 검증 도구는 기존 `.venv311`와 로컬 Docker Desktop의 설치된 `nginx:alpine` 이미지가 필요하며, Docker 이미지 게시나 실제 서비스 기동을 실행하지 않는다.
