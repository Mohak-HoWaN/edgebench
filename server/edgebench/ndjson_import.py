"""Read an NDJSON dataset (the Ultralytics format) into ordinary dataset files.

One JSON object per line. The first describes the dataset (``class_names``). Every ``image`` line gives a file name,
optionally a ``url`` to fetch the picture from, a ``split`` and the boxes as ``annotations.boxes``:
``[class, centre x, centre y, width, height]`` relative to the picture. Pictures uploaded with the file are matched by
name; the others are fetched from their ``url``.

The file becomes the layout the YOLO reader already understands (``images/<split>/name.jpg``,
``labels/<split>/name.txt``, ``data.yaml``), so everything after this step is the same as for any other dataset.

Fetching an address named in a file someone else wrote is a risk: the server could be made to look at its own network.
So only http and https are followed, every address (and every redirect) must be public, a picture may be at most
``MAX_IMAGE_BYTES`` and the total is capped. A trusted image server on your own network can be allowed with the
``allow_private_ndjson_urls`` setting. Known limit: the address is checked, then connected to by name, so a hostile DNS
server could still answer differently the second time.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

from sqlmodel import Session

from .artifacts import sha256_file
from .dataset_import import IMAGE_EXTENSIONS, ImportProblem
from .model_jobs import register_artifact
from .services import Services
from .worker import JobContext

NDJSON_SUFFIXES = {".ndjson", ".jsonl"}
MAX_IMAGE_BYTES = 50 * 1024**2
MAX_REDIRECTS = 3
FETCH_TIMEOUT = 30.0
REDIRECTS = (301, 302, 303, 307, 308)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: Any, **__: Any) -> None:  # we follow redirects ourselves, checking each address
        return None


def _check_public(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise ImportProblem(f"The address {host} could not be found.") from None
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ImportProblem(
                f"{host} is not a public address, so its picture was not fetched. A trusted image server on your own "
                "network can be allowed with the allow_private_ndjson_urls setting."
            )


def fetch_url(url: str, allow_private: bool = False) -> bytes:
    """Download one picture, refusing non-public addresses and anything over ``MAX_IMAGE_BYTES``."""
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(MAX_REDIRECTS + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ImportProblem(f"{url[:80]} is not an http or https address.")
        if not allow_private:
            _check_public(parts.hostname)
        request = urllib.request.Request(url, headers={"User-Agent": "EdgeBench"})
        try:
            with opener.open(request, timeout=FETCH_TIMEOUT) as response:
                data: bytes = response.read(MAX_IMAGE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in REDIRECTS and exc.headers.get("Location"):
                url = urllib.parse.urljoin(url, exc.headers["Location"])
                continue
            raise ImportProblem(f"{parts.hostname} answered {exc.code} for a picture.") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ImportProblem(
                f"A picture could not be fetched from {parts.hostname} ({type(exc).__name__})."
            ) from None
        if len(data) > MAX_IMAGE_BYTES:
            raise ImportProblem(f"A picture at {parts.hostname} is larger than {MAX_IMAGE_BYTES // 1024**2} MB.")
        return data
    raise ImportProblem("A picture address redirected too many times.")


def _records(sha: str, s: Services) -> tuple[dict[int, str], list[dict[str, Any]]]:
    names: dict[int, str] = {}
    images: list[dict[str, Any]] = []
    with s.store.path(sha).open(encoding="utf-8", errors="replace") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                raise ImportProblem(f"Line {number} of the NDJSON file is not valid JSON.") from None
            if not isinstance(record, dict):
                raise ImportProblem(f"Line {number} of the NDJSON file is not a JSON object.")
            if record.get("type") == "dataset" or ("class_names" in record and "file" not in record):
                raw = record.get("class_names") or {}
                items = raw.items() if isinstance(raw, dict) else enumerate(raw)
                names = {int(k): str(v) for k, v in items}
            elif record.get("type", "image") == "image":
                images.append(record)
    if not images:
        raise ImportProblem("The NDJSON file has no image lines.")
    return names, images


def _store(s: Services, session: Session, data: bytes) -> tuple[str, int]:
    tmp = s.store.tmp / f"ndjson-{os.getpid()}-{len(data)}"
    tmp.write_bytes(data)
    sha = sha256_file(tmp)
    s.store.put_file(tmp, sha)
    register_artifact(session, sha, "file", len(data))
    return sha, len(data)


def _label_text(boxes: Any, where: str) -> bytes:
    lines = []
    for box in boxes:
        if not isinstance(box, list) or len(box) != 5:
            raise ImportProblem(f"{where}: a box must be [class, x, y, width, height].")
        lines.append(f"{int(box[0])} " + " ".join(f"{float(v):.6f}" for v in box[1:]))
    return ("\n".join(lines) + ("\n" if lines else "")).encode()


def _image_name(rec: dict[str, Any], number: int) -> str:
    url = str(rec.get("url") or "")
    name = PurePosixPath(str(rec.get("file") or urllib.parse.urlsplit(url).path)).name
    if not name or PurePosixPath(name).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ImportProblem(
            f"Picture {number} has no usable file name ({name or 'none'}); it needs a .jpg, .png or similar."
        )
    return name


def expand_ndjson(
    s: Services, ndjson_sha: str, uploaded: list[dict[str, Any]], ctx: JobContext
) -> tuple[list[dict[str, Any]], set[str]]:
    """Turn one NDJSON file into dataset files. ``uploaded``: the pictures sent along. Returns (files, paths used)."""
    names, records = _records(ndjson_sha, s)
    if len(records) > s.settings.max_dataset_files:
        raise ImportProblem(f"The file lists {len(records)} pictures; the limit is {s.settings.max_dataset_files}.")
    by_name = {
        PurePosixPath(e["path"]).name: e
        for e in uploaded
        if PurePosixPath(e["path"]).suffix.lower() in IMAGE_EXTENSIONS
    }
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    taken: set[str] = set()
    missing: list[str] = []
    fetched = 0
    with Session(s.engine) as session:
        for n, rec in enumerate(records):
            ctx.progress(0.3 * n / len(records), f"Reading picture {n + 1} of {len(records)}")
            name = _image_name(rec, n + 1)
            split = str(rec.get("split") or "train")
            image_path = f"images/{split if split.isalnum() else 'train'}/{name}"
            if image_path in taken:
                image_path = image_path.replace(f"/{name}", f"/{n}_{name}")
            taken.add(image_path)
            if name in by_name:
                entry = by_name[name]
                used.add(entry["path"])
                sha, size = entry["sha256"], int(entry["size"])
            elif rec.get("url"):
                data = fetch_url(str(rec["url"]), s.settings.allow_private_ndjson_urls)
                fetched += len(data)
                if fetched > s.settings.max_dataset_unpacked_bytes:
                    raise ImportProblem("The pictures to fetch add up to more than the size limit.")
                sha, size = _store(s, session, data)
            else:
                missing.append(name)
                continue
            out.append({"path": image_path, "sha256": sha, "size": size})
            if rec.get("annotations") is not None:
                text = _label_text(rec["annotations"].get("boxes", []), name)
                label_sha, label_size = _store(s, session, text)
                label_path = "labels/" + image_path.removeprefix("images/").rsplit(".", 1)[0] + ".txt"
                out.append({"path": label_path, "sha256": label_sha, "size": label_size})
        if missing:
            shown = ", ".join(missing[:3]) + (" and more" if len(missing) > 3 else "")
            raise ImportProblem(
                f"{len(missing)} picture(s) in the NDJSON file were not sent with it and have no address: {shown}."
            )
        if names:
            ordered = [names.get(i, f"class_{i}") for i in range(max(names) + 1)]
            yaml_text = "names:\n" + "".join(f"  {i}: {json.dumps(n)}\n" for i, n in enumerate(ordered))
            sha, size = _store(s, session, yaml_text.encode())
            out.append({"path": "data.yaml", "sha256": sha, "size": size})
        session.commit()
    return out, used


def is_ndjson(path: str) -> bool:
    return Path(path).suffix.lower() in NDJSON_SUFFIXES
