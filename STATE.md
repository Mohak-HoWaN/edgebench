# STATE

## Phase 0: spikes (2026-11-09) - done, with two gaps
Verdict: `docs/phase-0-verdict.md`. Decisions: `docs/adr/0001` to `0004`. Scripts and raw results: `docs/phase-0/`.

Done and measured on the dev PC: 11 conversions + 4 fix-up variants, latency on 1/4/8 threads, drift against FP32, ncnn crash root cause,
PC telemetry options, Tectonic compile of 7 template classes, Node 26 frontend toolchain, ARM wheel availability (index only).

Not checked:
- TensorRT FP16/INT8 engine build: killed by the system for low memory (4.8 GB free of 15.7 GB). Install and builder init work. Retry with other apps closed.
- Anything on a real Raspberry Pi.
- Accuracy on JonaRu data (all numbers are COCO128 + the COCO yolo11n).
- PDF layout of the templates (compiled only).
## Phase 1: scaffold, database, health, frontend shell (2026-11-09) - done
Server (`server/`): FastAPI app that runs the migrations at start-up, SQLite in WAL mode, SQLite-backed job queue and worker (ADR 0001),
`GET /api/health`, WebSocket `/ws/events` (same-origin only), host-name allowlist, JSON logs, serves `web/dist` with a client-route fallback.
Tables created but empty: models, datasets, devices, experiments, runs, artifacts (jobs is in use). Web (`web/`): Vite + React 19 + strict
TypeScript + Tailwind 4 + shadcn/ui; nine pages with honest empty states, command palette, themes, toasts, confirm dialog.

Verified on this PC (2026-11-09):
- Live crash recovery (`tests/test_process_crash.py`): a real server process claims a job and hangs in its handler, is hard-killed, and a
  second server process on the same database finishes the job as attempt 2 (3.6 s).
- Server: 44 tests (stable over repeated runs), ruff, ruff format, mypy strict. Tests include four threads claiming 60 jobs (each exactly
  once), retries, cancellation (also when the handler then errors), a stale job recovered after a real process was killed, a restarted
  worker finishing a job a dead one left running, a worker that lost its job stopping its handler, a late result from a presumed-dead
  worker being ignored, a failing heartbeat write not killing the heartbeat, migration up/down, the SPA fallback refusing `../` paths and
  answering 404 (not HTML) for a missing file, and the host-name allowlist. Staleness is simulated by back-dating the heartbeat, not by sleeping.
- Web: tsc, ESLint (strict type-checked), Prettier, production build (one chunk per page).
- Browser (real Chrome): 88 tests on the built app: 46 colour-contrast checks (both themes), 16 smoke flows, 24 axe scans (every page, both
  themes, palette and confirm dialog open), 2 WebSocket checks. The same smoke and WebSocket tests (18) pass against the Vite dev server under
  React StrictMode. The WebSocket test was checked by planting the leak: with both safeguards removed it fails (2 open sockets).
- Reviews: `code-review` (medium) returned 11 findings; all were verified against the code and fixed, each with a test (queue and worker
  races, IPv6 host entry that could never match, missing file served as HTML, reset that rewrote its own key, shortcuts firing behind a
  dialog, flaky sleeps). `security-review` found nothing exploitable; its notes: the API has no authentication (by design while loopback-only),
  and `.dockerignore` does not exclude `.env`.
- Lighthouse accessibility: 100 on Dashboard, Models and Settings.
- A clean environment built only from `server/requirements.txt` boots, migrates and serves the app.

Generated shadcn files patched (all in `web/src/components/ui/`, listed so a regenerate does not silently undo them): `command.tsx`
(dialog header moved inside the popup), `button.tsx` (solid destructive variant), `sonner.tsx` (uses our theme store). `CommandDialog` also
needs a `<Command>` wrapper in this shadcn version.

Docker (verified 2026-11-09, Docker 29.5.3): `docker compose build` succeeds (image 259 MB). `docker compose up -d` gives a container that
Docker reports healthy, runs as uid 10001 (not root), is published on `127.0.0.1:8080` only, migrates on first start, and serves the app,
a client route (`/models`), `/api/health`, a 404 for a missing asset and a 400 for a spoofed Host. The WebSocket works through it (same
origin gets `hello`, a foreign origin is refused with 403). A restart keeps the database in the volume and does not re-run the migration;
`docker stop` exits 0. The throw-away container and volume were removed afterwards; the image was kept.

Not checked:
- The Docker image was built with `node:24-slim` while the code was developed on Node 26; the web build passed in the image, but the
  browser tests were not run against the container (they run against their own server).
