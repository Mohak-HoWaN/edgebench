# Graph Report - project-edgebench  (2026-11-10)

## Corpus Check
- 199 files · ~133,493 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 13 file(s) not represented in the graph (top: (none) 6, .fixture 4, .example 1)

## Summary
- 2426 nodes · 7434 edges · 91 communities (82 shown, 9 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 441 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `176512e8`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Dataset Import Scripts
- Server Settings Tests
- ExperimentDetail.tsx
- json
- Dataset Test Helpers
- Conversion Matrix
- Agent Protocol Tests
- Picture Inspector
- Dataset API
- Checkpoint Pickle Scanner
- RunDetail.tsx
- Benchmark Run Process
- App Shell
- dataset_versions.py
- time
- Model Matrix UI
- Agent API Endpoints
- Detection Evaluation Metrics
- enqueue
- Theme & Priority Settings
- api_runs.py
- typing
- Artifact Store
- Converter Client
- Model API
- Same-Origin Security
- Benchmark Tests
- api_experiments.py
- NewExperiment.tsx
- Decode & NMS
- Project State & Palette
- converter/convert.py
- Migrations & Worker
- test_agent_e2e.py
- TypeScript App Config
- Database & Migrations
- shadcn Components Config
- get
- Web Tooling Dependencies
- api_devices.py
- Runs E2E Tests
- Logging & API Tests
- expand
- Confirm Dialog
- TypeScript Node Config
- Handoff Brief
- Web Runtime Dependencies
- Web Dev Dependencies
- EventHub
- Runtime Runners
- Playwright & Vite Config
- README & Project Plan
- queue.py
- os
- Phase 5 Pi Agent
- Smoke & WebSocket Tests
- NPM Scripts
- Sources
- Models E2E Tests
- calibration.py
- Contrast Tests
- phase4.spec.ts
- TypeScript Root Config
- Phase 0 Verdict
- Phase 2 Brief
- Phase 3 Brief
- Agent Package
- Server Package
- Phase 6 Brief
- s2_bench.py
- Charts & Families Brief
- Phase 0 Brief
- Phase 4 Brief
- test_latency_drift.py
- Worker
- test_repeats.py
- ADR Agent Protocol
- Phase 9 Brief
- Converter README
- ADR Job Queue
- ADR Artifact Store
- ADR Statistics
- STATE.md
- Health
- _comparisons_and_drift
- CLAUDE.md
- dropdowns.spec.ts
- .check_cancelled
- _clean_handlers

## God Nodes (most connected - your core abstractions)
1. `services()` - 64 edges
2. `Services` - 64 edges
3. `Button()` - 57 edges
4. `enrolled()` - 54 edges
5. `get()` - 47 edges
6. `Settings` - 44 edges
7. `Variant` - 44 edges
8. `enqueue()` - 43 edges
9. `upload()` - 38 edges
10. `ImportProblem` - 37 edges

## Surprising Connections (you probably didn't know these)
- `Reuse` --references--> `decode()`  [INFERRED]
  phases/phase-2-models-conversion.md → agent/edgebench_agent/decode.py
- `Dropdown colours (2026-11-10, before Phase 4) - done, not committed` --references--> `NativeSelect()`  [INFERRED]
  STATE.md → web/src/components/Field.tsx
- `Phase 1: scaffold, database, health, frontend shell (2026-11-09) - done` --references--> `CommandDialog()`  [INFERRED]
  STATE.md → web/src/components/ui/command.tsx
- `Architecture` --references--> `speed_pass()`  [INFERRED]
  CLAUDE.md → agent/edgebench_agent/bench.py
- `Traps that already cost time` --references--> `match_predictions()`  [INFERRED]
  CLAUDE.md → agent/edgebench_agent/evaluate.py

## Import Cycles
- 3-file cycle: `server/edgebench/calibration.py -> server/edgebench/dataset_versions.py -> server/edgebench/model_jobs.py -> server/edgebench/calibration.py`
- 4-file cycle: `server/edgebench/calibration.py -> server/edgebench/dataset_versions.py -> server/edgebench/ndjson_import.py -> server/edgebench/model_jobs.py -> server/edgebench/calibration.py`

## Communities (91 total, 9 thin omitted)

### Community 0 - "Dataset Import Scripts"
Cohesion: 0.05
Nodes (49): _attach_coco(), _attach_voc(), _bucket(), choose_calibration(), _coco_box(), _encode(), _find_coco_json(), import_directory() (+41 more)

### Community 1 - "Server Settings Tests"
Cohesion: 0.09
Nodes (63): server(), server_settings(), Acceptance, Build, From Phase 0 (binding; see `docs/phase-0-verdict.md`, `docs/adr/`), Not in this phase, Phase 1: Scaffold, database, health, frontend shell, Risks (+55 more)

### Community 2 - "ExperimentDetail.tsx"
Cohesion: 0.08
Nodes (47): Traps that already cost time, lucide-react, Info(), Insights(), Box, Boxed(), COLOURS, Inspection (+39 more)

### Community 3 - "json"
Cohesion: 0.11
Nodes (20): main(), main(), blob(), ncnn_export(), onnx_fp16(), onnx_fp16_blockresize(), onnx_fp16_ortconv(), onnx_fp32() (+12 more)

### Community 4 - "Dataset Test Helpers"
Cohesion: 0.13
Nodes (41): commit_files(), folder_files(), make_dataset(), upload_file(), wait_version(), engine_of(), image_server(), _Images (+33 more)

### Community 5 - "Conversion Matrix"
Cohesion: 0.11
Nodes (26): Prepared, cache_key(), Op, settings_for(), settings_key(), add_variant(), cancel_variant(), _Conversion (+18 more)

### Community 6 - "Agent Protocol Tests"
Cohesion: 0.10
Nodes (60): add_device(), bearer(), enrolled(), seed_dataset(), seed_model(), short_poll(), start_run(), test_a_baseline_run_names_the_checkpoint_itself() (+52 more)

### Community 7 - "Picture Inspector"
Cohesion: 0.09
Nodes (59): @tanstack/react-query, useConfirm(), AddPictures(), commit(), ClassNameChoice(), FilePicker(), merge(), NewDataset() (+51 more)

### Community 8 - "Dataset API"
Cohesion: 0.08
Nodes (36): archive_dataset(), CalibrationRequest, _check_commit(), _check_model(), Commit, create_dataset(), _dataset_or_404(), DatasetOut (+28 more)

### Community 9 - "Checkpoint Pickle Scanner"
Cohesion: 0.09
Nodes (30): _allowed(), _Global, _read_pickles(), _Refused, scan_checkpoint(), ScanResult, _walk(), checkpoint() (+22 more)

### Community 10 - "RunDetail.tsx"
Cohesion: 0.08
Nodes (50): Section(), limitsQuery(), ExperimentInfo, ExperimentStatus, NewExperiment, PlanInfo, Sweep, useCancelExperiment() (+42 more)

### Community 11 - "Benchmark Run Process"
Cohesion: 0.15
Nodes (10): accuracy_pass(), metrics_dict(), one_picture(), preview_boxes(), speed_pass(), Dataset, Entry, load_rgb() (+2 more)

### Community 12 - "App Shell"
Cohesion: 0.09
Nodes (36): react-router-dom, zustand, AppShell(), NavGroup(), PageSkeleton(), Splash(), useScrollToHash(), Wordmark() (+28 more)

### Community 13 - "dataset_versions.py"
Cohesion: 0.07
Nodes (34): sha256_file(), ImportProblem, _build_bundle_versions(), clean_path(), _collect_files(), diff(), _fail(), finish_build() (+26 more)

### Community 14 - "time"
Cohesion: 0.08
Nodes (19): environment(), _mean(), read_file(), summarise(), row(), start_sampler(), test_a_reading_that_is_not_available_stays_none_and_is_never_zero(), test_a_throttle_flag_in_any_sample_shows_in_the_window() (+11 more)

### Community 15 - "Model Matrix UI"
Cohesion: 0.09
Nodes (45): sonner, AddInt8(), MIN_CALIBRATION, OPS, AddVariant(), OPS, SIZES, ConverterBanner() (+37 more)

### Community 16 - "Agent API Endpoints"
Cohesion: 0.11
Nodes (18): artifact_bundle_file(), _artifact_dir(), artifact_file(), Beat, claim(), _claimed(), enroll(), EnrollRequest (+10 more)

### Community 17 - "Detection Evaluation Metrics"
Cohesion: 0.13
Nodes (20): Accumulator, box_iou(), compute_ap(), match_predictions(), Metrics, _smooth(), test_a_box_survives_the_trip_into_the_model_and_back(), test_letterbox_fits_the_picture_and_pads_with_grey() (+12 more)

### Community 18 - "enqueue"
Cohesion: 0.16
Nodes (22): claim(), enqueue(), request_cancel(), make_stale(), test_a_job_that_fails_while_being_cancelled_is_cancelled_not_retried(), test_a_retry_clears_the_worker_and_the_finish_time(), test_cancelling_a_queued_job_is_immediate(), test_cancelling_a_running_job_sets_a_flag_the_job_can_see() (+14 more)

### Community 19 - "Theme & Priority Settings"
Cohesion: 0.11
Nodes (24): react-dom, PriorityEditor(), ThemeChoiceGroup(), Toaster(), TooltipProvider(), DEFAULT_LIMITS, DriftLimits, LIMITS_KEY (+16 more)

### Community 20 - "api_runs.py"
Cohesion: 0.10
Nodes (18): remove_experiment(), cancel_one(), cancel_run(), cell_label(), get_run(), list_runs(), remove_run(), run_again() (+10 more)

### Community 22 - "Artifact Store"
Cohesion: 0.17
Nodes (9): read(), ArtifactStore, chunks(), test_a_bundle_is_identified_by_its_files_and_stored_once(), test_a_bundle_with_a_subfolder_is_refused(), test_a_stream_is_hashed_while_it_is_written(), test_a_stream_over_the_limit_is_stopped_and_leaves_no_file(), test_leftovers_from_a_killed_run_are_cleared_at_start_up_but_stored_artifacts_are_not() (+1 more)

### Community 23 - "Converter Client"
Cohesion: 0.13
Nodes (8): Converter, ConverterInfo, kill_tree(), _last_result(), Outcome, converter(), test_a_failing_log_callback_does_not_stop_the_converter_output_being_read(), test_a_hung_process_is_killed_at_the_timeout_and_the_end_of_its_output_is_kept()

### Community 24 - "Model API"
Cohesion: 0.11
Nodes (28): add_custom_variant(), add_int8_variant(), archive_model(), _bundle_files(), cancel(), convert_model(), converter_status(), ConverterOut (+20 more)

### Community 26 - "Benchmark Tests"
Cohesion: 0.17
Nodes (21): class_map(), pin_to_cpus(), run(), unpack(), make_dataset(), Oracle, spec(), test_a_class_the_model_does_not_have_is_reported_and_left_out() (+13 more)

### Community 27 - "api_experiments.py"
Cohesion: 0.11
Nodes (28): cancel_experiment(), _config_key(), _earlier_ms(), _expand(), _experiment_or_404(), ExperimentOut, get_experiment(), Item (+20 more)

### Community 28 - "NewExperiment.tsx"
Cohesion: 0.10
Nodes (39): EmptyState(), Props, PageHeader(), Props, Skeleton(), cpuLimits(), DeviceInfo, DeviceKind (+31 more)

### Community 29 - "Decode & NMS"
Cohesion: 0.14
Nodes (12): decode(), iou_one_to_many(), Letterbox, nms(), to_blob(), to_original(), raw_output(), test_decode_suppresses_duplicates_within_a_class_but_not_across_classes() (+4 more)

### Community 30 - "Project State & Palette"
Cohesion: 0.11
Nodes (32): @base-ui/react, class-variance-authority, cn, react, CommandPalette(), LogDialog(), Props, Command() (+24 more)

### Community 31 - "converter/convert.py"
Cohesion: 0.15
Nodes (21): calibration_blobs(), detect_head_nodes(), first_output(), letterbox_blob(), main(), need(), op_ncnn(), op_onnx_fp16() (+13 more)

### Community 32 - "Migrations & Worker"
Cohesion: 0.19
Nodes (6): upgrade(), upgrade(), upgrade(), downgrade(), upgrade(), upgrade()

### Community 33 - "test_agent_e2e.py"
Cohesion: 0.06
Nodes (24): Agent, kill_tree(), bundle_hash(), Cache, Cancelled, Rejected, ServerClient, sha256_file() (+16 more)

### Community 34 - "TypeScript App Config"
Cohesion: 0.09
Nodes (22): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+14 more)

