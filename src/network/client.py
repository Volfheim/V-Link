"""
V-Link - HTTP Client
Adaptive async client for high-speed local transfers.
"""

import asyncio
import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import aiofiles
import aiohttp
import lz4.frame
from cryptography.fernet import Fernet


CHUNK_SIZE = 1024 * 1024  # 1 MB
MAX_RETRIES = 3
RETRY_DELAY = 1.0

_COMPRESSIBLE_EXT = {
    '.txt', '.csv', '.json', '.xml', '.yaml', '.yml', '.log', '.md',
    '.py', '.js', '.ts', '.html', '.css', '.ini', '.cfg', '.toml', '.sql'
}

_BINARY_EXT = {
    '.zip', '.rar', '.7z', '.gz', '.xz', '.bz2', '.mp4', '.mkv', '.avi',
    '.jpg', '.jpeg', '.png', '.webp', '.mp3', '.flac', '.pdf', '.iso', '.mov'
}


@dataclass
class TransferPlan:
    chunk_size: int
    parallel_uploads: int
    use_lz4: bool


class TransferClient:
    """HTTP client with adaptive transfer planning and silent auto-benchmark."""

    def __init__(
        self,
        auth_token: str = "",
        base_chunk_size_bytes: int = CHUNK_SIZE,
        verify_checksum: bool = False,
        auto_tune: bool = True,
        adaptive_profile: Optional[dict] = None,
        enable_encryption: bool = False,
        compatibility_mode: bool = False,
    ):
        self.auth_token = (auth_token or "").strip()
        self.base_chunk_size_bytes = max(64 * 1024, int(base_chunk_size_bytes))
        self.verify_checksum = verify_checksum
        self.auto_tune = auto_tune
        self.enable_encryption = enable_encryption
        self.compatibility_mode = compatibility_mode
        self._cipher: Optional[Fernet] = None
        if self.enable_encryption and self.auth_token:
            key = hashlib.sha256(self.auth_token.encode("utf-8")).digest()
            import base64
            self._cipher = Fernet(base64.urlsafe_b64encode(key))

        self._profile: Dict[str, float | int | bool] = {
            'calibrated': False,
            'ema_mbps': 0.0,
            'samples': 0,
            'best_chunk': int(self.base_chunk_size_bytes),
            'prefer_parallel': 1,
            'lz4_score': 0.0,
        }
        if isinstance(adaptive_profile, dict):
            self._profile.update({k: v for k, v in adaptive_profile.items() if k in self._profile})

        self.session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

        self.on_transfer_start: Optional[Callable] = None
        self.on_transfer_progress: Optional[Callable] = None
        self.on_transfer_complete: Optional[Callable] = None
        self.on_transfer_error: Optional[Callable] = None

    def get_adaptive_profile(self) -> dict:
        return dict(self._profile)

    async def start(self):
        await self._ensure_session()

    async def _ensure_session(self):
        async with self._session_lock:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(total=None, connect=20, sock_read=None)
                connector = aiohttp.TCPConnector(
                    limit=12 if self.compatibility_mode else 16,
                    force_close=self.compatibility_mode,
                    enable_cleanup_closed=True,
                )
                self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)

    async def stop(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def ping(self, host: str, port: int, timeout: float = 3.0, retries: int = 2) -> bool:
        await self._ensure_session()

        for attempt in range(retries):
            try:
                ping_timeout = aiohttp.ClientTimeout(total=timeout)
                async with self.session.get(f"http://{host}:{port}/ping", timeout=ping_timeout) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                if attempt < retries - 1:
                    await asyncio.sleep(0.2)
        return False

    async def send_file(
        self,
        filepath: str,
        host: str,
        port: int,
        plan: Optional[TransferPlan] = None,
        target_name: str = "",
    ) -> str:
        await self._ensure_session()

        transfer_id = str(uuid.uuid4())[:8]
        filename = os.path.basename(filepath)

        if not os.path.exists(filepath):
            error = f"File not found: {filepath}"
            if self.on_transfer_error:
                self.on_transfer_error(transfer_id, error)
            raise FileNotFoundError(error)

        total_size = os.path.getsize(filepath)
        use_plan = plan or TransferPlan(self.base_chunk_size_bytes, 1, False)

        if self.on_transfer_start:
            self.on_transfer_start(transfer_id, filename, total_size, True)

        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                result_id, elapsed = await self._send_file_attempt(
                    transfer_id,
                    filepath,
                    filename,
                    total_size,
                    host,
                    port,
                    use_plan,
                    target_name=target_name,
                )
                self._learn_from_transfer(total_size, elapsed, use_plan)
                return result_id
            except aiohttp.ClientError as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    await self.stop()
                    await self._ensure_session()
                    # Auto-fallback: switch to conservative plan for retries
                    # on nonstandard networks where full-speed failed.
                    if self.compatibility_mode and use_plan.chunk_size > 512 * 1024:
                        use_plan = TransferPlan(chunk_size=512 * 1024, parallel_uploads=1, use_lz4=False)
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            except Exception as e:
                last_error = e
                break

        error_msg = f"Failed after {MAX_RETRIES} attempts: {last_error}"
        if self.on_transfer_error:
            self.on_transfer_error(transfer_id, error_msg)
        raise Exception(error_msg)

    async def _send_file_attempt(
        self,
        transfer_id: str,
        filepath: str,
        filename: str,
        total_size: int,
        host: str,
        port: int,
        plan: TransferPlan,
        target_name: str = "",
    ) -> tuple[str, float]:
        file_hash = await self._hash_file(filepath, plan.chunk_size) if self.verify_checksum else None
        start_time = time.time()

        async def file_sender():
            sent = 0
            local_start = time.time()
            last_update = local_start

            compressor = lz4.frame.LZ4FrameCompressor() if plan.use_lz4 else None
            if compressor:
                header = compressor.begin()
                if header:
                    yield header

            async with aiofiles.open(filepath, 'rb') as f:
                while True:
                    chunk = await f.read(plan.chunk_size)
                    if not chunk:
                        break

                    payload = compressor.compress(chunk) if compressor else chunk
                    if payload:
                        if self._cipher:
                            token = self._cipher.encrypt(payload)
                            frame = len(token).to_bytes(4, "big") + token
                            yield frame
                        else:
                            yield payload
                    sent += len(chunk)

                    now = time.time()
                    if now - last_update > 0.15:
                        elapsed = now - local_start
                        speed = sent / elapsed if elapsed > 0 else 0
                        if self.on_transfer_progress:
                            self.on_transfer_progress(transfer_id, sent, speed)
                        last_update = now

            if compressor:
                tail = compressor.flush()
                if tail:
                    if self._cipher:
                        token = self._cipher.encrypt(tail)
                        frame = len(token).to_bytes(4, "big") + token
                        yield frame
                    else:
                        yield tail

        headers = {
            'X-Filename': filename,
            'X-Filesize': str(total_size),
            'X-Transfer-ID': transfer_id,
            'Content-Type': 'application/octet-stream',
        }
        if plan.use_lz4:
            headers['X-Content-Encoding'] = 'lz4-stream'
        if self._cipher:
            headers['X-Encrypted'] = 'fernet-frame'
        if file_hash:
            headers['X-File-SHA256'] = file_hash
        if self.auth_token:
            # Stable shared token for secure mode without hostname coupling.
            derived = hashlib.sha256(self.auth_token.encode("utf-8")).hexdigest()
            headers['X-Auth-Token'] = derived

        url = f"http://{host}:{port}/upload"
        request_timeout = aiohttp.ClientTimeout(
            total=None,
            connect=12 if self.compatibility_mode else 8,
            sock_connect=12 if self.compatibility_mode else 8,
            # Keep read timeout open for long/slow links; connectivity is validated by ping/connect.
            sock_read=None,
        )

        async with self.session.post(url, data=file_sender(), headers=headers, timeout=request_timeout) as resp:
            if resp.status == 200:
                if self.on_transfer_complete:
                    self.on_transfer_complete(transfer_id, filepath)
                return transfer_id, max(0.001, time.time() - start_time)

            error = await resp.text()
            raise aiohttp.ClientResponseError(
                resp.request_info,
                resp.history,
                status=resp.status,
                message=error,
            )

    async def send_files(self, filepaths: List[str], host: str, port: int, target_name: str = ""):
        plan = await self._build_plan(filepaths)

        if plan.parallel_uploads <= 1:
            for filepath in filepaths:
                await self.send_file(filepath, host, port, plan=plan, target_name=target_name)
            return

        sem = asyncio.Semaphore(plan.parallel_uploads)

        async def send_one(path: str):
            async with sem:
                await self.send_file(path, host, port, plan=plan, target_name=target_name)

        await asyncio.gather(*(send_one(filepath) for filepath in filepaths))

    async def _build_plan(self, filepaths: List[str]) -> TransferPlan:
        if not self.auto_tune:
            return TransferPlan(self.base_chunk_size_bytes, 1, False)

        existing = [p for p in filepaths if os.path.exists(p)]
        if not existing:
            return TransferPlan(self.base_chunk_size_bytes, 1, False)

        if not bool(self._profile.get('calibrated', False)):
            await self._run_silent_calibration(existing)

        sizes = [os.path.getsize(p) for p in existing]
        total = sum(sizes)
        avg = total / max(1, len(sizes))

        ema_mbps = float(self._profile.get('ema_mbps', 0.0) or 0.0)
        best_chunk = int(self._profile.get('best_chunk', self.base_chunk_size_bytes) or self.base_chunk_size_bytes)

        if avg >= 1024 * 1024 * 512:
            chunk_size = max(best_chunk, 8 * 1024 * 1024)
        elif avg >= 1024 * 1024 * 128:
            chunk_size = max(best_chunk, 4 * 1024 * 1024)
        elif avg <= 1024 * 1024 * 4:
            chunk_size = min(best_chunk, 1024 * 1024)
        else:
            chunk_size = best_chunk

        if ema_mbps > 120:
            chunk_size = min(8 * 1024 * 1024, max(chunk_size, 4 * 1024 * 1024))
        elif ema_mbps < 40 and avg < 1024 * 1024 * 32:
            chunk_size = min(chunk_size, 1024 * 1024)

        chunk_size = max(64 * 1024, min(8 * 1024 * 1024, int(chunk_size)))

        cpu = max(2, os.cpu_count() or 2)
        if len(existing) == 1:
            parallel = 1
        elif avg < 1024 * 1024 * 8:
            parallel = min(4, max(2, cpu // 2))
        elif avg < 1024 * 1024 * 64:
            parallel = min(3, max(1, cpu // 3))
        else:
            parallel = 1

        preferred_parallel = int(self._profile.get('prefer_parallel', parallel) or parallel)
        parallel = max(1, min(4, max(parallel, preferred_parallel if avg < 1024 * 1024 * 32 else 1)))

        compressible = sum(1 for p in existing if os.path.splitext(p)[1].lower() in _COMPRESSIBLE_EXT)
        compressed_like = sum(1 for p in existing if os.path.splitext(p)[1].lower() in _BINARY_EXT)
        lz4_score = float(self._profile.get('lz4_score', 0.0) or 0.0)

        use_lz4 = False
        if not self.enable_encryption:
            if compressible > compressed_like and avg < 1024 * 1024 * 64 and total > 1024 * 1024 * 8:
                use_lz4 = lz4_score >= -0.05

        return TransferPlan(chunk_size=chunk_size, parallel_uploads=parallel, use_lz4=use_lz4)

    async def _run_silent_calibration(self, filepaths: List[str]):
        """Quick CPU/compression calibration on first transfer, without UI."""
        self._profile['calibrated'] = True

        sample_path = filepaths[0]
        sample_size = min(4 * 1024 * 1024, os.path.getsize(sample_path))
        if sample_size <= 0:
            return

        try:
            async with aiofiles.open(sample_path, 'rb') as f:
                sample = await f.read(sample_size)
            if not sample:
                return

            rounds = 3
            t0 = time.perf_counter()
            out = b''
            for _ in range(rounds):
                out = lz4.frame.compress(sample)
            dt = max(1e-6, time.perf_counter() - t0)
            comp_mbps = (len(sample) * rounds) / dt / (1024 * 1024)
            ratio = len(out) / max(1, len(sample))

            self._profile['lz4_score'] = (1.0 - ratio) if comp_mbps > 300 else -0.2
            self._profile['best_chunk'] = 4 * 1024 * 1024 if comp_mbps > 500 else 2 * 1024 * 1024
            self._profile['prefer_parallel'] = 2 if os.cpu_count() and os.cpu_count() >= 6 else 1
        except Exception:
            self._profile['best_chunk'] = self.base_chunk_size_bytes
            self._profile['prefer_parallel'] = 1
            self._profile['lz4_score'] = -0.1

    def _learn_from_transfer(self, size_bytes: int, elapsed_sec: float, plan: TransferPlan):
        mbps = (size_bytes / (1024 * 1024)) / max(0.001, elapsed_sec)
        old_ema = float(self._profile.get('ema_mbps', 0.0) or 0.0)

        ema = mbps if old_ema <= 0 else (old_ema * 0.7 + mbps * 0.3)
        self._profile['ema_mbps'] = round(ema, 2)

        samples = int(self._profile.get('samples', 0) or 0) + 1
        self._profile['samples'] = samples

        best_chunk = int(self._profile.get('best_chunk', self.base_chunk_size_bytes) or self.base_chunk_size_bytes)
        if mbps >= old_ema * 0.95 or old_ema == 0:
            self._profile['best_chunk'] = int(plan.chunk_size)
            self._profile['prefer_parallel'] = int(plan.parallel_uploads)
        else:
            self._profile['best_chunk'] = int((best_chunk + plan.chunk_size) / 2)

        if plan.use_lz4:
            score = float(self._profile.get('lz4_score', 0.0) or 0.0)
            self._profile['lz4_score'] = (score * 0.8) + (0.2 if mbps >= old_ema else -0.2)

    async def _hash_file(self, filepath: str, chunk_size: int) -> str:
        import hashlib

        digest = hashlib.sha256()
        async with aiofiles.open(filepath, 'rb') as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