- Browsers other than Chrome; a phone-width layout (only tablet width, 768 px, was tested); the Pi's browser.
- The permission-prompt allow-list (`update-config` / `fewer-permission-prompts`) was not set up.
- The security review read the code only; Windows path edge cases (alternate data streams, device names) are reasoned, not tested. The pages
  and components were searched for XSS sinks, not read line by line.
- Nothing from Phase 0 or Phase 1 is committed or pushed.

## Phase 2: model upload and the conversion matrix (2026-11-10) - done
Upload a `.pt` (drag and drop or button), it is scanned, read in a separate process, and converted to ONNX FP32/FP16, TorchScript, OpenVINO
FP32/FP16 and ncnn FP32/FP16; each cell shows state, size, time, a check against PyTorch, a log, and Retry/Cancel. Files:
`server/edgebench/{ptscan,artifacts,matrix,converter_client,model_jobs,api_models,security}.py`, `converter/` (own environment, see its
README), web `pages/Models.tsx`, `pages/ModelDetail.tsx`, `components/{UploadZone,ModelMatrix,LogDialog,ConverterBanner}.tsx`.

Verified on this PC (2026-11-10):
- Server: 111 tests, ruff, mypy strict. Includes the full path with the REAL converter and the real `yolo11n.pt` (about 55 s): all 7 variants
  ready, FP32 variants within 1e-3 of PyTorch (measured about 1e-6), FP16 within 2% (measured about 1.6%), sizes equal to the bundles on disk,
  and the converter environment's packages unchanged afterwards. The other tests use a stand-in converter that can be told to fail, go
  missing, hang, mismatch or crash its check.
- Browser (Chrome): 101 tests on the built app, 29 under the Vite dev server (StrictMode); the grid, upload refusals, retry, log, removal,
  accessibility scans of the model screens in both themes. A real run drove the actual UI with the real model: the grid filled in live
  without a reload, 7 of 7 converted, no browser errors; the design was checked in light and dark screenshots.
- Upgrading the Phase 1 database in place (migration 0002) works, including over existing rows.

Reviews: `code-review` returned 11 findings, all fixed with tests (a 500 when cancelling a waiting cell, a hung pipe when the log callback
failed, unexpected zip errors escaping the scanner, a stale cache key on retry, a crash in the check discarding a good conversion, removed
models still queueing work, a 404 flash after removal, and more). The Phase 2 converter also leaked a scratch folder per conversion (16 folders,
147 MB were cleaned up); fixed and checked.

Security review of the upload path found two REAL holes in the pickle scanner; both fixed, each with tests, and every real checkpoint on this
PC still passes:
1. **Dotted global names.** A pickle that declares protocol 4 makes the real unpickler walk `a.b.c.Popen` attribute by attribute, and the old
   rule ("a capitalised name under an allowed namespace") passed `np.f2py.subprocess.Popen`, which resolves to `subprocess.Popen`
   (demonstrated: the same technique resolved `pathlib.Path`; `subprocess.Popen`, `multiprocessing.Process` and others were found reachable).
   Now: protocol above 2, STACK_GLOBAL and friends, and any global whose name is not a single identifier are refused.
2. **Calling classes with data from the file.** The scanner judged names only. A hostile pickle could *call* `DetectionModel("https://...")`
   with REDUCE; that constructor downloads the URL into the working directory and builds layers from it. Real checkpoints only ever *create*
   these classes (NEWOBJ). Now the scanner walks the pickle stack and allows REDUCE only on the ten data-rebuilding callables real checkpoints
   use (measured on 11 checkpoints); `torch._tensor._rebuild_from_type_v2`, which calls a function it is handed, was removed.
The scanner is still **not a sandbox**: BUILD can set attributes on allowed objects, and Ultralytics then runs methods on them. The converter
runs in its own process, with auto-install off, and the user is told to upload only models they trust.

Generated-file note: the `.venv-converter` setup is documented but was not built from scratch here; the converter used was the Phase 0
environment (same pins).

Not checked:
- The independent security sub-review was cut short (its last response was stopped by a safety classifier), so I did not get its findings on:
  zip parsing differences between Python's `zipfile` and PyTorch's reader (duplicate members, odd prefixes), whether PyTorch unpickles any member
  other than `data.pkl`, and other opcode tricks on allowed classes. The two holes above came from my own testing plus its partial report. Treat the
  scanner as hardened, not proven.
- Cross-site POST protection was tested with fabricated Origin headers (server tests and Playwright), not from a real second website.
- A converter environment built from `converter/requirements.txt` on a clean machine; Docker (the image does not contain the converter).
- Models other than YOLO detect (segment, pose, classify) and files over a few hundred MB.

