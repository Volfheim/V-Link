import pytest
import asyncio
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from network.server import TransferServer

import pytest_asyncio

@pytest.fixture
def temp_download_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Создаем тестовые файлы и папки
        (Path(tmpdir) / "test_file.txt").write_text("Hello World", encoding="utf-8")
        subfolder = Path(tmpdir) / "subfolder"
        subfolder.mkdir()
        (subfolder / "inner.txt").write_text("Inner file", encoding="utf-8")
        yield tmpdir

@pytest_asyncio.fixture
async def dav_client(temp_download_dir):
    # Создаем экземпляр TransferServer
    server = TransferServer(
        port=0,  # OS выберет свободный порт
        download_dir=temp_download_dir,
        verify_checksum=False
    )
    # Включаем мобильный доступ и генерируем токен
    token = server.enable_mobile_share(ttl_sec=3600)
    
    app = server.app
    # Запускаем тестовый сервер aiohttp
    async with TestClient(TestServer(app)) as client:
        client.token = token
        client.server_instance = server
        yield client

@pytest.mark.asyncio
async def test_webdav_unauthorized(dav_client):
    # Без токена и авторизации должен быть статус 401
    resp = await dav_client.request("OPTIONS", "/webdav")
    assert resp.status == 401
    assert "WWW-Authenticate" in resp.headers

@pytest.mark.asyncio
async def test_webdav_options(dav_client):
    # Запрос OPTIONS с токеном в query
    resp = await dav_client.request("OPTIONS", f"/webdav?token={dav_client.token}")
    assert resp.status == 200
    assert resp.headers["DAV"] == "1, 2"
    assert "PROPFIND" in resp.headers["Allow"]

@pytest.mark.asyncio
async def test_webdav_propfind_root(dav_client):
    # Запрос PROPFIND для корня
    headers = {"Depth": "1"}
    resp = await dav_client.request("PROPFIND", f"/webdav?token={dav_client.token}", headers=headers)
    assert resp.status == 207
    
    body = await resp.text()
    # Проверяем, что вернулся валидный XML
    root = ET.fromstring(body)
    assert "multistatus" in root.tag
    
    # Ищем элементы response
    responses = root.findall(".//{DAV:}response")
    # Должен быть корень + test_file.txt + subfolder
    assert len(responses) >= 3

@pytest.mark.asyncio
async def test_webdav_get_file(dav_client):
    # Запрос GET для существующего файла
    resp = await dav_client.request("GET", f"/webdav/test_file.txt?token={dav_client.token}")
    assert resp.status == 200
    text = await resp.text()
    assert text == "Hello World"

@pytest.mark.asyncio
async def test_webdav_directory_traversal(dav_client):
    # Попытка выйти за пределы директории
    resp = await dav_client.request("GET", f"/webdav/../secret.txt?token={dav_client.token}")
    # Должен быть статус 403 Forbidden или 404
    assert resp.status in (403, 404)
