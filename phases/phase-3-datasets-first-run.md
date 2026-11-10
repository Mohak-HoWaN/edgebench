# Phase 3: Datasets, the PC agent, and one benchmark run

**Goal:** import a dataset, start an agent on this PC, run one variant on it, and see accuracy and latency in the app.

## Build
- **Datasets:** import a folder or zip in YOLO format or COCO JSON (auto-detected). Show image count, class distribution, resolution
  histogram, previews with ground-truth boxes. **Capture source per image** (`rpi-cam3-wide`, `mobile`, other), set at import from
  a folder name, a `sources.csv`, or EXIF camera model; the dataset page shows image counts and class counts per source. Mobile
  photos need EXIF orientation applied and may be 12 MP or HEIC: normalise once into a cached working copy (keep originals and
  the hash of the original). Images with no label file are allowed: such a dataset supports speed runs only and accuracy shows
  "n/a (no labels)". Dataset hash = hash of sorted `(filename, bytes-hash, label-hash)`. Tag each dataset
  with its source: `catalogue`, `synthetic`, or `real camera`; results on catalogue images carry a warning banner (they overstate
  accuracy, as `tools/synth_scenes.py` documents).
- **Calibration subset:** mark a subset (default 200 images, seeded) and record exactly which files were used. Hard minimum 50.
- **Agent (PC):** `edgebench-agent` Python package, run on the **host**. Registers with a token, heartbeats, fingerprints hardware
  (OS, CPU, cores, RAM, GPU, library versions), pulls jobs, downloads artifact + dataset with checksum into a local cache, runs,
  uploads results. Outbound calls only.
- **Benchmark runner (first version):** loads one variant with its runtime (ORT / OpenVINO / ncnn / Ultralytics for `.pt`), runs warm-up
  then N measured iterations with `time.perf_counter_ns`, splitting preprocess / inference / postprocess; records model load time and
  first-inference time. No sweeps yet.
- **Accuracy:** one evaluator for all variants, decode + class-aware NMS shared (README rule 1). Compute mAP50, mAP50-95, precision,
  recall, F1, per-class AP, confusion matrix. Start from `project/pipeline/jonaru/evaluate.py` and extend to IoU 0.5:0.95.
- **"This device" panel (Devices page):** the page reads the browser's platform hint and tells the user whether it looks like a PC or
  a Pi, shows the one-line agent install command with a generated token for that device type, and switches to live status when the
  agent connects. The hint can be wrong (Windows on ARM, a 32-bit Pi OS reports `armv8l`), so the recorded type always comes from
  the agent fingerprint, and a mismatch is shown, not hidden. The calibration subset should mix capture sources.
- UI: Datasets page, Devices page (the PC agent, live status), a minimal "Run" form (model variant + dataset + device) and a result
  page with the numbers.

## Acceptance
- **Evaluator cross-check:** on the same dataset, EdgeBench's mAP50 and mAP50-95 for the `.pt` baseline match Ultralytics `model.val()`
  within 0.01. If not, fix the evaluator before anything else; every later number depends on it.
- pytest: AP maths on hand-built detections, dataset hash is stable and changes when one label changes, COCO and YOLO importers
  produce identical boxes for the same content, cache hit on the second dataset download.
- Real: run ONNX FP32 on the 10-image fixture and on a real folder; latency percentiles are present and plausible; stop the agent
  mid-run, the job returns to `queued` or is marked lost, not stuck.

## Skills
`claude-in-chrome` (previews and tables), `diagnosing-bugs` if the evaluator disagrees with Ultralytics, `simplify`, `code-review`,
`run`.

## Not in this phase
Sweeps, repeats, confidence intervals, drift against baseline, telemetry, INT8 (all Phase 4).

## Risks
Dataset not on disk (README open question 3). Large dataset transfer is a no-op on the PC (same disk); keep the cache path anyway
because Phase 5 relies on it.

## From Phase 0 (binding; see `docs/phase-0-verdict.md`)
- Each runtime benchmark runs in **its own subprocess**: ncnn crashed the process natively (access violation, no traceback) when an
  `ncnn.Mat` was built from a temporary array. Hold the source array in a variable until after `clone()`. A crash must mark one run failed,
  not take the agent down.
- Seed dataset for tests and the quickstart: COCO128 (public) with `yolo11n.pt`; it gives labels, so the mAP cross-check against Ultralytics
  `val()` can run before the owner's own dataset exists.
- Agent protocol: ADR 0003. Device type comes from the agent fingerprint, not the browser.

