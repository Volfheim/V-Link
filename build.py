"""
V-Link - Build Script
Builds Windows executable via PyInstaller.
"""

import os
import subprocess
import sys
from pathlib import Path


def _build_environment():
    env = os.environ.copy()
    if os.name == "nt":
        system_dir = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32").resolve()
        search_dirs = []
        for entry in env.get("PATH", "").split(os.pathsep):
            if not entry:
                continue
            directory = Path(entry)
            if directory.resolve() != system_dir and (directory / "icuuc.dll").is_file():
                continue
            search_dirs.append(entry)
        env["PATH"] = os.pathsep.join(search_dirs)
    return env


def _verify_bundle(exe_path):
    from PyInstaller.archive.readers import CArchiveReader

    bundled_icu = [
        name for name in CArchiveReader(str(exe_path)).toc
        if Path(name.replace("\\", "/")).name.lower().startswith("icu")
        and name.lower().endswith(".dll")
    ]
    if bundled_icu:
        raise RuntimeError(
            "Unexpected ICU DLLs in V-Link.exe: " + ", ".join(sorted(bundled_icu))
        )


def build():
    root = Path(__file__).resolve().parent
    dist_dir = root / "dist"

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    # QR matrix generation is pure Python; Qt renders it without Pillow.
    try:
        import qrcode  # noqa: F401
    except ImportError:
        print("Installing qrcode...")
        subprocess.run([sys.executable, "-m", "pip", "install", "qrcode"], check=True)

    # Keep runtime executable path stable for in-place updates and shortcuts.
    output_name = "V-Link"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        output_name,
        "--icon",
        "app_icon.ico",
        "--version-file",
        "version.txt",
        "--paths",
        "src",
        "--add-data",
        "app_icon.ico;.",
        "--add-data",
        "src/ui/web_interface.html;ui",
        "--add-data",
        "resources/logo.png;resources",
        "--add-data",
        "resources/locales/ru.json;resources/locales",
        "--add-data",
        "resources/locales/en.json;resources/locales",
        "--hidden-import",
        "qrcode",
        "--exclude-module",
        "PIL",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "PySide6",
        "--exclude-module",
        "PySide2",
        "--exclude-module",
        "PyQt5",
        "src/main.py",
    ]

    print("Build command:")
    print(" ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, env=_build_environment())

    exe_path = dist_dir / f"{output_name}.exe"
    if exe_path.exists():
        _verify_bundle(exe_path)
        for stale in dist_dir.glob("V-Link-*.exe"):
            try:
                stale.unlink()
            except Exception:
                pass
        print(f"\nBuild complete: {exe_path}")
        print(f"Size: {exe_path.stat().st_size // 1024} KB")
    else:
        raise FileNotFoundError(f"Expected output not found: {exe_path}")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    build()
