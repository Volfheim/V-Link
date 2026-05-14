"""
V-Link Relay Server (reference implementation)

Usage:
    python relay/relay_server.py

Environment variables:
    VLINK_RELAY_HOST=0.0.0.0
    VLINK_RELAY_PORT=8090
    VLINK_RELAY_STORAGE=./relay_storage
    VLINK_RELAY_PEER_TTL=40
    VLINK_RELAY_MESSAGE_TTL=86400
"""

import asyncio
import base64
import os
import time
import uuid
from pathlib import Path
from typing import Dict

import aiofiles
from aiohttp import web


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


HOST = os.getenv("VLINK_RELAY_HOST", "0.0.0.0")
PORT = _env_int("VLINK_RELAY_PORT", 8090)
STORAGE_DIR = Path(os.getenv("VLINK_RELAY_STORAGE", "./relay_storage")).resolve()
PEER_TTL = _env_int("VLINK_RELAY_PEER_TTL", 40)
MESSAGE_TTL = _env_int("VLINK_RELAY_MESSAGE_TTL", 86400)
CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_SIZE = 20 * 1024 * 1024 * 1024  # 20 GB


def _decode_b64(value: str, fallback: str = "") -> str:
    if not value:
        return fallback
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        text = raw.decode("utf-8", errors="ignore").strip()
        return text or fallback
    except Exception:
        return fallback


def _safe_name(name: str, fallback: str) -> str:
    stripped = (name or "").strip()
    return stripped if stripped else fallback


def _safe_channel(channel: str) -> str:
    clean = []
    for ch in (channel or "default").strip():
        if ch.isalnum() or ch in ("-", "_", "."):
            clean.append(ch)
        else:
            clean.append("_")
    value = "".join(clean).strip("._-")
    return value or "default"


def _safe_relative_path(path: str, fallback: str = "relay_file.bin") -> str:
    clean_parts = []
    for part in str(path or "").replace("\\", "/").split("/"):
        part = part.strip()
        if part and part not in {".", ".."} and not part.endswith(":"):
            clean_parts.append(part)
    if not clean_parts:
        return fallback
    return os.path.join(*clean_parts).replace("\\", "/")


def _message_view(message: Dict) -> Dict:
    return {
        "id": message["id"],
        "transfer_id": message["transfer_id"],
        "filename": message["filename"],
        "size": message["size"],
        "from_id": message["from_id"],
        "from_name": message["from_name"],
        "secure_mode": message["secure_mode"],
        "encrypted": message["encrypted"],
        "created_at": message["created_at"],
    }


async def _cleanup_state(app: web.Application):
    now = time.time()
    peer_ttl = float(app["peer_ttl"])
    message_ttl = float(app["message_ttl"])

    async with app["state_lock"]:
        peers = app["peers"]
        for key in list(peers.keys()):
            if now - float(peers[key].get("last_seen", now)) > peer_ttl:
                peers.pop(key, None)

        messages = app["messages"]
        for msg_id in list(messages.keys()):
            msg = messages[msg_id]
            created = float(msg.get("created_at", now))
            if now - created <= message_ttl:
                continue
            path = Path(msg.get("path", ""))
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
            messages.pop(msg_id, None)


async def _cleanup_loop(app: web.Application):
    while True:
        try:
            await _cleanup_state(app)
        except Exception:
            pass
        await asyncio.sleep(30)


async def on_startup(app: web.Application):
    app["storage_dir"].mkdir(parents=True, exist_ok=True)
    app["cleanup_task"] = asyncio.create_task(_cleanup_loop(app))


async def on_cleanup(app: web.Application):
    task = app.get("cleanup_task")
    if task:
        task.cancel()
        try:
            await task
        except BaseException:
            pass


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def presence(request: web.Request) -> web.Response:
    app = request.app
    body = await request.json()

    channel = _safe_channel(str(body.get("channel", "")).strip())
    client_id = str(body.get("client_id", "")).strip()
    name = _safe_name(str(body.get("name", "")).strip(), client_id or "unknown")
    secure_mode = bool(body.get("secure_mode", False))
    if not client_id:
        return web.json_response({"status": "error", "message": "client_id is required"}, status=400)

    now = time.time()
    key = f"{channel}:{client_id}"
    async with app["state_lock"]:
        app["peers"][key] = {
            "channel": channel,
            "id": client_id,
            "name": name,
            "secure_mode": secure_mode,
            "last_seen": now,
        }

    await _cleanup_state(app)

    peers_out = []
    async with app["state_lock"]:
        for peer in app["peers"].values():
            if peer["channel"] != channel or peer["id"] == client_id:
                continue
            peers_out.append(
                {
                    "id": peer["id"],
                    "name": peer["name"],
                    "secure_mode": bool(peer.get("secure_mode", False)),
                    "last_seen": float(peer.get("last_seen", now)),
                }
            )

    peers_out.sort(key=lambda x: x["name"].lower())
    return web.json_response({"status": "ok", "peers": peers_out})


