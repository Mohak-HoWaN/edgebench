# Phase 8: Generic ONNX plugins, polish, tests, README, demo seed

**Goal:** non-YOLO models work through a small plugin, the whole product is tested end to end, and a new user gets from clone to
results in five minutes.

## Build
- **Plugin system:** a plugin is one Python file defining `task` (detect / classify / segment), `preprocess(image) -> tensor`,
  `postprocess(outputs, meta) -> predictions`. Ship two examples: a generic detector and a classifier (use a small public ONNX model
  with a licence that allows redistribution, or none shipped and a documented download).
- **Sandbox:** a plugin runs in a **subprocess** with a timeout, no network, restricted environment, and file access limited to its
  temp dir, on the server (validation) and on agents (benchmarking). Validate by running it on one synthetic input and checking output
  shapes before it can be selected. Uploading a plugin shows its source and an explicit "this runs code on your devices" confirmation.
  State plainly in the docs what the sandbox does not stop (on Windows a subprocess is weaker than a container).
- **Polish:** loading and error states everywhere, keyboard shortcuts documented in the palette, empty states reviewed, consistent
  spacing, accessibility pass, Settings page (defaults, drift threshold, storage cleanup with a dry-run preview and confirmation).
- **Tests:** pytest for converters, metrics, stats; Playwright smoke for upload -> convert -> import -> run -> results -> report.
- **Demo seed script:** populates models, datasets, devices (one simulated Pi clearly labelled "demo"), experiments and results so the
  UI can be explored at once. Seeded data is marked and removable.
- **README:** one-command PC setup, one-command Pi agent install, a 5-minute quickstart with `yolo11n.pt` and a sample dataset,
  troubleshooting (missing TensorRT, Tectonic offline, throttling, firewall).
- **Final run:** execute the whole quickstart from a clean checkout and write what passed and what did not into `STATE.md`.

## Acceptance
Clean clone -> `docker compose up` + `edgebench-agent` on the host -> quickstart completes. Plugin that raises, hangs, or tries to
open a socket is stopped and reported without taking the agent down. Full test suites green.

## Skills
`security-review` (the sandbox is the highest-risk code in the project), `code-review` at `high` on the whole tree, ponytail's
`ponytail-audit` for a whole-repo audit (bugs, load, risky untested code, deletion candidates), `simplify`, `claude-in-chrome`, `run`.

## Risks
Plugin sandboxing on Windows is limited; do not describe it as secure isolation. Keep example plugins tiny.

## Owner request, 2026-11-10: more model families and dataset formats
See `docs/brief-charts-and-families.md`, sections 2 to 4: segment/pose/classify, an ONNX file uploaded directly, more annotation formats (LabelMe, CVAT, classification folders, CSV, video frames) and the engineer controls (Advanced section of the experiment form).
