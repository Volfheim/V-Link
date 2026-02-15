"""
V-Link auto-updater.
Checks GitHub releases, downloads and applies updates.
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import aiohttp

from version import __version__

GITHUB_API_LATEST = "https://api.github.com/repos/Volfheim/V-Link/releases/latest"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "V-Link-Updater",
}
CHECK_INTERVAL_HOURS = 12


class UpdateInfo:
    """Metadata for an available update."""

    __slots__ = ("version", "download_url", "body", "asset_name", "asset_size")

    def __init__(
        self,
        version: str,
        download_url: str,
        body: str,
        asset_name: str,
        asset_size: int,
    ):
        self.version = version
        self.download_url = download_url
        self.body = body
        self.asset_name = asset_name
        self.asset_size = asset_size


class Updater:
    """Manages update lifecycle: check -> download -> apply."""

    def __init__(self, settings):
        self.settings = settings
        self._info: Optional[UpdateInfo] = None
        self._checking = False
        self._downloading = False
        self._just_updated = self._check_and_clear_flag()
        self._cleanup_runtime_leftovers()

        self.on_update_available: Optional[Callable] = None   # (version: str, body: str)
        self.on_download_progress: Optional[Callable] = None  # (percent: int)
        self.on_update_ready: Optional[Callable] = None       # (path: str)
        self.on_error: Optional[Callable] = None              # (error: str)



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



    def _should_check(self) -> bool:
        if self._just_updated:
            return False
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
        for part in clean.split("."):
            try:
                parts.append(int(part))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    def _update_dir(self) -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if not local_app_data:
            local_app_data = os.path.expanduser("~\\AppData\\Local")
        return Path(local_app_data) / "V-Link" / "updates"

    @staticmethod
    def _powershell_exe() -> str:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if candidate.exists():
            return str(candidate)
        return "powershell"

    @staticmethod
    def _sanitized_child_env() -> dict:
        """Drop inherited onefile internals before spawning detached child processes."""
        env = dict(os.environ)
        for key in list(env.keys()):
            upper = key.upper()
            if upper == "_MEIPASS2" or upper.startswith("_PYI_"):
                env.pop(key, None)
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        return env

    @staticmethod
    def _reset_windows_dll_directory():
        """
        PyInstaller onefile may call SetDllDirectory(_MEIPASS), inherited by children.
        Reset to default before launching updater process.
        """
        if os.name != "nt":
            return
        try:
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass

    async def check_for_update(self, force: bool = False) -> Optional[UpdateInfo]:
        """Check GitHub for a newer release. Returns UpdateInfo or None."""
        if self._checking:
            return self._info
        if not force and not self._should_check():
            return self._info

        self._checking = True
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout, headers=GITHUB_HEADERS) as session:
                async with session.get(GITHUB_API_LATEST) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()

            tag_name = str(data.get("tag_name", "") or "")
            if not tag_name:
                return None

            remote_ver = self._parse_version(tag_name)
            local_ver = self._parse_version(__version__)
            if remote_ver <= local_ver:
                self.settings.set("last_update_check", datetime.now().isoformat())
                return None

            skipped = str(self.settings.get("skipped_version", "") or "")
            if not force and skipped == tag_name:
                return None

            version_hint = tag_name.lstrip("v").strip().lower()
            candidates = []
            for asset in data.get("assets", []):
                name = str(asset.get("name", "") or "")
                name_l = name.lower()
                if not name_l.endswith(".exe"):
                    continue
                if "setup" in name_l:
                    continue

                score = 0
                if version_hint and version_hint in name_l:
                    score += 100
                if name_l.startswith("v-link"):
                    score += 10
                size = int(asset.get("size", 0) or 0)
                if size > 1_000_000:
                    score += 5
                candidates.append((score, asset))

            if not candidates:
                return None

            candidates.sort(key=lambda x: (-x[0], str(x[1].get("name", "")).lower()))
            selected = candidates[0][1]

            download_url = str(selected.get("browser_download_url", "") or "")
            asset_size = int(selected.get("size", 0) or 0)
            asset_name = str(selected.get("name", "") or "")
            if not download_url:
                return None

            self._info = UpdateInfo(
                version=tag_name,
                download_url=download_url,
                body=str(data.get("body", "") or ""),
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



    def _download_target_path(self) -> Path:
        """
        Prefer downloading directly next to currently running executable.
        If asset name equals current executable name, use updates dir as staging.
        """
        update_dir = self._update_dir()
        desired_name = os.path.basename(str(self._info.asset_name or "").strip()) or "latest.exe"
        if not desired_name.lower().endswith(".exe"):
            desired_name += ".exe"

        if not self.is_frozen():
            return update_dir / desired_name

        current_exe = Path(sys.executable).resolve()
        app_dir = current_exe.parent
        preferred = app_dir / desired_name
        try:
            if preferred.resolve().samefile(current_exe):
                return update_dir / f"next-{desired_name}"
        except Exception:
            if str(preferred).lower() == str(current_exe).lower():
                return update_dir / f"next-{desired_name}"
        return preferred

    async def download_update(self):
        """Download release asset."""
        if self._downloading:
            return None
        if not self._info:
            if self.on_error:
                self.on_error("No update metadata available")
            return None

        self._downloading = True
        target: Optional[Path] = None

        try:
            update_dir = self._update_dir()
            update_dir.mkdir(parents=True, exist_ok=True)
            target = self._download_target_path()
            target.parent.mkdir(parents=True, exist_ok=True)

            if target.exists():
                try:
                    target.unlink()
                except Exception:
                    pass

            timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_read=120)
            async with aiohttp.ClientSession(timeout=timeout, headers=GITHUB_HEADERS) as session:
                async with session.get(self._info.download_url) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP error {resp.status}")

                    total_size = int(resp.headers.get("Content-Length", 0) or 0)
                    downloaded = 0

                    with open(target, "wb") as f:
                        async for chunk in resp.content.iter_chunked(256 * 1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0 and self.on_download_progress:
                                pct = int(downloaded / total_size * 100)
                                self.on_download_progress(max(0, min(100, pct)))

            if not target.exists():
                raise RuntimeError("Downloaded file not found")

            actual_size = target.stat().st_size
            if self._info.asset_size and actual_size != self._info.asset_size:
                raise RuntimeError(
                    f"Size mismatch: expected {self._info.asset_size}, got {actual_size}"
                )
            if actual_size < 1_000_000:
                raise RuntimeError("Downloaded file too small (<1MB)")

            with open(target, "rb") as f:
                mz = f.read(2)
            if mz != b"MZ":
                raise RuntimeError("Downloaded file is not a valid EXE")

            try:
                quoted_target = str(target).replace("'", "''")
                subprocess.run(
                    [
                        self._powershell_exe(),
                        "-NoProfile",
                        "-Command",
                        f"Unblock-File -LiteralPath '{quoted_target}'",
                    ],
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                )
            except Exception:
                pass

            if self.on_update_ready:
                self.on_update_ready(str(target))
            return target

        except Exception as e:
            try:
                if target and target.exists():
                    target.unlink()
            except Exception:
                pass
            if self.on_error:
                self.on_error(str(e))
            return None
        finally:
            self._downloading = False



    def _check_and_clear_flag(self) -> bool:
        """Check if app has just updated and clear marker."""
        try:
            flag = self._update_dir() / "applied.flag"
            if flag.exists():
                flag.unlink()
                return True
        except Exception:
            pass
        return False

    def _cleanup_runtime_leftovers(self):
        """Best-effort cleanup for leftovers from previous updater runs."""
        try:
            update_dir = self._update_dir()
            if update_dir.exists():
                for p in update_dir.glob("ready-*.flag"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
                for p in update_dir.glob("next-*.exe"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
        except Exception:
            pass

        if not self.is_frozen():
            return
        try:
            current_exe = Path(sys.executable).resolve()
            for path in (
                current_exe.with_name(f"{current_exe.stem}.new{current_exe.suffix}"),
                current_exe.with_name(f"{current_exe.stem}.old{current_exe.suffix}"),
                current_exe.with_name(f"{current_exe.name}.old"),
            ):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    @staticmethod
    def _ps_quote(value: Path | str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def apply_update(self, downloaded_exe: Path) -> bool:
        """
        Launch detached updater script.
        Caller should close app right after this returns True.
        """
        if not self.is_frozen():
            return False

        try:
            if not downloaded_exe.exists():
                if self.on_error:
                    self.on_error("Update file not found")
                return False

            current_exe = Path(sys.executable).resolve()
            current_pid = os.getpid()
            update_dir = self._update_dir()
            update_dir.mkdir(parents=True, exist_ok=True)
            downloaded_exe = downloaded_exe.resolve()

            # If file is staged as "next-*.exe", replace current executable name in place.
            if (
                downloaded_exe.parent == update_dir
                and downloaded_exe.name.lower().startswith("next-")
            ):
                final_exe = current_exe
            else:
                final_exe = current_exe.parent / downloaded_exe.name

            script_path = update_dir / "_v-link-update.cmd"
            flag_file = update_dir / "applied.flag"
            log_file = update_dir / "update.log"

            script_template = """@echo off
