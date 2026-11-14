# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

EdgeBench converts a vision model (`.pt`) into every runtime format and precision, benchmarks each variant on each device (this PC, a Raspberry
Pi), and turns the results into a dashboard and a paper. It is built in phases (`phases/phase-0` to `phase-9`, each file is that phase's brief).
**Read `STATE.md` first**: it says what is built, what was verified, and what was not. Update it before ending a session. Phases 0 to 4 are done (models and
conversion, datasets, the PC agent, experiments, sweeps with repeats and confidence intervals, telemetry, the accuracy check, INT8); the Pi,
reports and the JonaRu bridge (Phases 5 to 9) do not exist yet, so `Reports` is an honest empty state. `HANDOFF.md` is a short brief for a fresh session.

Decisions that are binding live in `docs/adr/0001` to `0004` (queue, artifact store, agent protocol, statistics) and `docs/phase-0-verdict.md`
(which conversion variants work and which were dropped). Do not re-decide them without evidence.

## Code graph (graphify)

`graphify-out/graph.json` is a graph of the code: files, functions, classes, imports and calls (about 2000 nodes, 160 code files, in named
communities; `graphify-out/GRAPH_REPORT.md` is the overview). Ask it before reading many files or grepping: it costs a few hundred tokens
where reading costs thousands.

```powershell
graphify query "how does an agent claim and run a benchmark" --budget 1500   # a traversal around the question
graphify explain "claim()"                       # one node and its neighbours (who calls it, what it imports)
graphify path "Agent" "ArtifactStore"            # the shortest chain between two things
graphify affected "Accumulator"                  # what depends on it (reverse traversal)
graphify god-nodes --top 15                      # the most connected nodes
graphify update .                                # after changing code: re-extract, no API key needed; commit graph.json
```

It covers code only (built with `graphify extract . --code-only`); the documents (STATE.md, the ADRs, the briefs) are not in it, so keep
reading those. A node shows its file and line (`src=server/edgebench/api_agent.py loc=L111`), so open that spot instead of the whole file. If the
graph looks stale (`GRAPH_REPORT.md` names the commit it was built from), run `graphify update .`. Community names come from an LLM
(`graphify label .`); `update` renames changed communities by their hub until that is rerun. The Claude Code hook (`graphify claude install`)
is **not** installed: it edits Claude Code's own settings, which was not authorised.

## Commands

Windows PowerShell; on Linux use `.venv/bin/python`. One venv at the repo root serves the server (`.venv`); `spikes/.venv` is a separate, heavy
(torch, OpenVINO, TensorRT) environment for Phase 0 experiments and is git-ignored.

```powershell
# server (run from server/)
..\.venv\Scripts\python -m pytest -q
..\.venv\Scripts\python -m pytest tests/test_queue.py::test_failures_retry_until_attempts_run_out -q    # one test
..\.venv\Scripts\python -m ruff check . ; ..\.venv\Scripts\python -m ruff format --check . ; ..\.venv\Scripts\python -m mypy .
..\.venv\Scripts\python -m edgebench                       # API on 127.0.0.1:8000, runs migrations at start-up

# web (run from web/)
npm run dev          # Vite on :5173, proxies /api and /ws to :8000
npm run typecheck ; npm run lint ; npm run format ; npm run build
npx playwright test                                   # needs `npm run build` first: it serves web/dist from a real server on :8765, in real Chrome
npx playwright test smoke -g "palette"                # one spec / one test
$env:E2E_DEV = "1"; npx playwright test websocket smoke runs   # same tests against the Vite dev server (React StrictMode)

# agent (run from agent/; its own environment holds numpy, OpenCV, ONNX Runtime, httpx and the server's dev requirements)
..\.venv-agent\Scripts\python -m pytest tests -q ; ..\.venv\Scripts\python -m ruff check .

# the easy way to run it all by hand
.\scripts\start-server.ps1 ; .\scripts\start-agent.ps1 -Token <token from the Devices page>
```

A phase is not done until all of the above pass; add one test per new branch of non-trivial logic. The pinned runtime dependencies are in
`server/requirements.txt` (what the Docker image installs) and `server/requirements-dev.txt`; web dependencies are exact versions in `package.json`.

## Architecture

**One process serves everything.** `server/edgebench/main.py` `create_app()` runs Alembic migrations, opens SQLite (WAL), starts the job `Worker`
in a thread, and serves the API, `/ws/events` and, when `EDGEBENCH_WEB_DIST` is set, the built web app with an `index.html` fallback so client
routes survive a reload. In development Vite serves the pages and proxies to the API; the proxy keeps them same-origin, which the WebSocket
origin check depends on. `TrustedHostMiddleware` (setting `allowed_hosts`) refuses unknown `Host` names (DNS rebinding); tests must list
`testserver`.

**Job queue (ADR 0001).** `queue.py` is the whole state machine: every transition is a single SQLAlchemy Core statement (so a claim is atomic across
workers), and completion calls take the `Claimed` handle and apply only if the job is still on that attempt, so a presumed-dead worker cannot
overwrite its retry. `worker.py` claims, heartbeats from a side thread, and maps handler outcomes (`Cancelled`, `PermanentError`, any other
exception = retry until `max_attempts`). Handlers are registered with `@worker.register("type")`; none exist in production code yet. Stale jobs are
recovered by `queue.requeue_stale` on the worker's first loop and every `stale_seconds/3`. Handlers will run converters and benchmarks in
**subprocesses** (see traps below); the worker only supervises.

**Events.** The worker thread calls `EventHub.publish`, which hops onto the event loop with `call_soon_threadsafe`; `/ws/events` fans events out
to browsers. The web app invalidates the health query on `job.*` events.

**Database conventions.** Timestamps are timezone-aware UTC (`models.utcnow`); SQLModel's datetime column raises on naive values. Statements that
touch jobs use the Core table (`inspect(Job).local_table`) so the UTC type applies; do not pass `datetime` to raw SQL (Python 3.12 deprecates the
sqlite adapter). Schema changes are migrations in `server/edgebench/migrations/versions` (batch mode, because SQLite cannot alter in place).
There is no `alembic.ini`: build the config with `edgebench.db._alembic_config(path)`, migrate a throw-away database to head, then
`command.revision(cfg, message=..., autogenerate=True)` against it and review the file by hand.

**Web.** `lib/nav.ts` is the single source for the sidebar, the command palette and the `g`-then-letter shortcuts. Pages are lazy route chunks; the
root route has a `HydrateFallback` (without it the app is blank until the first chunk loads, and early key presses are lost). Colours are tokens in
`src/index.css`, defined once for light and dark; `e2e/contrast.spec.ts` parses that file and checks WCAG AA pairs, so a new token pair belongs in
that test. `lib/connection.ts` keeps one WebSocket: its state must stay inside the effect run (React runs effects twice in development; shared
state leaves an orphan socket), and `e2e/websocket.spec.ts` guards it.

**Models and conversion (Phase 2).** `POST /api/models` streams a `.pt` to `artifacts/tmp` while hashing it (`artifacts.py`, content-addressed,
ADR 0002), runs `ptscan.scan_checkpoint` on it, and only then stores it and queues an `inspect` job. Handlers in `model_jobs.py` start child
processes through `converter_client.py`: `converter/inspect_pt.py` reads the model card, then `ensure_matrix` queues one `convert` job per cell
of `matrix.OPS`; each runs `converter/convert.py` (own Python environment, `EDGEBENCH_CONVERTER_PYTHON`), which converts, then compares with
PyTorch. A failed conversion is a cell state (`failed`, `unavailable`, `cancelled`), not a job error. The scanner (`ptscan.py`) is a security
control: it reads pickle opcodes without running them, refuses protocol above 2, dotted global names and any REDUCE on a global outside
`_REDUCIBLE` (the ten callables real checkpoints use), because `DetectionModel("https://...")` and `np.f2py.subprocess.Popen` were both real
bypasses. Do not widen its allowlists without checking against real checkpoints and adding an attack test. `security.same_origin` guards every
POST/DELETE against cross-site pages. Tests use a stand-in converter (`server/tests/fake_converter`, driven by `FAKE_BEHAVIOR`); the one
real end-to-end test (`tests/test_real_converter.py`) skips when `spikes/.venv` and a sample model are absent.

**Model compatibility (guards G1 to G5).** A checkpoint made by a newer Ultralytics than the converter has is not refused by the library: it loads and
is decoded wrongly, and the PyTorch-versus-converted check passes because both sides share the wrong reading. So `inspect_pt.py` also reports the file's
own `version` / `train_args.model`, `compat.py` (pure) turns that into a card on the model (`incompatible` blocks conversion, with a plain message that
blames the converter, not the model), variants record the converter versions that built them (`Variant.toolchain`, `compat.stale_reason`; stale cells are
refused in runs and rebuilt on request), and `RunOut.diagnosis` points at the tools when a result looks wrong. `docs/brief-model-compatibility-guards.md`.

**Datasets, agent, experiments and runs (Phase 3).** A dataset is a name and a history of `DatasetVersion`s (`dataset_versions.py`,
`api_datasets.py`). A version is a manifest (path, SHA-256, size per file); the files are in the artifact store by hash and shared between
versions. A commit uploads files one by one (`POST .../blobs`, nothing changes yet) and then `POST .../commit` queues the `build_version` job,
which lays the manifest out as a folder (hard links), runs `dataset_import.py` over it and stores the **normalised zip** the agents read
(`data.json` with relative boxes and capture sources, plus `images/*.jpg`; upright JPEGs are kept byte for byte because re-encoding shifted mAP).
Restore is a commit whose base is an older version; share is a bundle zip (every manifest plus the blobs) rebuilt by the `import_bundle` job.
A build that cannot finish (no pictures, bad label, nothing changed) leaves a failed version with the reason; it is a job *outcome*, not a
failed job. Agents never see the database: `api_agent.py` is the whole protocol (enrol with a one-time token, long-poll `claim`, `heartbeat`,
`result`, `artifacts` with `Range`). Jobs of type `benchmark` carry a `device_id`; `queue.claim` gives the server's worker only non-agent jobs
and an agent only its own device's. An **experiment** (`api_experiments.py`) is a named set of runs sharing a dataset version, a device and
settings; it validates every item first, so all its runs start or none do. A run (`api_runs.py`) is one variant, or the `.pt` baseline, on
one dataset *version* on one device; its status is derived from its job unless the agent reported an outcome; thread counts and CPU lists are
checked against the device's reported logical CPUs. The agent (`agent/edgebench_agent`) runs every benchmark in a child process (`bench.py`,
which pins CPUs first when asked); `decode.py` is the one preprocess/decode/NMS path and `evaluate.py` the one evaluator (both numpy only),
checked against Ultralytics `val()`. The agent's tests drive the real agent against the real server in-process (`agent/tests/conftest.py`
puts `server/` on the path), so they need `.venv-agent`. Web: `lib/metrics.ts` holds the result metrics and the owner's priority order (kept
in the browser); `lib/history.ts` feeds the back/forward buttons from the router. The charts, more model families and dataset formats are in
`docs/brief-charts-and-families.md`.

