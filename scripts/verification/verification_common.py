"""2026-11-05 hoyeon.han: 검증 도구의 출력 경로와 개인 보존 기준 입력 계약."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / '.codex/outputs/verification'
# 2026-11-05 hoyeon.han: 개인 입력의 기존 위치만 호환하며 파일 자체는 배포하지 않는다.
DEFAULT_BASELINE = ROOT / '.codex/user-management/data-baseline.json'


def add_baseline_argument(parser):
    """실데이터 파일별 SHA256을 담은 개인 입력 파일을 명시적으로 선택한다."""
    parser.add_argument(
        '--baseline', type=Path, default=DEFAULT_BASELINE,
        help='보존 기준 JSON 경로(업무파일 상대경로: SHA256). 파일이 없거나 일치하지 않으면 검증을 중단합니다.',
    )


def load_baseline(path=None, *, root=ROOT):
    """유효하고 현재 업무파일과 일치하는 보존 기준만 반환한다.

    누락된 개인 자료를 빈 목록으로 대체하면 보존 검사가 통과한 것처럼
    보이므로, 실행 전에 형식·경로·내용을 확인하고 한국어 오류를 제공한다.
    """
    baseline_path = Path(path if path is not None else DEFAULT_BASELINE).expanduser()
    try:
        baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(
            f'보존 기준 파일을 읽을 수 없습니다: {baseline_path}. '
            '현재 업무파일의 SHA256 기준 JSON을 준비하고 --baseline 경로를 지정해 주세요.'
        ) from exc
    if not isinstance(baseline, dict) or not baseline:
        raise ValueError('보존 기준은 업무파일 상대경로와 SHA256을 담은 비어 있지 않은 JSON 객체여야 합니다.')
    repository_root = Path(root).resolve()
    for name, expected_hash in baseline.items():
        if (
            not isinstance(name, str)
            or not name
            or Path(name).is_absolute()
            or PureWindowsPath(name).is_absolute()
            or '..' in Path(name).parts
            or '\\' in name
            or not isinstance(expected_hash, str)
            or re.fullmatch(r'[0-9a-f]{64}', expected_hash) is None
        ):
            raise ValueError('보존 기준은 저장소 내부 상대파일경로와 소문자 64자리 SHA256 형식이어야 합니다.')
        source_path = (repository_root / name).resolve()
        if not source_path.is_relative_to(repository_root):
            raise ValueError(f'보존 기준의 업무파일 경로가 저장소 밖을 가리킵니다: {name}')
        try:
            actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError(f'보존 기준의 업무파일을 읽을 수 없습니다: {name}. 파일 위치와 --baseline을 확인해 주세요.') from exc
        if actual_hash != expected_hash:
            raise ValueError(f'보존 기준과 현재 업무파일의 SHA256이 다릅니다: {name}. 올바른 --baseline을 선택해 주세요.')
    return baseline
