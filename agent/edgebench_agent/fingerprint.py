"""What this machine is, recorded with every device so a result can be tied to the hardware that produced it."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import struct
import subprocess
from pathlib import Path
from typing import Any

from .runtimes import package_versions


def _pi_model() -> str | None:
    try:
        text = Path("/proc/device-tree/model").read_text(encoding="utf-8", errors="replace").strip("\x00\n ")
    except OSError:
        return None
    return text if "raspberry pi" in text.lower() else None


def _cpu_name() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith(("model name", "hardware")):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _gpu() -> str | None:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out.splitlines()[0] if out else None


def collect() -> dict[str, Any]:
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "bits": struct.calcsize("P") * 8,  # a 32-bit Pi OS reports armv8l and cannot run the runtimes
        "cpu": _cpu_name(),
        "python": platform.python_version(),
        "logical_cores": os.cpu_count(),
        "pi_model": _pi_model(),
        "gpu": _gpu(),
        "packages": package_versions(),
    }
    try:
        import psutil

        info["physical_cores"] = psutil.cpu_count(logical=False)
        info["ram_bytes"] = psutil.virtual_memory().total
    except ImportError:
        info["physical_cores"], info["ram_bytes"] = None, None
    return info
