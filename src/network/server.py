"""
V-Link - HTTP Server
Async server for receiving files over local network.
"""

import os
import sys
import time
import base64
import json
import hashlib
import secrets
import string
import socket
import errno
import ipaddress
import subprocess
from pathlib import Path
from typing import Callable, Optional

import aiofiles
import lz4.frame
from aiohttp import web
from cryptography.fernet import Fernet

from core.i18n import i18n, t


CHUNK_SIZE = 1024 * 1024  # 1 MB
DEFAULT_PORT = 8765
PORT_RANGE = 10
MOBILE_TOKEN_ALPHABET = string.ascii_uppercase + string.digits
MOBILE_TOKEN_LEN = 6


class TransferServer:
    """HTTP server for receiving files with fallback port scan."""

    VPN_IFACE_MARKERS = (
        "vpn",
        "wireguard",
        "wintun",
        "openvpn",
        "tap-",
        "tun",
        "ppp",
        "hamachi",
        "zerotier",
        "tailscale",
        "nordlynx",
        "forti",
        "anyconnect",
        "windscribe",
    )
    VIRTUAL_IFACE_MARKERS = (
        "hyper-v",
        "vethernet",
        "wsl",
        "virtual",
        "vmware",
        "virtualbox",
        "docker",
        "bluetooth",
        "loopback",
        "npcap",
    )

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        download_dir: str = None,
        auth_token: str = "",
        chunk_size_bytes: int = CHUNK_SIZE,
        verify_checksum: bool = False,
        enable_encryption: bool = False,
    ):
        self.requested_port = port
        self.port = port
        self.download_dir = download_dir or str(Path.home() / "Downloads" / "V-Link")
        self.auth_token = (auth_token or "").strip()
        self.chunk_size_bytes = max(64 * 1024, int(chunk_size_bytes))
        self.verify_checksum = verify_checksum
        self.enable_encryption = enable_encryption
        self._cipher: Optional[Fernet] = None
        if self.enable_encryption and self.auth_token:
            key = hashlib.sha256(self.auth_token.encode("utf-8")).digest()
            self._cipher = Fernet(base64.urlsafe_b64encode(key))
        self.app = web.Application(client_max_size=0)  # No upload size limit
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.sites: list[web.TCPSite] = []
        self._running = False
        self.mobile_share_enabled = False
        self.mobile_token = ""
        self.mobile_token_expire_at = 0.0
        self._mobile_template_cache: Optional[str] = None
        self._logo_b64_cache: Optional[str] = None

        self.on_transfer_start: Optional[Callable] = None
        self.on_transfer_progress: Optional[Callable] = None
        self.on_transfer_complete: Optional[Callable] = None
        self.on_transfer_error: Optional[Callable] = None
        self.on_server_error: Optional[Callable] = None
        self.on_clipboard_update: Optional[Callable] = None

        self._setup_routes()

    def _load_logo_base64(self) -> str:
        """Загрузить PNG-логотип и вернуть Base64-строку (с кэшированием)."""
        if self._logo_b64_cache:
            return self._logo_b64_cache
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "resources" / "logo.png")
        candidates.append(Path(__file__).resolve().parent.parent.parent / "resources" / "logo.png")
        for path in candidates:
            try:
                if path.exists():
                    self._logo_b64_cache = base64.b64encode(path.read_bytes()).decode("ascii")
                    return self._logo_b64_cache
            except Exception:
                continue
        self._logo_b64_cache = ""
        return self._logo_b64_cache

    def _setup_routes(self):
        self.app.router.add_get('/', self._handle_mobile_index)
        self.app.router.add_post('/upload', self._handle_upload)
        self.app.router.add_post('/clipboard', self._handle_clipboard)
        self.app.router.add_get('/ping', self._handle_ping)
        self.app.router.add_get('/info', self._handle_info)
        self.app.router.add_get('/api/mobile/files', self._handle_mobile_files)
        self.app.router.add_post('/api/mobile/upload', self._handle_mobile_upload)
        self.app.router.add_get('/api/mobile/download/{filename:.+}', self._handle_mobile_download)

    @classmethod
    def _is_vpn_iface_name(cls, iface_name: str) -> bool:
        probe = str(iface_name or "").lower()
        return any(marker in probe for marker in cls.VPN_IFACE_MARKERS)

    @classmethod
    def _is_virtual_iface_name(cls, iface_name: str) -> bool:
        probe = str(iface_name or "").lower()
        return any(marker in probe for marker in cls.VIRTUAL_IFACE_MARKERS)

    @classmethod
    def _windows_interface_ip_pairs(cls, timeout_sec: float = 1.8) -> list[tuple[str, str]]:
        if os.name != "nt":
            return []

        pairs: list[tuple[str, str]] = []
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            proc = subprocess.run(
                ["ipconfig"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                timeout=timeout_sec,
                check=False,
            )
            current_iface = ""
            for raw in (proc.stdout or "").splitlines():
                line = raw.rstrip()
                if not line:
                    continue
                stripped = line.strip()
                if stripped.endswith(":") and "." not in stripped:
                    current_iface = stripped[:-1]
                    continue
                if "IPv4" not in line or ":" not in line:
                    continue
                candidate = line.split(":", 1)[1].strip()
                if candidate:
                    pairs.append((current_iface, candidate))
        except Exception:
            pass
        return pairs

    @staticmethod
    def _valid_bind_ip(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(str(ip or "").strip())
        except ValueError:
            return False
        if addr.version != 4 or addr.is_loopback or addr.is_link_local or addr.is_multicast:
            return False
        return True

    @classmethod
    def _physical_lan_ips(cls) -> list[str]:
        ranked: list[tuple[tuple[int, str], str]] = []
        seen: set[str] = set()
        for iface_name, ip in cls._windows_interface_ip_pairs():
            if ip in seen or not cls._valid_bind_ip(ip):
                continue
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if not addr.is_private:
                continue
            if cls._is_vpn_iface_name(iface_name) or cls._is_virtual_iface_name(iface_name):
                continue
            seen.add(ip)
            if ip.startswith("192.168.137."):
                rank = 0
            elif ip.startswith("192.168."):
                rank = 1
            elif ip.startswith("10."):
                rank = 2
            elif ip.startswith("172."):
                rank = 3
            else:
                rank = 4
            ranked.append(((rank, ip), ip))
        ranked.sort(key=lambda item: item[0])
        return [ip for _rank, ip in ranked]

    def enable_mobile_share(self, ttl_sec: int = 0) -> str:
        """Enable mobile web share and return session token."""
        self.mobile_share_enabled = True
        self.mobile_token = "".join(secrets.choice(MOBILE_TOKEN_ALPHABET) for _ in range(MOBILE_TOKEN_LEN))
        self.mobile_token_expire_at = (time.time() + int(ttl_sec)) if ttl_sec > 0 else 0.0
        return self.mobile_token

    def disable_mobile_share(self):
        self.mobile_share_enabled = False
        self.mobile_token = ""
        self.mobile_token_expire_at = 0.0

    def get_mobile_url(self, host_ip: str) -> str:
        ip = str(host_ip or "").strip() or "127.0.0.1"
        if not self.mobile_token:
            self.enable_mobile_share(ttl_sec=0)
        return f"http://{ip}:{self.port}/?token={self.mobile_token}"

    def _extract_mobile_token(self, request: web.Request) -> str:
        return str(
            request.query.get("token")
            or request.headers.get("X-Mobile-Token")
            or ""
        ).strip()

    def _mobile_token_valid(self, token: str) -> bool:
        if not self.mobile_share_enabled:
            return False
        if self.mobile_token_expire_at and time.time() > self.mobile_token_expire_at:
            self.disable_mobile_share()
            return False
        return bool(token) and token == self.mobile_token

    @staticmethod
    def _mobile_forbidden_json() -> web.Response:
        return web.json_response(
            {"status": "error", "message": "Mobile access is disabled or token is invalid"},
            status=403,
        )

    @staticmethod
    def _safe_relative_path(path: str) -> str:
        clean_parts = []
        for part in str(path or "").replace("\\", "/").split("/"):
            part = part.strip()
            if part and part not in {".", ".."} and not part.endswith(":"):
                clean_parts.append(part)
        if not clean_parts:
            return ""
        return os.path.join(*clean_parts)

    @staticmethod
    def _unique_path(path: str) -> str:
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        counter = 1
        while True:
            candidate = f"{base}_{counter}{ext}"
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def _get_forbidden_html(self) -> str:
        lang = "en" if i18n.language == "en" else "ru"
        return """<!DOCTYPE html>
<html lang="@@LANG@@">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#170F30">
    <title>@@TITLE@@</title>
    <style>
        body {
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #170F30 0%, #0B1020 100%);
            color: #f8fafc;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            box-sizing: border-box;
        }
        .card {
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            padding: 32px 24px;
            border-radius: 24px;
            text-align: center;
            max-width: 400px;
            width: 100%;
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.1);
        }
        .icon {
            width: 64px;
            height: 64px;
            background: rgba(239, 68, 68, 0.15);
            color: #ef4444;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 20px;
        }
        h2 { margin: 0 0 12px; font-size: 20px; font-weight: 700; }
        p { margin: 0 0 24px; color: #cbd5e1; line-height: 1.5; font-size: 15px; }
        .btn {
            display: block;
            width: 100%;
            padding: 14px;
            background: #8b5cf6;
            color: white;
            border: none;
            border-radius: 16px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: background 0.2s, transform 0.1s;
            box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
        }
        .btn:active { background: #7c3aed; transform: scale(0.98); }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon" style="background: transparent;">
            <img src="data:image/png;base64,{{LOGO_BASE64}}" style="width: 64px; height: 64px; object-fit: contain;">
        </div>
        <h2>@@DENIED@@</h2>
        <p>@@TEXT@@</p>
        <button class="btn" onclick="window.close()">@@CLOSE@@</button>
    </div>
</body>
</html>""".replace("@@LANG@@", lang).replace("@@TITLE@@", t("Доступ ограничен")).replace(
            "@@DENIED@@", t("Доступ закрыт")
        ).replace(
            "@@TEXT@@",
            t("Для передачи файлов откройте окно «Мобильник» в приложении V-Link на компьютере. Текущий токен устарел."),
        ).replace(
            "@@CLOSE@@", t("Закрыть окно")
        ).replace(
            "{{LOGO_BASE64}}", self._load_logo_base64()
        )

    def _mobile_i18n_map(self) -> dict:
        return {
            "online": t("Онлайн"),
            "uploadTitle": t("Отправить файлы"),
            "uploadDesc": t("Выберите файлы или папку для отправки"),
            "chooseFiles": t("Файлы"),
            "chooseFolder": t("Папка"),
            "filesOnPc": t("Файлы на ПК"),
            "loadingList": t("Загрузка списка..."),
            "emptyFolder": t("Папка загрузок пуста"),
            "uploadSuccess": t("Файлы успешно отправлены"),
            "uploadError": t("Ошибка загрузки"),
            "networkError": t("Ошибка сети"),
            "accessErrorTitle": t("Ошибка доступа"),
            "accessErrorText": t("Отсканируйте QR-код заново в приложении V-Link."),
            "uploading": t("Передача..."),
            "uploadComplete": t("Готово"),
            "selectedFiles": t("Выбрано файлов: {count}"),
            "selectedFolder": t("Папка: {name}"),
            "uploadBytes": t("{sent} из {total}"),
        }

    def _load_mobile_html(self) -> str:
        if self._mobile_template_cache:
            return self._mobile_template_cache

        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "ui" / "web_interface.html")
        candidates.append(Path(__file__).resolve().parent.parent / "ui" / "web_interface.html")

        for path in candidates:
            try:
                if path.exists():
                    raw = path.read_text(encoding="utf-8")
                    rendered = raw.replace("{{LOGO_BASE64}}", self._load_logo_base64())
                    rendered = rendered.replace("{{HTML_LANG}}", "en" if i18n.language == "en" else "ru")
                    rendered = rendered.replace(
                        "{{I18N_JSON}}",
                        json.dumps(self._mobile_i18n_map(), ensure_ascii=False),
                    )
                    self._mobile_template_cache = rendered
                    return self._mobile_template_cache
            except Exception:
                continue

        self._mobile_template_cache = (
            "<!doctype html><html><body>"
            "<h3>V-Link Mobile</h3><p>Web interface file not found.</p>"
            "</body></html>"
        )
        return self._mobile_template_cache

    async def _handle_mobile_index(self, request: web.Request) -> web.Response:
        token = self._extract_mobile_token(request)
        if not self._mobile_token_valid(token):
            return web.Response(
                text=self._get_forbidden_html(),
                content_type="text/html",
                status=403,
            )
        html = self._load_mobile_html()
        return web.Response(text=html, content_type="text/html")

    async def _handle_mobile_files(self, request: web.Request) -> web.Response:
        token = self._extract_mobile_token(request)
        if not self._mobile_token_valid(token):
            return self._mobile_forbidden_json()

        os.makedirs(self.download_dir, exist_ok=True)
        items = []
        root = Path(self.download_dir)
        for entry in root.rglob("*"):
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
                rel_name = entry.relative_to(root).as_posix()
                items.append(
                    {
                        "name": rel_name,
                        "size": int(stat.st_size),
                        "mtime": int(stat.st_mtime),
                    }
                )
            except OSError:
                continue
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return web.json_response({"status": "ok", "files": items[:300]})

    async def _handle_mobile_upload(self, request: web.Request) -> web.Response:
        token = self._extract_mobile_token(request)
        if not self._mobile_token_valid(token):
            return self._mobile_forbidden_json()

        os.makedirs(self.download_dir, exist_ok=True)
        transfer_id = f"mobile-{int(time.time() * 1000)}"
        saved = []

        try:
            import urllib.parse
            try:
                expected_total = int(request.headers.get("X-Upload-Total-Size", "0") or "0")
            except ValueError:
                expected_total = 0
            upload_name = self._safe_relative_path(
                urllib.parse.unquote(request.headers.get("X-Upload-Name", ""))
            )
            display_name = upload_name or t("Мобильная передача")
            if self.on_transfer_start:
                self.on_transfer_start(transfer_id, display_name, expected_total, False)

            reader = await request.multipart()
            received_total = 0
            started = time.time()
            last_update = started
            completed_path = ""

            while True:
                field = await reader.next()
                if field is None:
                    break
                if not getattr(field, "filename", None):
                    continue

                try:
                    raw_name = urllib.parse.unquote(field.filename)
                except Exception:
                    raw_name = field.filename

                name = self._safe_relative_path(raw_name)
                if not name:
                    continue

                filepath = self._unique_path(os.path.join(self.download_dir, name))
                os.makedirs(os.path.dirname(filepath), exist_ok=True)

                received = 0

                async with aiofiles.open(filepath, "wb") as f:
                    while True:
                        chunk = await field.read_chunk(self.chunk_size_bytes)
                        if not chunk:
                            break
                        await f.write(chunk)
                        received += len(chunk)
                        received_total += len(chunk)
                        now = time.time()
                        if now - last_update > 0.2 and self.on_transfer_progress:
                            elapsed = max(0.001, now - started)
                            self.on_transfer_progress(transfer_id, received_total, received_total / elapsed)
                            last_update = now

                if not completed_path:
                    if os.path.sep in name:
                        completed_path = os.path.join(self.download_dir, name.split(os.path.sep, 1)[0])
                    else:
                        completed_path = filepath
                saved.append(
                    {
                        "name": os.path.relpath(filepath, self.download_dir).replace("\\", "/"),
                        "size": received,
                    }
                )

            if not saved:
                if self.on_transfer_error:
                    self.on_transfer_error(transfer_id, "No files provided")
                return web.json_response({"status": "error", "message": "No files provided"}, status=400)

            if self.on_transfer_progress:
                elapsed = max(0.001, time.time() - started)
                self.on_transfer_progress(transfer_id, received_total, received_total / elapsed)
            if self.on_transfer_complete:
                if len(saved) > 1 and not completed_path:
                    completed_path = self.download_dir
                self.on_transfer_complete(transfer_id, completed_path or self.download_dir)
            return web.json_response({"status": "ok", "files": saved})

        except Exception as e:
            if self.on_transfer_error:
                self.on_transfer_error(transfer_id, f"Mobile upload error: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_mobile_download(self, request: web.Request) -> web.StreamResponse:
        token = self._extract_mobile_token(request)
        if not self._mobile_token_valid(token):
            return self._mobile_forbidden_json()

        import urllib.parse
        try:
            raw_name = urllib.parse.unquote(request.match_info.get("filename", ""))
        except Exception:
            raw_name = request.match_info.get("filename", "")

        name = self._safe_relative_path(raw_name)
        if not name:
            return web.json_response({"status": "error", "message": "Invalid filename"}, status=400)

        path = Path(self.download_dir) / name
        if not path.exists() or not path.is_file():
            return web.json_response({"status": "error", "message": "File not found"}, status=404)

        response = web.FileResponse(path)
        safe_download_name = (os.path.basename(name) or "download").replace('"', "'")
        quoted_name = urllib.parse.quote(safe_download_name)
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{safe_download_name}"; filename*=UTF-8\'\'{quoted_name}'
        )
        return response

    async def _handle_clipboard(self, request: web.Request) -> web.Response:
        try:
            if self.auth_token:
                provided_token = request.headers.get('X-Auth-Token', '')
                expected_token = hashlib.sha256(self.auth_token.encode("utf-8")).hexdigest()
                if provided_token != expected_token:
                    return web.json_response({'status': 'error', 'message': 'Unauthorized'}, status=401)

            payload = await request.json()
            if not isinstance(payload, dict):
                return web.json_response({'status': 'error', 'message': 'Invalid payload'}, status=400)

            payload_type = str(payload.get("type", "")).lower()
            if payload_type not in ("text", "image"):
                return web.json_response({'status': 'error', 'message': 'Unsupported clipboard type'}, status=400)

            content = payload.get("content", "")
            if payload_type == "text":
                if not isinstance(content, str):
                    return web.json_response({'status': 'error', 'message': 'Text content must be string'}, status=400)
                if len(content) > 200_000:
                    return web.json_response({'status': 'error', 'message': 'Text payload too large'}, status=413)
            else:
                if not isinstance(content, str):
                    return web.json_response({'status': 'error', 'message': 'Image content must be base64 string'}, status=400)
                if len(content) > 14_000_000:
                    return web.json_response({'status': 'error', 'message': 'Image payload too large'}, status=413)

            if self.on_clipboard_update:
                self.on_clipboard_update(payload)
            return web.json_response({'status': 'ok'})
        except Exception as e:
            return web.json_response({'status': 'error', 'message': str(e)}, status=500)

    async def _handle_ping(self, request: web.Request) -> web.Response:
        return web.json_response({'status': 'ok', 'port': self.port})

    async def _handle_info(self, request: web.Request) -> web.Response:
        import socket
        from version import __version__
        return web.json_response({
            'name': socket.gethostname(),
            'version': __version__,
            'ready': True,
            'port': self.port,
        })

    async def _handle_upload(self, request: web.Request) -> web.Response:
        transfer_id = request.headers.get('X-Transfer-ID', str(time.time()))
        filepath = None

        try:
            if self.auth_token:
                provided_token = request.headers.get('X-Auth-Token', '')
                expected_token = hashlib.sha256(self.auth_token.encode("utf-8")).hexdigest()
                if provided_token != expected_token:
                    return web.json_response({'status': 'error', 'message': 'Unauthorized'}, status=401)

            import urllib.parse
            filename_raw = request.headers.get('X-Filename', 'unknown')
            rel_path_raw = request.headers.get('X-Relative-Path', '')
            try:
                total_size = int(request.headers.get('X-Filesize', 0) or 0)
            except ValueError:
                total_size = 0
            content_encoding = request.headers.get('X-Content-Encoding', '').lower()
            expected_sha256 = request.headers.get('X-File-SHA256', '').lower()
            encrypted_mode = request.headers.get('X-Encrypted', '').lower() == 'fernet-frame'
            
            try:
                filename = urllib.parse.unquote(filename_raw)
            except Exception:
                filename = filename_raw

            try:
                rel_path = urllib.parse.unquote(rel_path_raw)
            except Exception:
                rel_path = ""
                
            try:
                filename = filename.encode('latin-1').decode('utf-8')
            except Exception:
                pass
            try:
                rel_path = rel_path.encode('latin-1').decode('utf-8')
            except Exception:
                pass

            display_name = rel_path if rel_path else filename
            safe_rel_path = self._safe_relative_path(display_name)
            if not safe_rel_path:
                raise ValueError('Invalid filename')

            filepath = self._unique_path(os.path.join(self.download_dir, safe_rel_path))
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            if self.on_transfer_start:
                self.on_transfer_start(transfer_id, display_name, total_size, False)

            received = 0
            start_time = time.time()
            last_update = start_time
            hasher = None
            if self.verify_checksum and expected_sha256:
                hasher = hashlib.sha256()

            decompressor = None
            if content_encoding == 'lz4-stream':
                decompressor = lz4.frame.LZ4FrameDecompressor()

            async with aiofiles.open(filepath, 'wb') as f:
                if encrypted_mode:
                    if not self._cipher:
                        raise ValueError("Encrypted mode is not enabled on receiver")
                    buffer = b""
                    async for raw_chunk in request.content.iter_chunked(self.chunk_size_bytes):
                        buffer += raw_chunk
                        while len(buffer) >= 4:
                            frame_len = int.from_bytes(buffer[:4], "big")
                            if frame_len <= 0 or frame_len > 32 * 1024 * 1024:
                                raise ValueError("Invalid encrypted frame")
                            if len(buffer) < 4 + frame_len:
                                break
                            token = buffer[4:4 + frame_len]
                            buffer = buffer[4 + frame_len:]
                            decoded = self._cipher.decrypt(token)
                            chunk = decoded
                            if decompressor:
                                chunk = decompressor.decompress(decoded)
                                if not chunk:
                                    continue
                            await f.write(chunk)
                            received += len(chunk)
                            if hasher:
                                hasher.update(chunk)

                            now = time.time()
                            if now - last_update > 0.15:
                                elapsed = now - start_time
                                speed = received / elapsed if elapsed > 0 else 0
                                if self.on_transfer_progress:
                                    self.on_transfer_progress(transfer_id, received, speed)
                                last_update = now
                    if buffer:
                        raise ValueError("Truncated encrypted payload")
                else:
                    async for raw_chunk in request.content.iter_chunked(self.chunk_size_bytes):
                        chunk = raw_chunk
                        if decompressor:
                            chunk = decompressor.decompress(raw_chunk)
                            if not chunk:
                                continue

                        await f.write(chunk)
                        received += len(chunk)
                        if hasher:
                            hasher.update(chunk)

                        now = time.time()
                        if now - last_update > 0.15:
                            elapsed = now - start_time
                            speed = received / elapsed if elapsed > 0 else 0
                            if self.on_transfer_progress:
                                self.on_transfer_progress(transfer_id, received, speed)
                            last_update = now

            if self.on_transfer_progress:
                elapsed = max(0.001, time.time() - start_time)
                self.on_transfer_progress(transfer_id, received, received / elapsed)

            if total_size > 0 and received != total_size:
                try:
                    os.remove(filepath)
                except OSError:
                    pass
                raise ValueError(f'Invalid upload size: expected {total_size}, got {received}')

            if hasher and hasher.hexdigest().lower() != expected_sha256:
                try:
                    os.remove(filepath)
                except OSError:
                    pass
                raise ValueError('Checksum verification failed')

            if self.on_transfer_complete:
                self.on_transfer_complete(transfer_id, filepath)

            return web.json_response({'status': 'success', 'filename': os.path.basename(filepath), 'size': received})

        except Exception as e:
            if filepath and os.path.exists(filepath):
                # Remove partial file if transfer failed.
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            if self.on_transfer_error:
                self.on_transfer_error(transfer_id, str(e))
            return web.json_response({'status': 'error', 'message': str(e)}, status=500)

    async def start(self) -> int:
        if self._running:
            return self.port

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        def candidate_hosts(lan_only: bool = True) -> list[str]:
            hosts = []

            def add_host(ip: str):
                ip = str(ip or "").strip()
                if not ip or ip in hosts:
                    return
                if not self._valid_bind_ip(ip):
                    return
                hosts.append(ip)

            for ip in self._physical_lan_ips():
                add_host(ip)

            if lan_only:
                return hosts

            def host_rank(ip: str) -> tuple[int, str]:
                if ip.startswith("192.168.137."):
                    return (1, ip)
                if ip.startswith("192.168."):
                    return (2, ip)
                if ip.startswith("10."):
                    return (3, ip)
                if ip.startswith("172."):
                    return (4, ip)
                return (5, ip)

            try:
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    probe.connect(("8.8.8.8", 80))
                    add_host(probe.getsockname()[0])
                finally:
                    probe.close()
            except Exception:
                pass

            try:
                _, _, host_ips = socket.gethostbyname_ex(socket.gethostname())
                for ip in host_ips:
                    add_host(ip)
            except Exception:
                pass
            primary = hosts[:1]
            rest = sorted(hosts[1:], key=host_rank)
            result = primary + rest
            if "0.0.0.0" not in result:
                result.append("0.0.0.0")
            return result

        async def start_on_port(try_port: int, hosts: list[str]) -> bool:
            last_bind_error: Optional[OSError] = None
            started_sites: list[web.TCPSite] = []
            for host in hosts:
                try:
                    site = web.TCPSite(self.runner, host, try_port)
                    await site.start()
                    started_sites.append(site)
                    bound_port = try_port
                    if try_port == 0:
                        server_obj = getattr(site, "_server", None)
                        sockets = getattr(server_obj, "sockets", None) or []
                        if sockets:
                            bound_port = int(sockets[0].getsockname()[1])
                    self.port = int(bound_port)
                    if try_port == 0:
                        break
                except OSError as e:
                    last_bind_error = e
                    continue

            if started_sites:
                self.sites.extend(started_sites)
                self.site = started_sites[0]
                self._running = True
                return True

            if last_bind_error:
                text = str(last_bind_error).lower()
                winerror = int(getattr(last_bind_error, "winerror", 0) or 0)
                err_no = int(getattr(last_bind_error, "errno", 0) or 0)
                if self.on_server_error and (
                    winerror in (10013, 10048)
                    or err_no in (10013, 10048, errno.EADDRINUSE, errno.EACCES, errno.EPERM)
                    or "forbidden by its access permissions" in text
                    or "address already in use" in text
                ):
                    self.on_server_error(
                        t(
                            "Порт {port} недоступен: {error}. Поиск следующего порта...",
                            port=try_port,
                            error=last_bind_error,
                        )
                    )
            return False

        try:
            if self.requested_port == 0:
                if await start_on_port(0, ["127.0.0.1"]):
                    return self.port

            tried_ports = set()
            for port_offset in range(PORT_RANGE):
                try_port = self.requested_port + port_offset
                tried_ports.add(int(try_port))
                hosts = candidate_hosts(lan_only=(try_port != 0))
                if hosts and await start_on_port(try_port, hosts):
                    return self.port

            # Stable fallback range to avoid random port jumps across restarts.
            for try_port in range(17864, 17896):
                if try_port in tried_ports:
                    continue
                tried_ports.add(try_port)
                hosts = candidate_hosts(lan_only=True)
                if hosts and await start_on_port(try_port, hosts):
                    return self.port

            # Broad fallback: useful when interface detection fails.
            for port_offset in range(PORT_RANGE):
                try_port = self.requested_port + port_offset
                if await start_on_port(try_port, candidate_hosts(lan_only=False)):
                    return self.port

            # Last resort: ask OS for any free port instead of failing startup.
            if await start_on_port(0, ["127.0.0.1", "0.0.0.0"]):
                return self.port
        except Exception:
            try:
                if self.runner:
                    await self.runner.cleanup()
            except Exception:
                pass
            self.runner = None
            self.site = None
            self._running = False
            raise

        error_msg = (
            f'Failed to start server: all ports '
            f'{self.requested_port}-{self.requested_port + PORT_RANGE - 1} are busy'
        )
        if self.on_server_error:
            self.on_server_error(error_msg)
        try:
            if self.runner:
                await self.runner.cleanup()
        except Exception:
            pass
        self.runner = None
        self.site = None
        self._running = False
        raise OSError(error_msg)

    async def stop(self):
        self._running = False
        self.disable_mobile_share()
        try:
            for site in list(self.sites or ([] if not self.site else [self.site])):
                try:
                    await site.stop()
                except Exception:
                    pass
            self.sites = []
            self.site = None
            if self.runner:
                await self.runner.cleanup()
                self.runner = None
        except Exception as e:
            if self.on_server_error:
                self.on_server_error(f'Server stop error: {e}')

    def is_running(self) -> bool:
        return self._running
