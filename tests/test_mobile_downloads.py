import ctypes
import os
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from network.server import TransferServer


def _create_sparse_file(path: Path, size: int):
    with path.open("w+b") as stream:
        if os.name == "nt":
            import msvcrt
            from ctypes import wintypes

            device_io_control = ctypes.windll.kernel32.DeviceIoControl
            device_io_control.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                wintypes.LPVOID,
            ]
            device_io_control.restype = wintypes.BOOL
            set_file_pointer = ctypes.windll.kernel32.SetFilePointerEx
            set_file_pointer.argtypes = [
                wintypes.HANDLE,
                ctypes.c_longlong,
                ctypes.POINTER(ctypes.c_longlong),
                wintypes.DWORD,
            ]
            set_file_pointer.restype = wintypes.BOOL
            set_end_of_file = ctypes.windll.kernel32.SetEndOfFile
            set_end_of_file.argtypes = [wintypes.HANDLE]
            set_end_of_file.restype = wintypes.BOOL
            handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
            returned = wintypes.DWORD()
            marked_sparse = device_io_control(
                handle,
                0x000900C4,  # FSCTL_SET_SPARSE
                None,
                0,
                None,
                0,
                ctypes.byref(returned),
                None,
            )
            if not marked_sparse:
                raise ctypes.WinError()
            if not set_file_pointer(handle, size, None, 0):
                raise ctypes.WinError()
            if not set_end_of_file(handle):
                raise ctypes.WinError()
        else:
            stream.truncate(size)


@pytest.mark.asyncio
async def test_multi_gigabyte_mobile_download_supports_head_and_ranges(tmp_path):
    size = 8 * 1024**3 + 123
    archive = tmp_path / "Booting.zip"
    _create_sparse_file(archive, size)

    server = TransferServer(port=0, download_dir=str(tmp_path))
    token = server.enable_mobile_share(ttl_sec=0)
    async with TestClient(TestServer(server.app)) as client:
        url = f"/api/mobile/download/{archive.name}?token={token}"

        async with client.head(url) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(size)
            assert response.headers["Accept-Ranges"] == "bytes"
            assert response.headers["Cache-Control"] == "private, no-transform"
            assert response.headers["X-Content-Type-Options"] == "nosniff"

        async with client.get(url, headers={"Range": "bytes=0-1023"}) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == f"bytes 0-1023/{size}"
            assert response.headers["Content-Length"] == "1024"
            assert len(await response.read()) == 1024

        start = size - 1024
        async with client.get(
            url,
            headers={"Range": f"bytes={start}-{size - 1}"},
        ) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == f"bytes {start}-{size - 1}/{size}"
            assert response.headers["Content-Length"] == "1024"
            assert len(await response.read()) == 1024

        compatibility_url = f"{url}&compat=1"
        async with client.head(compatibility_url) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(size)
            assert response.headers["Accept-Ranges"] == "bytes"
            assert response.headers["Content-Type"] == "application/octet-stream"
            assert 'filename="Booting.zip.txt"' in response.headers["Content-Disposition"]
            assert "filename*=UTF-8''Booting.zip.txt" in response.headers["Content-Disposition"]

        async with client.get(
            compatibility_url,
            headers={"Range": f"bytes={start}-{size - 1}"},
        ) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == f"bytes {start}-{size - 1}/{size}"
            assert response.headers["Content-Length"] == "1024"
            assert len(await response.read()) == 1024


@pytest.mark.asyncio
async def test_mobile_page_is_never_served_from_an_old_browser_cache(tmp_path):
    server = TransferServer(port=0, download_dir=str(tmp_path))
    token = server.enable_mobile_share(ttl_sec=0)

    async with TestClient(TestServer(server.app)) as client:
        async with client.get(f"/?token={token}") as response:
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-store, max-age=0"
            assert response.headers["Pragma"] == "no-cache"
            assert response.headers["Expires"] == "0"
