import base64
import hashlib

import pytest
from aiohttp.test_utils import TestClient, TestServer
from cryptography.fernet import Fernet

from security.derivation import PROTOCOL_VERSION, auth_matches, auth_token, encryption_key, fernet_key
from network.server import TransferServer


def test_v2_auth_and_encryption_material_are_independent():
    secret = "test shared secret"
    assert auth_token(secret) != hashlib.sha256(secret.encode()).hexdigest()
    assert auth_token(secret).encode() != encryption_key(secret)
    assert fernet_key(secret) != base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def test_v2_auth_is_versioned_and_legacy_is_explicitly_accepted():
    secret = "test shared secret"
    assert auth_matches(secret, auth_token(secret), PROTOCOL_VERSION) == PROTOCOL_VERSION
    assert auth_matches(secret, auth_token(secret, "1"), "1") == "1"
    assert auth_matches(secret, auth_token(secret, "1"), None) == "1"
    assert auth_matches(secret, auth_token(secret), "1") is None
    assert auth_matches(secret, "wrong", PROTOCOL_VERSION) is None


@pytest.mark.asyncio
async def test_clipboard_accepts_v2_and_legacy_auth_headers(tmp_path):
    secret = "test shared secret"
    server = TransferServer(port=0, download_dir=str(tmp_path), auth_token=secret, enable_encryption=True)
    async with TestClient(TestServer(server.app)) as client:
        payload = {"type": "text", "content": "ok"}
        v2 = await client.post("/clipboard", json=payload, headers={
            "X-Auth-Version": "2", "X-Auth-Token": auth_token(secret),
        })
        legacy = await client.post("/clipboard", json=payload, headers={
            "X-Auth-Token": auth_token(secret, "1"),
        })
        denied = await client.post("/clipboard", json=payload, headers={
            "X-Auth-Version": "2", "X-Auth-Token": auth_token(secret, "1"),
        })
    assert v2.status == legacy.status == 200
    assert denied.status == 401


@pytest.mark.asyncio
async def test_server_decrypts_legacy_and_v2_frames(tmp_path):
    secret = "test shared secret"
    server = TransferServer(port=0, download_dir=str(tmp_path), auth_token=secret, enable_encryption=True)
    async with TestClient(TestServer(server.app)) as client:
        for version in ("1", PROTOCOL_VERSION):
            data = f"payload-{version}".encode()
            frame = Fernet(fernet_key(secret, version)).encrypt(data)
            response = await client.post("/upload", data=len(frame).to_bytes(4, "big") + frame, headers={
                "X-Auth-Version": version,
                "X-Auth-Token": auth_token(secret, version),
                "X-Filename": f"file-{version}.txt",
                "X-Filesize": str(len(data)),
                "X-Encrypted": "fernet-frame",
                "X-Transfer-ID": f"transfer-{version}",
            })
            assert response.status == 200, await response.text()
            assert (tmp_path / f"file-{version}.txt").read_bytes() == data