### Community 35 - "Database & Migrations"
Cohesion: 0.11
Nodes (17): _alembic_config(), downgrade(), make_engine(), migrate(), _pragmas(), configure_logging(), create_app(), lifespan() (+9 more)

### Community 36 - "shadcn Components Config"
Cohesion: 0.09
Nodes (21): aliases, components, hooks, lib, ui, utils, iconLibrary, menuAccent (+13 more)

### Community 37 - "get"
Cohesion: 0.15
Nodes (23): get(), JobContext, register(), sleepy(), make_worker(), test_a_failed_heartbeat_write_does_not_stop_later_heartbeats(), beat(), test_a_job_runs_and_its_result_is_stored() (+15 more)

### Community 38 - "Web Tooling Dependencies"
Cohesion: 0.11
Nodes (19): cmdk, eslint, @eslint/js, eslint-plugin-react-hooks, @fontsource/ibm-plex-sans, globals, prettier, shadcn (+11 more)

### Community 39 - "api_devices.py"
Cohesion: 0.17
Nodes (13): add_device(), _device_or_404(), DeviceOut, Enrolment, _issue_enroll_token(), list_devices(), NewDevice, _out() (+5 more)

### Community 40 - "Runs E2E Tests"
Cohesion: 0.15
Nodes (14): addDataset(), addModel(), finishJobs(), FIXTURES, FOLDER, Id, PREDICTIONS, read() (+6 more)

