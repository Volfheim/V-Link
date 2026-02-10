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

    def _update_dir(self) -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if not local_app_data:
            local_app_data = os.path.expanduser("~\\AppData\\Local")
        return Path(local_app_data) / "V-Link" / "updates"

    async def check_for_update(self, force: bool = False) -> Optional[UpdateInfo]:
        """Check GitHub for a newer release. Returns UpdateInfo or None."""
        if self._checking:
            return self._info
        if not force and not self._should_check():
            return self._info

        self._checking = True
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(GITHUB_API_LATEST, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()

            tag_name = data.get("tag_name", "")
            if not tag_name:
                return None

            remote_ver = self._parse_version(tag_name)
            local_ver = self._parse_version(__version__)

            # Simple comparison tuple vs tuple
            if remote_ver <= local_ver:
                self.settings.set("last_update_check", datetime.now().isoformat())
                return None

            # Check if skipped
            skipped = self.settings.get("skipped_version", "")
            if not force and skipped == tag_name:
                return None

            assets = data.get("assets", [])
            download_url = ""
            asset_size = 0
            asset_name = ""

            for asset in assets:
                name = asset.get("name", "").lower()
                if name.endswith(".exe") and "setup" not in name:
                    download_url = asset.get("browser_download_url")
                    asset_size = asset.get("size", 0)
                    asset_name = asset.get("name", "")
                    break

            if not download_url:
                return None

            self._info = UpdateInfo(
                version=tag_name,
                download_url=download_url,
                body=data.get("body", ""),
                asset_name=asset_name,
                asset_size=asset_size,
            )
            self.settings.set("last_update_check", datetime.now().isoformat())
            
            if self.on_update_available:
                self.on_update_available(self._info.version, self._info.body)
            
            return self._info

        except Exception:
            return None
        finally:
            self._checking = False

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def download_update(self):
        """Download asset to %LOCALAPPDATA%/V-Link/updates/."""
        if self._downloading: 
            return None
        if not self._info:
            if self.on_error:
                self.on_error("Нет информации об обновлении")
            return None

        self._downloading = True
        try:
            update_dir = self._update_dir()
            update_dir.mkdir(parents=True, exist_ok=True)
            target = update_dir / "latest.exe"

            # Clean previous
            if target.exists():
                try:
                    target.unlink()
                except Exception:
                    pass

            async with aiohttp.ClientSession() as session:
                async with session.get(self._info.download_url) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP Error {resp.status}")
                    
                    total_size = int(resp.headers.get('Content-Length', 0))
                    downloaded = 0
                    
                    with open(target, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(65536):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0 and self.on_download_progress:
                                pct = int(downloaded / total_size * 100)
                                self.on_download_progress(pct)

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
        """Safely apply update using atomic rename strategy (Windows + PyInstaller safe)."""
        if not self.is_frozen():
            return

        current_exe = Path(sys.executable).resolve()
        current_pid = os.getpid()

        update_dir = self._update_dir()
        bat_path = update_dir / "_v-link-update.bat"

        old_exe = current_exe.with_suffix(".old")
        new_exe = current_exe.with_suffix(".new")

        # Autostart flag preserved for future use
        autostart_flag = "1" if self.settings.get("autostart", False) else "0"

        bat = f'''@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: -------------------------------------------------
:: Wait for current process to exit
:: -------------------------------------------------
:wait
tasklist /FI "PID eq {current_pid}" >NUL 2>&1
if %ERRORLEVEL%==0 (
    timeout /t 1 /nobreak >NUL
    goto wait
)

:: Extra delay to ensure DLL handles are released
timeout /t 3 /nobreak >NUL

:: -------------------------------------------------
:: Cleanup previous leftovers
:: -------------------------------------------------
if exist "{old_exe}" del /f /q "{old_exe}"
if exist "{new_exe}" del /f /q "{new_exe}"

:: -------------------------------------------------
:: Unblock downloaded file (critical)
:: -------------------------------------------------
powershell -Command "Unblock-File -Path '{downloaded_exe}'" >NUL 2>&1

:: -------------------------------------------------
:: Copy update to .new (NEVER overwrite live exe)
:: -------------------------------------------------
copy /Y /B "{downloaded_exe}" "{new_exe}" >NUL
if not exist "{new_exe}" exit /b 1

:: Small pause to ensure filesystem flush
timeout /t 1 /nobreak >NUL

:: -------------------------------------------------
:: Replace executable atomically
:: -------------------------------------------------
move /Y "{current_exe}" "{old_exe}" >NUL
move /Y "{new_exe}" "{current_exe}" >NUL

:: -------------------------------------------------
:: Final unblock (safety net)
:: -------------------------------------------------
powershell -Command "Unblock-File -Path '{current_exe}'" >NUL 2>&1

:: -------------------------------------------------
:: Start new version
:: -------------------------------------------------
start "" "{current_exe}"

:: -------------------------------------------------
:: Deferred cleanup (do NOT rush this)
:: -------------------------------------------------
timeout /t 5 /nobreak >NUL
if exist "{old_exe}" del /f /q "{old_exe}"
if exist "{downloaded_exe}" del /f /q "{downloaded_exe}"

:: NOTE: update_dir intentionally NOT removed here
:: new version may still rely on it during startup

:: Self-delete
(goto) 2>nul & del "%~f0"
'''

        update_dir.mkdir(parents=True, exist_ok=True)
        bat_path.write_text(bat, encoding="cp437", errors="ignore")

        # subprocess.Popen with DETACHED_PROCESS to allow self-delete
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            creationflags=0x00000008,  # DETACHED_PROCESS
            close_fds=True,
        )
        sys.exit(0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def skip_version(self):
        """Mark the current available update as skipped."""
        if self._info:
            self.settings.set("skipped_version", self._info.version)
            self._info = None
