"""
V-Link - Build Script
Builds Windows executable via PyInstaller.
"""

import os
import subprocess
import sys
from pathlib import Path


def build():
    root = Path(__file__).resolve().parent
    dist_dir = root / "dist"

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    # Ensure QR dependencies are present for mobile connect dialog.
    try:
        import qrcode  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Installing QR dependencies (qrcode[pil])...")
        subprocess.run([sys.executable, "-m", "pip", "install", "qrcode[pil]"], check=True)

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
        "--hidden-import",
        "qrcode.image.pil",
        "--hidden-import",
        "PIL.Image",
        "--exclude-module",
        "numpy",
        "src/main.py",
    ]

    print("Build command:")
    print(" ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)

    exe_path = dist_dir / f"{output_name}.exe"
    if exe_path.exists():
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