**Sweeps, repeats, telemetry, drift and INT8 (Phase 4).** A run is `repeats` timed rounds, each with its own warm-up (`bench.py`
`speed_pass`; ADR 0004). The agent (`agent.py` `_run_child`) starts `telemetry.py` as a **separate process** beside the benchmark child (5 Hz,
NDJSON; Windows performance counters through `ctypes`/pdh, psutil, `vcgencmd` on a Pi, NVML if present); a reading the machine cannot give is
`null`, never 0. `repeats.py` (pure) merges the samples into each repeat's window, marks a repeat invalid when a throttle flag was up or the
clock averaged more than 10% below where the run started, and pools the valid ones; a run with no valid repeat is "invalid for latency" and
is left out of speed rankings. The server computes everything derived **when a run is read**, so old runs show the same way: `latency.py`
(headline = mean of repeat medians, Student t interval; `compare` = Welch test against the baseline run at the same settings), `drift.py`
(mean box agreement with the baseline's detections, mAP and per-class AP deltas, class flips, pass/fail against limits that the browser sends as
query parameters, defaults in `Thresholds`), `stats.py` (no scipy; checked against scipy in the tests). `sweep.py` (pure) expands
variant x threads x CPU sets x input size, prunes what cannot run with the reason, and estimates the time; `api_experiments.py` has `/plan`,
`/resume` (remakes only cancelled and lost runs) and keeps the plan in `Experiment.plan`. INT8: `OpenVINO INT8` (NNCF) and `ONNX INT8` (QDQ, the
detect head found as the highest `/model.N/` prefix and kept in float) are `matrix.OPS` with `calibrated=True`, so "convert everything" never
makes them; `calibration.py` picks at least 50 **different** pictures (by content hash) from a dataset version, stores the list in the artifact
store and keeps only its hash in the variant's settings; the converter refuses fewer than 50 distinct pictures too. Whether an INT8 variant is
still good is the accuracy check in an experiment that also holds the `.pt` baseline, not a tolerance.

