"""A local cache of what the server sends, keyed by checksum, so each model and dataset is transferred once."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .client import ServerClient, sha256_file
from .dataset import unpack


class Cache:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def model(self, client: ServerClient, ref: dict[str, Any], stop: Callable[[], bool]) -> Path:
        """Return the path of the model's main file, downloading the files if they are not cached yet."""
        sha: str = ref["sha256"]
        if ref["layout"] == "file":
            folder = self.root / "files" / sha
            # named as the runtime expects: Ultralytics reads the file type from the name
            target = folder / ref["main"]
            if not target.exists():
                client.download(sha, None, target, stop)
            return target
        folder = self.root / "bundles" / sha
        done = folder / ".verified"
        if not done.exists():
            shutil.rmtree(folder, ignore_errors=True)
            for name in ref["files"]:
                client.download(sha, name, folder / name, stop)
            if bundle_hash(folder) != sha:
                shutil.rmtree(folder, ignore_errors=True)
                raise ValueError("The downloaded model files do not match their checksum. Try again.")
            done.write_text("ok")
        return folder / ref["main"]

    def dataset(self, client: ServerClient, ref: dict[str, Any], stop: Callable[[], bool]) -> Path:
        sha: str = ref["sha256"]
        archive = self.root / "datasets" / f"{sha}.zip"
        if not archive.exists():
            client.download(sha, None, archive, stop)
        return unpack(archive, self.root / "datasets" / sha)


def bundle_hash(folder: Path) -> str:
    """The server's bundle id: SHA-256 over the sorted ``name, file hash`` lines (artifacts.py ``put_directory``)."""
    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    manifest = "".join(f"{p.name}\0{sha256_file(p)}\n" for p in files)
    return hashlib.sha256(manifest.encode()).hexdigest()