### Community 41 - "Logging & API Tests"
Cohesion: 0.14
Nodes (13): JsonFormatter, _spa(), test_health_counts_queued_jobs(), test_health_degrades_instead_of_failing_when_the_database_breaks(), test_health_reports_database_queue_and_worker(), test_json_log_lines_carry_extra_fields_and_tracebacks(), test_requests_for_an_unknown_host_name_are_refused(), test_spa_does_not_swallow_unknown_api_paths_or_escape_the_folder() (+5 more)

### Community 42 - "expand"
Cohesion: 0.16
Nodes (17): expand(), skip(), median(), Pruned, seconds_for_run(), Subject, subject(), test_a_cpu_that_does_not_exist_prunes_every_run_that_names_it() (+9 more)

### Community 43 - "Confirm Dialog"
Cohesion: 0.24
Nodes (14): Confirm, ConfirmContext, ConfirmOptions, ConfirmProvider(), AlertDialog(), AlertDialogAction(), AlertDialogCancel(), AlertDialogContent() (+6 more)

### Community 44 - "TypeScript Node Config"
Cohesion: 0.12
Nodes (16): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+8 more)

### Community 45 - "Handoff Brief"
Cohesion: 0.15
Nodes (12): HANDOFF (updated 2026-11-10, after Phase 4), Live data on this PC (in `data/`, git-ignored), Not verified, Owner decisions (2026-11-09), Phase 4: decisions I made that the owner may want to change, Run it, Security, Starter prompt for the new session (+4 more)