### Phase 2 follow-up (2026-11-10): downloads
The converted files could not be downloaded, which made the conversion matrix of little use. Added `GET /api/variants/{id}/download` (the
file itself for ONNX and TorchScript, a zip for the multi-file OpenVINO and ncnn bundles), `GET /api/models/{id}/download` (every finished
variant in one zip, one folder per variant), Download buttons in the grid and a "Download all converted (zip)" button, and a sentence on the
model page saying the cells are one model in different formats, not separate models. Checked with the real `yolo11n`: the downloaded
ONNX FP32 has exactly the reported size and loads in ONNX Runtime; the zip holds all 13 files. Tests: server 3, browser 1.

## Phase 3: datasets, the PC agent and the first benchmark run (2026-11-10) - done
Built: dataset import (zip upload or a folder path; YOLO or COCO detected; EXIF-upright, 1920 px cap, upright JPEGs stored byte for byte;
capture source per image from `sources.csv`, folder name or camera EXIF; origin tag with a catalogue warning; seeded calibration subset,
minimum 50; previews with ground-truth boxes), the agent (`agent/`, own README), the agent protocol of ADR 0003 (`/agent/enroll`, `claim`
long poll, `heartbeat`, `result`, resumable `artifacts`), devices with one-time enrolment tokens (hashes only stored) and a "This device"
hint, runs (`/api/runs`: create, list, cancel, run again, remove), the shared decode/NMS path, the evaluator (mAP50, mAP50-95, P, R, F1,
per-class AP, confusion matrix) and the benchmark process (ONNX Runtime, OpenVINO, ncnn, TorchScript and the `.pt` baseline, each run in its
own process). UI: Datasets (+ detail), Devices, New experiment (the run form), Results (+ run detail).

Verified on this PC:
- **Evaluator cross-check (the Phase 3 gate).** COCO128 + `yolo11n.pt`, 640 px: EdgeBench mAP50 0.6761 and mAP50-95 0.5076 against
  Ultralytics `model.val()` 0.6753 and 0.5099 (limit 0.01). Method: the same decode settings as the validator (confidence 0.001, IoU 0.7,
  300 detections, multi-label). Remaining difference: Ultralytics evaluates with rectangular batches and counts the 2 label-less pictures as
  background; EdgeBench leaves label-less pictures out of accuracy. Re-encoding JPEGs cost about 0.006 mAP50-95, so upright JPEGs are now kept
  byte for byte.
- **Real runs through the live app**, agent on this PC, 4 threads, COCO128 (all eight finished): ONNX FP32 / OpenVINO FP32 / ncnn FP32 /
  TorchScript / the `.pt` baseline all give exactly 0.6761 / 0.5076; the FP16 variants are within 0.001 of that (0.6768 to 0.6772). Median
  time per image: ONNX 28.0 ms, OpenVINO 27.5, ncnn FP32 51.1, TorchScript 50.0, `.pt` 55.6 (model alone: 21.7 / 22.0 / 45.8 / 43.8 / 49.0).
  These agree with Phase 0 (ONNX 20.8 ms, ncnn 36 ms at 4 threads, measured on one image, runtime call only).
- **Agent killed mid-run** (the process and its benchmark child, with the hard kill): the run showed "lost" 36 s later and the device went
  offline; nothing stayed "running".
- Server 166 tests (importer 19, dataset API 12, agent protocol and runs 21), agent 36 tests (AP maths on hand-built detections, letterbox,
  NMS, the benchmark process with a runtime that knows the answers, the real agent against the real server: crash, cancel, resume, cache hit,
  unreachable server), browser 116 tests on the built app and 32 on the Vite dev server (new: `runs.spec.ts`, 13 tests including axe scans
  of the dataset, device, run-form and run pages in both themes), ruff, ruff format, mypy strict, ESLint, Prettier, tsc.
- Migration 0003 applied to a copy of the real database (with models and variants in it) and reversed.

Design choices worth knowing:
- The server's own worker never takes a benchmark (`queue.AGENT_JOB_TYPES`); an agent takes only jobs queued for its device. A benchmark has
  one attempt: if the agent disappears the run is **lost**, not silently repeated on a warmer machine ("Run again" repeats it on purpose).
