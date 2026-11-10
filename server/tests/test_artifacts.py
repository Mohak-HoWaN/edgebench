from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from edgebench.artifacts import ArtifactStore, TooLarge


async def chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


def test_a_stream_is_hashed_while_it_is_written(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    tmp, sha, size = asyncio.run(store.save_stream(chunks(b"hello ", b"world"), 100))
    assert sha == hashlib.sha256(b"hello world").hexdigest() and size == 11
    assert tmp.read_bytes() == b"hello world"


def test_a_stream_over_the_limit_is_stopped_and_leaves_no_file(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(TooLarge):
        asyncio.run(store.save_stream(chunks(b"a" * 60, b"b" * 60), 100))
    assert list(store.tmp.iterdir()) == []


def test_the_same_file_is_stored_once(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    first, sha, _ = asyncio.run(store.save_stream(chunks(b"model bytes"), 100))
    stored = store.put_file(first, sha)
    second, sha2, _ = asyncio.run(store.save_stream(chunks(b"model bytes"), 100))
    assert sha2 == sha and store.put_file(second, sha2) == stored
    assert stored == store.path(sha) and stored.read_bytes() == b"model bytes"
    assert list(store.tmp.iterdir()) == [], "the duplicate upload's temp copy was dropped"


def test_a_bundle_is_identified_by_its_files_and_stored_once(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    def make(weights: bytes) -> Path:
        d = store.new_workdir()
        (d / "model.xml").write_text("<net/>")
        (d / "model.bin").write_bytes(weights)
        return d

    sha, size = store.put_directory(make(b"w" * 50))
    again, size2 = store.put_directory(make(b"w" * 50))
    different, _ = store.put_directory(make(b"x" * 50))
    assert again == sha and size2 == size == len("<net/>") + 50
    assert different != sha, "different weights make a different bundle"
    assert sorted(p.name for p in store.path(sha).iterdir()) == ["model.bin", "model.xml"]
    assert list(store.tmp.iterdir()) == [], "the duplicate workdir was removed"


def test_a_bundle_with_a_subfolder_is_refused(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    d = store.new_workdir()
    (d / "inner").mkdir()
    with pytest.raises(ValueError, match="flat"):
        store.put_directory(d)


def test_leftovers_from_a_killed_run_are_cleared_at_start_up_but_stored_artifacts_are_not(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    tmp, sha, _ = asyncio.run(store.save_stream(chunks(b"keep me"), 100))
    kept = store.put_file(tmp, sha)
    (store.tmp / "upload-half-done").write_bytes(b"partial")
    (store.tmp / "work-half-done").mkdir()
    (store.tmp / "work-half-done" / "model.onnx").write_bytes(b"partial")
    ArtifactStore(tmp_path).clean_tmp()
    assert list(store.tmp.iterdir()) == [] and kept.read_bytes() == b"keep me"
