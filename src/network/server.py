"""
V-Link - HTTP Server
Async server for receiving files over local network.
"""

import os
import time
import hashlib
import socket
import errno
from pathlib import Path
from typing import Callable, Optional

import aiofiles
import lz4.frame
from aiohttp import web
from cryptography.fernet import Fernet


CHUNK_SIZE = 1024 * 1024  # 1 MB
DEFAULT_PORT = 8765
PORT_RANGE = 10


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

        self.on_transfer_start: Optional[Callable] = None
        self.on_transfer_progress: Optional[Callable] = None
        self.on_transfer_complete: Optional[Callable] = None
        self.on_transfer_error: Optional[Callable] = None
        self.on_server_error: Optional[Callable] = None

        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_post('/upload', self._handle_upload)
        self.app.router.add_get('/ping', self._handle_ping)
        self.app.router.add_get('/info', self._handle_info)

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

        async def start_on_port(try_port: int) -> bool:
            try:
                self.site = web.TCPSite(self.runner, '0.0.0.0', try_port)
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
                is_addr_in_use = (
                    'address already in use' in str(e).lower()
                    or e.errno in (10048, errno.EADDRINUSE)
                )
                if is_addr_in_use:
                    self.site = None
                    return False
                raise

        try:
            for port_offset in range(PORT_RANGE):
                try_port = self.requested_port + port_offset
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
