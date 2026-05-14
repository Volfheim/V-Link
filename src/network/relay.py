"""
V-Link - Relay Client
Optional relay transport for restrictive networks (guest/campus/AP isolation).
"""

import asyncio
import base64
import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin

import aiofiles
import aiohttp
from cryptography.fernet import Fernet


UPLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


class RelayClient:
    """Background relay service with peer sync + inbox polling."""

    def __init__(
        self,
        server_url: str,
        channel: str,
        client_id: str,
        display_name: str,
        download_dir: str,
        secure_mode: bool = False,
        auth_token: str = "",
    ):
        self.server_url = (server_url or "").strip().rstrip("/")
        self.channel = (channel or "").strip() or "default"
        self.client_id = (client_id or "").strip()
        self.display_name = (display_name or "").strip() or self.client_id or "V-Link"
        self.download_dir = download_dir or str(Path.home() / "Downloads" / "V-Link")
        self.secure_mode = bool(secure_mode)
        self.auth_token = (auth_token or "").strip()

        self._cipher: Optional[Fernet] = None
        if self.secure_mode and self.auth_token:
            key = hashlib.sha256(self.auth_token.encode("utf-8")).digest()
            self._cipher = Fernet(base64.urlsafe_b64encode(key))

        self._session_lock = asyncio.Lock()
        self.session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._low_power_mode = False
        self._presence_task: Optional[asyncio.Task] = None
        self._inbox_task: Optional[asyncio.Task] = None
        self._processing: set[str] = set()

        self._presence_interval_active = 7.0
        self._presence_interval_low = 20.0
        self._poll_interval_active = 2.0
        self._poll_interval_low = 5.0

        self._peers: Dict[str, Dict] = {}

        self.on_peer_added: Optional[Callable] = None
        self.on_peer_removed: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

        self.on_transfer_start: Optional[Callable] = None
        self.on_transfer_progress: Optional[Callable] = None
        self.on_transfer_complete: Optional[Callable] = None
        self.on_transfer_error: Optional[Callable] = None

    def is_enabled(self) -> bool:
        return bool(self.server_url and self.client_id)

    def set_low_power_mode(self, enabled: bool):
        self._low_power_mode = bool(enabled)

    def get_peers(self) -> Dict[str, Dict]:
        return {k: dict(v) for k, v in self._peers.items()}

    def has_peer(self, peer_id: str) -> bool:
        return peer_id in self._peers

    def find_peer_by_name(self, name: str) -> Optional[str]:
        target = (name or "").strip().lower()
        if not target:
            return None

        target_variants = {
            target,
            target.replace(" (relay)", ""),
            target.replace("[relay] ", ""),
        }
        for peer_id, peer in self._peers.items():
            peer_name = str(peer.get("name", "")).strip().lower()
            peer_variants = {
                peer_name,
                peer_name.replace(" (relay)", ""),
                peer_name.replace("[relay] ", ""),
            }
            if target_variants & peer_variants:
                return peer_id
        return None

    async def start(self):
        if self._running:
            return
        if not self.is_enabled():
            raise ValueError("Relay is not configured")

        self._running = True
        await self._ensure_session()
        self._presence_task = asyncio.create_task(self._presence_loop())
        self._inbox_task = asyncio.create_task(self._inbox_loop())
        # Non-blocking warm-up: do not delay app startup on relay handshake.
        asyncio.create_task(self._initial_sync())

    async def _initial_sync(self):
        if not self._running:
            return
        try:
            await self._sync_presence()
        except Exception as e:
            if self.on_error:
                self.on_error(f"Relay startup sync error: {e}")

    async def stop(self):
        self._running = False

        tasks = [self._presence_task, self._inbox_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass

        self._presence_task = None
        self._inbox_task = None

        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

        stale = list(self._peers.keys())
        for peer_id in stale:
            peer = self._peers.pop(peer_id, None)
            if peer and self.on_peer_removed:
                self.on_peer_removed(peer)

    async def refresh_peers(self):
        if not self._running:
            return
        await self._sync_presence()

    async def _ensure_session(self):
        async with self._session_lock:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(total=None, connect=12, sock_read=None)
                connector = aiohttp.TCPConnector(limit=8, enable_cleanup_closed=True)
                self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)

    def _presence_interval(self) -> float:
        return self._presence_interval_low if self._low_power_mode else self._presence_interval_active

    def _poll_interval(self) -> float:
        return self._poll_interval_low if self._low_power_mode else self._poll_interval_active

    def _endpoint(self, path: str) -> str:
        return urljoin(self.server_url + "/", path.lstrip("/"))

    async def _presence_loop(self):
        while self._running:
            try:
                await self._sync_presence()
            except Exception as e:
                if self.on_error:
                    self.on_error(f"Relay presence error: {e}")
            await asyncio.sleep(self._presence_interval())

    async def _inbox_loop(self):
        while self._running:
            try:
                messages = await self._fetch_inbox()
                for msg in messages:
                    msg_id = str(msg.get("id", "")).strip()
                    if not msg_id or msg_id in self._processing:
                        continue
                    self._processing.add(msg_id)
                    try:
                        await self._receive_message(msg)
                    finally:
                        self._processing.discard(msg_id)
            except Exception as e:
                if self.on_error:
                    self.on_error(f"Relay inbox error: {e}")
            await asyncio.sleep(self._poll_interval())

    async def _sync_presence(self):
        await self._ensure_session()
        payload = {
            "channel": self.channel,
            "client_id": self.client_id,
            "name": self.display_name,
            "secure_mode": self.secure_mode,
        }
        timeout = aiohttp.ClientTimeout(total=10, connect=6, sock_read=8)
        async with self.session.post(self._endpoint("/api/v1/presence"), json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"{resp.status}: {text}")
            data = await resp.json()

        peers = data.get("peers", [])
        if not isinstance(peers, list):
            peers = []

        fresh: Dict[str, Dict] = {}
        for item in peers:
            if not isinstance(item, dict):
                continue
            peer_id = str(item.get("id", "")).strip()
            if not peer_id or peer_id == self.client_id:
                continue
            peer_name = str(item.get("name", "")).strip() or peer_id
            fresh[peer_id] = {
                "id": peer_id,
                "name": peer_name,
                "secure_mode": bool(item.get("secure_mode", False)),
                "last_seen": float(item.get("last_seen", 0.0) or 0.0),
            }

        previous_ids = set(self._peers.keys())
        fresh_ids = set(fresh.keys())

        for peer_id in sorted(previous_ids - fresh_ids):
            peer = self._peers.pop(peer_id, None)
            if peer and self.on_peer_removed:
                self.on_peer_removed(peer)

        for peer_id in sorted(fresh_ids):
            new_peer = fresh[peer_id]
            old_peer = self._peers.get(peer_id)
            self._peers[peer_id] = new_peer
            if old_peer != new_peer and self.on_peer_added:
                self.on_peer_added(new_peer)

    async def _fetch_inbox(self) -> List[Dict]:
        await self._ensure_session()
        params = {"channel": self.channel, "client_id": self.client_id, "limit": "5"}
        timeout = aiohttp.ClientTimeout(total=8, connect=5, sock_read=7)
        async with self.session.get(self._endpoint("/api/v1/inbox"), params=params, timeout=timeout) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"{resp.status}: {text}")
            data = await resp.json()
        messages = data.get("messages", [])
        return messages if isinstance(messages, list) else []

    async def send_files(self, files: List[str | tuple[str, str]], target_peer_id: str, target_name: str = ""):
        normalized = []
        for item in files:
            if isinstance(item, tuple):
                normalized.append(item)
            else:
                normalized.append((item, os.path.basename(item)))

        for filepath, rel_path in normalized:
            await self.send_file(filepath, target_peer_id, target_name=target_name, target_rel_path=rel_path)

    async def send_file(self, filepath: str, target_peer_id: str, target_name: str = "", target_rel_path: str = "") -> str:
        await self._ensure_session()
        transfer_id = str(uuid.uuid4())[:8]
        filename = target_rel_path if target_rel_path else os.path.basename(filepath)

        if not os.path.exists(filepath):
            error = f"File not found: {filepath}"
            if self.on_transfer_error:
                self.on_transfer_error(transfer_id, error)
            raise FileNotFoundError(error)

        peer = self._peers.get(target_peer_id)
        if peer and bool(peer.get("secure_mode", False)) != self.secure_mode:
            error = "Security mode mismatch with relay peer"
            if self.on_transfer_error:
                self.on_transfer_error(transfer_id, error)
            raise ValueError(error)

        total_size = os.path.getsize(filepath)
        if self.on_transfer_start:
            self.on_transfer_start(transfer_id, filename, total_size, True)

        started = time.time()

        async def file_sender():
            sent = 0
            last_update = started

            async with aiofiles.open(filepath, "rb") as f:
                while True:
                    chunk = await f.read(UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break

                    if self._cipher:
                        token = self._cipher.encrypt(chunk)
                        frame = len(token).to_bytes(4, "big") + token
                        payload = frame
                    else:
                        payload = chunk

                    yield payload
                    sent += len(chunk)

                    now = time.time()
                    if now - last_update > 0.12 and self.on_transfer_progress:
                        elapsed = max(0.001, now - started)
                        self.on_transfer_progress(transfer_id, sent, sent / elapsed)
                        last_update = now

        headers = {
            "X-Channel": self.channel,
            "X-Client-ID": self.client_id,
            "X-Target-ID": target_peer_id,
            "X-Sender-Name-B64": base64.urlsafe_b64encode(self.display_name.encode("utf-8")).decode("ascii"),
            "X-Filename-B64": base64.urlsafe_b64encode(filename.encode("utf-8")).decode("ascii"),
            "X-Filesize": str(total_size),
            "X-Transfer-ID": transfer_id,
            "X-Secure-Mode": "1" if self.secure_mode else "0",
            "X-Encrypted": "fernet-frame" if self._cipher else "none",
        }
        if target_name:
            headers["X-Target-Name-B64"] = base64.urlsafe_b64encode(target_name.encode("utf-8")).decode("ascii")

        timeout = aiohttp.ClientTimeout(total=None, connect=12, sock_connect=12, sock_read=None)
        async with self.session.post(
            self._endpoint("/api/v1/upload"),
            data=file_sender(),
            headers=headers,
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                error = f"{resp.status}: {text}"
                if self.on_transfer_error:
                    self.on_transfer_error(transfer_id, error)
                raise RuntimeError(error)
            await resp.read()

        if self.on_transfer_complete:
            if self.on_transfer_progress:
                # Keep the UI at exact file size even when the last chunk was too fast
                # to trigger an intermediate progress callback.
                elapsed = max(0.001, time.time() - started)
                self.on_transfer_progress(transfer_id, total_size, total_size / elapsed)
            self.on_transfer_complete(transfer_id, filepath)
        return transfer_id

    async def _receive_message(self, message: Dict):
        msg_id = str(message.get("id", "")).strip()
        transfer_id = str(message.get("transfer_id", "")).strip() or str(uuid.uuid4())[:8]
        filename = self._safe_relative_path(str(message.get("filename", "")).strip() or "relay_file.bin")
        expected_size = int(message.get("size", 0) or 0)
        secure_required = bool(message.get("secure_mode", False))
        encrypted = str(message.get("encrypted", "")).strip().lower() == "fernet-frame"

        if secure_required != self.secure_mode:
            await self._ack(msg_id, "error", "SECURE_MODE_MISMATCH")
            if self.on_transfer_error:
                self.on_transfer_error(transfer_id, "Security mode mismatch with relay peer")
            return

        if encrypted and not self._cipher:
            await self._ack(msg_id, "error", "RECEIVER_NO_CIPHER")
            if self.on_transfer_error:
                self.on_transfer_error(transfer_id, "Encrypted relay payload cannot be decrypted")
            return

        if self.on_transfer_start:
            self.on_transfer_start(transfer_id, filename, expected_size, False)

        destination = self._unique_path(filename)
        writer = None
        received = 0
        started = time.time()
        last_update = started
        buffer = b""

        try:
            os.makedirs(self.download_dir, exist_ok=True)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            await self._ensure_session()

            params = {"client_id": self.client_id}
            timeout = aiohttp.ClientTimeout(total=None, connect=12, sock_read=None)
            async with self.session.get(self._endpoint(f"/api/v1/download/{msg_id}"), params=params, timeout=timeout) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"{resp.status}: {text}")

                writer = await aiofiles.open(destination, "wb")

                if encrypted:
                    async for raw in resp.content.iter_chunked(DOWNLOAD_CHUNK_SIZE):
                        buffer += raw
                        while len(buffer) >= 4:
                            frame_len = int.from_bytes(buffer[:4], "big")
                            if frame_len <= 0 or frame_len > 32 * 1024 * 1024:
                                raise ValueError("Invalid encrypted relay frame")
                            if len(buffer) < 4 + frame_len:
                                break
                            token = buffer[4:4 + frame_len]
                            buffer = buffer[4 + frame_len:]
                            decoded = self._cipher.decrypt(token)
                            await writer.write(decoded)
                            received += len(decoded)

                            now = time.time()
                            if now - last_update > 0.12 and self.on_transfer_progress:
                                elapsed = max(0.001, now - started)
                                self.on_transfer_progress(transfer_id, received, received / elapsed)
                                last_update = now
                    if buffer:
                        raise ValueError("Truncated encrypted relay payload")
                else:
                    async for raw in resp.content.iter_chunked(DOWNLOAD_CHUNK_SIZE):
                        if not raw:
                            continue
                        await writer.write(raw)
                        received += len(raw)

                        now = time.time()
                        if now - last_update > 0.12 and self.on_transfer_progress:
                            elapsed = max(0.001, now - started)
                            self.on_transfer_progress(transfer_id, received, received / elapsed)
                            last_update = now

            if writer:
                await writer.close()
                writer = None

            if expected_size > 0 and received != expected_size:
                raise ValueError(f"Relay size mismatch: expected {expected_size}, got {received}")

            await self._ack(msg_id, "ok", "")
            if self.on_transfer_progress:
                elapsed = max(0.001, time.time() - started)
                self.on_transfer_progress(transfer_id, received, received / elapsed)
            if self.on_transfer_complete:
                self.on_transfer_complete(transfer_id, destination)
        except Exception as e:
            if writer:
                await writer.close()
            try:
                if os.path.exists(destination):
                    os.remove(destination)
            except OSError:
                pass
            await self._ack(msg_id, "error", str(e))
            if self.on_transfer_error:
                self.on_transfer_error(transfer_id, f"Relay receive failed: {e}")

    async def _ack(self, message_id: str, status: str, error: str):
        if not message_id:
            return
        await self._ensure_session()
        payload = {
            "client_id": self.client_id,
            "status": status,
            "error": error,
        }
        timeout = aiohttp.ClientTimeout(total=8, connect=5, sock_read=7)
        try:
            async with self.session.post(
                self._endpoint(f"/api/v1/ack/{message_id}"),
                json=payload,
                timeout=timeout,
            ) as resp:
                await resp.read()
        except Exception:
            pass

    def _safe_relative_path(self, path: str) -> str:
        clean_parts = []
        for part in path.replace("\\", "/").split("/"):
            part = part.strip()
            if part and part not in {".", ".."} and not part.endswith(":"):
                clean_parts.append(part)
        if not clean_parts:
            return "relay_file.bin"
        return os.path.join(*clean_parts)

    def _unique_path(self, filename: str) -> str:
        base_path = os.path.join(self.download_dir, filename)
        if not os.path.exists(base_path):
            return base_path

        stem, ext = os.path.splitext(base_path)
        counter = 1
        while True:
            candidate = f"{stem}_{counter}{ext}"
            if not os.path.exists(candidate):
                return candidate
            counter += 1
