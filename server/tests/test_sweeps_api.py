"""Phase 4 through the API: sweeps and their plan, cancel and resume, latency comparisons, drift from the baseline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select
from test_agent_api import bearer, enrolled, seed_dataset, seed_model

from edgebench.models import Experiment, Variant

EIGHT_CORES = {"hostname": "desk", "os": "Windows 11", "machine": "AMD64", "pi_model": None, "logical_cores": 8}


def repeats(*p50s: float, valid: list[bool] | None = None) -> dict[str, Any]:
    flags = valid or [True] * len(p50s)
    reps = [
        {"index": i, "valid": v, "stats": {"p50": p, "mean": p}, "total_ms": [p] * 5}
        for i, (p, v) in enumerate(zip(p50s, flags, strict=True))
    ]
    return {
        "stages": {"total": {"p50": p50s[0]}},
        "repeats": reps,
        "valid_repeats": sum(flags),
        "latency_valid": any(flags),
    }


def box(x: float, cls: int = 0) -> list[float]:
    return [x, 0.1, x + 0.2, 0.3, 0.9, float(cls)]


def result(
    *p50s: float, detections: dict[str, list[list[float]]] | None = None, map50: float | None = None
) -> dict[str, Any]:
    accuracy: dict[str, Any] = {"available": False}
    if map50 is not None:
        accuracy = {"available": True, "map50": map50, "map50_95": map50 / 2, "per_class": {"chips": {"ap50": map50}}}
    out: dict[str, Any] = {"speed": repeats(*p50s), "accuracy": accuracy}
    if detections is not None:
        out["predictions"] = {"min_confidence": 0.25, "pictures": detections}
    return out


def finish(c: TestClient, token: str, results: dict[int | None, dict[str, Any]], only: int | None = None) -> int:
    """Answer claimed jobs. ``results`` maps a run's variant id (None: baseline) to its result. Returns the count."""
    done = 0
    while only is None or done < only:
        claimed = c.post("/agent/claim", headers=bearer(token))
        if claimed.status_code != 200:
            break
        spec = claimed.json()
        run = next(r for r in c.get("/api/runs?limit=500").json() if r["id"] == spec["run_id"])
        body = {"job_id": spec["job_id"], "ok": True, "result": results[run["variant_id"]]}
        assert c.post("/agent/result", json=body, headers=bearer(token)).status_code == 200
        done += 1
    return done


def add_size_variant(c: TestClient, imgsz: int) -> int:
    """The seeded conversion again at another input size (the same files: only the record matters here)."""
    s = c.app.state.services  # type: ignore[attr-defined]
    with Session(s.engine) as session:
        base = session.exec(select(Variant)).first()
        assert base is not None
        v = Variant(
            model_id=base.model_id, op=base.op, format=base.format, precision=base.precision, imgsz=imgsz,
            state="ready", artifact_sha256=base.artifact_sha256, main_file=base.main_file,
            size_bytes=base.size_bytes, cache_key=f"k{imgsz}",
        )  # fmt: skip
        session.add(v)
        session.commit()
        session.refresh(v)
        assert v.id is not None
        return v.id


def body_for(c: TestClient, tmp_path: Path, device_id: int, **extra: Any) -> dict[str, Any]:
    model_id, variant_id = seed_model(c, tmp_path)
    items = extra.pop("items", [{"model_id": model_id, "variant_id": variant_id}])
    return {
        "name": "sweep",
        "dataset_id": seed_dataset(c, tmp_path),
        "device_id": device_id,
        "params": {"threads": 2, "warmup": 1, "iterations": 5, "repeats": 3, **extra.pop("params", {})},
        "items": items,
        **extra,
    }