## Traps that already cost time

- **shadcn-generated files are patched** (`web/src/components/ui/command.tsx`, `button.tsx`, `sonner.tsx`; listed in `STATE.md`). Regenerating them
  undoes the fixes (a palette header outside the popup, a destructive button below 4.5:1 contrast, `next-themes`). `CommandDialog` needs an explicit
  `<Command>` child. ESLint and Prettier skip `components/ui`.
- Pin `typescript@~6.0`: `typescript-eslint` does not support 7. `create-vite` ships oxlint; this project uses ESLint.
- **Never run conversions or benchmarks in the API process or with Ultralytics auto-install on.** Set `YOLO_AUTOINSTALL=False`; Ultralytics once
  replaced the pinned CPU `onnxruntime` with `onnxruntime-gpu` mid-export. Pin torch and both OpenCV packages with a constraints file.
- `ncnn.Mat(arr[0].copy())` crashes the interpreter (the temporary is freed before `.clone()`); keep the array in a variable. Native crashes
  cannot be caught, which is why each runtime benchmark gets its own subprocess.
- For ONNX FP16 use `onnxruntime.transformers.float16.convert_float_to_float16` (the `onnxconverter-common` output does not load); INT8 ONNX needs the
  detect head excluded or it returns zero detections; the accuracy gate must catch that. Details and numbers: `docs/phase-0-verdict.md`.
