"""
Windows autostart helper for V-Link.
"""

from pathlib import Path
import sys


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "V-Link"


def _build_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    python_exe = sys.executable
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{python_exe}" "{main_py}"'


def set_autostart(enabled: bool):
    import winreg

    access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _build_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def is_autostart_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False
