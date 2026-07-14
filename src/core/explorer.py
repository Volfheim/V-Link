"""Open files and folders in the operating system file manager."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def reveal_in_explorer(path: str) -> bool:
    target = Path(str(path or "")).expanduser()
    if not str(path or "").strip():
        return False

    if not target.exists():
        target = target.parent
        while target != target.parent and not target.exists():
            target = target.parent
    if not target.exists():
        return False

    try:
        if os.name == "nt":
            normalized = os.path.normpath(str(target.resolve()))
            if target.is_file():
                subprocess.Popen(
                    ["explorer.exe", "/select,", normalized],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                    close_fds=True,
                )
            else:
                os.startfile(normalized)
            return True

        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(target.resolve())], close_fds=True)
        return True
    except Exception:
        return False
