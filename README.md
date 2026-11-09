# EdgeBench

Convert a vision model (`.pt`) into every runtime format and precision, benchmark each variant on each device (this PC, a Raspberry Pi), and turn the results into an interactive dashboard and an IEEE-style paper (PDF + LaTeX + reproduce script).

This folder is a **plan, not code yet**. Build order is in `phases/`; each phase file can be handed to a Claude session as its brief.
It replaces the earlier JonaRu-only "Model Lab" plan (`../dataset/docs/model-lab-portal-plan.md`), whose JonaRu-specific parts
now live in Phase 9 as an optional bridge.

## What was merged from the two ideas

| Topic | Model Lab plan (earlier) | EdgeBench prompt | Decision |
|---|---|---|---|
| Scope | JonaRu only: class remap, cart scenes, promote to `manifest.json` | Generic, any YOLO/ONNX model, any device | **Generic core.** JonaRu parts become a profile + Phase 9 bridge. |
| Frontend | Next.js | React + Vite + Tailwind + shadcn/ui | **Vite SPA** (prompt wins; no server rendering needed for a local tool). |
| Database | stdlib sqlite3 | SQLModel + SQLite WAL + Alembic | **Prompt wins**; migrations matter once several phases add tables. |
| Job queue | threads + log files | arq/RQ + Redis, or SQLite queue | **SQLite-backed queue.** Redis is not installed and has no native Windows build; add a Redis backend only if it is ever needed. |
| Inference/decode | Reuse `project/pipeline/jonaru/detector.py` for ONNX/OpenVINO | Ultralytics + ORT + OpenVINO + ncnn | **One shared decode/eval path for every variant** (see below). Reuse jonaru code where it fits. |
| Accuracy | AP50, precision, recall (`jonaru/evaluate.py`) | mAP50, mAP50-95, per-class AP, drift | Extend the existing evaluator to mAP50-95; **cross-check it against Ultralytics `val()` on the `.pt`** so the numbers are trusted. |
| INT8 | NNCF, refuse under 50 calibration images, accuracy gate | NNCF/ONNX static INT8 with a 200-image seeded calibration set | Keep both rules: seeded 200 default, hard minimum 50, and drift flag against the FP32 baseline. |
| Devices | dev PC only; Pi through result-file import | Agents on PC and Pi, pull model, stream telemetry | **Agents** (prompt wins). Pi install is constrained by how the Pi is managed (below). |
| Reports | Model cards | Full IEEE paper | **Paper** (prompt wins); model card = a one-page export of the same data. |
| Extras kept from Model Lab | Failure browser, hard-example export, cart-scene metric, promotion + rollback, golden set, domain-gap warning | not mentioned | Kept: failure browser in Phase 6, the rest in Phase 9. Domain-gap tag is a dataset field from Phase 3. |

### Rules that came out of the JonaRu code and were not in the prompt
1. **Same decode path for every variant.** The Ultralytics `.pt` path and the ONNX/OpenVINO path give different boxes for the same
   weights (different NMS). Drift numbers are only meaningful if the `.pt` baseline and every export go through one decode + NMS.
   The native Ultralytics run is kept as an extra, labelled "Ultralytics native".
2. **Compare classes by name, never index.** v_0.0.0 and v_0.0.0.2 have different class orders. Each model stores a name list; a
   profile (`profiles/jonaru.yaml`) can map names onto canonical ones.
3. **The PC agent runs on the host, not in Docker.** Docker Desktop on Windows runs in a WSL2 VM, which distorts latency and hides
   CPU affinity and temperatures. Only the server (API, queue, converter, report) goes in `docker compose`.
4. **Known results are regression tests.** `pipeline/models/production/README.md` records that the shipped INT8 drifts (mean score
   difference 0.22 on 9 images) and that `v_0.0.0.2_int8_.onnx` is about 40x slower in ONNX Runtime. EdgeBench must reproduce both.
