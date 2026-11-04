"""2026-11-04 hoyeon.han: 이미지 기본 CMD와 명시한 실행 명령의 보존을 검증한다.

운영 Docker·DB를 사용하지 않고 기존 합성 백업 fixture와 제한된 runner만 사용한다.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def snapshot(tmp_path):
    # 2026-11-04 hoyeon.han: 공통 합성 DB·마운트·이미지를 재사용한다.
    name = "snapshot_command_fixture_" + str(id(tmp_path))
    spec = importlib.util.spec_from_file_location(
        name, ROOT / ".codex/user-management/verify_manual_archive.py"
    )
    helper = importlib.util.module_from_spec(spec)
    sys.modules[name] = helper
    spec.loader.exec_module(helper)
    source = helper.SyntheticArchive(parent=tmp_path)
    api = helper.release_api()
    nginx = source.app / "nginx.site"
    nginx.write_text((ROOT / "nginx-host-api.conf.example").read_text())

    class SnapshotRunner(helper.RecordingRunner):
        def run(self, argv, *, input=None, env=None):
            args = list(map(str, argv))
            if args[:3] == ["docker", "image", "save"]:
                self.calls.append(args)
                output = Path(args[args.index("--output") + 1])
                output.write_bytes((source.backup / "images.tar").read_bytes())
                return ""
            return super().run(args, input=input, env=env)

    runner = SnapshotRunner(source)
    manager = api.ReleaseManager(source.app, nginx, runner=runner)
    try:
        yield SimpleNamespace(api=api, source=source, runner=runner, manager=manager)
    finally:
        source.close()


def app_command(snapshot, mode):
    service = deepcopy(snapshot.source.compose["services"]["sollume-app"])
    if mode == "missing":
        service.pop("command")
    else:
        service["command"] = None
    item = deepcopy(snapshot.source.containers[0])
    return service, item


@pytest.mark.parametrize("mode", ["missing", "null"])
def test_inherited_command_matches_the_exact_running_image_default(snapshot, mode):
    service, item = app_command(snapshot, mode)
    service["image"] = "mutable-tag:latest"
    item["Config"]["Image"] = "another-mutable-tag:latest"
    snapshot.manager._assert_command(service, item)
    assert snapshot.runner.calls == [["docker", "image", "inspect", item["Image"]]]


@pytest.mark.parametrize("mode", ["missing", "null"])
@pytest.mark.parametrize("actual", [None, [], ["python", "different-application.py"]])
def test_inherited_command_rejects_runtime_drift(snapshot, mode, actual):
    service, item = app_command(snapshot, mode)
    item["Config"]["Cmd"] = actual
    with pytest.raises(snapshot.api.SafetyError, match="실행 명령"):
        snapshot.manager._assert_command(service, item)


@pytest.mark.parametrize("command", [[], ["python", "changed-command.py"]])
def test_explicit_command_does_not_fall_back_to_matching_image_default(snapshot, command):
    service, item = app_command(snapshot, "null")
    service["command"] = command
    with pytest.raises(snapshot.api.SafetyError, match="실행 명령"):
        snapshot.manager._assert_command(service, item)
    assert snapshot.runner.calls == []


@pytest.mark.parametrize("command,actual", [([], None), ([], []), (["gunicorn", "app:app"], ["gunicorn", "app:app"])])
def test_matching_explicit_command_keeps_empty_and_list_semantics(snapshot, command, actual):
    service, item = app_command(snapshot, "null")
    service["command"] = command
    item["Config"]["Cmd"] = actual
    snapshot.manager._assert_command(service, item)
    assert snapshot.runner.calls == []


@pytest.mark.parametrize("entrypoint", [[], ["/app/explicit-entrypoint"]])
@pytest.mark.parametrize("actual", [None, []])
def test_explicit_entrypoint_does_not_inherit_image_command(snapshot, entrypoint, actual):
    service, item = app_command(snapshot, "null")
    service["entrypoint"] = entrypoint
    item["Config"]["Cmd"] = actual
    snapshot.manager._assert_command(service, item)
    assert snapshot.runner.calls == []


@pytest.mark.parametrize("entrypoint", [[], ["/app/explicit-entrypoint"]])
def test_explicit_entrypoint_rejects_unexpected_inherited_command(snapshot, entrypoint):
    service, item = app_command(snapshot, "null")
    service["entrypoint"] = entrypoint
    with pytest.raises(snapshot.api.SafetyError, match="실행 명령"):
        snapshot.manager._assert_command(service, item)
    assert snapshot.runner.calls == []


@pytest.mark.parametrize("mode", ["missing", "null"])
def test_capture_accepts_inherited_command_without_changing_sources(snapshot, mode):
    source = snapshot.source
    service, _ = app_command(snapshot, mode)
    source.compose["services"]["sollume-app"] = service
    source.compose["services"]["sollume-app"]["entrypoint"] = None
    source.compose["services"]["sollume-api"]["entrypoint"] = None
    (source.app / "docker-compose.cloud.yml").write_text(json.dumps(source.compose))
    protected = [source.app / name for name in (
        ".env", "docker-compose.cloud.yml", "database/users.db",
        "database/customer_master.db", "order_data/current.xlsm",
    )]
    before = {str(path): path.read_bytes() for path in protected}
    archives_before = source.archive_hashes()

    result = snapshot.manager.capture()

    assert result["captured"] is True
    release = Path(result["release"])
    saved = json.loads((release / "compose.json").read_text())
    manifest = json.loads((release / "manifest.json").read_text())
    assert saved["services"]["sollume-app"].get("command") is None
    for item in source.containers:
        role = item["Config"]["Labels"]["com.docker.compose.service"]
        assert saved["services"][role]["image"] == item["Image"]
        assert manifest["services"][role]["image_id"] == item["Image"]
    assert saved["services"]["sollume-api"]["command"] == source.containers[1]["Config"]["Cmd"]
    assert (release / "images.tar").read_bytes() == (source.backup / "images.tar").read_bytes()
    assert source.archive_hashes() == archives_before
    assert {str(path): path.read_bytes() for path in protected} == before


@pytest.mark.parametrize("mode", ["missing", "null"])
def test_capture_rejects_changed_default_command_before_snapshot_creation(snapshot, mode):
    service, _ = app_command(snapshot, mode)
    snapshot.source.compose["services"]["sollume-app"] = service
    snapshot.source.containers[0]["Config"]["Cmd"] = ["python", "unexpected.py"]
    original_releases = set(snapshot.manager.releases_dir.iterdir())
    original_archives = snapshot.source.archive_hashes()
    with pytest.raises(snapshot.api.SafetyError, match="실행 명령"):
        snapshot.manager.capture()
    assert set(snapshot.manager.releases_dir.iterdir()) == original_releases
    assert snapshot.source.archive_hashes() == original_archives
    assert not any(call[:3] == ["docker", "image", "save"] for call in snapshot.runner.calls)