### Community 46 - "Web Runtime Dependencies"
Cohesion: 0.12
Nodes (16): dependencies, @base-ui/react, class-variance-authority, cmdk, cn, @fontsource/ibm-plex-sans, lucide-react, react (+8 more)

### Community 47 - "Web Dev Dependencies"
Cohesion: 0.12
Nodes (16): devDependencies, @axe-core/playwright, eslint, @eslint/js, eslint-plugin-react-hooks, globals, @playwright/test, prettier (+8 more)

### Community 48 - "EventHub"
Cohesion: 0.19
Nodes (4): events(), _same_origin(), EventHub, test_publishing_after_the_event_loop_closed_never_raises_into_the_worker()

### Community 49 - "Runtime Runners"
Cohesion: 0.13
Nodes (9): kind_for_op(), load_runner(), NcnnRunner, need(), OnnxRunner, OpenVinoRunner, Runner, TorchRunner (+1 more)

### Community 50 - "Playwright & Vite Config"
Cohesion: 0.15
Nodes (7): @axe-core/playwright, @tailwindcss/vite, vite, @vitejs/plugin-react, PATHS, TAGS, api

### Community 51 - "README & Project Plan"
Cohesion: 0.15
Nodes (12): Architecture (unchanged from the prompt, with the rules above), Constraints from this machine (checked 2026-11-09), Definition of done (every phase), EdgeBench, Owner decisions (2026-11-09), Phases, Rules that came out of the JonaRu code and were not in the prompt, Run it (state after Phase 4) (+4 more)