- A run that cannot be done (runtime missing, model will not load) and a dataset that cannot be imported are outcomes of the job, not job
  failures (the Dashboard's failed count stays for real faults), as with conversion cells.
- Classes are matched by name. A class the dataset has and the model does not is reported and left out. A dataset with no class names is
  matched by position and says so.
- A picture with no label file is "unlabelled" and is left out of accuracy (Ultralytics treats it as background). A dataset where none have
  labels runs for speed only and shows "n/a (no labels)".

Not checked:
- **Nothing on a real Raspberry Pi.** The agent has only run on this PC. A Pi on another network cannot reach the server yet: it binds
  127.0.0.1 and refuses other Host names (Phase 5). The Devices page says so.
- **Accuracy on the owner's own data.** All numbers are COCO128 with a COCO model; no JonaRu dataset exists on disk yet. The COCO128
  dataset in the live database is tagged "real camera" (the tag is fixed at import) although it is public photos.
- HEIC photos (refused with a message), very large datasets (a 12 MP phone set was not imported; the cap and the EXIF path are unit-tested
  with small pictures), COCO files with polygons or crowd annotations beyond the basic cases.
- Windows only. Linux and macOS are untested for the agent (the code has Linux branches: `/proc/cpuinfo`, `/proc/device-tree/model`).
- INT8, the calibration subset being used for anything (Phase 4), sweeps and confidence intervals (Phase 4), temperature (Phase 4).
- No independent code review or security review was run for Phase 3 (done in Phases 1 and 2). New attack surface: the agent routes, the
  folder-path import (reads a directory on this machine, copies pictures into the store), zip unpacking. Tested: zip entries that escape
  their folder, a hostile Origin on every browser POST/DELETE, tokens stored as hashes, revoked tokens, other devices' jobs.
- The agent keeps the device token in `~/.edgebench-agent/agent.json` unencrypted (it can only act as that device).
- **The Docker image was not rebuilt after Phase 3** (Docker Desktop was not running when I finished). Phase 3 added `pillow==13.0.0` to
  `server/requirements.txt`, which the image installs, and the image has neither the converter nor the agent. Run `docker compose up --build`
  and open the Datasets page before relying on it.

## Phase 3 follow-up: the owner's review of 2026-11-10 - done, with the charts left for the brief
The owner used the app and raised eight points. What each became:
1. **No "What are these pictures?" field; datasets work like a repository.** The picture-kind tag is gone (pictures always come from a camera).
   A dataset is a name plus a history of **versions**; each save is a version with a message, a change summary (+added, -removed, ~changed) and
   its own statistics. Any version can be **downloaded** (the original files, or the normalised copy the agents read), **restored** (makes a new
   version with those files; nothing is deleted), **used in an experiment**, and the whole dataset can be **shared** as one bundle file that
   another EdgeBench imports with its history. Files are stored once by hash and shared between versions. A run records the exact version.
   Server: `dataset_versions.py`, `api_datasets.py`, migration 0004.
2. **No zip needed.** Choose photos, choose a folder, or drop either on the box; annotation files among them are picked up (YOLO txt +
   data.yaml, COCO json, Pascal VOC xml, new); photos alone make a dataset for speed runs, and the page says so. A zip is still accepted, and a
   folder on the server's machine can be read by path.
3. **Threads follow the device.** The experiment form limits threads to what the selected device reports (this PC: 24 threads, 16 physical
   cores), shows that number, and the server refuses more (422 naming the limit). **Pinning to CPUs** is available ("0-7,16"); the benchmark
   process sets its CPU affinity before the runtime starts and the result records which CPUs were used.
4. **Experiments.** The form takes a name and notes and a set of model variants (several models, "select all"), one dataset version and
   one device, and starts one run per variant. Results shows **one row per experiment**; opening it shows the variants. Up/Down/Enter walk the
   rows. The 8 runs made before experiments existed were gathered into one experiment by the migration.
5. **Result priorities in Settings.** An ordered list of metrics (mAP50-95, mAP50, F1, precision, recall, median time, 95th percentile time,
   load time). The first ranks the rows on an experiment page; the columns follow the order; the best in each column is marked; the choice is
   kept in this browser.
6. **More variants.** "Add a conversion of your own" on the model page: any format and precision at another input size (a multiple of 32), or
   an unsimplified ONNX export; the cells it is built from are added too; the grid has one table per input size. Pascal VOC import added.
   More model families and dataset formats are in the brief, not built.
7. **Charts: in the brief, not built** (as the owner said): `docs/brief-charts-and-families.md` lists 17 charts with the question each answers,
   how to read it, the red flags the page should call out and the data each needs, plus the build order.
8. **Back and forward buttons** at the top left of the workspace, always visible; back is off on the first page you opened, forward only after
   going back, and opening a new page cuts off what was ahead.

Verified (2026-11-10): server 192 tests (new: versions, uploads, bundles, VOC, experiments, CPU limits, custom variants, migration), agent 38
tests (new: CPU pinning), browser 124 tests on the built app and 40 on the Vite dev server (new `runs.spec.ts`: loose photos, whole folder, zip,
failed zip and discard, add/restore/download/share, bundle import, device limits, a six-run experiment followed live and ranked, priorities in
Settings kept across a reload, keyboard walk of Results, history buttons, run/experiment removal, custom conversion, axe scans of eight pages
in both themes), ruff, mypy strict, ESLint, Prettier, tsc. Migration 0004 applied to the real database (the COCO128 dataset became version 1,
the earlier runs became one experiment) and a real pinned experiment ran on this PC: ONNX FP32, OpenVINO FP16 and ncnn FP32 on CPUs 0-7, results
recorded as pinned to 0-7, 99 threads and a non-existent CPU refused. The Phase 2 and 3 acceptance runs were not repeated.

Found while doing it: an empty YOLO label file (a picture with nothing in it) was refused as an empty upload; it is now allowed for `.txt`.
Deleting an experiment needs its runs flushed first (SQLAlchemy does not order the deletes without a relationship). A bundle whose picture
already exists in the store is not re-checked against the bundle's copy (it is not read), which is correct, and tested with a file the store
does not have.

Not checked:
- **Dropping a folder on the box** (the drag-and-drop path, `webkitGetAsEntry`) has no automated test: Playwright cannot build a directory
  drop. Choosing a folder with the folder button, choosing photos and choosing a zip are tested. Try it by hand.
- Uploading thousands of photos (one request per file, three at a time) and 12 MP phone photos; only small pictures were used. Storage grows by
  one normalised copy per version (upright JPEGs are the same bytes as the originals, so the cost is mostly for converted files).
- Pinning and the thread limit were checked on this PC only. The hybrid-core numbers were not investigated: the pinned run to CPUs 0-7 was
  slower than the unpinned one on this laptop (ONNX FP32: 33.7 ms median pinned against about 28 ms unpinned in Phase 3), which shows that "the
  first CPUs" are not necessarily the fast ones.
- Share/import was tested between two datasets on the same server, not between two machines.
- A version made before versions existed (the migrated COCO128) has no original files: it can be run, previewed and downloaded normalised,
  not restored or downloaded as files (the page says so). Docker was not rebuilt.
- The history buttons use React Router's entry numbers; a page opened in a new tab starts at back-off. Alt+Left and Alt+Right are the browser's
  own and work as well.

## Quick add-ons (2026-11-10, later the same day)
- **NDJSON datasets.** Upload a `.ndjson` (or `.jsonl`) file in the dataset picker. Format: the Ultralytics one (a `dataset` line with
  `class_names`, then one `image` line per picture with `file`, optional `url`, `split` and `annotations.boxes`). Pictures sent along are
  matched by file name; the others are fetched from their `url`. The file is expanded into the usual `images/<split>/`, `labels/<split>/` and
  `data.yaml`, so versions, previews and runs work as for any dataset (`ndjson_import.py`). Only http/https and **public** addresses are
  fetched (every redirect re-checked), 50 MB per picture, size and count caps; a trusted image server on your own network needs
  `EDGEBENCH_ALLOW_PRIVATE_NDJSON_URLS=true`. Known limit: the address is checked and then connected to by name, so a hostile DNS server could answer
  differently the second time. Not checked: a real Ultralytics-exported NDJSON file (only files written to the spec in the tests), and a large
  one with thousands of URLs.
- **Delete an experiment with a typed confirmation.** The experiment page has "Delete experiment": the dialog asks "Do you really want to
  delete <name>?" and the button stays disabled until you type `delete <name>` exactly (case matters). It works while the experiment is running:
  waiting runs are cancelled, a run on the agent is told to stop on its next heartbeat, and its late result is ignored. The same typed
  confirmation is available to any other dialog via `typeToConfirm`; only experiments use it so far.
- Tests: server 197, browser 125.

## Second review round (2026-11-10, evening) - done
Seven recommendations from the owner, and what each became:
1. **Metrics, not three judges.** More metrics (accuracy, mean IoU, missed objects, false alarms, wrong class, images per second, on top of the
   earlier mAP50-95, mAP50, F1, precision, recall, median and 95th percentile time, load time); a chooser on the experiment page edits the
   same list as Settings; the Settings section is called "Metrics you judge by" and says that none of them is the one right way (`lib/metrics.ts`).
   Accuracy, missed, false alarms and wrong class are worked out from the confusion matrix (so they exist for old runs); mean IoU is new in the
   agent and only present for runs made after this change.
2. **Pictures next to the parameters.** On the experiment page the dataset version's pictures sit to the right of the parameters. Choosing one
   shows the real boxes and what *each run* found in it, side by side, with a confidence cut-off slider. For this the agent now keeps every
   picture's detections (confidence 0.25 and up, 50 per picture, first 3000 pictures; also for datasets with no annotations), the server stores
   them as one file per run in the artifact store, and `GET /api/experiments/{id}/inspect?image=N` returns them. Runs made before this have no
   detections and the panel says so.
3. **The "left out because the model has no such class" line is gone** (the data is still in the result).
4. **"i" hints and insights.** Static help is now a small "i" that explains on hover or keyboard focus (page headers, section titles, field
   labels, column headings; the text is also the button's name for screen readers). The freed space holds **Insights**: sentences worked out from
   the data, such as the fastest variant and its images per second, which runs are tied on accuracy and who is fastest of them, the speed-up and
   accuracy change against the PyTorch baseline, what did not finish, how far repeats of a variant disagree (experiment page); throughput, where
   the time goes, steady or uneven, the weakest class, the rank in the experiment (run page) (`lib/insights.ts`).
5. **Sidebar sub-links.** Under the page you are on, the sidebar lists its parts and jumps to them (Models: Add a model, Your models; Datasets:
   Create a dataset, Your datasets, Other ways in; Devices: Add a device, Your devices; New experiment and Settings too). The Datasets page now
   lists Create first.
6. **Run again** now returns a "Watch live" action, the **Live run page exists** (every running and waiting run with progress, plus the last
   finished ones), and a run made again is **tinted and numbered "run again #2"** in its experiment.
7. **"Best" with ties.** Rows are ordered by your metrics in turn (a tie on the first is settled by the second, and so on), values count as equal
   at the precision shown, and a column where several runs tie gives its "best" to the run that leads by the whole order. If every run is
   identical on every metric, nothing is marked.

Verified: server 198 tests, agent 40, browser 131 (built app) and 47 (Vite dev server; includes the new ones: sidebar sub-links, hover hints,
insights and the metric chooser, ties, run again and the live page, the picture inspector, and axe scans of the redesigned pages in both
themes), ruff, mypy, ESLint, Prettier, tsc. A real five-variant experiment plus one repeat ran on this PC and was inspected in the browser: every
variant's box on the zebra picture shows next to the real one; two inconsistencies in the insight sentences (the "most accurate" run disagreeing
with the table's tie-break, "-0.0 points") were found by looking at it and fixed.

Not checked: the hover hints on a touch screen (hover does not exist there; focus does); how the page looks at phone width; the inspector with
thousands of pictures (it loads 18 thumbnails at a time and one picture's detections per click, reading the run's whole detections file each
time, which is cached for the last 8); a dataset with no annotations in the inspector (the unit test covers the agent side only).
Old runs show no mean IoU and no inspector detections: run them again.

## Repository and the code graph (2026-11-10)
The work was committed to `main` in phase order (0 to 3, then the docs and the graph). Each commit holds its files in their **final**
state, not as they were when that phase ended: the intermediate states were never saved, so an early commit on its own does not build
(for example `main.py` in Phase 1 imports routers that arrive in Phases 2 and 3). Check out the last commit to run anything.

`graphify-out/` is a code graph built with `graphify extract . --code-only` and refreshed with `graphify update .` (2083 nodes, 6379 edges,
85 communities; documents are not in it). `graph.json`, `GRAPH_REPORT.md` and the community labels are committed; the HTML view, cache and
manifest are rebuilt locally. The graphify hook for Claude Code was **not** installed (the installer edits Claude Code settings and was
blocked); run `graphify claude install` yourself if you want it. Not checked: that the graph answers well for questions outside the few tried
(an agent claim, `evaluate.py`), and that `graphify update` on another machine gives the same communities.

## Dropdown colours (2026-11-10, before Phase 4) - done, not committed
Dropdown lists were grey on grey: a native `<select>` draws its list from its own background, and ours was translucent. Selects now have a
solid `bg-background` and `text-foreground` (`Field.tsx`, `index.css`), and the raw `<select>` in `DatasetUpload.tsx` became `NativeSelect`.
`e2e/dropdowns.spec.ts` reads the colours the browser will paint (select and options, both themes) and checks they are opaque, readable (4.5:1)
and the same; it fails against the old styles (checked). Only the two dropdowns that need no data (Settings, Devices) are covered by it.

## Phase 4: sweeps, repeats, telemetry, accuracy check, INT8 (2026-11-10) - done, verified on this PC only
**What exists.** *Repeats:* a run is N timed rounds repeated R times (default 20 warm-up and 200 timed, 3 repeats; "Quick look" is 5/50/1), each
repeat with its own warm-up; the headline is the mean of the repeats' medians with a 95% Student t interval, and a run with one repeat says it
has no error bar (`stats.py`, `latency.py`, ADR 0004). *Comparison:* each converted run is tested against the `.pt` baseline at the same
settings with Welch's test; "not significant" is said in the table and in the insights. *Sweeps:* the wizard varies thread counts, CPU sets
(`0-7; 8-15`) and input sizes; `POST /api/experiments/plan` shows the run count, an estimated time (from earlier runs of that conversion on that
device, else a 40 ms guess, and it says which) and every combination left out with its reason (more threads than CPUs, a CPU that does not exist,
no finished conversion at that size, the `.pt` only at its own size). Cancel keeps finished runs; **Resume** remakes only cancelled and lost
runs (refused while any run is still going or stopping). *Telemetry:* `telemetry.py` runs as its own process at 5 Hz (per-core CPU, RSS of the
benchmark tree, clock, temperature, throttle flag where there is one, GPU through NVML); what cannot be read is `null` and shown as "not available".
The environment (power plan or governor, cores) is recorded. A repeat is invalid when a throttle flag was up or its clock averaged more than 10%
below where the run started; invalid repeats are left out of the numbers, a run with none left is "invalid for latency" and out of speed rankings.
*Accuracy check:* every converted run is compared with the `.pt` baseline of the same model: mAP and per-class AP deltas, mean box agreement
(each baseline detection against the variant's best box; a miss counts 0), class flips; pass/fail uses limits set in Settings (default: mAP50 may
drop 5 points, agreement at least 0.80); a variant that finds nothing always fails. *INT8:* OpenVINO NNCF and ONNX static QDQ (detect head found
as the highest `/model.N/` and left in float), added from the model page, calibrated on at least 50 *different* pictures of a dataset version
(`calibration.py`; the list is stored, so a variant knows which pictures); never made by "convert everything".

**Measured on this PC (yolo11n, COCO128, 128 pictures, 4 threads, 3 repeats, real agent, throw-away server):**
| Variant | Median per image (95% interval) | vs `.pt` | mAP50 | Box agreement | Accuracy check |
|---|---|---|---|---|---|
| PyTorch `.pt` | 55.9 +/- 1.3 ms | | 0.676 | | baseline |
| ONNX FP32 | 30.0 +/- 3.8 ms | 1.86x, real | 0.676 | 1.000 | pass |
| OpenVINO FP32 | 27.4 +/- 2.0 ms | 2.04x, real | 0.676 | 1.000 | pass |
| OpenVINO INT8 (128 pictures) | 17.0 +/- 0.7 ms | 3.28x, real | 0.641 (-3.5 pts) | 0.825 | pass (5 pts / 0.80) |
| ONNX INT8 (128 pictures) | 25.0 +/- 0.4 ms | 2.23x, real | 0.610 (-6.6 pts) | 0.738 | **fail** |
The default limits were chosen from this table: they keep OpenVINO INT8 (kept in Phase 0) and fail ONNX INT8 (experimental in Phase 0). That is one
model on one dataset; the owner should set them for their own data.
- *Calibration regression* (the repo's old recipe): OpenVINO INT8 calibrated on one picture repeated 50 times: mAP50 0.620 (-5.6 pts), agreement
  0.709, **fails**; on 128 different pictures: 0.641 (-3.5), 0.825. Fewer than 50 different pictures, or copies of one, are refused by the server
  and by the converter (tests for both).
- *24-run sweep* (6 conversions x 1, 2, 4, 8 threads, 2 repeats, no accuracy pass): 80 s against an estimated 119 s. Cancelled after 8 runs, resumed:
  the 8 finished runs were untouched (same finish times), 23 of 24 combinations done and **one cancelled** because the run that was still
  stopping when I resumed was not replaced. That was a real edge; resume now refuses while a run is going or stopping (test added, the sweep not
  rerun). Median per image at 1, 2, 4, 8 threads: ONNX FP32 72.5, 42.2, 27.6, 21.9 ms; OpenVINO INT8 37.6, 23.3, 16.5, 13.2 ms; ONNX INT8 50.4,
  32.3, 25.3, 25.5 ms (no gain from 4 to 8 threads).
- *Telemetry cost.* Interleaved and rotated, three rounds of five repeats with 25 s of cooling between runs, OpenVINO FP32 at 4 threads: no sampler
  27.0 +/- 0.4 ms, full sampler 26.3 +/- 0.5 ms, without temperature 26.7 +/- 0.3, without clock and temperature 27.1 +/- 0.4. No slowdown is
  measurable; the 0.7 ms gap is in the *faster* direction and is the size of the drift between rounds, which the intervals do not include.
  An earlier, un-rotated attempt (telemetry on straight after the 24-run sweep) gave 37 to 65 ms per repeat with the clock 20 to 30% below
  start and 8 of 10 repeats marked invalid: the machine was hot (the ACPI zone read 90 to 97 degrees C), the telemetry-off runs could not flag it, and the marking
  worked as designed. **Lesson for results on this laptop: it throttles after a few minutes of load; repeats and the clock rule exist because of it.**
- Verified counts: server 248 tests, agent 58, browser 146 on the built app and 58 on the Vite dev server (the Phase 4 spec has 11 tests: plan and
  pruning, nothing-can-run, quick/full, intervals and "not significant", the zero-detection model failing the check, limits in Settings kept
  and reset, a throttled run, repeats and machine on the run page, cancel and resume, INT8 refused with too few pictures, axe in both themes),
  ruff, mypy strict, ESLint, Prettier, tsc. The real-converter test now also converts both INT8 files from COCO128 pictures.
- The statistics module was checked against scipy 1.18.1 (Welch t, p and df identical to six places, t quantiles to 1e-12).

**Not checked, and limits to know.**
- **Anything on a Raspberry Pi** (`vcgencmd get_throttled` is in the code and untested; ARM INT8 speed unknown). Linux and macOS agents untested.
- **Windows has no throttle flag** without administrator rights, so only the clock-drop rule marks a repeat there; the temperature is the ACPI
  thermal zone (the chassis), not the CPU die. GPU readings come from NVML and were not validated against another tool.
- **Batch-size sweeps are not built** (every conversion is batch 1; the brief asked for 1, 4, 8) and **TensorRT** still is not.
- The time estimate does not model threads (the same figure for 1 and 8 threads), so a one-thread sweep runs longer than it says.
- The accuracy-check limits come from one model and one dataset. Per-class drift is in the API (`drift.per_class_ap50_delta`) but not shown yet.
- The 24-run sweep and the overhead tests ran on a throw-away server (port 8011, data in `%TEMP%\eb_e2e`); the live app was not used and **has not
  been restarted**: migration 0005 (`experiments.plan`) applies the next time it starts, and it needs the new web build (`npm run build`).
  Experiments made before this have no saved plan, so they cannot be resumed.
- An INT8 file is checked against PyTorch only by shape and finiteness at conversion time ("Accuracy: check it in an experiment" in the grid).
- No independent code or security review of the new endpoints (`/int8`, `/plan`, `/resume`) or the calibration extraction. The Docker image was
  not rebuilt (the server has new modules and Pillow since Phase 3).
- The calibration pictures come from the normalised dataset zip, so INT8 sees the same pictures the benchmark sees: calibrating and judging on
  the same dataset flatters the result. Use a separate dataset (or version) for calibration when it matters.

## Results columns (2026-11-10, after Phase 4)
The Results page showed two "Best" columns; it now shows the first **three** metrics of "Metrics you judge by", in that order (fewer if fewer are
chosen). The experiment page still shows all chosen metrics. The choice is kept in the browser's `localStorage` **per address**: `localhost:8000`
and `127.0.0.1:8000` are different places and do not share it. Test: `e2e/phase4.spec.ts` (headers follow Settings, only three, kept on reload).

## Picture inspector fixes (2026-11-11)
- Each run's caption in the picture inspector now names its **threads** (and pinned CPUs) and its run number, so the runs of a thread sweep are no
  longer all "v_0.0.0.2_, ONNX FP32". `GET /api/experiments/{id}/inspect` returns `threads` and `cpu_list` per run.
- A box label **wraps** (up to 7.5 rem wide) instead of being cut with an ellipsis; it sits above its box, inside the box when the box touches the
  top, and grows leftwards from boxes on the right half, so it stays inside the picture. Test: `e2e/phase4.spec.ts` (captions, wrapping, label
  inside the picture). `e2e/websocket.spec.ts` "reconnects after the server closes it" failed once in a full run and passed three times alone: a
  timing flake, not investigated.
- Not checked: labels on boxes that fill the whole picture, and labels longer than three lines.
