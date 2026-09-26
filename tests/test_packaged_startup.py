import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows GUI smoke test")
@pytest.mark.parametrize("profile_kind", ["clean", "settings_copy"])
def test_packaged_app_starts_services(tmp_path, profile_kind):
    exe = os.environ.get("VLINK_TEST_EXE")
    if not exe:
        pytest.skip("Set VLINK_TEST_EXE to check a packaged build")
    settings_source = os.environ.get("VLINK_TEST_SETTINGS_SOURCE")
    if profile_kind == "settings_copy" and not settings_source:
        pytest.skip("Set VLINK_TEST_SETTINGS_SOURCE for copied-settings startup")

    psutil = pytest.importorskip("psutil")
    profile = tmp_path / "profile"
    profile.mkdir()
    if profile_kind == "settings_copy":
        config_dir = profile / ".v-link"
        config_dir.mkdir()
        shutil.copyfile(settings_source, config_dir / "settings.json")
    else:
        config_dir = profile / ".v-link"
        config_dir.mkdir()

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        test_port = probe.getsockname()[1]
    config_file = config_dir / "settings.json"
    settings = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    settings["port"] = test_port
    config_file.write_text(json.dumps(settings), encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "HOME": str(profile),
        "USERPROFILE": str(profile),
        "APPDATA": str(profile / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(profile / "AppData" / "Local"),
        "VLINK_SKIP_AUTOSTART_SYNC": "1",
    })
    stderr_path = tmp_path / "stderr.txt"
    ready_flag = tmp_path / "ready.flag"
    with stderr_path.open("wb") as stderr:
        args = [exe, "--update-ready-flag", str(ready_flag)]
        if profile_kind == "settings_copy":
            args.append("--show-after-update")
        process = subprocess.Popen(args, cwd=str(Path(exe).parent), env=env, stderr=stderr)
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if ready_flag.exists():
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.25)

            assert ready_flag.exists() and process.poll() is None, (
                f"V-Link did not complete startup (exit={process.poll()}): "
                + stderr_path.read_text(encoding="utf-8", errors="replace")
            )
        finally:
            try:
                children = psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                children = []
            for child in reversed(children):
                child.terminate()
            if process.poll() is None:
                process.terminate()
            _, alive = psutil.wait_procs(children, timeout=5)
            for child in alive:
                child.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