- Playwright tests the *built* app: forgetting `npm run build` means testing stale code.
- **Vite's string proxy shorthand turns on `changeOrigin`**, which rewrites `Host` but not `Origin`, so the same-origin guard answered 403 to every
  POST in dev. `vite.config.ts` uses the object form with `changeOrigin: false`; keep it.
- **Ultralytics decides what a file is from its extension** and the store names files by hash: the converter scripts copy the checkpoint to
  `model.pt` first. The stand-in converter cannot catch bugs like this; only the real-converter test can.
- **Ultralytics' matcher takes the first prediction, not the best-overlapping one** (`match_predictions`: the re-sort by IoU is commented out
  upstream). `evaluate.py` copies that on purpose; "fixing" it moves mAP away from `model.val()`. Predictions must arrive sorted by confidence.
- A zip stores timestamps and Pillow's encoder is version-dependent: dataset identity is the hash over the *originals* (`dataset_hash`), never
  the hash of the normalised zip.
- In a Bash heredoc or a Python string given to the shell tool, apostrophes and backslash escapes get mangled (a \n written as two
  characters became a real newline, a \0 became a NUL byte). For code files use the Write or Edit tool, and check generated files for stray
  control characters (grep calling a file binary is the symptom).
- Help text is an `<Info>` (a button named by its text, tooltip on hover or focus), not a paragraph: the tooltip is not in the page until hovered,
  so tests find it with `getByRole("button", { name: /.../ })`, and a label such as "Timed rounds" also matches an Info whose text contains it
  (use `exact: true`). Room freed this way belongs to computed content (`lib/insights.ts`), never to more static prose.
