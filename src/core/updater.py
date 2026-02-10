"""
V-Link - Auto-updater
Checks GitHub releases, downloads & applies updates.
"""

import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import aiohttp

from version import __version__

GITHUB_API_LATEST = "https://api.github.com/repos/Volfheim/V-Link/releases/latest"
CHECK_INTERVAL_HOURS = 12


class UpdateInfo:
    """Metadata for an available update."""

    __slots__ = ("version", "download_url", "body", "asset_name", "asset_size")

    def __init__(self, version: str, download_url: str, body: str, asset_name: str, asset_size: int):
        self.version = version
        self.download_url = download_url
        self.body = body
        self.asset_name = asset_name
        self.asset_size = asset_size


class Updater:
    """Manages update lifecycle: check → download → apply."""

    def __init__(self, settings):
        self.settings = settings
        self._info: Optional[UpdateInfo] = None
        self._checking = False
        self._downloading = False

        # Callbacks (all called from async context)
        self.on_update_available: Optional[Callable] = None   # (version: str, body: str)
        self.on_download_progress: Optional[Callable] = None  # (percent: int)
        self.on_update_ready: Optional[Callable] = None       # (path: str)
        self.on_error: Optional[Callable] = None              # (error: str)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @staticmethod
    def is_frozen() -> bool:
        return getattr(sys, "frozen", False)

    @property
    def has_update(self) -> bool:
        return self._info is not None

    @property
    def update_version(self) -> str:
        return self._info.version if self._info else ""

    @property
    def update_body(self) -> str:
        return self._info.body if self._info else ""

    # ------------------------------------------------------------------
    # Check
    # ------------------------------------------------------------------

    def _should_check(self) -> bool:
        if not self.is_frozen():
            return False
        if not self.settings.get("auto_check_updates", True):
            return False
        last_check = self.settings.get("last_update_check", "")
        if not last_check:
            return True
        try:
            last_dt = datetime.fromisoformat(last_check)
            hours = (datetime.now() - last_dt).total_seconds() / 3600
            return hours >= CHECK_INTERVAL_HOURS
        except Exception:
            return True

    @staticmethod
    def _parse_version(text: str):
        clean = text.lstrip("v").strip()
        parts = []
        for p in clean.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    async def check_for_update(self, force: bool = False) -> Optional[UpdateInfo]:
        """Check GitHub for a newer release. Returns UpdateInfo or None."""
        if self._checking:
            return self._info
        if not force and not self._should_check():
            return self._info

        self._checking = True
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(GITHUB_API_LATEST) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()

            tag = data.get("tag_name", "")
            body = data.get("body", "")

            remote = self._parse_version(tag)
            local = self._parse_version(__version__)

            self.settings.set("last_update_check", datetime.now().isoformat())

            if remote <= local:
                self._info = None
                return None

            skipped = self.settings.get("skipped_version", "")
            if skipped and skipped == tag and not force:
                return None

            download_url = ""
            asset_name = ""
            asset_size = 0
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.lower().endswith(".exe"):
                    download_url = asset.get("browser_download_url", "")
                    asset_name = name
                    asset_size = asset.get("size", 0)
                    break

            if not download_url:
                return None

            self._info = UpdateInfo(tag, download_url, body, asset_name, asset_size)

            if self.on_update_available:
                self.on_update_available(tag, body)

            return self._info

        except Exception:
            return None
        finally:
            self._checking = False

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    @staticmethod
    def _update_dir() -> Path:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "V-Link" / "updates"

    async def download_update(self) -> Optional[Path]:
        """Download the update EXE. Returns path on success."""
        if not self._info or self._downloading:
            return None

        self._downloading = True
        update_dir = self._update_dir()
        update_dir.mkdir(parents=True, exist_ok=True)

        # Clean previous downloads
        for f in update_dir.iterdir():
            try:
                f.unlink()
            except Exception:
                pass

        target = update_dir / self._info.asset_name

        try:
            timeout = aiohttp.ClientTimeout(total=600)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self._info.download_url) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")

                    total = self._info.asset_size or int(resp.headers.get("Content-Length", 0))
                    received = 0

                    with open(target, "wb") as f:
                        async for chunk in resp.content.iter_chunked(256 * 1024):
                            f.write(chunk)
                            received += len(chunk)
                            if total > 0 and self.on_download_progress:
                                self.on_download_progress(min(100, int(received * 100 / total)))

            # Strict size check
            if not target.exists():
                raise RuntimeError("File not found after download")
            
            actual_size = target.stat().st_size
            if self._info.asset_size and actual_size != self._info.asset_size:
                raise RuntimeError(f"Size check failed: expected {self._info.asset_size}, got {actual_size}")
            
            if actual_size < 1_000_000:
                raise RuntimeError("Downloaded file is too small (<1MB)")

            # Unblock file using Powershell (critical for Windows 10/11)
            try:
                subprocess.run(
                    ["powershell", "-Command", f"Unblock-File -Path '{str(target)}'"],
                    check=False, creationflags=0x08000000
                )
            except Exception:
                pass

            if self.on_update_ready:
                self.on_update_ready(str(target))

            return target

        except Exception as e:
            try:
                if target.exists():
                    target.unlink()
            except Exception:
                pass
            if self.on_error:
                self.on_error(str(e))
            return None
        finally:
            self._downloading = False

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply_update(self, downloaded_exe: Path):
        """Create a bat helper, launch it, and signal the app to quit."""
        if not self.is_frozen():
            return

        current_exe = Path(sys.executable).resolve()
        current_pid = os.getpid()
        update_dir = self._update_dir()
        bat_path = update_dir / "_v-link-update.bat"
        old_exe = current_exe.parent / (current_exe.stem + ".old")

        # Strip Windows Zone.Identifier to prevent Defender from blocking
        # the extracted DLLs when the new EXE launches.
        try:
            ads_path = str(downloaded_exe) + ":Zone.Identifier"
            if os.path.exists(ads_path):
                os.remove(ads_path)
        except Exception:
            pass

        # If autostart is on, we need to refresh the registry entry
        autostart_flag = "1" if self.settings.get("autostart", False) else "0"

        # Use copy+del instead of move to avoid cross-drive issues.
        # move /Y silently fails or corrupts PyInstaller EXEs when
        # source (%LOCALAPPDATA%) and destination are on different drives.
        bat = (
            '@echo off\r\n'
            'chcp 65001 >nul 2>&1\r\n'
            '\r\n'
            ':: Wait for V-Link to exit\r\n'
            ':wait\r\n'
            f'tasklist /FI "PID eq {current_pid}" 2>NUL | find "{current_pid}" >NUL\r\n'
            'if %ERRORLEVEL%==0 (\r\n'
            '    timeout /t 1 /nobreak >NUL\r\n'
            '    goto wait\r\n'
            ')\r\n'
            '\r\n'
            ':: Extra delay for file handles to be released\r\n'
            'timeout /t 3 /nobreak >NUL\r\n'
            '\r\n'
            ':: Remove previous .old if exists\r\n'
            f'if exist "{old_exe}" del /f /q "{old_exe}"\r\n'
            '\r\n'
            ':: Rename running exe to .old\r\n'
            f'move /Y "{current_exe}" "{old_exe}"\r\n'
            '\r\n'
            ':: Unblock the new file again (just in case)\r\n'
            f'powershell -Command "Unblock-File -Path \'{downloaded_exe}\'" >NUL 2>&1\r\n'
            '\r\n'
            ':: Copy new exe (copy works across drives, move may not)\r\n'
            f'copy /Y /B "{downloaded_exe}" "{current_exe}" >NUL\r\n'
            '\r\n'
            ':: Verify copy\r\n'
            f'if not exist "{current_exe}" (\r\n'
            f'    move /Y "{old_exe}" "{current_exe}"\r\n'
            '    exit /b 1\r\n'
            ')\r\n'
            '\r\n'
            ':: Start new version\r\n'
            f'start "" "{current_exe}"\r\n'
            '\r\n'
            ':: Cleanup\r\n'
            'timeout /t 5 /nobreak >NUL\r\n'
            f'if exist "{old_exe}" del /f /q "{old_exe}"\r\n'
            f'if exist "{downloaded_exe}" del /f /q "{downloaded_exe}"\r\n'
            f'rmdir /s /q "{update_dir}" 2>NUL\r\n'
            '\r\n'
            ':: Self-delete\r\n'
            'del "%~f0"\r\n'
        )

        bat_path.write_text(bat, encoding="utf-8")

        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            close_fds=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def skip_version(self):
        """Mark the current available update as skipped."""
        if self._info:
            self.settings.set("skipped_version", self._info.version)
            self._info = None
