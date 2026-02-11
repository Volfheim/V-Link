"""
V-Link - Clipboard synchronization manager.
Synchronizes text and optional images between discovered peers.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from typing import Callable, Iterable, Optional

import aiohttp
from PyQt6.QtCore import QBuffer, QIODevice, QObject, QTimer
from PyQt6.QtGui import QGuiApplication, QImage


class ClipboardSyncManager(QObject):
    """Bidirectional clipboard sync over local HTTP endpoints."""

    MAX_TEXT_CHARS = 200_000
    MAX_IMAGE_BYTES = 10 * 1024 * 1024
    SEND_COOLDOWN_SEC = 0.25

    def __init__(
        self,
        settings,
        peer_provider: Callable[[], Iterable[tuple[str, int]]],
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self._peer_provider = peer_provider

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._auth_secret = ""
        self._enabled = bool(self.settings.get("clipboard_sync_enabled", True))
        self._sync_images = bool(self.settings.get("clipboard_sync_images", False))

        self._sender_id = self._resolve_sender_id()
        self._internal_update = False
        self._last_sent_digest = ""
        self._last_applied_digest = ""
        self._last_send_ts = 0.0

        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._clear_internal_update)

        self._clipboard = QGuiApplication.clipboard()
        self._clipboard.dataChanged.connect(self._on_clipboard_changed)

    def configure(self, loop: asyncio.AbstractEventLoop, auth_secret: str):
        self._loop = loop
        self._auth_secret = (auth_secret or "").strip()
        self._enabled = bool(self.settings.get("clipboard_sync_enabled", True))
        self._sync_images = bool(self.settings.get("clipboard_sync_images", False))

    async def stop(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    def refresh_from_settings(self):
        self._enabled = bool(self.settings.get("clipboard_sync_enabled", True))
        self._sync_images = bool(self.settings.get("clipboard_sync_images", False))

    def _resolve_sender_id(self) -> str:
        """
        Resolve a stable per-device sender id.
        If id is missing in settings, create and persist it.
        """
        try:
            sid = getattr(self.settings, "clipboard_node_id")
            sid = str(sid or "").strip()
            if sid:
                return sid
        except Exception:
            pass

        try:
            sid = str(self.settings.get("clipboard_node_id", "") or "").strip()
            if sid:
                return sid
        except Exception:
            pass

        sid = uuid.uuid4().hex[:16]
        try:
            self.settings.set("clipboard_node_id", sid)
        except Exception:
            pass
        return sid

    def _clear_internal_update(self):
        self._internal_update = False

    def _on_clipboard_changed(self):
        if not self._enabled or self._internal_update:
            return
        payload = self._build_payload_from_local_clipboard()
        if not payload:
            return

        digest = self._digest_payload(payload)
        now = time.monotonic()
        if digest == self._last_sent_digest and (now - self._last_send_ts) < 1.0:
            return
        if (now - self._last_send_ts) < self.SEND_COOLDOWN_SEC:
            return

        self._last_sent_digest = digest
        self._last_send_ts = now
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._broadcast_payload(payload))
            )

    def _build_payload_from_local_clipboard(self) -> Optional[dict]:
        if not self._clipboard:
            return None
        mime = self._clipboard.mimeData()
        if not mime:
            return None

        if mime.hasText():
            text = self._clipboard.text() or ""
            if not text:
                return None
            if len(text) > self.MAX_TEXT_CHARS:
                text = text[: self.MAX_TEXT_CHARS]
            return {
                "type": "text",
                "content": text,
                "timestamp": time.time(),
                "sender": self._sender_id,
            }

        if self._sync_images and mime.hasImage():
            img = self._clipboard.image()
            if img is None or img.isNull():
                return None
            raw = self._image_to_png_bytes(img)
            if not raw:
                return None
            if len(raw) > self.MAX_IMAGE_BYTES:
                return None
            encoded = base64.b64encode(raw).decode("ascii")
            return {
                "type": "image",
                "content": encoded,
                "timestamp": time.time(),
                "sender": self._sender_id,
            }

        return None

    @staticmethod
    def _image_to_png_bytes(img: QImage) -> bytes:
        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            return b""
        try:
            if not img.save(buffer, "PNG"):
                return b""
            return bytes(buffer.data())
        finally:
            buffer.close()

    @staticmethod
    def _digest_payload(payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8", "ignore")
        return hashlib.sha256(raw).hexdigest()

    def _auth_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._auth_secret:
            token = hashlib.sha256(self._auth_secret.encode("utf-8")).hexdigest()
            headers["X-Auth-Token"] = token
        return headers

    async def _ensure_session(self):
        if self._session and not self._session.closed:
            return
        timeout = aiohttp.ClientTimeout(total=8, connect=3, sock_read=5)
        connector = aiohttp.TCPConnector(limit=8, enable_cleanup_closed=True)
        self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)

    async def _broadcast_payload(self, payload: dict):
        if not self._enabled:
            return
        peers = list(self._peer_provider() or [])
        if not peers:
            return

        await self._ensure_session()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = self._auth_headers()

        for ip, port in peers:
            try:
                url = f"http://{ip}:{int(port)}/clipboard"
                async with self._session.post(url, data=body, headers=headers):
                    pass
            except Exception:
                continue

    def apply_remote_payload(self, payload: dict):
        if not self._enabled or not isinstance(payload, dict):
            return

        payload_type = str(payload.get("type", "") or "").strip().lower()
        sender = str(payload.get("sender", "") or "").strip()
        if sender and sender == self._sender_id:
            return
        if payload_type not in ("text", "image"):
            return
        if payload_type == "image" and not self._sync_images:
            return

        digest = self._digest_payload(payload)
        if digest == self._last_applied_digest:
            return
        if digest == self._last_sent_digest and (time.monotonic() - self._last_send_ts) < 2.0:
            return

        self._internal_update = True
        self._reset_timer.start(900)

        try:
            if payload_type == "text":
                text = str(payload.get("content", "") or "")
                if len(text) > self.MAX_TEXT_CHARS:
                    text = text[: self.MAX_TEXT_CHARS]
                self._clipboard.setText(text)
            else:
                encoded = str(payload.get("content", "") or "")
                if not encoded:
                    return
                raw = base64.b64decode(encoded.encode("ascii"), validate=False)
                if len(raw) > self.MAX_IMAGE_BYTES:
                    return
                image = QImage.fromData(raw, "PNG")
                if image.isNull():
                    return
                self._clipboard.setImage(image)
            self._last_applied_digest = digest
        finally:
            if not self._reset_timer.isActive():
                self._internal_update = False
