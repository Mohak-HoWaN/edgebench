"""A model made by a newer Ultralytics than the converter has is stopped and explained, not converted to look-alikes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from test_agent_api import FINGERPRINT_PC, enrolled, seed_model, start_run
from test_models_api import by_op, model, settled, upload, wait

from edgebench import compat
from edgebench.config import find_converter_python
from edgebench.model_jobs import queue_missing_cards
from edgebench.models import MlModel, Variant

OLD, NEW = {"ultralytics": "8.3.248", "torch": "2.6.0"}, {"ultralytics": "8.4.212", "torch": "2.6.0"}


def card(**kw: Any) -> dict[str, Any]:
    return {"trained_with": "8.4.208", "train_model": "ul://ultralytics/yolo26/yolo26n", **kw}


def test_a_model_trained_with_a_newer_library_is_not_ok_and_the_message_blames_the_converter() -> None:
    verdict = compat.check(card(), OLD, "py.exe")
    assert not verdict["ok"] and verdict["architecture"] == "yolo26n"
    msg = verdict["message"]
    assert (
        "8.4.208" in msg
        and "8.3.248" in msg
        and "Nothing is wrong with your model" in msg
        and 'ultralytics>=8.4"' in msg
    )
    assert compat.check(card(), NEW, "py.exe")["ok"]


def test_the_family_alone_is_enough_when_the_file_has_no_version_stamp() -> None:
    assert not compat.check({"trained_with": None, "train_model": "yolo26n.pt"}, OLD, None)["ok"]
    assert compat.check({"trained_with": None, "train_model": "yolo11n.pt"}, OLD, None)["ok"]
    assert compat.check({"trained_with": None, "train_model": None}, OLD, None)["ok"]  # nothing known: not blocked


def test_an_older_model_on_a_newer_converter_is_fine() -> None:
    assert compat.check({"trained_with": "8.3.235", "train_model": "yolo11n.pt"}, NEW, None)["ok"]


def test_a_variant_is_stale_when_the_converter_changed_or_its_versions_were_never_recorded() -> None:
    assert compat.stale_reason(NEW, NEW) is None
    assert "8.3.248" in (compat.stale_reason(OLD, NEW) or "") and "8.4.212" in (compat.stale_reason(OLD, NEW) or "")
    assert "before converter versions" in (compat.stale_reason(None, NEW) or "")
    assert (
        compat.stale_reason({"ultralytics": "8.4.212", "numpy": "1"}, {**NEW, "numpy": "2"}) is None
    )  # only the listed libraries count


def test_a_conversion_older_than_its_model_is_called_out() -> None:
    assert "8.3.248" in (compat.older_than_model("8.3.248", "8.4.208", "Built by") or "")
    assert compat.older_than_model("8.4.212", "8.4.208", "Built by") is None
    assert compat.older_than_model(None, "8.4.208", "Built by") is None


def test_upload_of_a_model_the_converter_is_too_old_for_is_blocked_then_unblocked_after_an_upgrade(
    mclient: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_TRAINED_WITH", "8.4.208")
    monkeypatch.setenv("FAKE_TRAIN_MODEL", "ul://ultralytics/yolo26/yolo26n")
    monkeypatch.setenv("FAKE_ULTRALYTICS", "8.3.248")
    mclient.app.state.services.converter.info(refresh=True)  # type: ignore[attr-defined]
    body = upload(mclient).json()
    wait(lambda: model(mclient, body["id"])["status"] != "inspecting")
    m = model(mclient, body["id"])
    assert m["status"] == "incompatible" and "Nothing is wrong with your model" in m["error"]
    assert m["variants"] == [] and m["card"]["trained_with"] == "8.4.208" and not m["card"]["ok"]

    # a run on it is refused with the same words
    refused = mclient.post("/api/runs", json={"model_id": body["id"], "dataset_id": 1, "device_id": 1})
    assert refused.status_code == 422 and "cannot be run yet" in refused.json()["detail"]

    monkeypatch.setenv("FAKE_ULTRALYTICS", "8.4.212")  # the owner upgraded the converter
    assert mclient.post(f"/api/models/{body['id']}/inspect").status_code == 200
    wait(lambda: settled(mclient, body["id"]))
    m = model(mclient, body["id"])
    assert m["status"] == "ready" and m["card"]["ok"] and m["error"] is None
    assert all(v["built_with"]["ultralytics"] == "8.4.212" and v["stale"] is None for v in m["variants"])


def test_variants_built_by_an_older_converter_are_flagged_refused_in_runs_and_can_be_rebuilt(
    mclient: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FAKE_ULTRALYTICS", "8.3.248")
    mclient.app.state.services.converter.info(refresh=True)  # type: ignore[attr-defined]
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    assert all(v["stale"] is None for v in model(mclient, body["id"])["variants"])

    monkeypatch.setenv("FAKE_ULTRALYTICS", "8.4.212")
    mclient.app.state.services.converter.info(refresh=True)  # type: ignore[attr-defined]
    cells = by_op(mclient, body["id"])
    assert all("8.3.248" in v["stale"] and "8.4.212" in v["stale"] for v in cells.values())

    cell = cells["onnx_fp32"]
    assert mclient.post(f"/api/variants/{cell['id']}/retry").status_code == 200  # rebuilding a finished cell is allowed
    wait(lambda: by_op(mclient, body["id"])["onnx_fp32"]["state"] == "ready")
    assert by_op(mclient, body["id"])["onnx_fp32"]["stale"] is None
    assert mclient.post(f"/api/variants/{cell['id']}/retry").status_code == 409  # a current one is not retried

    assert (
        mclient.post(f"/api/models/{body['id']}/convert").status_code == 200
    )  # "convert everything" rebuilds the rest
    wait(lambda: all(v["stale"] is None and v["state"] == "ready" for v in model(mclient, body["id"])["variants"]))


def test_a_variant_with_no_recorded_versions_reads_as_built_before_they_were_recorded(mclient: TestClient) -> None:
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    engine = mclient.app.state.engine  # type: ignore[attr-defined]
    cell = by_op(mclient, body["id"])["onnx_fp32"]
    with Session(engine) as session:
        v = session.get(Variant, cell["id"])
        assert v is not None
        v.toolchain = None
        session.add(v)
        session.commit()
    assert "before converter versions" in by_op(mclient, body["id"])["onnx_fp32"]["stale"]


def test_without_a_converter_nothing_is_called_stale() -> None:
    assert compat.stale_reason(None, {}) is None


def test_a_run_says_when_the_tool_may_be_at_fault_and_stays_quiet_otherwise(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client, fingerprint={**FINGERPRINT_PC, "packages": {"ultralytics": "8.3.248"}})
    model_id, variant_id = seed_model(client, tmp_path)
    variant_run = start_run(client, tmp_path, device_id)["id"]
    baseline_run = start_run(client, tmp_path, device_id, baseline=True)["id"]
    quiet = [client.get(f"/api/runs/{r}").json()["diagnosis"] for r in (variant_run, baseline_run)]
    assert quiet == [[], []]  # nothing recorded about where the model came from

    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        m, v = session.get(MlModel, model_id), session.get(Variant, variant_id)
        assert m is not None and v is not None
        m.card, v.toolchain = {"trained_with": "8.4.208"}, {"ultralytics": "8.3.248"}
        session.add_all([m, v])
        session.commit()
    said = [client.get(f"/api/runs/{r}").json()["diagnosis"] for r in (variant_run, baseline_run)]
    assert "This conversion was built by Ultralytics 8.3.248" in said[0][0]
    assert "The device's agent has Ultralytics 8.3.248" in said[1][0]
    assert token  # the agent exists only so the baseline run can name its library


def test_the_converter_can_be_looked_at_again_after_an_upgrade(
    mclient: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert mclient.get("/api/converter").json()["versions"]["ultralytics"] == "0"
    monkeypatch.setenv("FAKE_ULTRALYTICS", "8.4.212")
    assert mclient.get("/api/converter").json()["versions"]["ultralytics"] == "0"  # cached for a while
    assert mclient.post("/api/converter/refresh").json()["versions"]["ultralytics"] == "8.4.212"
    assert mclient.get("/api/converter").json()["versions"]["ultralytics"] == "8.4.212"


def test_a_model_read_before_cards_existed_gets_its_card_without_being_converted_again(mclient: TestClient) -> None:
    body = upload(mclient).json()
    wait(lambda: settled(mclient, body["id"]))
    s = mclient.app.state.services  # type: ignore[attr-defined]
    with Session(s.engine) as session:
        m = session.get(MlModel, body["id"])
        assert m is not None
        m.card = None
        session.add(m)
        session.commit()
    before = {v["id"]: v["updated_at"] for v in model(mclient, body["id"])["variants"]}
    assert queue_missing_cards(s) == 1
    wait(lambda: model(mclient, body["id"])["card"] is not None)
    after = model(mclient, body["id"])
    assert after["status"] == "ready" and after["card"]["ok"]
    assert {v["id"]: v["updated_at"] for v in after["variants"]} == before  # nothing was rebuilt
    assert queue_missing_cards(s) == 0


def test_the_converter_environment_is_found_next_to_the_repository_in_the_scripts_order(tmp_path: Path) -> None:
    assert find_converter_python(tmp_path) is None
    spikes = tmp_path / "spikes" / ".venv" / "Scripts"
    spikes.mkdir(parents=True)
    (spikes / "python.exe").write_text("")
    assert find_converter_python(tmp_path) == spikes / "python.exe"
    own = tmp_path / ".venv-converter" / "bin"
    own.mkdir(parents=True)
    (own / "python").write_text("")
    assert find_converter_python(tmp_path) == own / "python"  # the dedicated environment wins
