# 2026-11-05 hoyeon.han: .codex 소스가 없는 clone의 검증 경로·baseline 계약을 확인한다.
"""운영 접속 없이 검증 모듈의 독립 import와 명시 baseline 입력을 확인한다."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFICATION_DIR = ROOT / "scripts" / "verification"


def _load(name, monkeypatch):
    module_name = "repository_verification_" + name
    spec = importlib.util.spec_from_file_location(module_name, VERIFICATION_DIR / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", [
    "verification_common", "verify_resource_limits", "verify_docker_user_cli",
    "verify_deployment_preflight", "verify_manual_archive", "verify_rollback",
])
def test_import_uses_source_location_without_reading_baseline_or_running_commands(name, tmp_path, monkeypatch):
    # 파일 위치가 기준이므로 다른 cwd에도 운영 baseline이나 Docker가 필요하지 않다.
    monkeypatch.chdir(tmp_path)
    def unexpected_command(*args, **kwargs):
        pytest.fail("검증 모듈 import 중 외부 명령이 실행되었습니다.")
    monkeypatch.setattr(subprocess, "run", unexpected_command)
    module = _load(name, monkeypatch)
    assert module.ROOT == ROOT
    assert Path(module.__file__).resolve().parent == VERIFICATION_DIR


def _baseline(tmp_path, monkeypatch):
    module = _load("verification_common", monkeypatch)
    business = tmp_path / "database" / "synthetic.db"
    business.parent.mkdir()
    business.write_bytes(b"synthetic verification fixture")
    expected = {"database/synthetic.db": hashlib.sha256(business.read_bytes()).hexdigest()}
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(expected), encoding="utf-8")
    return module, business, path, expected


def test_explicit_baseline_is_checked_against_its_requested_root(tmp_path, monkeypatch):
    module, business, path, expected = _baseline(tmp_path, monkeypatch)
    assert module.load_baseline(path, root=tmp_path) == expected
    assert module.DEFAULT_OUTPUT_DIR == ROOT / ".codex" / "outputs" / "verification"
    assert business.read_bytes() == b"synthetic verification fixture"


def test_baseline_detects_changed_business_file(tmp_path, monkeypatch):
    module, business, path, expected = _baseline(tmp_path, monkeypatch)
    business.write_bytes(b"changed synthetic verification fixture")
    with pytest.raises(ValueError):
        module.load_baseline(path, root=tmp_path)
    assert json.loads(path.read_text()) == expected


@pytest.mark.parametrize("kind", ["missing", "invalid_json", "empty", "bad_digest", "absolute", "escape", "missing_file"])
def test_missing_or_invalid_baseline_fails_closed(kind, tmp_path, monkeypatch):
    module, business, path, expected = _baseline(tmp_path, monkeypatch)
    digest = expected["database/synthetic.db"]
    if kind == "missing":
        path.unlink()
    elif kind == "invalid_json":
        path.write_text("not a JSON object")
    elif kind == "empty":
        path.write_text("{}")
    else:
        invalid = {
            "bad_digest": {"database/synthetic.db": "invalid"},
            "absolute": {str(business): digest},
            "escape": {"../outside.db": digest},
            "missing_file": {"database/missing.db": digest},
        }[kind]
        path.write_text(json.dumps(invalid))
    with pytest.raises(ValueError):
        module.load_baseline(path, root=tmp_path)


# 2026-11-05 hoyeon.han: 테스트 소스만 추적되고 개인 자료·검증 결과는 제외되는지 확인한다.
@pytest.mark.parametrize("relative,ignored", [
    ("tests/test_new_clone.py", False),
    ("tests/security/test_new_clone.py", False),
    ("tests/operations/test_new_clone.py", False),
    ("tests/nested/helpers.py", False),
    ("tests/private-orders.xlsm", True),
    ("tests/fixtures/private-ecount.xlsx", True),
    ("tests/fixtures/private-data.csv", True),
    ("tests/outputs/verification.json", True),
    (".codex/user-management/verify_local.py", True),
    (".Codex/outputs/verification.json", True),
    (".codex/outputs/verification/report.json", True),
    ("AGENTS.md", True),
])
def test_gitignore_keeps_python_tests_and_excludes_local_inputs(relative, ignored, tmp_path):
    # 실제 저장소의 인덱스를 건드리지 않고 export 환경에서도 같은 규칙을 검사한다.
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], capture_output=True, text=True, check=True)
    (tmp_path / ".gitignore").write_text((ROOT / ".gitignore").read_text())
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", relative],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode in (0, 1), result.stderr
    assert (result.returncode == 0) is ignored