5. **Thresholds are not tuned to hide a weak detector** (owner's rule). Threshold views are read-only.

## Constraints from this machine (checked 2026-11-09)

| Item | Status | Consequence |
|---|---|---|
| Docker 29.5.3 | present | server via compose works |
| Node v26.7.0 | present | Vite frontend; pin versions in the lockfile, node 26 is very new, so verify each dependency installs |
| NVIDIA RTX 4050 Laptop, 6 GB | present | TensorRT and GPU rows are possible; 6 GB limits engine builds and batch size |
| Redis | missing | SQLite queue (above) |
| LaTeX / Tectonic | missing | Phase 7 installs Tectonic (single binary) and falls back to WeasyPrint |
| Python | default is Anaconda; project envs are Python 3.12 in `.venv` | create `project-edgebench/.venv` on 3.12; do not use Anaconda base |
| Windows | no `taskset` | core pinning uses `psutil.Process.cpu_affinity` on Windows, `taskset`/`sched_setaffinity` on Linux |

## Owner decisions (2026-11-09)

1. **It is a developer tool, used from a browser, including on the Pi.** The website itself detects what it is running on
   (PC or Pi) and offers the right enrolment steps. A browser cannot run native benchmarks, so the page shows a one-line install
   command for the agent (Phase 3 for the PC, Phase 5 for the Pi) and then shows that device live once the agent connects. The
   browser's guess (`aarch64` / `armv8l` Linux) is only a hint; the agent's hardware fingerprint (`/proc/device-tree/model`) is what
   the app records. Agent install is a one-time manual step on a **development Pi**; EdgeBench does not need the fleet agent. Do not
   install it on the shop's production Pi (that one is managed through the fleet agent).
2. **The Pi has its own internet (Wi-Fi, LAN or hotspot)**, so it may not be on the PC's network. Supported modes, checked in Phase 5:
   (a) both on the same network/hotspot, direct to the PC's address; (b) different networks, through a private overlay such as
   Tailscale (or a tunnel). The agent only makes outbound calls, so it works behind NAT in mode (b). The server's address is entered
   once in the install command.
3. **The dataset is the owner's own**, captured with the Raspberry Pi Camera Module 3 Wide and a mobile phone. Datasets therefore
   carry a **capture source per image** (`rpi-cam3-wide`, `mobile`, other), results can be split by source, and images may be
   unlabelled (speed-only runs). Details in Phase 3 and Phase 6. Labelling happens outside EdgeBench (YOLO or COCO export).
4. **No power meter.** Energy per inference and the INA219 feature are dropped everywhere. Temperature, clocks and throttle flags stay.
5. **A paper template library**, not only IEEE. The export dialog asks which template the user wants (Phase 7).

### Still open
- Is the Pi you will use a development Pi (not the shop's)? Assumed yes.
- Which template does your course or venue require, if any? The library starts with the common ones; a required one can be added.

## Architecture (unchanged from the prompt, with the rules above)

```
Browser (React/Vite, on PC or on the Pi) --REST+WebSocket--> Server (FastAPI, SQLite, queue, converter, report) [docker compose]
                                              ^   artifacts: data/artifacts/<sha256>
        outbound polling + telemetry upload   |
                  Agent (PC, host process) ---+--- Agent (Raspberry Pi, pip install, ARM64)
```
Server converts by default; agents build device-specific formats (TensorRT). Artifacts and datasets are content-addressed and cached
on each agent by hash.

## Phases

| # | File | Result you can see |
|---|---|---|
| 0 | `phases/phase-0-spikes.md` | A one-page verdict on each risky dependency (ncnn, OpenVINO on ARM, ONNX INT8, TensorRT, Tectonic) |
| 1 | `phases/phase-1-scaffold.md` | App opens with navigation, themes, health check, empty states |
| 2 | `phases/phase-2-models-conversion.md` | Upload `yolo11n.pt`, see the conversion grid fill in |
| 3 | `phases/phase-3-datasets-first-run.md` | Import a dataset, run one benchmark on the PC with mAP and latency |
| 4 | `phases/phase-4-telemetry-sweeps-int8.md` | Sweeps, repeats, confidence intervals, drift flag, working INT8 |
| 5 | `phases/phase-5-pi-agent.md` | The same experiment runs on the Pi with throttle tracking |
| 6 | `phases/phase-6-results-explorer.md` | Pareto, box plots, heatmaps, compare 4 runs, failure browser |
| 7 | `phases/phase-7-report.md` | Pick a paper template (IEEE, ACM, Springer, Elsevier, arXiv-style...), get PDF + LaTeX zip + reproduce script |
| 8 | `phases/phase-8-plugins-polish.md` | Generic ONNX plugin, tests, README, demo seed |
| 9 | `phases/phase-9-jonaru-bridge.md` | Optional: cart-scene metric, promote to `manifest.json`, hard-example export |

Never start a phase until the previous one's acceptance block passes and a short "State / Not checked" note is added to
`STATE.md` (create it in Phase 1).

## Skills: which to use and when

Skills live in two places. The **user-level ones** below work anywhere. The **project ones** (`architecture`, `frontend-design`,
`diagnosing-bugs`, `graphify`) sit in `project/.claude/skills/` and only apply to files under `project/`. `project-edgebench` is a
sibling folder, so either copy those folders into `project-edgebench/.claude/skills/` or start the session from `project/`.
(I have not copied them; say if you want that.)

| Skill | Use it | Phases |
|---|---|---|
| `ponytail` (installed, level `full`) | Default for backend work: smallest complete change, one self-check per non-trivial logic. Switch with `/ponytail lite` for UI and report polish phases, where the prompt asks for a Linear/Vercel-level finish and `full` will push back on extra polish. | all (lite for 6, 7) |
| `init` | Create `project-edgebench/CLAUDE.md` (commands, conventions, "read STATE.md first") | 1 |
| `architecture` (project) | Write an ADR for each hard-to-reverse choice: queue, agent protocol, artifact store, stats method | 0, 4, 5 |
| `frontend-design` (project) | Visual direction, type, spacing, dark/light tokens before building the shell | 1, 6, 7 |
| `dataviz` | Before any chart code: palette, Pareto/box/heatmap form choice, colour-blind-safe series. Use the same palette in ECharts and in the paper's matplotlib figures so they match | 6, 7 |
| `run` | Launch the server, web app and agent and drive them to confirm a phase works in the real app | every phase |
| `claude-in-chrome` | Look at the real UI in your browser: themes, tables, charts, responsive width. Playwright covers the automated smoke test; this covers "does it look right" | 1, 3, 6, 7 |
| `diagnosing-bugs` (project) | Failed conversions, a latency number that looks wrong, WebSocket drops, the INT8 slowdown | 2, 4, 5 |
| `pdf` | Inspect the generated report: page count, two-column layout, text extraction, figure resolution | 7 |
| `simplify` | After each phase, before review: remove what that phase added but did not need | every phase |
| `code-review` (`medium`) | End of each phase, on the phase's diff | every phase |
| `security-review` | Server bound to LAN, agent tokens, artifact download, plugin sandbox (arbitrary Python runs on devices) | 1, 5, 8 |
| `update-config` / `fewer-permission-prompts` | One-time: allow the repeated safe commands (pytest, npm, docker compose, ruff, mypy) | 1 |
| `graphify` (project) | After the first real code exists, to keep the code graph current | 2 onward |

Not useful here: `artifact-*` (claude.ai pages), `docs`/`docx`/`pptx`/`xlsx`/`google-workspace`, `claude-api`, `schedule`, `loop`
(long benchmarks are tracked in the app itself), `skill-creator` (only if you later want an "edgebench" skill of your own).

Agents: use `Explore` when a phase needs to read existing JonaRu code, `Plan` only at Phase 0 and Phase 5 (the two phases with real
design risk). Everything else is direct work in one session.

## Definition of done (every phase)

- Code runs on this machine, not just compiles: the phase's acceptance commands were executed and their output is in `STATE.md`.
- No stubs, no TODO, no commented-out code in delivered files; a feature that can't be built yet is absent, not faked.
- Python: ruff and mypy clean. Frontend: `tsc --noEmit`, ESLint, Prettier clean.
- Tests listed in the phase pass; one new test for each new branch of non-trivial logic.
- `STATE.md` has a "Not checked" line (for example: "no Pi measured", "only 10-image dataset").
- Nothing pushed without being asked. No secrets in git (agent tokens live in `.env`, git-ignored).
