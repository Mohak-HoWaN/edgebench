import getpass
import os
import sys
from pathlib import Path

import uvicorn

from .auth import MIN_PASSWORD, Auth, check_bind
from .config import find_converter_python, get_settings

if __name__ == "__main__":
    # Started by hand (not by scripts/start-server.ps1): still find the converter environment, unless one was named.
    if "EDGEBENCH_CONVERTER_PYTHON" not in os.environ and (
        found := find_converter_python(Path(__file__).resolve().parents[2])
    ):
        os.environ["EDGEBENCH_CONVERTER_PYTHON"] = str(found)
    s = get_settings()
    auth = Auth(s.data_dir)
    if sys.argv[1:] == ["set-password"]:
        first = getpass.getpass(f"New owner password (at least {MIN_PASSWORD} characters): ")
        if first != getpass.getpass("Again: "):
            raise SystemExit("The two passwords differ; nothing was changed.")
        try:
            auth.set_password(first)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        raise SystemExit(f"Password saved in {auth.file}. A running server asks for it from now on.")
    try:
        check_bind(s.host, auth)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    uvicorn.run("edgebench.main:app", host=s.host, port=s.port, log_config=None)
