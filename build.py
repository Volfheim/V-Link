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

    sys.path.insert(0, str(root / "src"))
    from version import __version__

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    output_name = f"V-Link-{__version__}"

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
        "src/main.py",
    ]

    print("Build command:")
    print(" ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)

    exe_path = dist_dir / f"{output_name}.exe"
    if exe_path.exists():
        print(f"\nBuild complete: {exe_path}")
        print(f"Size: {exe_path.stat().st_size // 1024} KB")
    else:
        raise FileNotFoundError(f"Expected output not found: {exe_path}")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    build()
