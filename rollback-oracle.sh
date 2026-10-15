#!/usr/bin/env bash
# 2026-10-15 hoyeon.han: 명시적인 운영 가상환경으로만 오프라인 복구를 실행한다.
# 기본 실행은 검증 계획이며 실제 변경에는 helper의 --apply가 필요하다.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_EXECUTABLE="${SOLLUME_OPS_PYTHON:-$SCRIPT_DIR/.venv-ops/bin/python}"
if [ ! -x "$PYTHON_EXECUTABLE" ]; then
    echo "운영 가상환경을 준비하거나 SOLLUME_OPS_PYTHON에 가상환경 Python 절대 경로를 지정하세요." >&2
    exit 1
fi
exec "$PYTHON_EXECUTABLE" "$SCRIPT_DIR/scripts/release_snapshot.py" rollback "$@"