setlocal enableextensions
set "PID=@@PID@@"
set "CURRENT=@@CURRENT_EXE@@"
set "DOWNLOADED=@@DOWNLOADED_EXE@@"
set "FINAL=@@FINAL_EXE@@"
set "FLAG=@@FLAG_FILE@@"
set "LOG=@@LOG_FILE@@"

set "PYINSTALLER_RESET_ENVIRONMENT=1"
set "_MEIPASS2="
set "_PYI_APPLICATION_HOME_DIR="
set "_PYI_ARCHIVE_FILE="
set "_PYI_PARENT_PROCESS_LEVEL="
set "_PYI_SPLASH_IPC="

call :log Updater started

for /L %%A in (1,1,25) do (
  tasklist /FI "PID eq %PID%" 2>NUL | find "%PID%" >NUL
  if errorlevel 1 goto wait_done
  timeout /t 1 /nobreak >NUL
)
taskkill /PID %PID% /F >NUL 2>&1
timeout /t 1 /nobreak >NUL

:wait_done
if not exist "%DOWNLOADED%" (
  call :log Downloaded file not found
  goto cleanup
)

if /I not "%DOWNLOADED%"=="%FINAL%" (
  copy /Y /B "%DOWNLOADED%" "%FINAL%" >NUL
  if errorlevel 1 (
    call :log Failed to copy update to final location
    goto cleanup
  )
)

