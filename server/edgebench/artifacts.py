"""Content-addressed artifact store (ADR 0002).

An uploaded checkpoint is a file at ``<root>/<sha[:2]>/<sha>``. A converted model is a *bundle*: a folder of files
at a path of the same kind, named by the SHA-256 of the sorted ``name, file-hash`` list, so an OpenVINO ``.xml`` +
``.bin`` pair is one artifact. Everything is written under ``<root>/tmp`` first and moved into place with one
rename, so a crash leaves nothing half-written.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import uuid
from collections.abc import AsyncIterable
from pathlib import Path
from typing import BinaryIO


class TooLarge(Exception):
    """The upload went over the size limit."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.tmp = root / "tmp"
        self.tmp.mkdir(parents=True, exist_ok=True)

    def clean_tmp(self) -> None:
        """Remove what an earlier run left half-done. Call at start-up, before any job runs."""
        for entry in self.tmp.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)

    def path(self, sha: str) -> Path:
        return self.root / sha[:2] / sha

    def exists(self, sha: str | None) -> bool:
        return bool(sha) and self.path(sha).exists()  # type: ignore[arg-type]

    def new_workdir(self) -> Path:
        d = self.tmp / f"work-{uuid.uuid4().hex}"
        d.mkdir()
        return d

    async def save_stream(self, chunks: AsyncIterable[bytes], max_bytes: int) -> tuple[Path, str, int]:
        """Write an upload to a temp file while hashing it. Returns (temp path, sha256, size)."""
        tmp = self.tmp / f"upload-{uuid.uuid4().hex}"
        h, size = hashlib.sha256(), 0

        def write(f: BinaryIO, chunk: bytes) -> None:
            h.update(chunk)
            f.write(chunk)

        def finish(f: BinaryIO) -> None:
            f.flush()
            os.fsync(f.fileno())

        try:
            with tmp.open("wb") as f:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        raise TooLarge
                    # Hashing and writing a big upload would otherwise stall every other request on the event loop.
                    await asyncio.to_thread(write, f, chunk)
                await asyncio.to_thread(finish, f)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return tmp, h.hexdigest(), size

    def put_file(self, tmp: Path, sha: str) -> Path:
        """Move a temp file into the store. If the same content is already there, the temp copy is dropped."""
        target = self.path(sha)
        if target.exists():
            tmp.unlink(missing_ok=True)
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, target)
        return target

    def put_directory(self, src: Path) -> tuple[str, int]:
        """Store a folder of files as a bundle. Returns (bundle sha256, total size in bytes)."""
        files = sorted(p for p in src.iterdir())
        if any(not p.is_file() for p in files):
            raise ValueError("a bundle holds flat files only")
        manifest = "".join(f"{p.name}\0{sha256_file(p)}\n" for p in files)
        sha = hashlib.sha256(manifest.encode()).hexdigest()
        size = sum(p.stat().st_size for p in files)
        target = self.path(sha)
        if target.exists():
            shutil.rmtree(src, ignore_errors=True)
            return sha, size
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, target)
        return sha, size
