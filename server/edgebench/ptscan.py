"""Static check of an uploaded PyTorch checkpoint, run before anything loads it.

A ``.pt`` file is a zip holding a pickle, and unpickling can call any importable function. The pickle names every
function it will call as a ``GLOBAL`` opcode, so we read those names without executing anything and refuse the file
if it names anything a model checkpoint has no need for (``os.system``, ``eval``, ``subprocess``,
``ultralytics.utils.checks.check_requirements``, which installs packages, ...). The allowed set comes from real
Ultralytics checkpoints (final and training-run files), not from a guess; see STATE.md.

This narrows what a hostile file can do; it is not a sandbox. The loader still runs in a separate process
(``converter/``).
"""

from __future__ import annotations

import pickletools
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

MAX_PICKLE_BYTES = 256 * 1024 * 1024  # the pickle holds structure only; tensor data lives in separate zip members

# Exact names a checkpoint legitimately uses.
_EXACT = frozenset(
    {
        "__builtin__.set",
        "builtins.set",
        "collections.OrderedDict",
        "_codecs.encode",
        "numpy.dtype",
        "numpy.ndarray",
        "numpy.core.multiarray.scalar",
        "numpy.core.multiarray._reconstruct",
        "numpy._core.multiarray.scalar",
        "numpy._core.multiarray._reconstruct",
        "torch.Size",
        "torch.device",
        "torch._utils._rebuild_parameter",
        "torch._utils._rebuild_tensor_v2",
        "ultralytics.utils.IterableSimpleNamespace",
        "ultralytics.utils.tal.TaskAlignedAssigner",
    }
)
# What a pickle may *call* (REDUCE): data rebuilders and containers only. Measured on real checkpoints (detect
# models, final and training-run files): these ten are all that is ever called. Layer, task-model and loss classes
# appear only as objects to *create* (NEWOBJ does not run __init__); calling one with data from the file is how
# DetectionModel("https://...") would make Ultralytics download and parse a file.
# torch._tensor._rebuild_from_type_v2 is not here: it calls a function the file hands it, which would be a way
# around this list.
_REDUCIBLE = frozenset(
    {
        "__builtin__.set",
        "builtins.set",
        "collections.OrderedDict",
        "_codecs.encode",
        "numpy.dtype",
        "numpy.core.multiarray.scalar",
        "numpy.core.multiarray._reconstruct",
        "numpy._core.multiarray.scalar",
        "numpy._core.multiarray._reconstruct",
        "torch.Size",
        "torch.device",
        "torch._utils._rebuild_parameter",
        "torch._utils._rebuild_tensor_v2",
        "ultralytics.utils.IterableSimpleNamespace",
    }
)
_STORAGE = re.compile(r"torch\.(Float|Half|BFloat16|Double|Long|Int|Short|Char|Byte|Bool)Storage")
_TASK_MODEL = re.compile(
    r"ultralytics\.nn\.tasks\.(Detection|Segmentation|Pose|Classification|OBB|World|RTDETRDetection)Model"
)
_LOSS = re.compile(
    r"ultralytics\.utils\.loss\.\w*Loss"
)  # matched with fullmatch: no ^$ (a trailing newline slips past $)
# Layer classes: a capitalised name in these namespaces is a class (functions there are lower-case and stay refused).
_CLASS_NAMESPACES = ("torch.nn.modules.", "ultralytics.nn.modules.")


@dataclass
class ScanResult:
    ok: bool
    problem: str | None = None
    refused: list[str] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)


def _allowed(name: str) -> bool:
    if name in _EXACT or _STORAGE.fullmatch(name) or _TASK_MODEL.fullmatch(name) or _LOSS.fullmatch(name):
        return True
    return name.startswith(_CLASS_NAMESPACES) and name.rsplit(".", 1)[-1][:1].isupper()


class _Refused(Exception):
    """The file cannot be read as a PyTorch checkpoint; the message is meant for the person who uploaded it."""


class _Global(str):
    """A global the pickle named, as it sits on the simulated stack, so a later REDUCE is judged by what it calls."""


_BANNED_OPCODES = ("STACK_GLOBAL", "INST", "OBJ", "EXT1", "EXT2", "EXT4")
MAX_PROTOCOL = 2  # torch.save's default. Dotted-name resolution in GLOBAL starts at protocol 4; 3 has no use either.
_MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")  # no dots: one attribute, not a path
_GETS = ("GET", "BINGET", "LONG_BINGET")
_PUTS = ("PUT", "BINPUT", "LONG_BINPUT")