### Community 52 - "queue.py"
Cohesion: 0.23
Nodes (12): Architecture, utcnow(), cancel_requested(), Claimed, complete(), fail(), heartbeat(), mark_cancelled() (+4 more)

### Community 53 - "os"
Cohesion: 0.16
Nodes (11): collect(), _cpu_name(), _gpu(), _pi_model(), package_versions(), free_port(), healthy(), start_server() (+3 more)

### Community 54 - "Phase 5 Pi Agent"
Cohesion: 0.22
Nodes (8): Acceptance, Build, Decide first (Plan agent + ADR), Decided (owner, 2026-11-09), From Phase 0 (binding; see `docs/phase-0-verdict.md`), Phase 5: Raspberry Pi agent and multi-device experiments, Risks, Skills

### Community 55 - "Smoke & WebSocket Tests"
Cohesion: 0.22
Nodes (3): @playwright/test, PAGES, Tracked

### Community 56 - "NPM Scripts"
Cohesion: 0.22
Nodes (9): scripts, build, dev, format, format:fix, lint, preview, test:e2e (+1 more)

### Community 57 - "Sources"
Cohesion: 0.15
Nodes (4): main(), Pdh, _PdhValue, Sources

### Community 58 - "Models E2E Tests"
Cohesion: 0.32
Nodes (6): EVIL, FIXTURES, GOOD, payload(), upload(), uploadAndSettle()

### Community 59 - "calibration.py"
Cohesion: 0.16
Nodes (7): CalibrationProblem, distinct_images(), extract(), plan(), find_version(), head_version(), Artifact

### Community 60 - "Contrast Tests"
Cohesion: 0.33
Nodes (5): BOUNDARY, css, luminance(), ratio(), TEXT

### Community 61 - "phase4.spec.ts"
Cohesion: 0.16
Nodes (13): addDataset(), addModel(), BOXES, FIXTURES, Id, read(), readyVariants(), result() (+5 more)

### Community 62 - "TypeScript Root Config"
Cohesion: 0.40
Nodes (4): compilerOptions, paths, files, references

### Community 63 - "Phase 0 Verdict"
Cohesion: 0.25
Nodes (7): 1. Conversion matrix: what works, 2. Benchmark numbers (this PC, one image, 10 warm-up + 100 timed runs, runtime call only), 3. Findings that change the plan, 4. Regression targets, and what was and was not reproduced, 5. Not verified, 6. Final supported matrix for the first release, Phase 0 verdict

### Community 64 - "Phase 2 Brief"
Cohesion: 0.25
Nodes (7): Acceptance, Build, From Phase 0 (binding; see `docs/phase-0-verdict.md`), Phase 2: Model upload and the conversion matrix, Reuse, Risks, Skills

### Community 65 - "Phase 3 Brief"
Cohesion: 0.25
Nodes (7): Acceptance, Build, From Phase 0 (binding; see `docs/phase-0-verdict.md`), Not in this phase, Phase 3: Datasets, the PC agent, and one benchmark run, Risks, Skills

### Community 70 - "Phase 6 Brief"
Cohesion: 0.25
Nodes (7): Acceptance, Before charts, Build, Owner request, 2026-11-10: charts with interpretations, Phase 6: Results Explorer, Risks, Skills

### Community 71 - "s2_bench.py"
Cohesion: 0.26
Nodes (8): candidates(), compare(), iou(), latency(), main(), make_runner(), run(), prep()

### Community 72 - "Charts & Families Brief"
Cohesion: 0.29
Nodes (6): 1. Charts and how to read them, 2. More model families, 3. More dataset formats and controls, 4. Controls for computer-vision engineers, 5. Suggested order, Brief: charts, more model families, more dataset formats, engineer controls

### Community 73 - "Phase 0 Brief"
Cohesion: 0.29
Nodes (6): Acceptance, Do, Output, Phase 0: Spikes (throwaway checks, no app code), Risks, Skills

### Community 74 - "Phase 4 Brief"
Cohesion: 0.29
Nodes (6): Acceptance, Build, From Phase 0 (binding; see `docs/phase-0-verdict.md`), Phase 4: Telemetry, sweeps, repeats, statistics, drift, INT8, Risks, Skills

### Community 75 - "test_latency_drift.py"
Cohesion: 0.05
Nodes (48): Acceptance, Build, Owner request, 2026-11-10: more model families and dataset formats, Phase 8: Generic ONNX plugins, polish, tests, README, demo seed, Risks, Skills, accuracy_delta(), agreement() (+40 more)

