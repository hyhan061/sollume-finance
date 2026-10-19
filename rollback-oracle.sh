#!/usr/bin/env bash
# 2026-10-15 hoyeon.han: 명시적인 운영 가상환경으로만 오프라인 복구를 실행한다.
# 기본 실행은 검증 계획이며 실제 변경에는 helper의 --apply가 필요하다.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 2026-10-19 hoyeon.han: 일반 도움말에서도 압축 백업과 기존 snapshot의 구분을 안내한다.
if test "$#" -eq 1 && { test "$1" = --help || test "$1" = -h; }; then
    echo "압축 백업 점검: rollback-oracle.sh --app-dir 원래절대경로 --backup-dir 절대백업경로"
    echo "실제 구버전 복구: 위 인자와 모든 --nginx-config 사이트, --legacy-private --restore-users --apply 지정"
    echo "기존 전용 snapshot: --backup-dir 대신 --release 복구지점 사용"
    echo "기본은 조회만 수행하며 구버전 복구 후 외부 접속을 재개하지 않습니다."
    exit 0
fi
PYTHON_EXECUTABLE="${SOLLUME_OPS_PYTHON:-$SCRIPT_DIR/.venv-ops/bin/python}"
if [ ! -x "$PYTHON_EXECUTABLE" ]; then
    echo "운영 가상환경을 준비하거나 SOLLUME_OPS_PYTHON에 가상환경 Python 절대 경로를 지정하세요." >&2
    exit 1
fi
# exec "$PYTHON_EXECUTABLE" "$SCRIPT_DIR/scripts/release_snapshot.py" rollback "$@"
# 2026-10-19 hoyeon.han: 압축 백업을 지정하면 전용 검증·복구로 보내고 기본은 조회만 수행한다.
ROLLBACK_COMMAND=rollback
for argument in "$@"; do
    case "$argument" in
        --backup-dir|--backup-dir=*) ROLLBACK_COMMAND=manual-rollback ;;
    esac
done
exec "$PYTHON_EXECUTABLE" "$SCRIPT_DIR/scripts/release_snapshot.py" "$ROLLBACK_COMMAND" "$@"