async def upload(request: web.Request) -> web.Response:
    app = request.app

    channel = _safe_channel(request.headers.get("X-Channel", "").strip())
    from_id = request.headers.get("X-Client-ID", "").strip()
    target_id = request.headers.get("X-Target-ID", "").strip()
    transfer_id = request.headers.get("X-Transfer-ID", "").strip() or str(uuid.uuid4())[:8]
    filename = _safe_relative_path(_decode_b64(request.headers.get("X-Filename-B64", ""), "relay_file.bin"))
    from_name = _decode_b64(request.headers.get("X-Sender-Name-B64", ""), from_id or "unknown")
    secure_mode = request.headers.get("X-Secure-Mode", "0").strip() == "1"
    encrypted = request.headers.get("X-Encrypted", "none").strip().lower()

    if not from_id or not target_id:
        return web.json_response({"status": "error", "message": "X-Client-ID and X-Target-ID are required"}, status=400)

    try:
        expected_size = int(request.headers.get("X-Filesize", "0") or "0")
    except ValueError:
        expected_size = 0

    msg_id = uuid.uuid4().hex[:20]
    store_dir = app["storage_dir"] / channel
    store_dir.mkdir(parents=True, exist_ok=True)
    file_path = store_dir / f"{msg_id}.bin"

    written = 0
    try:
        async with aiofiles.open(file_path, "wb") as f:
            async for chunk in request.content.iter_chunked(CHUNK_SIZE):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_UPLOAD_SIZE:
                    raise ValueError("upload is too large")
                await f.write(chunk)
    except Exception as e:
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass
        return web.json_response({"status": "error", "message": str(e)}, status=400)

    if expected_size > 0 and written == 0:
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass
        return web.json_response({"status": "error", "message": "empty upload body"}, status=400)

    now = time.time()
    async with app["state_lock"]:
        app["messages"][msg_id] = {
            "id": msg_id,
            "channel": channel,
            "from_id": from_id,
            "from_name": from_name,
            "target_id": target_id,
            "transfer_id": transfer_id,
            "filename": filename,
            "size": expected_size if expected_size > 0 else written,
            "stored_size": written,
            "secure_mode": secure_mode,
            "encrypted": encrypted,
            "created_at": now,
            "path": str(file_path),
            "status": "pending",
        }

    return web.json_response({"status": "queued", "message_id": msg_id, "size": written})


async def inbox(request: web.Request) -> web.Response:
    app = request.app
    channel = _safe_channel(request.query.get("channel", "").strip())
    client_id = request.query.get("client_id", "").strip()
    if not client_id:
        return web.json_response({"status": "error", "message": "client_id is required"}, status=400)

    try:
        limit = max(1, min(20, int(request.query.get("limit", "5") or "5")))
    except ValueError:
        limit = 5

    await _cleanup_state(app)

    messages_out = []
    async with app["state_lock"]:
        pending = [
            msg for msg in app["messages"].values()
            if msg.get("channel") == channel
            and msg.get("target_id") == client_id
            and msg.get("status") in {"pending", "downloading"}
        ]
        pending.sort(key=lambda m: float(m.get("created_at", 0.0)))
        for msg in pending[:limit]:
            messages_out.append(_message_view(msg))

    return web.json_response({"status": "ok", "messages": messages_out})


async def download(request: web.Request) -> web.Response:
    app = request.app
    msg_id = request.match_info["message_id"]
    client_id = request.query.get("client_id", "").strip()
    if not client_id:
        return web.json_response({"status": "error", "message": "client_id is required"}, status=400)

    async with app["state_lock"]:
        msg = app["messages"].get(msg_id)
        if not msg:
            return web.json_response({"status": "error", "message": "message not found"}, status=404)
        if msg.get("target_id") != client_id:
            return web.json_response({"status": "error", "message": "forbidden"}, status=403)
        msg["status"] = "downloading"

        path = Path(msg.get("path", ""))
        if not path.exists():
            app["messages"].pop(msg_id, None)
            return web.json_response({"status": "error", "message": "payload missing"}, status=404)

        response = web.FileResponse(path=path)
        response.headers["X-Transfer-ID"] = str(msg.get("transfer_id", ""))
        response.headers["X-Filename"] = str(msg.get("filename", ""))
        response.headers["X-Filesize"] = str(msg.get("size", 0))
        response.headers["X-Secure-Mode"] = "1" if bool(msg.get("secure_mode", False)) else "0"
        response.headers["X-Encrypted"] = str(msg.get("encrypted", "none"))
        return response


async def ack(request: web.Request) -> web.Response:
    app = request.app
    msg_id = request.match_info["message_id"]
    body = await request.json()

    client_id = str(body.get("client_id", "")).strip()
    if not client_id:
        return web.json_response({"status": "error", "message": "client_id is required"}, status=400)

    async with app["state_lock"]:
        msg = app["messages"].get(msg_id)
        if not msg:
            return web.json_response({"status": "ok"})
        if msg.get("target_id") != client_id:
            return web.json_response({"status": "error", "message": "forbidden"}, status=403)

        path = Path(msg.get("path", ""))
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        app["messages"].pop(msg_id, None)

    return web.json_response({"status": "ok"})


def create_app() -> web.Application:
    app = web.Application(client_max_size=MAX_UPLOAD_SIZE)
    app["storage_dir"] = STORAGE_DIR
    app["peers"] = {}
    app["messages"] = {}
    app["state_lock"] = asyncio.Lock()
    app["peer_ttl"] = PEER_TTL
    app["message_ttl"] = MESSAGE_TTL

    app.router.add_get("/health", health)
    app.router.add_post("/api/v1/presence", presence)
    app.router.add_post("/api/v1/upload", upload)
    app.router.add_get("/api/v1/inbox", inbox)
    app.router.add_get("/api/v1/download/{message_id}", download)
    app.router.add_post("/api/v1/ack/{message_id}", ack)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main():
    print(f"V-Link Relay listening on {HOST}:{PORT}")
    print(f"Storage: {STORAGE_DIR}")
    web.run_app(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