### Community 77 - "test_repeats.py"
Cohesion: 0.11
Nodes (24): finalize(), invalid_repeats(), merge_telemetry(), pool(), stats_ms(), EdgeBench agent, Environments, How a benchmark is measured (+16 more)

### Community 78 - "ADR Agent Protocol"
Cohesion: 0.33
Nodes (5): ADR 0003: Agents poll over HTTP; the browser gets live updates over WebSocket, Alternatives rejected, Consequences, Context, Decision

### Community 79 - "Phase 9 Brief"
Cohesion: 0.33
Nodes (5): Acceptance, Build, Not allowed, Phase 9 (optional): JonaRu bridge, Skills

### Community 80 - "Converter README"
Cohesion: 0.33
Nodes (5): INT8 (Phase 4), Rules the scripts follow, Set it up, The converter environment, Try it by hand

### Community 81 - "ADR Job Queue"
Cohesion: 0.40
Nodes (4): ADR 0001: Job queue is a SQLite table, not Redis, Consequences, Context, Decision

### Community 82 - "ADR Artifact Store"
Cohesion: 0.40
Nodes (4): ADR 0002: Content-addressed artifact store with a toolchain-aware cache key, Consequences, Context, Decision

### Community 83 - "ADR Statistics"
Cohesion: 0.33
Nodes (5): ADR 0004: How latency results and differences are reported, Consequences, Context, Decision, Revisited after Phase 4 (2026-11-10)

### Community 84 - "STATE.md"
Cohesion: 0.15
Nodes (12): class_names(), Dropdown colours (2026-11-10, before Phase 4) - done, not committed, Phase 0: spikes (2026-11-09) - done, with two gaps, Phase 1: scaffold, database, health, frontend shell (2026-11-09) - done, Phase 2 follow-up (2026-11-10): downloads, Phase 2: model upload and the conversion matrix (2026-11-10) - done, Phase 3: datasets, the PC agent and the first benchmark run (2026-11-10) - done, Phase 3 follow-up: the owner's review of 2026-11-10 - done, with the charts left for the brief (+4 more)

### Community 85 - "Health"
Cohesion: 0.29
Nodes (4): _db_health(), DbHealth, Health, counts()

### Community 86 - "_comparisons_and_drift"
Cohesion: 0.43
Nodes (4): _comparisons_and_drift(), _drift_numbers(), inspect_picture(), _predictions()

### Community 87 - "CLAUDE.md"
Cohesion: 0.33
Nodes (4): Code graph (graphify), Commands, Project rules that are easy to miss, What this is

### Community 88 - "dropdowns.spec.ts"
Cohesion: 0.47
Nodes (5): channel(), contrast(), DROPDOWNS, luminance(), Painted

## Knowledge Gaps
- **13 isolated node(s):** `edgebench-agent`, `edgebench-server`, `@fontsource/ibm-plex-sans`, `tailwindcss`, `tw-animate-css` (+8 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 753 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Traps that already cost time` connect `ExperimentDetail.tsx` to `Database & Migrations`, `Detection Evaluation Metrics`, `CLAUDE.md`, `NewExperiment.tsx`, `Project State & Palette`?**
  _High betweenness centrality (0.260) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `Services` (e.g. with `_keep_predictions()` and `_check_commit()`) actually correct?**
  _`Services` has 49 INFERRED edges - model-reasoned connections that need verification._
- **What connects `edgebench-agent`, `edgebench-server`, `@fontsource/ibm-plex-sans` to the rest of the system?**
  _13 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Dataset Import Scripts` be split into smaller, more focused modules?**
  _Cohesion score 0.054136874361593465 - nodes in this community are weakly interconnected._
- **Why does `mclient()` connect `Database & Migrations` to `Server Settings Tests`, `ExperimentDetail.tsx`?**
  _High betweenness centrality (0.141) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `enrolled()` (e.g. with `test_a_baseline_run_gets_the_checkpoint_under_a_name_ultralytics_understands()` and `test_a_crashing_benchmark_fails_one_run_and_the_agent_carries_on()`) actually correct?**
  _`enrolled()` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Should `Server Settings Tests` be split into smaller, more focused modules?**
  _Cohesion score 0.08714247527399091 - nodes in this community are weakly interconnected._