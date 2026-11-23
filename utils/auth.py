"""Bounded local authentication throttling and safe registration uploads."""
from collections import OrderedDict, deque
from functools import lru_cache
import re
import time
from uuid import uuid4
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from utils.security import hash_password

ROOT = Path(__file__).resolve().parents[1]
UPLOAD_ROOT = ROOT / "static" / "uploads"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def normalize_username(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[+\d()\s.-]+", value):
        return re.sub(r"[()\s.-]", "", value)
    return value


class AttemptLimiter:
    """Process-local bound: deploy a shared limiter for multiple instances."""
    def __init__(self, limit=12, window=60.0, capacity=4096):
        self.limit, self.window, self.capacity = limit, window, capacity
        self.entries = OrderedDict()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        attempts = self.entries.pop(key, deque())
        while attempts and attempts[0] <= now - self.window:
            attempts.popleft()
        allowed = len(attempts) < self.limit
        if allowed:
            attempts.append(now)
        self.entries[key] = attempts
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)
        return allowed


login_limiter = AttemptLimiter()
registration_limiter = AttemptLimiter(limit=6, window=300)


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    return hash_password("nonexistent-account-password")


def file_extension(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return ".pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    raise ValueError("Unsupported document type")


async def save_document(upload, directory: str) -> Path:
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Document exceeds upload limit or is empty")
    extension = file_extension(content)
    folder = UPLOAD_ROOT / directory
    path = folder / (uuid4().hex + extension)
    await run_in_threadpool(folder.mkdir, parents=True, exist_ok=True)
    try:
        await run_in_threadpool(path.write_bytes, content)
    except Exception:
        await run_in_threadpool(path.unlink, missing_ok=True)
        raise
    return path


async def remove_documents(paths):
    for path in paths:
        resolved = path.resolve()
        if resolved.is_relative_to(UPLOAD_ROOT.resolve()):
            await run_in_threadpool(resolved.unlink, missing_ok=True)
