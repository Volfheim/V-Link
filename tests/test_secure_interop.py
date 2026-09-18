"""Real HTTP client/server tests with isolated files and loopback-only listeners."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import MethodType, SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cryptography.fernet import Fernet

from core.clipboard_sync import ClipboardSyncManager
from network.client import TransferClient
from network.relay import RelayClient
from network.server import TransferServer
from security.derivation import auth_token, auth_matches, fernet_key

SECRET = "test-shared-secret"  # Test data only; never a credential.


@pytest.mark.parametrize("version", ["0", "3", "unknown"])
def test_unknown_versions_fail_closed(version):
    with pytest.raises(ValueError):
        fernet_key(SECRET, version)
    with pytest.raises(ValueError):
        auth_token(SECRET, version)
    assert auth_matches(SECRET, auth_token(SECRET), version, allow_legacy=True) is None


def test_malformed_token_does_not_raise():
    assert auth_matches(SECRET, "é" * 64, "2") is None


@pytest.mark.parametrize("kind", ["server", "client", "relay"])
def test_secure_mode_requires_key(kind, tmp_path):
    with pytest.raises(ValueError, match="shared key"):
        if kind == "server":
            TransferServer(download_dir=str(tmp_path), enable_encryption=True)
        elif kind == "client":
            TransferClient(enable_encryption=True)
        else:
            RelayClient("http://127.0.0.1", "fixture", "a", "A", str(tmp_path), secure_mode=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [b"", b"short", b"long fixture" * 100_000], ids=['empty', 'small', 'multiple-frames'])
async def test_actual_v2_client_roundtrip(tmp_path, data):
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    dest = tmp_path / "received"
    server = TransferServer(download_dir=str(dest), auth_token=SECRET, enable_encryption=True, verify_checksum=True)
    client = TransferClient(auth_token=SECRET, enable_encryption=True, verify_checksum=True, auto_tune=False)
    async with TestServer(server.app) as endpoint:
        try:
            await client.send_file(str(source), endpoint.host, endpoint.port)
        finally:
            await client.stop()
    assert (dest / source.name).read_bytes() == data


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_legacy", [False, True])
async def test_401_cannot_silently_downgrade_client(tmp_path, allow_legacy):
    seen = []
    received = []
    async def old_upload(request):
        seen.append(dict(request.headers))
        # v2.4.8 token and frame contract; no v2 helpers involved.
        if request.headers.get("X-Auth-Token") != hashlib.sha256(SECRET.encode()).hexdigest():
            await request.read()
            return web.Response(status=401, text="Unauthorized")
        wire = await request.read()
        assert int.from_bytes(wire[:4], "big") == len(wire) - 4
        old_cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET.encode()).digest()))
        received.append(old_cipher.decrypt(wire[4:]))
        return web.json_response({"status": "success"})
    app = web.Application()
    app.router.add_post('/upload', old_upload)
    source = tmp_path / "fixture.txt"
    source.write_bytes(b"legacy-compatible")
    client = TransferClient(auth_token=SECRET, enable_encryption=True, auto_tune=False, allow_legacy_secure=allow_legacy)
    async with TestServer(app) as endpoint:
        try:
            if allow_legacy:
                await client.send_file(str(source), endpoint.host, endpoint.port)
            else:
                with pytest.raises(Exception, match="401"):
                    await client.send_file(str(source), endpoint.host, endpoint.port)
        finally:
            await client.stop()
    assert [h['X-Auth-Version'] for h in seen] == (["2", "1"] if allow_legacy else ["2"])
    assert received == ([b"legacy-compatible"] if allow_legacy else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_request", ["plaintext", "legacy", "tampered"])
async def test_secure_receiver_rejects_downgrade_and_corruption(tmp_path, bad_request):
    server = TransferServer(download_dir=str(tmp_path), auth_token=SECRET, enable_encryption=True)
    headers = {"X-Auth-Version": "2", "X-Auth-Token": auth_token(SECRET), "X-Filename": "attack.bin", "X-Filesize": "3"}
    body = b"bad"
    if bad_request == "legacy":
        headers.update({'X-Auth-Version':'1', 'X-Auth-Token':auth_token(SECRET, '1')})
    elif bad_request == "tampered":
        headers['X-Encrypted'] = 'fernet-frame'
        token = bytearray(Fernet(fernet_key(SECRET)).encrypt(b"bad"))
        token[30] ^= 1
        body = len(token).to_bytes(4, 'big') + bytes(token)
    async with TestClient(TestServer(server.app)) as endpoint:
        response = await endpoint.post('/upload', data=body, headers=headers)
        assert response.status >= 400
    assert not list(tmp_path.rglob('attack.bin'))


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_legacy", [False, True])
async def test_clipboard_sender_does_not_downgrade_without_opt_in(allow_legacy):
    seen = []
    async def old_clipboard(request):
        seen.append(dict(request.headers))
        assert json.loads(await request.read()) == {'type':'text', 'content':'fixture'}
        return web.Response(status=200 if request.headers.get('X-Auth-Token') == auth_token(SECRET, '1') else 401)
    app = web.Application()
    app.router.add_post('/clipboard', old_clipboard)
    async with TestServer(app) as endpoint, aiohttp.ClientSession() as session:
        # Exercise the real sender without constructing/accessing a system clipboard.
        manager = SimpleNamespace(_enabled=True, _auth_secret=SECRET, _session=session,
            settings={'allow_legacy_secure':allow_legacy}, _peer_provider=lambda:[(endpoint.host, endpoint.port)])
        manager._auth_headers = MethodType(ClipboardSyncManager._auth_headers, manager)
        manager._ensure_session = MethodType(ClipboardSyncManager._ensure_session, manager)
        await ClipboardSyncManager._broadcast_payload(manager, {'type':'text', 'content':'fixture'})
    assert len(seen) == (2 if allow_legacy else 1)
    assert seen[0]['X-Auth-Token'] == auth_token(SECRET)
    if allow_legacy:
        assert seen[1]['X-Auth-Token'] == auth_token(SECRET, '1')


def relay_app(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'relay/relay_server.py'
    spec = importlib.util.spec_from_file_location('fixture_relay_server', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.STORAGE_DIR = tmp_path / 'relay-storage'
    return module.create_app()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_peer", [False, True])
async def test_relay_presence_upload_download_and_ack(tmp_path, legacy_peer):
    app = relay_app(tmp_path)
    async with TestServer(app) as endpoint:
        sender = RelayClient(str(endpoint.make_url('/')), 'fixture', 'sender', 'Sender', str(tmp_path/'a'), True, SECRET, allow_legacy_secure=legacy_peer)
        receiver = RelayClient(str(endpoint.make_url('/')), 'fixture', 'receiver', 'Receiver', str(tmp_path/'b'), True, SECRET, allow_legacy_secure=legacy_peer)
        failures = []
        receiver.on_transfer_error = lambda *args: failures.append(args)
        source = tmp_path / 'source.bin'
        source.write_bytes(b'relay roundtrip' * 150_000)
        try:
            await receiver._sync_presence()
            if legacy_peer:
                # Old peers omit protocol_version; the reference server reports v1.
                async with receiver.session.post(receiver._endpoint('/api/v1/presence'), json={
                    'channel':'fixture', 'client_id':'receiver', 'name':'Old receiver', 'secure_mode':True}) as response:
                    assert response.status == 200
            await sender._sync_presence()
            assert sender.get_peers()['receiver']['protocol_version'] == ('1' if legacy_peer else '2')
            await sender.send_file(str(source), 'receiver')
            messages = await receiver._fetch_inbox()
            assert len(messages) == 1
            assert messages[0]['protocol_version'] == ('1' if legacy_peer else '2')
            await receiver._receive_message(messages[0])
            assert not failures
            assert (tmp_path/'b/source.bin').read_bytes() == source.read_bytes()
            assert await receiver._fetch_inbox() == []
        finally:
            await sender.stop()
            await receiver.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ['1', '3'])
async def test_relay_unknown_or_legacy_peer_is_not_silently_used(tmp_path, version):
    async with TestServer(relay_app(tmp_path)) as endpoint:
        client = RelayClient(str(endpoint.make_url('/')), 'fixture', 'a', 'A', str(tmp_path), True, SECRET)
        client._peers['old'] = {'secure_mode':True, 'protocol_version':version}
        source=tmp_path/'test.txt'
        source.write_bytes(b'private')
        try:
            with pytest.raises(ValueError):
                await client.send_file(str(source), 'old')
            assert not endpoint.app['messages']
        finally:
            await client.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("encrypted,version", [('none','2'), ('fernet-frame','1'), ('fernet-frame','3')])
async def test_relay_rejects_insecure_message_before_download(tmp_path, encrypted, version):
    client = RelayClient('http://127.0.0.1', 'fixture', 'a', 'A', str(tmp_path), True, SECRET)
    acknowledgments = []
    async def ack(*args): acknowledgments.append(args)
    client._ack = ack
    await client._receive_message({'id':'fixture', 'filename':'private.bin', 'size':3, 'secure_mode':True,
                                   'encrypted':encrypted, 'protocol_version':version})
    assert acknowledgments[0][1] == 'error'
    assert client.session is None
    assert not list(tmp_path.iterdir())
