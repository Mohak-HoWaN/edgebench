"""The agent as a source package the server hands out: ``pip install <server>/agent/package/<file>``.

Built in memory from the repository's ``agent/`` folder (pure Python: no wheel tooling needed); the bytes are the
same on every call. It holds no secrets: the agent is open source and the enrolment token travels separately.
"""

from __future__ import annotations

import gzip
import io
import tarfile
import tomllib
from pathlib import Path

INCLUDE = ("pyproject.toml", "README.md")


def build(agent_dir: Path) -> tuple[str, bytes] | None:
    """(file name, bytes) of the agent's sdist, or None when this server has no agent source (the Docker image)."""
    try:
        project = tomllib.loads((agent_dir / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    except (OSError, KeyError, ValueError):
        return None
    root = f"{project['name'].replace('-', '_')}-{project['version']}"
    files = [agent_dir / name for name in INCLUDE if (agent_dir / name).is_file()]
    files += sorted(p for p in (agent_dir / "edgebench_agent").rglob("*.py") if "__pycache__" not in p.parts)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as zipped, tarfile.open(fileobj=zipped, mode="w") as tar:
        for path in files:
            data = path.read_bytes()
            info = tarfile.TarInfo(f"{root}/{path.relative_to(agent_dir).as_posix()}")
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    return f"{root}.tar.gz", buffer.getvalue()
