from __future__ import annotations

import io
import os
import pickle
import re
import subprocess
import sys
import time
import zipfile
from collections import OrderedDict
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from edgebench.config import Settings
from edgebench.converter_client import ConverterInfo
from edgebench.main import create_app
from edgebench.matrix import OPS
from edgebench.models import Variant
from edgebench.worker import Worker

FAKE = Path(__file__).parent / "fake_converter"
ALL_OPS = [op.name for op in OPS]
FINAL = {"ready", "failed", "unavailable", "cancelled"}


def checkpoint_bytes(extra: Any = None) -> bytes:
    """A file the scanner accepts: a zip holding a pickle that only uses allowed names."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # A fixed timestamp: zips record the time, and two uploads of "the same file" must really be the same bytes.
        entry = zipfile.ZipInfo("model/data.pkl", date_time=(2026, 1, 1, 0, 0, 0))
        z.writestr(entry, pickle.dumps(OrderedDict(model=OrderedDict(), extra=extra), protocol=2))
    return buf.getvalue()


@pytest.fixture
def fake_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "runs.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_PIDS", str(tmp_path / "pids.log"))
    monkeypatch.delenv("FAKE_BEHAVIOR", raising=False)
    monkeypatch.delenv("FAKE_INSPECT", raising=False)
    return log


@pytest.fixture
def mclient(settings: Settings, fake_env: Path) -> Iterator[TestClient]:
    configured = settings.model_copy(
        update={"converter_python": Path(sys.executable), "converter_dir": FAKE, "converter_timeout_seconds": 60}
    )
    with TestClient(create_app(configured)) as c:
        yield c


def upload(
    c: TestClient, data: bytes | None = None, name: str = "retail.pt", headers: dict[str, str] | None = None
) -> Any:
    return c.post(
        "/api/models",
        content=data if data is not None else checkpoint_bytes(),
        headers={"x-filename": quote(name), **(headers or {})},
    )


def wait(check: Callable[[], bool], timeout: float = 40) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise AssertionError("timed out")


def model(c: TestClient, model_id: int) -> dict[str, Any]:
    r = c.get(f"/api/models/{model_id}")
    assert r.status_code == 200
    return r.json()  # type: ignore[no-any-return]


def settled(c: TestClient, model_id: int) -> bool:
    m = model(c, model_id)
    return (
        m["status"] == "ready"
        and len(m["variants"]) == len(ALL_OPS)
        and all(v["state"] in FINAL for v in m["variants"])
    )


def by_op(c: TestClient, model_id: int) -> dict[str, dict[str, Any]]:
    return {v["op"]: v for v in model(c, model_id)["variants"]}


def runs(log: Path) -> list[str]:
    return log.read_text().split() if log.exists() else []


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_an_uploaded_model_is_read_and_the_whole_matrix_converts(mclient: TestClient) -> None:
    r = upload(mclient)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "inspecting" and body["name"] == "retail" and body["filename"] == "retail.pt"
    wait(lambda: settled(mclient, body["id"]))

    m = model(mclient, body["id"])
    assert m["task"] == "detect" and m["imgsz"] == 640 and m["class_names"] == ["chips", "biscuit", "chocolate"]
    assert m["parameters"] == 2616248 and m["gflops"] == 6.5 and m["sha256"]
    cells = by_op(mclient, body["id"])
    assert set(cells) == set(ALL_OPS)
    assert all(c["state"] == "ready" and not c["mismatch"] and not c["cached"] for c in cells.values())
    assert cells["openvino_fp32"]["size_bytes"] > 1000  # the bundle counts the weights file, not just the .xml
    assert m["variant_counts"] == {"ready": len(ALL_OPS)}
    listed = mclient.get("/api/models").json()
    assert [x["id"] for x in listed] == [body["id"]]


def test_stored_bundles_match_what_is_reported(mclient: TestClient, settings: Settings) -> None:
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    store_root = settings.data_dir / "artifacts"
    with_weights = by_op(mclient, body["id"])["ncnn_fp16"]
    folders = [p for p in store_root.glob("*/*") if p.is_dir() and p.name != "tmp"]
    assert folders, "bundles are folders in the store"
    assert any(sum(f.stat().st_size for f in d.iterdir()) == with_weights["size_bytes"] for d in folders)
    assert not list((store_root / "tmp").iterdir()), "nothing is left half-written"


def test_a_converted_model_can_be_downloaded(mclient: TestClient, settings: Settings) -> None:
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    cells = by_op(mclient, body["id"])

    one = mclient.get(f"/api/variants/{cells['onnx_fp32']['id']}/download")
    assert one.status_code == 200 and one.content.startswith(b"fake onnx_fp32 of ")
    assert 'filename="retail-onnx_fp32.onnx"' in one.headers["content-disposition"]

    several = mclient.get(f"/api/variants/{cells['openvino_fp16']['id']}/download")
    assert (
        several.status_code == 200 and 'filename="retail-openvino_fp16.zip"' in several.headers["content-disposition"]
    )
    with zipfile.ZipFile(io.BytesIO(several.content)) as z:
        assert sorted(z.namelist()) == ["model.bin", "model.xml"]
        assert len(z.read("model.bin")) == 1000

    everything = mclient.get(f"/api/models/{body['id']}/download")
    assert everything.status_code == 200 and "retail-variants.zip" in everything.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(everything.content)) as z:
        assert {n.split("/")[0] for n in z.namelist()} == set(ALL_OPS)
        assert "ncnn_fp32/model.ncnn.bin" in z.namelist()
    assert not list((settings.data_dir / "artifacts" / "tmp").iterdir()), "the zip made for a download is removed"


def test_only_a_finished_conversion_of_a_kept_model_can_be_downloaded(
    mclient: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "ncnn_fp16=fail")
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    cells = by_op(mclient, body["id"])
    failed = mclient.get(f"/api/variants/{cells['ncnn_fp16']['id']}/download")
    assert failed.status_code == 409 and "not finished" in failed.json()["detail"]
    assert mclient.get("/api/variants/9999/download").status_code == 404
    assert mclient.get("/api/models/9999/download").status_code == 404

    mclient.delete(f"/api/models/{body['id']}")
    assert mclient.get(f"/api/variants/{cells['onnx_fp32']['id']}/download").status_code == 404
    assert mclient.get(f"/api/models/{body['id']}/download").status_code == 404


def test_download_all_with_nothing_converted_says_so(mclient: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", ",".join(f"{op}=fail" for op in ALL_OPS))
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    r = mclient.get(f"/api/models/{body['id']}/download")
    assert r.status_code == 409 and "Nothing has been converted" in r.json()["detail"]


def test_a_renamed_text_file_is_rejected_with_a_readable_message(mclient: TestClient) -> None:
    r = upload(mclient, b"hello, I am not a model", name="notes.pt")
    assert r.status_code == 422 and "not a PyTorch checkpoint" in r.json()["detail"]
    assert mclient.get("/api/models").json() == []


def test_a_file_that_is_not_dot_pt_is_rejected(mclient: TestClient) -> None:
    r = upload(mclient, name="model.onnx")
    assert r.status_code == 422 and ".pt" in r.json()["detail"]


def test_a_checkpoint_that_would_run_code_is_refused_before_it_is_stored(
    mclient: TestClient, settings: Settings
) -> None:
    class Evil:
        def __reduce__(self) -> tuple[Any, tuple[Any, ...]]:
            return os.system, ("echo pwned",)

    r = upload(mclient, checkpoint_bytes(extra=Evil()), name="trojan.pt")
    assert r.status_code == 422 and "never needs" in r.json()["detail"]
    assert mclient.get("/api/models").json() == []
    stored = [p for p in (settings.data_dir / "artifacts").glob("*/*") if p.name != "tmp"]
    assert stored == [], "a refused upload leaves nothing behind"


def test_an_empty_upload_and_an_oversized_upload_are_refused(settings: Settings, fake_env: Path) -> None:
    small = settings.model_copy(
        update={"max_upload_bytes": 2000, "converter_python": Path(sys.executable), "converter_dir": FAKE}
    )
    with TestClient(create_app(small)) as c:
        assert upload(c, b"").status_code == 422
        big = upload(c, b"x" * 5000)
        assert big.status_code == 413 and "limit" in big.json()["detail"]
        chunked = c.post("/api/models", content=iter([b"x" * 1500, b"y" * 1500]), headers={"x-filename": "a.pt"})
        assert chunked.status_code == 413  # no Content-Length to check up front: caught while streaming


def test_uploading_the_same_file_again_returns_the_existing_model(mclient: TestClient, fake_env: Path) -> None:
    first = upload(mclient).json()
    wait(lambda: settled(mclient, first["id"]))
    before = runs(fake_env)
    again = upload(mclient)
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    time.sleep(0.5)
    assert runs(fake_env) == before, "nothing was converted a second time"


def test_one_failing_conversion_does_not_stop_the_others(mclient: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "ncnn_fp16=fail")
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    cells = by_op(mclient, body["id"])
    assert cells["ncnn_fp16"]["state"] == "failed" and "RuntimeError: boom" in cells["ncnn_fp16"]["error"]
    assert cells["ncnn_fp16"]["has_log"]
    assert [op for op, c in cells.items() if c["state"] == "ready"] == [op for op in ALL_OPS if op != "ncnn_fp16"]
    log = mclient.get(f"/api/variants/{cells['ncnn_fp16']['id']}/log").text
    assert "fake converting ncnn_fp16" in log and "boom" in log


def test_a_missing_package_is_reported_as_unavailable_not_failed(
    mclient: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "ncnn_fp32=unavailable")
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    cell = by_op(mclient, body["id"])["ncnn_fp32"]
    assert cell["state"] == "unavailable" and "not installed" in cell["error"]


def test_a_conversion_that_disagrees_with_pytorch_is_marked_mismatch(
    mclient: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "onnx_fp16=mismatch")
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    cell = by_op(mclient, body["id"])["onnx_fp16"]
    assert cell["state"] == "ready" and cell["mismatch"] is True and cell["verify"]["relative"] == 0.9


def test_cells_built_from_onnx_fail_clearly_when_it_fails_and_recover_when_it_is_retried(
    mclient: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "onnx_fp32=fail")
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    cells = by_op(mclient, body["id"])
    assert cells["onnx_fp32"]["state"] == "failed"
    for op in ("onnx_fp16", "openvino_fp32", "openvino_fp16"):
        assert cells[op]["state"] == "failed" and cells[op]["error"].startswith("Needs ONNX FP32")
    assert cells["torchscript"]["state"] == "ready" and cells["ncnn_fp32"]["state"] == "ready"

    monkeypatch.setenv("FAKE_BEHAVIOR", "")  # the cause is fixed
    assert mclient.post(f"/api/variants/{cells['onnx_fp32']['id']}/retry").status_code == 200
    wait(lambda: settled(mclient, body["id"]))
    assert {c["state"] for c in by_op(mclient, body["id"]).values()} == {"ready"}, (
        "the waiting cells followed their source"
    )


def test_converting_again_only_runs_what_is_missing(
    mclient: TestClient, fake_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "torchscript=fail")
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    assert runs(fake_env).count("torchscript") == 1 and runs(fake_env).count("onnx_fp32") == 1

    monkeypatch.setenv("FAKE_BEHAVIOR", "")
    assert mclient.post(f"/api/models/{body['id']}/convert").status_code == 200
    wait(lambda: settled(mclient, body["id"]))
    assert runs(fake_env).count("torchscript") == 2, "the failed cell ran again"
    assert runs(fake_env).count("onnx_fp32") == 1, "the ready cells were left alone"
    assert {c["state"] for c in by_op(mclient, body["id"]).values()} == {"ready"}


def test_an_identical_conversion_is_reused_instead_of_run_again(mclient: TestClient, fake_env: Path) -> None:
    first = upload(mclient).json()
    wait(lambda: settled(mclient, first["id"]))
    ran = len(runs(fake_env))
    assert mclient.delete(f"/api/models/{first['id']}").status_code == 204
    assert mclient.get("/api/models").json() == []
    assert mclient.get(f"/api/models/{first['id']}").status_code == 404

    second = upload(mclient)  # the same file again, now that the first model is archived
    assert second.status_code == 201 and second.json()["id"] != first["id"]
    wait(lambda: settled(mclient, second.json()["id"]))
    cells = by_op(mclient, second.json()["id"])
    assert all(c["state"] == "ready" and c["cached"] for c in cells.values())
    assert len(runs(fake_env)) == ran, "no converter process was started for the second model"


def test_cancelling_a_running_conversion_kills_its_process_and_the_queue_moves_on(
    mclient: TestClient, fake_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "torchscript=hang")
    body = upload(mclient).json()
    pids = fake_env.parent / "pids.log"
    wait(lambda: pids.exists() and "torchscript" in pids.read_text())
    cell = by_op(mclient, body["id"])["torchscript"]
    pid = int(dict(line.split() for line in pids.read_text().splitlines())["torchscript"])
    assert pid_alive(pid)

    assert mclient.post(f"/api/variants/{cell['id']}/cancel").status_code == 200
    wait(lambda: by_op(mclient, body["id"])["torchscript"]["state"] == "cancelled")
    wait(lambda: not pid_alive(pid), timeout=15)
    wait(lambda: settled(mclient, body["id"]))
    states = {op: c["state"] for op, c in by_op(mclient, body["id"]).items()}
    assert states["torchscript"] == "cancelled" and all(s == "ready" for op, s in states.items() if op != "torchscript")


def test_a_conversion_that_never_finishes_is_stopped_and_reported(
    settings: Settings, fake_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "torchscript=hang")
    quick = settings.model_copy(
        update={"converter_python": Path(sys.executable), "converter_dir": FAKE, "converter_timeout_seconds": 1.5}
    )
    with TestClient(create_app(quick)) as c:
        body = upload(c).json()
        wait(lambda: settled(c, body["id"]))
        cell = by_op(c, body["id"])["torchscript"]
        assert cell["state"] == "failed" and "Stopped after" in cell["error"]
        assert by_op(c, body["id"])["ncnn_fp32"]["state"] == "ready"


def test_retry_and_cancel_only_apply_where_they_make_sense(mclient: TestClient) -> None:
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    ready = by_op(mclient, body["id"])["onnx_fp32"]
    assert mclient.post(f"/api/variants/{ready['id']}/retry").status_code == 409
    assert mclient.post(f"/api/variants/{ready['id']}/cancel").status_code == 409
    assert mclient.post("/api/variants/9999/retry").status_code == 404
    assert mclient.get("/api/models/9999").status_code == 404


def test_an_unreadable_model_is_rejected_with_the_reason(mclient: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_INSPECT", "bad")
    body = upload(mclient).json()
    wait(lambda: model(mclient, body["id"])["status"] != "inspecting")
    m = model(mclient, body["id"])
    assert m["status"] == "rejected" and "not an Ultralytics model" in m["error"] and m["variants"] == []


def test_without_a_converter_environment_the_model_waits_and_says_why(settings: Settings, fake_env: Path) -> None:
    with TestClient(create_app(settings)) as c:  # no converter_python configured
        info = c.get("/api/converter").json()
        assert info["available"] is False and "EDGEBENCH_CONVERTER_PYTHON" in info["message"]
        body = upload(c).json()
        wait(lambda: model(c, body["id"])["status"] != "inspecting")
        m = model(c, body["id"])
        assert m["status"] == "converter_missing" and "EDGEBENCH_CONVERTER_PYTHON" in m["error"]
        assert c.post(f"/api/models/{body['id']}/convert").status_code == 409


def test_the_converter_status_lists_versions_and_missing_packages(mclient: TestClient) -> None:
    info = mclient.get("/api/converter").json()
    assert info["available"] is True and info["versions"]["torch"] == "0" and info["missing"] == ["ncnn"]


def test_a_page_on_another_site_cannot_change_anything(mclient: TestClient) -> None:
    hostile = {"origin": "http://evil.example"}
    assert upload(mclient, headers=hostile).status_code == 403
    body = upload(mclient).json()
    assert mclient.post(f"/api/models/{body['id']}/convert", headers=hostile).status_code == 403
    assert mclient.delete(f"/api/models/{body['id']}", headers=hostile).status_code == 403
    assert mclient.post("/api/variants/1/retry", headers=hostile).status_code == 403
    assert upload(mclient, headers={"origin": "http://testserver"}).status_code in (
        200,
        201,
    )  # the app's own origin is fine
    assert mclient.get("/api/models", headers=hostile).status_code == 200  # reading is not state-changing


def test_cancelling_a_waiting_conversion_marks_it_cancelled(
    mclient: TestClient, fake_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cell whose job has not started has nothing else to update it, so the cancel does (this once returned a 500)."""
    monkeypatch.setenv("FAKE_BEHAVIOR", "torchscript=hang")
    body = upload(mclient).json()
    pids = fake_env.parent / "pids.log"
    wait(lambda: pids.exists() and "torchscript" in pids.read_text())
    waiting = by_op(mclient, body["id"])["ncnn_fp16"]
    assert waiting["state"] == "pending"

    r = mclient.post(f"/api/variants/{waiting['id']}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    assert by_op(mclient, body["id"])["ncnn_fp16"]["state"] == "cancelled"
    torchscript = by_op(mclient, body["id"])["torchscript"]
    assert mclient.post(f"/api/variants/{torchscript['id']}/cancel").status_code == 200  # let the queue finish
    wait(lambda: settled(mclient, body["id"]))
    assert "ncnn_fp16" not in runs(fake_env), "the cancelled cell never ran"


def test_removing_a_model_stops_its_running_work_and_leaves_nothing_waiting(
    mclient: TestClient, fake_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "torchscript=hang")
    body = upload(mclient).json()
    pids = fake_env.parent / "pids.log"
    wait(lambda: pids.exists() and "torchscript" in pids.read_text())
    pid = int(dict(line.split() for line in pids.read_text().splitlines())["torchscript"])

    assert mclient.delete(f"/api/models/{body['id']}").status_code == 204
    wait(lambda: not pid_alive(pid), timeout=15)

    def only_final_states() -> bool:
        with Session(mclient.app.state.engine) as session:  # type: ignore[attr-defined]
            states = {v.state for v in session.exec(select(Variant).where(Variant.model_id == body["id"])).all()}
        return states <= {"ready", "cancelled"}

    wait(only_final_states)
    time.sleep(1)  # a cancelled queue must stay quiet: nothing starts after the model is gone
    assert set(runs(fake_env)) <= {"onnx_fp32", "torchscript"}


def test_a_model_removed_before_it_was_read_gets_no_conversions(settings: Settings, fake_env: Path) -> None:
    idle = settings.model_copy(
        update={"worker_enabled": False, "converter_python": Path(sys.executable), "converter_dir": FAKE}
    )
    with TestClient(create_app(idle)) as c:
        body = upload(c).json()
        assert c.delete(f"/api/models/{body['id']}").status_code == 204
        s = c.app.state.services  # type: ignore[attr-defined]
        assert Worker(s.engine, s.publish).run_once() is True  # the waiting read job runs now, and must see the removal
        with Session(s.engine) as session:
            assert session.exec(select(Variant)).all() == []
    assert runs(fake_env) == []


def test_retrying_a_cell_renames_its_cache_entry_after_the_converter_changed(
    mclient: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "ncnn_fp16=fail")
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    cell = by_op(mclient, body["id"])["ncnn_fp16"]
    engine = mclient.app.state.engine  # type: ignore[attr-defined]

    def key() -> str:
        with Session(engine) as session:
            return session.get(Variant, cell["id"]).cache_key  # type: ignore[union-attr]

    before = key()
    monkeypatch.setenv("FAKE_BEHAVIOR", "")
    mclient.app.state.services.converter._info = ConverterInfo(True, fingerprint="after-an-upgrade")  # type: ignore[attr-defined]
    assert mclient.post(f"/api/variants/{cell['id']}/retry").status_code == 200
    wait(lambda: settled(mclient, body["id"]))
    assert key() != before, "the key names the toolchain that actually converted it"


def test_a_check_that_crashes_does_not_throw_the_conversion_away(
    mclient: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BEHAVIOR", "onnx_fp16=verifyfail")
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    cell = by_op(mclient, body["id"])["onnx_fp16"]
    assert cell["state"] == "ready" and cell["mismatch"] is True and cell["size_bytes"] > 0
    assert "the check crashed" in cell["verify"]["error"]


def test_an_upload_that_breaks_the_scanner_is_a_422_and_leaves_no_temp_file(
    mclient: TestClient, settings: Settings
) -> None:
    buf = io.BytesIO()
    info = zipfile.ZipInfo("model/data.pkl", date_time=(2026, 1, 1, 0, 0, 0))
    info.flag_bits |= 0x1
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(info, b"x")
    r = upload(mclient, buf.getvalue(), name="odd.pt")
    assert r.status_code == 422 and "could not be read safely" in r.json()["detail"]
    assert list((settings.data_dir / "artifacts" / "tmp").iterdir()) == []


# --- custom variants: another input size, an unsimplified export ----------------------------


def add_variant(c: TestClient, model_id: int, op: str, imgsz: int, **extra: Any) -> Any:
    return c.post(f"/api/models/{model_id}/variants", json={"op": op, "imgsz": imgsz, **extra})


def test_a_variant_at_another_input_size_brings_the_cell_it_is_built_from(mclient: TestClient) -> None:
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    before = {v["id"] for v in model(mclient, body["id"])["variants"]}
    assert add_variant(mclient, body["id"], "openvino_fp16", 320).status_code == 201
    wait(lambda: all(v["state"] in FINAL for v in model(mclient, body["id"])["variants"]))
    added = [v for v in model(mclient, body["id"])["variants"] if v["id"] not in before]
    # the ONNX FP32 export it is built from, at the new size, and the OpenVINO cell itself
    assert {v["op"] for v in added} == {"onnx_fp32", "openvino_fp16"} and all(v["state"] == "ready" for v in added)
    # asking again changes nothing: the cells are already there
    assert len(add_variant(mclient, body["id"], "openvino_fp16", 320).json()["variants"]) == len(before) + 2


def test_an_onnx_export_can_be_left_unsimplified_as_its_own_cell(mclient: TestClient) -> None:
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    r = add_variant(mclient, body["id"], "onnx_fp32", 640, simplify=False)
    assert r.status_code == 201
    wait(lambda: all(v["state"] in FINAL for v in model(mclient, body["id"])["variants"]))
    cells = [v for v in model(mclient, body["id"])["variants"] if v["op"] == "onnx_fp32"]
    assert len(cells) == 2 and all(v["state"] == "ready" for v in cells)  # the default and the unsimplified one


def test_a_custom_variant_is_validated(mclient: TestClient) -> None:
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    assert "Unknown conversion" in add_variant(mclient, body["id"], "tflite_int8", 640).json()["detail"]
    assert "multiple of 32" in add_variant(mclient, body["id"], "onnx_fp32", 330).json()["detail"]
    assert add_variant(mclient, body["id"], "onnx_fp32", 16).status_code == 422
    assert "Only the ONNX FP32" in add_variant(mclient, body["id"], "ncnn_fp32", 320, simplify=False).json()["detail"]
    assert add_variant(mclient, 999, "onnx_fp32", 320).status_code == 404
    assert add_variant(mclient, body["id"], "onnx_fp32", 320, simplify=True).status_code == 201
    assert (
        add_variant(
            mclient,
            body["id"],
            "onnx_fp32",
            320,
            simplify=True,
        ).status_code
        == 201
    )
    hostile = mclient.post(
        f"/api/models/{body['id']}/variants",
        json={"op": "onnx_fp32", "imgsz": 320},
        headers={"origin": "https://evil.example"},
    )
    assert hostile.status_code == 403


def test_custom_cells_download_under_names_that_tell_them_apart(mclient: TestClient) -> None:
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    add_variant(mclient, body["id"], "onnx_fp32", 320)
    add_variant(mclient, body["id"], "onnx_fp32", 640, simplify=False)
    wait(lambda: all(v["state"] in FINAL for v in model(mclient, body["id"])["variants"]))
    names = {}
    for v in model(mclient, body["id"])["variants"]:
        if v["op"] == "onnx_fp32":
            names[v["id"]] = mclient.get(f"/api/variants/{v['id']}/download").headers["content-disposition"]
    assert sorted(re.findall(r'filename="([^"]+)"', n)[0] for n in names.values()) == [
        "retail-onnx_fp32-320px.onnx",
        "retail-onnx_fp32-unsimplified.onnx",
        "retail-onnx_fp32.onnx",
    ]
    everything = zipfile.ZipFile(io.BytesIO(mclient.get(f"/api/models/{body['id']}/download").content))
    folders = {n.split("/")[0] for n in everything.namelist()}
    assert {"onnx_fp32", "onnx_fp32-320px", "onnx_fp32-unsimplified"} <= folders
