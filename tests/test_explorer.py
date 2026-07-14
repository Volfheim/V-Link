import os

import pytest

from core import explorer


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Explorer integration")


def test_reveal_file_selects_it_in_explorer(monkeypatch, tmp_path):
    target = tmp_path / "received.txt"
    target.write_text("ok", encoding="utf-8")
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(explorer.subprocess, "Popen", fake_popen)

    assert explorer.reveal_in_explorer(str(target))
    assert calls[0][0] == ["explorer.exe", "/select,", os.path.normpath(str(target.resolve()))]


def test_reveal_missing_file_opens_existing_parent(monkeypatch, tmp_path):
    opened = []
    missing = tmp_path / "folder" / "missing.txt"
    missing.parent.mkdir()
    monkeypatch.setattr(explorer.os, "startfile", opened.append)

    assert explorer.reveal_in_explorer(str(missing))
    assert opened == [os.path.normpath(str(missing.parent.resolve()))]
