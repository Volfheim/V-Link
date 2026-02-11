"""
Windows autostart helper for V-Link.
Recommended strategy: HKCU Run key only.
"""

import os
import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "V-Link"


def _build_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'

    python_exe = Path(sys.executable).resolve()
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{python_exe}" "{main_py}"'


def _legacy_startup_paths() -> list[Path]:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        base = Path(appdata)
    else:
        base = Path.home() / "AppData" / "Roaming"

    startup_dir = base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return [
        startup_dir / "V-Link-Autostart.cmd",
        startup_dir / "V-Link.cmd",
        startup_dir / "V-Link Autostart.cmd",
    ]


def _cleanup_legacy_startup_files():
    for path in _legacy_startup_paths():
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass


def set_autostart(enabled: bool):
    import winreg

    command = _build_command()
    _cleanup_legacy_startup_files()

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def is_autostart_enabled() -> bool:
    import winreg

    _cleanup_legacy_startup_files()

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(str(value or "").strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False