- "Best" and ranking live in `lib/metrics.ts` (`compareRuns`, `bestByMetric`): ties are broken by the next metric in the person's order, with
  values compared at the precision shown. Insights must use the same functions (`bestRun(..., tieBreakers)`, `sameResult`) or they contradict the table.
- SQLAlchemy does not order deletes between tables that have no `relationship()`: delete the child rows and `session.flush()` before deleting
  the parent, or the foreign key fails (experiments and their runs).
- An empty YOLO `.txt` label file is real data (a picture with nothing in it); do not reject empty uploads for labels.
- A bundle's file that is already in the store is skipped, not re-verified against the bundle's copy; to test the checksum check, use a file the
  store has never seen.
- On Windows a venv's `python.exe` is a launcher that starts the real interpreter as a child, so `Popen.pid` is not the pid the process reports
  for itself. The telemetry sampler sums memory over the whole child tree for that reason, and its test compares against the process tree.
- Windows gives no throttle flag without administrator rights: a throttled repeat there is caught only by the clock dropping more than 10%.
  The temperature is the ACPI thermal zone (the chassis), not the CPU die; the page says so. None of this was checked on a Raspberry Pi.
- A hook called after an early `return` in a React component fails the lint (`usePlan` in `NewExperiment.tsx` sits above the loading return on purpose).
- Shared pytest fixtures live in `server/tests/conftest.py` (`mclient` and `fake_env` moved there); importing a fixture into a test module trips ruff F811.
- A zip stores a timestamp, so test fixtures that must be byte-identical (dedupe by hash) set a fixed `date_time`.
- In PowerShell a double backtick inside a double-quoted string is an escape, which silently breaks text replacement of Markdown-style code spans;
  use single-quoted strings or the edit tool.

## Project rules that are easy to miss

- Compare classes by name, never by index; every variant, including the `.pt` baseline, must go through one shared decode and NMS path, or drift
  numbers measure NMS differences instead of quantization.
- Agents run on the real machine, never in Docker (Windows Docker runs in a VM and distorts latency and temperatures); only the server is in `docker-compose.yml`.
- A run that cannot be done, or a dataset that cannot be imported, is an outcome shown on the run or dataset, not a failed job; failed jobs on the
  Dashboard mean a real fault. A benchmark has one attempt (lost, never silently repeated).
- Do not tune thresholds to hide a weak detector; threshold views are read-only. No power or energy measurement (the owner has no meter).
- Pi work targets a development Pi, not the shop's production Pi (that one is managed through the fleet agent, no SSH).
- The server binds `127.0.0.1` by default. Any other `EDGEBENCH_HOST` is refused unless an owner password exists (`python -m edgebench set-password`, ADR 0005); the login is built but **not reviewed by anyone else**, and `allowed_hosts` still has to list the names used.
- Nothing is pushed without being asked. `data/`, `spikes/`, models (`*.pt`, `*.onnx`, `*.bin`, `*.engine`) and `.env` are git-ignored.
- State plainly what was not tested. `docker compose up --build` was verified in Phase 1 (see `STATE.md`); re-verify it after changing the
  `Dockerfile`, `server/requirements.txt` or the web build, since the unit and browser tests do not run against the image.