def _walk(data: bytes) -> tuple[set[str], list[str]]:
    """Walk one pickle's opcodes without running it. Returns (every global named, every callee a REDUCE would call).

    The stack is simulated the way ``pickletools.dis`` does, remembering which entries are globals. That is how a
    global that is only *created* (NEWOBJ, which does not run ``__init__``) is told apart from one that is *called*
    with data from the file (REDUCE): calling ``DetectionModel("https://...")`` makes Ultralytics download a file
    and parse it as a model.
    """
    seen: set[str] = set()
    called: list[str] = []
    stack: list[object] = []
    memo: dict[int, object] = {}
    for op, arg, _pos in pickletools.genops(data):
        if op.name == "PROTO" and isinstance(arg, int) and arg > MAX_PROTOCOL:
            raise _Refused(
                f"The checkpoint uses pickle protocol {arg}; PyTorch saves models with {MAX_PROTOCOL}. "
                "Re-save the model with torch.save and upload that file."
            )
        if op.name in _BANNED_OPCODES:
            raise _Refused(
                f"The checkpoint uses the pickle instruction {op.name}, which PyTorch's own saver does not "
                "produce for models. Re-save the model with torch.save and upload that file."
            )
        after: list[Any] = list(op.stack_after)
        if op.name == "GLOBAL":
            module, _, name = str(arg).partition(" ")
            # A dotted *name* is an attribute path that protocol 4 resolves step by step, so "numpy.f2py.x.Popen"
            # can be made to end in a capitalised word yet reach subprocess.Popen. A model never needs one.
            if not (_MODULE.fullmatch(module) and _NAME.fullmatch(name)):
                raise _Refused(
                    f"The checkpoint refers to {module}.{name} by a dotted path, which a model never does "
                    "and a hostile file uses to reach code it should not."
                )
            seen.add(f"{module}.{name}")
            after = [_Global(f"{module}.{name}")]
        if op.name == "REDUCE":
            callee = stack[-2]  # REDUCE pops (callable, args)
            called.append(str(callee) if isinstance(callee, _Global) else "a callable the file computes")
        numtopop = len(op.stack_before)
        if pickletools.markobject in op.stack_before or (
            op.name == "POP" and stack and stack[-1] is pickletools.markobject
        ):
            while stack[-1] is not pickletools.markobject:  # drop everything above the mark, then the mark
                stack.pop()
            stack.pop()
            numtopop = op.stack_before.index(pickletools.markobject) if pickletools.markobject in op.stack_before else 0
        if op.name in _PUTS:
            memo[cast(int, arg)] = stack[-1]
        elif op.name == "MEMOIZE":
            memo[len(memo)] = stack[-1]
        elif op.name in _GETS:
            after = [memo[cast(int, arg)]]
        if numtopop:
            del stack[-numtopop:]
        stack.extend(after)
    return seen, called


def _read_pickles(path: Path) -> tuple[set[str], list[str]]:
    """Everything the checkpoint's pickles name and call. Reads opcodes only; nothing is executed."""
    if not zipfile.is_zipfile(path):
        raise _Refused("This is not a PyTorch checkpoint (a .pt file is a zip archive; this file is not).")
    seen: set[str] = set()
    called: list[str] = []
    with zipfile.ZipFile(path) as archive:
        pickles = [i for i in archive.infolist() if i.filename.endswith("data.pkl")]
        if not pickles:
            raise _Refused("This zip archive has no data.pkl, so it is not a PyTorch checkpoint.")
        for info in pickles:
            if info.file_size > MAX_PICKLE_BYTES:
                raise _Refused("The checkpoint's pickle is unreasonably large.")
            names, calls = _walk(archive.read(info))
            seen |= names
            called += calls
    return seen, called


def scan_checkpoint(path: Path) -> ScanResult:
    """Read the pickle(s) in a checkpoint and list what they would name and call. Never executes any of it."""
    try:
        seen, called = _read_pickles(path)
    except _Refused as exc:
        return ScanResult(False, str(exc))
    except Exception as exc:
        # Hostile or damaged input can make zipfile and pickletools raise almost anything (an encrypted member, an
        # unsupported compression, a bad length...). Whatever it is, the answer is "refused", never a crash.
        return ScanResult(False, f"The checkpoint could not be read safely ({type(exc).__name__}: {exc}).")
    refused = sorted(n for n in seen if not _allowed(n))
    if refused:
        shown = ", ".join(refused[:5]) + (f" and {len(refused) - 5} more" if len(refused) > 5 else "")
        return ScanResult(
            False,
            f"The checkpoint refers to code a model never needs ({shown}), so it was not opened. "
            "Only upload checkpoints you trained or got from a source you trust.",
            refused=refused,
            seen=seen,
        )
    forbidden = sorted({c for c in called if c not in _REDUCIBLE})
    if forbidden:
        shown = ", ".join(forbidden[:5]) + (f" and {len(forbidden) - 5} more" if len(forbidden) > 5 else "")
        return ScanResult(
            False,
            f"The checkpoint calls {shown} with data from the file. A model's pickle only rebuilds tensors and "
            "containers; calling anything else is how a hostile file makes the reader run code or fetch files.",
            refused=forbidden,
            seen=seen,
        )
    return ScanResult(True, seen=seen)
