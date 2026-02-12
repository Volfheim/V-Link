"""
V-Link - HTTP Server
Async server for receiving files over local network.
"""

import os
import sys
import time
import hashlib
import secrets
import string
import socket
import errno
import ipaddress
from pathlib import Path
from typing import Callable, Optional

import aiofiles
import lz4.frame
from aiohttp import web
from cryptography.fernet import Fernet


CHUNK_SIZE = 1024 * 1024  # 1 MB
DEFAULT_PORT = 8765
PORT_RANGE = 10
MOBILE_TOKEN_ALPHABET = string.ascii_uppercase + string.digits
MOBILE_TOKEN_LEN = 6


class TransferServer:
    """HTTP server for receiving files with fallback port scan."""

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
            import base64
            self._cipher = Fernet(base64.urlsafe_b64encode(key))
        self.app = web.Application(client_max_size=0)  # No upload size limit
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._running = False
        self.mobile_share_enabled = False
        self.mobile_token = ""
        self.mobile_token_expire_at = 0.0
        self._mobile_template_cache: Optional[str] = None

        self.on_transfer_start: Optional[Callable] = None
        self.on_transfer_progress: Optional[Callable] = None
        self.on_transfer_complete: Optional[Callable] = None
        self.on_transfer_error: Optional[Callable] = None
        self.on_server_error: Optional[Callable] = None
        self.on_clipboard_update: Optional[Callable] = None

        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get('/', self._handle_mobile_index)
        self.app.router.add_post('/upload', self._handle_upload)
        self.app.router.add_post('/clipboard', self._handle_clipboard)
        self.app.router.add_get('/ping', self._handle_ping)
        self.app.router.add_get('/info', self._handle_info)
        self.app.router.add_get('/api/mobile/files', self._handle_mobile_files)
        self.app.router.add_post('/api/mobile/upload', self._handle_mobile_upload)
        self.app.router.add_get('/api/mobile/download/{filename}', self._handle_mobile_download)

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
    def _safe_filename(filename: str) -> str:
        base = os.path.basename(str(filename or "").strip())
        if not base or base in (".", ".."):
            return ""
        return base

    def _get_forbidden_html(self) -> str:
        return """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0f172a">
    <title>Доступ ограничен</title>
    <style>
        body {
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #0f172a;
            color: #f8fafc;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            box-sizing: border-box;
        }
        .card {
            background: #1e293b;
            padding: 32px 24px;
            border-radius: 24px;
            text-align: center;
            max-width: 400px;
            width: 100%;
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
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
        p { margin: 0 0 24px; color: #94a3b8; line-height: 1.5; font-size: 15px; }
        .btn {
            display: block;
            width: 100%;
            padding: 12px;
            background: #334155;
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: background 0.2s;
        }
        .btn:active { background: #475569; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
            </svg>
        </div>
        <h2>Доступ закрыт</h2>
        <p>Для передачи файлов откройте окно <b>«Мобильник»</b> в приложении V-Link на компьютере.</p>
        <button class="btn" onclick="location.reload()">Попробовать снова</button>
    </div>
</body>
</html>"""

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
                    self._mobile_template_cache = path.read_text(encoding="utf-8")
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
        for entry in Path(self.download_dir).iterdir():
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
                items.append(
                    {
                        "name": entry.name,
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
            reader = await request.multipart()
            while True:
                field = await reader.next()
                if field is None:
                    break
                if not getattr(field, "filename", None):
                    continue

                name = self._safe_filename(field.filename)
                if not name:
                    continue

                filepath = os.path.join(self.download_dir, name)
                base, ext = os.path.splitext(filepath)
                counter = 1
                while os.path.exists(filepath):
                    filepath = f"{base}_{counter}{ext}"
                    counter += 1

                if self.on_transfer_start:
                    self.on_transfer_start(transfer_id, os.path.basename(filepath), 0, False)

                received = 0
                started = time.time()
                last_update = started

                async with aiofiles.open(filepath, "wb") as f:
                    while True:
                        chunk = await field.read_chunk(self.chunk_size_bytes)
                        if not chunk:
                            break
                        await f.write(chunk)
                        received += len(chunk)
                        now = time.time()
                        if now - last_update > 0.2 and self.on_transfer_progress:
                            elapsed = now - started
                            speed = received / elapsed if elapsed > 0 else 0
                            self.on_transfer_progress(transfer_id, received, speed)
                            last_update = now

                if self.on_transfer_complete:
                    self.on_transfer_complete(transfer_id, filepath)
                saved.append(
                    {
                        "name": os.path.basename(filepath),
                        "size": received,
                    }
                )

            if not saved:
                return web.json_response({"status": "error", "message": "No files provided"}, status=400)
            return web.json_response({"status": "ok", "files": saved})

        except Exception as e:
            if self.on_transfer_error:
                self.on_transfer_error(transfer_id, f"Mobile upload error: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_mobile_download(self, request: web.Request) -> web.StreamResponse:
        token = self._extract_mobile_token(request)
        if not self._mobile_token_valid(token):
            return self._mobile_forbidden_json()

        name = self._safe_filename(request.match_info.get("filename", ""))
        if not name:
            return web.json_response({"status": "error", "message": "Invalid filename"}, status=400)

        path = Path(self.download_dir) / name
        if not path.exists() or not path.is_file():
            return web.json_response({"status": "error", "message": "File not found"}, status=404)

        response = web.FileResponse(path)
        response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
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

            filename = request.headers.get('X-Filename', 'unknown')
            total_size = int(request.headers.get('X-Filesize', 0))
            content_encoding = request.headers.get('X-Content-Encoding', '').lower()
            expected_sha256 = request.headers.get('X-File-SHA256', '').lower()
            encrypted_mode = request.headers.get('X-Encrypted', '').lower() == 'fernet-frame'

            try:
                filename = filename.encode('latin-1').decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass

            filename = os.path.basename(filename.strip())
            if not filename or filename in ('.', '..'):
                raise ValueError('Invalid filename')

            os.makedirs(self.download_dir, exist_ok=True)
            filepath = os.path.join(self.download_dir, filename)

            base, ext = os.path.splitext(filepath)
            counter = 1
            while os.path.exists(filepath):
                filepath = f"{base}_{counter}{ext}"
                counter += 1

            if self.on_transfer_start:
                self.on_transfer_start(transfer_id, filename, total_size, False)

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

        def candidate_hosts() -> list[str]:
            hosts = ["0.0.0.0"]

            def add_host(ip: str):
                ip = str(ip or "").strip()
                if not ip or ip in hosts:
                    return
                try:
                    addr = ipaddress.ip_address(ip)
                    if addr.version != 4 or addr.is_loopback or addr.is_link_local or addr.is_multicast:
                        return
                except ValueError:
                    return
                hosts.append(ip)

            def host_rank(ip: str) -> tuple[int, str]:
                if ip == "0.0.0.0":
                    return (0, ip)
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
            return primary + rest

        async def start_on_port(try_port: int) -> bool:
            last_bind_error: Optional[OSError] = None
            for host in candidate_hosts():
                try:
                    self.site = web.TCPSite(self.runner, host, try_port)
                    await self.site.start()
                    bound_port = try_port
                    if try_port == 0:
                        server_obj = getattr(self.site, "_server", None)
                        sockets = getattr(server_obj, "sockets", None) or []
                        if sockets:
                            bound_port = int(sockets[0].getsockname()[1])
                    self.port = int(bound_port)
                    self._running = True
                    return True
                except OSError as e:
                    last_bind_error = e
                    self.site = None
                    continue

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
                        f"Порт {try_port} недоступен: {last_bind_error}. Поиск следующего порта..."
                    )
            return False

        try:
            tried_ports = set()
            for port_offset in range(PORT_RANGE):
                try_port = self.requested_port + port_offset
                tried_ports.add(int(try_port))
                if await start_on_port(try_port):
                    return self.port

            # Stable fallback range to avoid random port jumps across restarts.
            for try_port in range(17864, 17896):
                if try_port in tried_ports:
                    continue
                tried_ports.add(try_port)
                if await start_on_port(try_port):
                    return self.port

            # Last resort: ask OS for any free port instead of failing startup.
            if await start_on_port(0):
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
            if self.site:
                await self.site.stop()
                self.site = None
            if self.runner:
                await self.runner.cleanup()
                self.runner = None
        except Exception as e:
            if self.on_server_error:
                self.on_server_error(f'Server stop error: {e}')

    def is_running(self) -> bool:
        return self._running