start "" "%FINAL%" --show-after-update

echo 1>"%FLAG%"

if /I not "%FINAL%"=="%CURRENT%" (
  call :delete "%CURRENT%"
)
if /I not "%DOWNLOADED%"=="%FINAL%" (
  call :delete "%DOWNLOADED%"
)

call :log Updater finished successfully
goto cleanup

:delete
set "TARGET=%~1"
if "%TARGET%"=="" exit /b 0
for /L %%N in (1,1,20) do (
  if not exist "%TARGET%" exit /b 0
  del /F /Q "%TARGET%" >NUL 2>&1
  if not exist "%TARGET%" exit /b 0
  timeout /t 1 /nobreak >NUL
)
exit /b 0

:log
set "MSG=%*"
>>"%LOG%" echo [%date% %time%] %MSG%
exit /b 0

:cleanup
(goto) 2>NUL & del "%~f0"
endlocal
exit /b 0
"""

            script = (
                script_template
                .replace("@@PID@@", str(int(current_pid)))
                .replace("@@CURRENT_EXE@@", str(current_exe))
                .replace("@@DOWNLOADED_EXE@@", str(downloaded_exe))
                .replace("@@FINAL_EXE@@", str(final_exe))
                .replace("@@FLAG_FILE@@", str(flag_file))
                .replace("@@LOG_FILE@@", str(log_file))
            )
            script_path.write_text(script, encoding="cp866", errors="ignore")

            self._reset_windows_dll_directory()

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            subprocess.Popen(
                [
                    "cmd",
                    "/c",
                    str(script_path),
                ],
                env=self._sanitized_child_env(),
                startupinfo=startupinfo,
                creationflags=creationflags,
                close_fds=True,
            )
            return True

        except Exception as e:
            if self.on_error:
                self.on_error(str(e))
            return False



    def skip_version(self):
        """Mark the current available update as skipped."""
        if self._info:
            self.settings.set("skipped_version", self._info.version)
            self._info = None
