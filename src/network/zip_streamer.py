"""
V-Link - ZIP Streaming
Stream a folder as a ZIP archive over an aiohttp StreamResponse.
"""

import io
import zipfile
from pathlib import Path

from aiohttp import web

MEDIA_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.heic', '.heif',
    '.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.3gp',
    '.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.wma',
}
ZIP_CHUNK_SIZE = 256 * 1024


async def stream_folder_as_zip(folder_path: Path, response: web.StreamResponse) -> int:
    """Build a ZIP archive in memory and stream it in chunks.

    Returns total bytes written to the response.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for file_path in sorted(folder_path.rglob('*')):
            if file_path.is_symlink() or not file_path.is_file():
                continue
            rel = file_path.relative_to(folder_path).as_posix()
            ext = file_path.suffix.lower()
            compress = zipfile.ZIP_STORED if ext in MEDIA_EXTENSIONS else zipfile.ZIP_DEFLATED
            try:
                zf.write(str(file_path), rel, compress_type=compress)
            except (OSError, PermissionError):
                continue

    data = buf.getvalue()
    total = len(data)
    offset = 0
    while offset < total:
        chunk = data[offset:offset + ZIP_CHUNK_SIZE]
        await response.write(chunk)
        offset += len(chunk)
    return total


def estimate_folder_size(folder_path: Path) -> tuple[int, int]:
    """Return (total_bytes, file_count) for non-symlink files in folder."""
    total = 0
    count = 0
    for f in folder_path.rglob('*'):
        if f.is_symlink() or not f.is_file():
            continue
        try:
            total += f.stat().st_size
            count += 1
        except OSError:
            pass
    return total, count