def test_the_plan_counts_the_runs_leaves_out_what_cannot_run_and_estimates_the_time(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, _ = enrolled(client, fingerprint=EIGHT_CORES)
    body = body_for(client, tmp_path, device_id, sweep={"threads": [1, 2, 4, 16]})
    plan = client.post("/api/experiments/plan", json=body)
    assert plan.status_code == 200, plan.text
    p = plan.json()
    assert p["run_count"] == 3 and [r["threads"] for r in p["runs"]] == [1, 2, 4]
    assert len(p["pruned"]) == 1 and "16 threads do not fit on the device's 8 CPUs" in p["pruned"][0]["reason"]
    assert p["guessed_runs"] == 3 and p["repeats"] == 3 and p["estimated_seconds"] > 3 * 3
    assert client.get("/api/experiments").json() == []  # a plan changes nothing


def test_the_estimate_uses_what_this_device_measured_before(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client, fingerprint=EIGHT_CORES)
    _, variant_id = seed_model(client, tmp_path)
    guess = client.post("/api/experiments/plan", json=body_for(client, tmp_path, device_id)).json()
    assert client.post("/api/experiments", json=body_for(client, tmp_path, device_id)).status_code == 201
    finish(client, token, {variant_id: result(100.0, 100.0, 100.0)})
    measured = client.post("/api/experiments/plan", json=body_for(client, tmp_path, device_id)).json()
    assert guess["guessed_runs"] == 1 and measured["guessed_runs"] == 0
    assert (
        measured["estimated_seconds"] > guess["estimated_seconds"]
    )  # 100 ms per inference is slower than the 40 ms guess


def test_a_sweep_makes_a_run_per_combination_and_remembers_what_it_was_asked(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, _ = enrolled(client, fingerprint=EIGHT_CORES)
    model_id, variant_id = seed_model(client, tmp_path)
    small = add_size_variant(client, 416)
    body = body_for(
        client,
        tmp_path,
        device_id,
        items=[{"model_id": model_id, "variant_id": variant_id}, {"model_id": model_id, "variant_id": None}],
        sweep={"threads": [1, 2], "imgsz": [640, 416, 512]},
    )
    plan = client.post("/api/experiments/plan", json=body).json()
    # ONNX: 2 threads x (640, 416) = 4 runs, 512 has no conversion; baseline: 2 threads x 640 (the .pt has one size)
    assert plan["run_count"] == 6
    reasons = sorted(p["reason"] for p in plan["pruned"])
    assert sum("no finished conversion at 512 px" in r for r in reasons) == 2
    assert sum("own input size" in r for r in reasons) == 4  # the baseline at 416 and 512, for two thread counts each
    e = client.post("/api/experiments", json=body).json()
    assert len(e["runs"]) == 6
    assert {(r["params"]["threads"], r["variant_id"]) for r in e["runs"] if r["variant_id"]} == {
        (1, variant_id),
        (2, variant_id),
        (1, small),
        (2, small),
    }
    assert any("416 px" in r["variant_label"] for r in e["runs"])


def test_a_sweep_in_which_nothing_can_run_is_refused_with_the_reasons(client: TestClient, tmp_path: Path) -> None:
    device_id, _ = enrolled(client, fingerprint=EIGHT_CORES)
    body = body_for(client, tmp_path, device_id, sweep={"threads": [32, 64]})
    r = client.post("/api/experiments", json=body)
    assert r.status_code == 422 and "left out" in r.json()["detail"] and "32 threads" in r.json()["detail"]
    assert client.post("/api/experiments/plan", json=body).status_code == 422
    assert client.get("/api/experiments").json() == []


def test_a_cancelled_sweep_keeps_what_finished_and_resume_makes_only_the_rest(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(client, fingerprint=EIGHT_CORES)
    _, variant_id = seed_model(client, tmp_path)
    e = client.post(
        "/api/experiments", json=body_for(client, tmp_path, device_id, sweep={"threads": [1, 2, 4, 8]})
    ).json()
    assert len(e["runs"]) == 4 and not e["resumable"]
    assert finish(client, token, {variant_id: result(10.0, 10.0, 10.0)}, only=2) == 2  # two runs finish
    cancelled = client.post(f"/api/experiments/{e['id']}/cancel").json()
    assert sorted(r["status"] for r in cancelled["runs"]) == ["cancelled", "cancelled", "done", "done"]
    assert cancelled["resumable"] and cancelled["status"] == "partly"
    done_ids = {r["id"] for r in cancelled["runs"] if r["status"] == "done"}

    resumed = client.post(f"/api/experiments/{e['id']}/resume")
    assert resumed.status_code == 200, resumed.text
    runs = resumed.json()["runs"]
    assert len(runs) == 4 and done_ids <= {r["id"] for r in runs}  # the finished runs are still there, untouched
    assert sorted(r["status"] for r in runs) == ["done", "done", "queued", "queued"]
    assert sorted(r["params"]["threads"] for r in runs) == [1, 2, 4, 8]  # every setting once, none twice
    assert client.post(f"/api/experiments/{e['id']}/resume").status_code == 409  # nothing is left to make
    finish(client, token, {variant_id: result(10.0, 10.0, 10.0)})
    assert client.get(f"/api/experiments/{e['id']}").json()["status"] == "done"


def test_resume_waits_while_a_run_is_still_going_or_stopping(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client, fingerprint=EIGHT_CORES)
    e = client.post("/api/experiments", json=body_for(client, tmp_path, device_id, sweep={"threads": [1, 2]})).json()
    assert client.post("/agent/claim", headers=bearer(token)).status_code == 200  # one run is now running
    client.post(f"/api/experiments/{e['id']}/cancel")  # the agent has not noticed yet: it is still "running"
    r = client.post(f"/api/experiments/{e['id']}/resume")
    assert r.status_code == 409 and "still going or stopping" in r.json()["detail"]
    assert len(client.get(f"/api/experiments/{e['id']}").json()["runs"]) == 2  # nothing was made twice


def test_an_experiment_from_before_plans_were_kept_cannot_be_resumed(client: TestClient, tmp_path: Path) -> None:
    device_id, _ = enrolled(client)
    e = client.post("/api/experiments", json=body_for(client, tmp_path, device_id)).json()
    s = client.app.state.services  # type: ignore[attr-defined]
    with Session(s.engine) as session:
        row = session.get(Experiment, e["id"])
        assert row is not None
        row.plan = None
        session.add(row)
        session.commit()
    r = client.post(f"/api/experiments/{e['id']}/resume")
    assert r.status_code == 409 and "cannot be resumed" in r.json()["detail"]


def test_a_run_reports_its_headline_latency_with_an_interval_over_the_repeats(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(client)
    _, variant_id = seed_model(client, tmp_path)
    client.post("/api/experiments", json=body_for(client, tmp_path, device_id))
    finish(client, token, {variant_id: result(10.0, 12.0, 14.0)})
    run = client.get("/api/runs").json()[0]
    lat = run["latency"]
    assert lat["p50_ms"] == 12.0 and lat["n"] == 3 and lat["wide"] and lat["valid"] and lat["ci_half_width_ms"] > 4


def test_converted_runs_are_compared_with_the_baseline_at_the_same_settings(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    model_id, variant_id = seed_model(client, tmp_path)
    e = client.post(
        "/api/experiments",
        json=body_for(
            client, tmp_path, device_id,
            items=[{"model_id": model_id, "variant_id": variant_id}, {"model_id": model_id, "variant_id": None}],
        ),
    ).json()  # fmt: skip
    finish(client, token, {variant_id: result(10.0, 10.1, 9.9), None: result(20.0, 20.2, 19.8)})
    got = client.get(f"/api/experiments/{e['id']}").json()
    converted = next(r for r in got["runs"] if r["variant_id"])
    baseline = next(r for r in got["runs"] if r["variant_id"] is None)
    c = got["comparisons"][str(converted["id"])]
    assert c["vs_run_id"] == baseline["id"] and c["significant"] is True and abs(c["speedup"] - 2.0) < 0.01
    assert str(baseline["id"]) not in got["comparisons"]  # the baseline is the reference, not compared with itself


def test_drift_from_the_baseline_and_the_configurable_gate(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    model_id, variant_id = seed_model(client, tmp_path)
    e = client.post(
        "/api/experiments",
        json=body_for(
            client, tmp_path, device_id,
            items=[{"model_id": model_id, "variant_id": variant_id}, {"model_id": model_id, "variant_id": None}],
        ),
    ).json()  # fmt: skip
    truth = {str(i): [box(0.1), box(0.5, 1)] for i in range(4)}
    shifted = {str(i): [box(0.13), box(0.5, 1)] for i in range(4)}
    finish(
        client,
        token,
        {
            variant_id: result(10.0, 10.0, 10.0, detections=shifted, map50=0.78),
            None: result(20.0, 20.0, 20.0, detections=truth, map50=0.80),
        },
    )
    got = client.get(f"/api/experiments/{e['id']}").json()
    run_id = str(next(r["id"] for r in got["runs"] if r["variant_id"]))
    d = got["drift"][run_id]
    assert d["agreement_available"] and d["matched"] == 8 and 0.8 < d["mean_box_iou"] < 1.0
    assert abs(d["map50_delta"] + 0.02) < 1e-9
    strict = client.get(f"/api/experiments/{e['id']}?min_agreement=0.99&max_map_drop=0.01").json()["drift"][run_id]
    assert strict["verdict"]["passed"] is False and len(strict["verdict"]["reasons"]) == 2
    lenient = client.get(f"/api/experiments/{e['id']}?min_agreement=0.5&max_map_drop=0.1").json()["drift"][run_id]
    assert lenient["verdict"] == {"passed": True, "reasons": []}


def test_a_variant_that_finds_nothing_fails_the_gate_end_to_end(client: TestClient, tmp_path: Path) -> None:
    """The INT8 ONNX file that loads, runs fast and returns zero detections must not pass as a faster model."""
    device_id, token = enrolled(client)
    model_id, variant_id = seed_model(client, tmp_path)
    e = client.post(
        "/api/experiments",
        json=body_for(
            client, tmp_path, device_id,
            items=[{"model_id": model_id, "variant_id": variant_id}, {"model_id": model_id, "variant_id": None}],
        ),
    ).json()  # fmt: skip
    truth = {str(i): [box(0.1), box(0.5, 1)] for i in range(4)}
    finish(
        client,
        token,
        {
            variant_id: result(2.0, 2.0, 2.0, detections={}, map50=0.0),
            None: result(20.0, 20.0, 20.0, detections=truth, map50=0.8),
        },
    )
    got = client.get(
        f"/api/experiments/{e['id']}?min_agreement=0&max_map_drop=1"
    ).json()  # the loosest limits there are
    d = got["drift"][str(next(r["id"] for r in got["runs"] if r["variant_id"]))]
    assert d["variant_detections"] == 0 and d["mean_box_iou"] == 0.0
    assert d["verdict"]["passed"] is False and "finds nothing" in d["verdict"]["reasons"][0]


def test_without_a_baseline_run_there_is_no_comparison_and_no_drift(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    _, variant_id = seed_model(client, tmp_path)
    e = client.post("/api/experiments", json=body_for(client, tmp_path, device_id)).json()
    finish(client, token, {variant_id: result(10.0, 10.0, 10.0)})
    got = client.get(f"/api/experiments/{e['id']}").json()
    assert got["comparisons"] == {} and got["drift"] == {}


def test_the_picture_inspector_names_each_runs_threads(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client, fingerprint=EIGHT_CORES)
    _, variant_id = seed_model(client, tmp_path)
    e = client.post("/api/experiments", json=body_for(client, tmp_path, device_id, sweep={"threads": [1, 4]})).json()
    finish(client, token, {variant_id: result(10.0, 10.0, 10.0)})
    runs = client.get(f"/api/experiments/{e['id']}/inspect?image=0").json()["runs"]
    assert sorted((r["variant_label"], r["threads"]) for r in runs) == [("ONNX FP32", 1), ("ONNX FP32", 4)]
