import os
from pathlib import Path

import pytest

from build import _build_environment, _verify_bundle


@pytest.mark.skipif(os.name != "nt", reason="Windows DLL search path")
def test_build_does_not_search_external_icu_directory(tmp_path, monkeypatch):
    windows = tmp_path / "Windows"
    system_dir = windows / "System32"
    foreign_dir = tmp_path / "foreign-tools"
    safe_dir = tmp_path / "safe-tools"
    for directory in (system_dir, foreign_dir, safe_dir):
        directory.mkdir(parents=True)
    (system_dir / "icuuc.dll").touch()
    (foreign_dir / "icuuc.dll").touch()

    monkeypatch.setenv("SystemRoot", str(windows))
    monkeypatch.setenv(
        "PATH", os.pathsep.join((str(system_dir), str(foreign_dir), str(safe_dir)))
    )

    assert _build_environment()["PATH"].split(os.pathsep) == [
        str(system_dir), str(safe_dir)
    ]


def test_packaged_app_has_no_foreign_icu_dll():
    exe = os.environ.get("VLINK_TEST_EXE")
    if not exe:
        pytest.skip("Set VLINK_TEST_EXE to check a packaged build")
    _verify_bundle(Path(exe))
