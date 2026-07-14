from urllib.parse import quote

import pytest
from aiohttp.test_utils import TestClient, TestServer

from main_window import MainWindow
from network.server import TransferServer


def test_desktop_folder_collection_keeps_one_root(tmp_path):
    folder = tmp_path / "Photos"
    nested = folder / "day-one"
    nested.mkdir(parents=True)
    (folder / "cover.jpg").write_bytes(b"cover")
    (nested / "shot.png").write_bytes(b"shot")

    files, folder_count = MainWindow._collect_transfer_files(None, [str(folder)])
    relative_paths = {relative for _path, relative in files}

    assert folder_count == 1
    assert relative_paths == {
        "Photos/cover.jpg",
        "Photos/day-one/shot.png",
    }


@pytest.mark.asyncio
async def test_direct_folder_upload_keeps_one_root(tmp_path):
    server = TransferServer(
        port=0,
        download_dir=str(tmp_path),
        verify_checksum=False,
    )
    relative_path = "Photos/day-one/shot.png"
    data = b"shot"

    async with TestClient(TestServer(server.app)) as client:
        response = await client.post(
            "/upload",
            headers={
                "X-Transfer-ID": "desktop-folder",
                "X-Filename": quote("shot.png", safe=""),
                "X-Relative-Path": quote(relative_path, safe=""),
                "X-Filesize": str(len(data)),
                "Content-Type": "application/octet-stream",
            },
            data=data,
        )
        payload = await response.json()

    assert response.status == 200
    assert payload["status"] == "success"
    assert (tmp_path / "Photos" / "day-one" / "shot.png").read_bytes() == data
    assert not (tmp_path / "Photos" / "Photos").exists()
