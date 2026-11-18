# 2026-11-05 hoyeon.han: 재사용 검증 소스를 tests의 보안·운영 테스트로 분리한다.
"""2026-11-04 hoyeon.han: 이미지 검증과 게시 경계의 회귀 검증."""
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_probe_checks_actual_mfa_download_and_settlement_without_operational_data(tmp_path):
    protected = [ROOT / ".env", ROOT / "database/users.db", ROOT / "database/customer_master.db"]
    before = {str(path): path.read_bytes() if path.is_file() else None for path in protected}
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/verify_image_runtime.py")],
        cwd=tmp_path, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout
    report = json.loads(result.stdout)
    assert set(report) == {"passed", "checks", "check_count"}
    assert report["passed"] and report["check_count"] == len(report["checks"])
    assert {"python_virtual_environment", "authentication_modules_available",
            "password_only_denied_image.owner", "mfa_completed_image.owner",
            "owner_download_allowed", "anonymous_download_denied", "other_owner_download_denied",
            "unassigned_page_denied", "permission_revocation_denied", "settlement_excel_single",
            "settlement_excel_per_seller", "temporary_fixture_removed"} <= set(report["checks"])
    assert before == {str(path): path.read_bytes() if path.is_file() else None for path in protected}


def test_publication_is_after_verification_and_skipped_for_pull_requests():
    text = (ROOT / ".github/workflows/docker-publish.yml").read_text()
    steps = dict(part.split("\n", 1) for part in text.split("      - name: ")[1:])
    names = list(steps)
    assert names.index("Verify authentication, settlement and deployment") < names.index("Build verification image")
    assert names.index("Verify actual image runtime") < names.index("Login to Docker Hub")
    assert names.index("Verify actual image runtime") < names.index("Build and push (linux/amd64, linux/arm64)")
    assert "push: false" in steps["Build verification image"]
    assert "--network none --read-only" in steps["Verify actual image runtime"]
    for name in ("Login to Docker Hub", "Extract image metadata (tags, labels)",
                 "Build and push (linux/amd64, linux/arm64)", "Image digest summary"):
        assert "if: github.event_name != 'pull_request'" in steps[name]


def test_latest_is_only_published_from_main_and_main_push_triggers_build():
    text = (ROOT / ".github/workflows/docker-publish.yml").read_text()
    active = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "  push:\n    branches:\n      - main\n" in active
    assert "  pull_request:\n    branches:\n      - main\n" in active
    assert "flavor: latest=false" in active
    assert "type=raw,value=latest,enable=${{ github.ref == 'refs/heads/main' }}" in active
    assert "enable=${{ startsWith(github.ref, 'refs/tags/v') }}" not in active


# 2026-11-18 hoyeon.han: 버전 태그는 재빌드 없이 main에서 검증·게시된 이미지에 태그만 붙인다.
def test_release_tag_retags_verified_main_image_without_rebuild_or_latest():
    text = (ROOT / ".github/workflows/docker-publish.yml").read_text()
    active = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    build_job, retag_job = active.split("\n  release-retag:\n", 1)
    assert "      - \"v*\"\n" in active
    assert "    if: ${{ !startsWith(github.ref, 'refs/tags/v') }}\n" in build_job
    assert "    if: ${{ startsWith(github.ref, 'refs/tags/v') }}\n" in retag_job
    # 재태깅 job은 빌드·latest 게시를 하지 않고, main에 있는 커밋의 sha 이미지만 원본으로 쓴다.
    assert "build-push-action" not in retag_job
    assert "flavor: latest=false" in retag_job
    assert "type=raw" not in retag_job and "value=latest" not in retag_job
    assert '*:latest) echo "::error::' in retag_job
    assert "git merge-base --is-ancestor \"$GITHUB_SHA\" FETCH_HEAD" in retag_job
    assert 'SOURCE="${IMAGE_NAME}:sha-${GITHUB_SHA::7}"' in retag_job
    assert "docker buildx imagetools inspect \"$SOURCE\"" in retag_job
    assert "docker buildx imagetools create \"${args[@]}\" \"$SOURCE\"" in retag_job
    assert "type=sha,prefix=sha-,format=short" in build_job
    for pattern in ("{{version}}", "{{major}}.{{minor}}", "{{major}}"):
        assert f"type=semver,pattern={pattern}\n" in retag_job
