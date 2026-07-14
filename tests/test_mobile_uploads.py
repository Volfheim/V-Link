from pathlib import Path
from urllib.parse import quote

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from network.server import TransferServer


@pytest_asyncio.fixture
async def mobile_upload_client(tmp_path):
    server = TransferServer(
        port=0,
        download_dir=str(tmp_path),
        verify_checksum=False,
    )
    token = server.enable_mobile_share(ttl_sec=3600)
    completed = []
    server.on_transfer_complete = lambda transfer_id, path: completed.append(
        (transfer_id, path)
    )

    async with TestClient(TestServer(server.app)) as client:
        client.mobile_token = token
        client.transfer_server = server
        client.completed_transfers = completed
        client.download_dir = tmp_path
        yield client


async def upload_queue_file(
    client,
    *,
    transfer_id,
    path,
    data,
    index=0,
    count=1,
    upload_name="",
    upload_type="files",
    total_size=None,
    file_size=None,
    skip=False,
):
    headers = {
        "X-Upload-Path": quote(path, safe=""),
        "X-Upload-Transfer-Id": transfer_id,
        "X-Upload-Total-Size": str(len(data) if total_size is None else total_size),
        "X-Upload-File-Index": str(index),
        "X-Upload-File-Count": str(count),
        "X-Upload-Name": quote(upload_name, safe=""),
        "X-Upload-File-Size": str(len(data) if file_size is None else file_size),
        "Content-Type": "application/octet-stream",
    }
    if upload_type:
        headers["X-Upload-Type"] = upload_type
    if skip:
        headers["X-Upload-Skip"] = "1"

    response = await client.post(
        f"/api/mobile/upload?token={client.mobile_token}",
        headers=headers,
        data=b"" if skip else data,
    )
    payload = await response.json()
    return response, payload


@pytest.mark.asyncio
async def test_single_mobile_file_is_saved_without_wrapper_folder(mobile_upload_client):
    client = mobile_upload_client
    data = b"screenshot"

    response, payload = await upload_queue_file(
        client,
        transfer_id="single-file",
        path="Screenshot.png",
        data=data,
        upload_name="Screenshot.png",
    )

    target = client.download_dir / "Screenshot.png"
    assert response.status == 200
    assert payload["status"] == "ok"
    assert target.read_bytes() == data
    assert not (target / "Screenshot.png").exists()
    assert client.completed_transfers == [("single-file", str(target))]
    assert not client.transfer_server._active_uploads


@pytest.mark.asyncio
async def test_multiple_selected_files_are_saved_directly(mobile_upload_client):
    client = mobile_upload_client

    first, _ = await upload_queue_file(
        client,
        transfer_id="selected-files",
        path="one.txt",
        data=b"one",
        index=0,
        count=2,
        upload_name="mobile-upload",
        total_size=6,
    )
    second, _ = await upload_queue_file(
        client,
        transfer_id="selected-files",
        path="two.txt",
        data=b"two",
        index=1,
        count=2,
        upload_name="mobile-upload",
        total_size=6,
    )

    assert first.status == second.status == 200
    assert (client.download_dir / "one.txt").read_bytes() == b"one"
    assert (client.download_dir / "two.txt").read_bytes() == b"two"
    assert not (client.download_dir / "mobile-upload").exists()
    assert client.completed_transfers == [
        ("selected-files", str(client.download_dir))
    ]


@pytest.mark.asyncio
async def test_mobile_folder_keeps_exactly_one_root(mobile_upload_client):
    client = mobile_upload_client

    response, _ = await upload_queue_file(
        client,
        transfer_id="folder-upload",
        path="day-one/Screenshot.png",
        data=b"image",
        upload_name="Photos",
        upload_type="folder",
    )

    folder = client.download_dir / "Photos"
    assert response.status == 200
    assert (folder / "day-one" / "Screenshot.png").read_bytes() == b"image"
    assert not (folder / "Photos").exists()
    assert client.completed_transfers == [("folder-upload", str(folder))]


@pytest.mark.asyncio
async def test_resumed_folder_finishes_when_last_file_is_skipped(mobile_upload_client):
    client = mobile_upload_client
    folder = client.download_dir / "Photos"
    folder.mkdir()
    (folder / "existing.txt").write_bytes(b"old")

    first, _ = await upload_queue_file(
        client,
        transfer_id="resume-folder",
        path="new.txt",
        data=b"new",
        index=0,
        count=2,
        upload_name="Photos",
        upload_type="folder",
        total_size=6,
    )
    skipped, payload = await upload_queue_file(
        client,
        transfer_id="resume-folder",
        path="existing.txt",
        data=b"old",
        index=1,
        count=2,
        upload_name="Photos",
        upload_type="folder",
        total_size=6,
        skip=True,
    )

    assert first.status == skipped.status == 200
    assert payload["skipped"] is True
    assert (folder / "new.txt").read_bytes() == b"new"
    assert (folder / "existing.txt").read_bytes() == b"old"
    assert not (client.download_dir / "Photos_1").exists()
    assert client.completed_transfers == [("resume-folder", str(folder))]
    assert not client.transfer_server._active_uploads


@pytest.mark.asyncio
async def test_cached_mobile_page_folder_path_is_not_duplicated(mobile_upload_client):
    client = mobile_upload_client

    response, _ = await upload_queue_file(
        client,
        transfer_id="legacy-folder",
        path="Archive/nested/file.txt",
        data=b"legacy",
        upload_name="Archive",
        upload_type="",
    )

    folder = client.download_dir / "Archive"
    assert response.status == 200
    assert (folder / "nested" / "file.txt").read_bytes() == b"legacy"
    assert not (folder / "Archive").exists()


@pytest.mark.asyncio
async def test_incomplete_mobile_file_does_not_replace_destination(mobile_upload_client):
    client = mobile_upload_client
    folder = client.download_dir / "Photos"
    folder.mkdir()
    target = folder / "broken.bin"
    target.write_bytes(b"original")

    response, payload = await upload_queue_file(
        client,
        transfer_id="broken-file",
        path="broken.bin",
        data=b"bad",
        upload_name="Photos",
        upload_type="folder",
        file_size=5,
    )

    assert response.status == 500
    assert payload["status"] == "error"
    assert target.read_bytes() == b"original"
    assert not list(client.download_dir.rglob("*.part"))
    assert not client.transfer_server._active_uploads
