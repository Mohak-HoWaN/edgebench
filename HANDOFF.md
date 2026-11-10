# HANDOFF (updated 2026-11-10, after Phase 3 and the owner's review of it)

For a Claude session that has none of the earlier conversation. Read this, then `STATE.md` (what is verified and what is not), then
`CLAUDE.md` (commands, architecture, traps). Do not re-decide anything in `docs/adr/0001-0004` or `docs/phase-0-verdict.md` without new
evidence.

## What this is
EdgeBench: a developer tool, used from a browser (also on a Raspberry Pi), that converts a vision `.pt` into ONNX / OpenVINO / ncnn /
TorchScript (/ TensorRT) variants, benchmarks them on the PC and the Pi through agents, checks accuracy drift, and writes a paper from a
template library. Built for the owner's JonaRu shop-billing detector, but generic. Repo root: `...\JonaRu\Development\project-edgebench\`.
Remote: `https://github.com/Mohak-HoWaN/edgebench.git`, branch `main`.

## Owner decisions (2026-11-09)
- A developer tool in a browser; the site detects PC vs Pi (done as a hint; the device's real type comes from the agent). The Pi has its own
  internet, so it may be on another network.
- Dataset is the owner's own: RPi Camera Module 3 Wide plus a phone. No labelled data exists on disk yet.
- No power meter, so no power/energy features. A paper template library (ask which form the user wants).
- Install into virtual envs, never the global Python. Workflow: the owner says "Go on with phase N".
- **Push only when asked.** Pi work targets a development Pi, never the shop's production Pi.
- The owner expects every stage to be *usable*, not just built: after Phase 2 they found no way to download a converted file and no place to
  compare models. Say plainly what a phase does not give yet (comparison is Phase 6) and check the obvious "can I do X with this?" before
  calling a phase done.

## Status
| Phase | State |
|---|---|
| 0 spikes | done (TensorRT engine build never completed: out of memory) |
| 1 scaffold, DB, queue, web shell | done |
| 2 model upload, conversion matrix, downloads | done |
| 3 datasets, PC agent, experiments | **done**, verified on the PC only. The owner's 8-point review (versioned datasets, folders without zip, device-limited threads and CPU pinning, experiments as rows, result priorities, history buttons, custom variants, VOC) is done; **charts, more model families and more dataset formats are only in `docs/brief-charts-and-families.md`** |
| 4 sweeps, repeats, confidence intervals, drift, INT8, telemetry | **next** (`phases/phase-4-telemetry-sweeps-int8.md`) |
| 5-9 | not started |

**Nothing from Phases 0-3 is committed.** The last commit is `f7cd4f4` (plan only). Ask the owner before committing or pushing.

## Run it
```powershell
.\scripts\start-server.ps1            # http://127.0.0.1:8000 ; uses .venv, web\dist, data\, and the converter env it finds
.\scripts\start-agent.ps1 -Token <token>   # token from Devices -> "Get a connection command"; afterwards without -Token
cd server ; ..\.venv\Scripts\python -m pytest -q        # 198 tests, about 2 minutes (one uses the real converter)
cd agent  ; ..\.venv-agent\Scripts\python -m pytest tests -q    # 40 tests
cd web ; npm run typecheck ; npm run lint ; npm run build ; npx playwright test   # build first: the tests serve web/dist
```
Environments (all git-ignored): `.venv` (server, Python 3.12), `.venv-agent` (agent tests: numpy, OpenCV, ONNX Runtime, httpx, plus the
server's dev requirements), `spikes/.venv` (heavy runtime env: torch 2.6.0+cu124, ultralytics 8.3.248, openvino 2026.1.0, ncnn; `httpx` was
added for the agent). The converter and the agent both prefer `spikes/.venv` when no `.venv-converter` exists. A converter environment built
from scratch from `converter/requirements.txt` has never been tried.

## Live data on this PC (in `data/`, git-ignored)
Model 1 `yolo11n` with seven converted variants; dataset 1 `COCO128` (version 1, 128 pictures, 126 annotated; made before versions existed, so it
has no original files); device 1 `This PC`; experiment 1 (the eight first runs, grouped by the migration) and experiment 2 ("Pinned to 8 CPUs").
**The owner runs their own agent** with its identity in `~/.edgebench-agent`; using "Connect again" replaces the device's token, which stops any
other agent started with the old one (this happened during the session: a temporary agent got 401). To start an agent on the owner's identity:
`spikes\.venv\Scripts\python -m edgebench_agent --server http://127.0.0.1:8000 --state-dir %USERPROFILE%\.edgebench-agent` from `agent/`.

## Traps (full list in CLAUDE.md)
Ultralytics decides file type from the extension (the converter and the agent stage `model.pt`); Vite's string proxy sets `changeOrigin` and
breaks the same-origin POST guard (keep the object form, `/agent` is proxied too); Playwright tests the built `web/dist`; shadcn files in
`components/ui/` are patched; zips store timestamps; ncnn crashes natively (hence one subprocess per benchmark); Ultralytics' matcher takes the
first prediction, not the best IoU (copied on purpose in `evaluate.py`); the shell tool mangles backslash escapes in heredocs (use Write/Edit).

## Security
`.pt` upload runs the pickle scanner (`server/edgebench/ptscan.py`): hardened, **not proven, not a sandbox**; an independent review was cut short.
The server binds 127.0.0.1 with no user login; devices authenticate with tokens (hashes stored). Phase 3's new surface (agent routes, folder
import, zip unpacking) has tests but **no independent review**. Do not widen the bind or `allowed_hosts` before Phase 5's review.

## Not verified
TensorRT; anything on a real Pi; accuracy on JonaRu data; Docker with the converter or the agent (the image has neither; the Phase 3 image
was **not** rebuilt after adding Pillow, see STATE.md for whether it was checked); browsers other than Chrome; phone-width layout; HEIC photos;
Linux/macOS agent.

The owner's two review rounds of 2026-11-10 are in `STATE.md`; the second one (metrics, picture inspector, insights, hover hints, sidebar
sub-links, live page, tie-aware best) is done. The owner reviews by using the app: expect more rounds of this kind.

## What the owner asked for that is *not* built yet
Charts with interpretations (17 in the brief), more model families (segment, pose, classify, an ONNX file uploaded directly), more annotation
formats (LabelMe, CVAT, classification folders, CSV, video frames), an Advanced section for detection/runtime/export/quantization settings.
All in `docs/brief-charts-and-families.md` with a suggested order. Say so plainly when asked; do not call a phase done without them being
listed as open.

## Phase 4 questions to settle with the owner before building
1. INT8: which paths (OpenVINO NNCF is the one Phase 0 found good: ~2x faster; ONNX INT8 needs the detect head excluded) and what accuracy gate
   fails a variant?
2. Sweeps: threads 1, 2, 4, 8 and the physical-core count were the Phase 0 plan; how many repeats and what confidence level (ADR 0004)?
3. Telemetry on this PC without admin rights: Windows performance counters and NVML work (Phase 0 finding 9); the thermal zone is not
   necessarily the CPU die.
4. The calibration subset exists (seeded, min 50, mixes sources) but nothing uses it yet.

## Starter prompt for the new session
> Read `project-edgebench/HANDOFF.md`, `STATE.md` and `CLAUDE.md`. Phases 0-3 are done and uncommitted. Start the server with
> `scripts/start-server.ps1` and the agent with `scripts/start-agent.ps1` to confirm they work, then read `phases/phase-4-*.md` and tell me
> the plan and the open questions before writing code. Do not commit or push unless I ask. Use virtual envs only.
