# Graph Report - project-edgebench  (2026-11-10)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2083 nodes · 6379 edges · 85 communities (75 shown, 10 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 404 edges (avg confidence: 0.92)
- Token cost: 39,464 input · 1,033 output

## Graph Freshness
- Built from commit: `7c57d8b4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Dataset Import Scripts
- Server Settings Tests
- Experiments UI
- Model Converter Ops
- Dataset Test Helpers
- Conversion Matrix
- Agent Protocol Tests
- Picture Inspector
- Dataset API
- Checkpoint Pickle Scanner
- Dataset Upload UI
- Benchmark Run Process
- App Shell
- Dataset Versions & Builds
- Agent Test Fixtures
- Model Matrix UI
- Agent API Endpoints
- Detection Evaluation Metrics
- Project Docs & Database
- Theme & Priority Settings
- Runs API
- Agent Client Protocol
- Artifact Store
- Converter Client
- Model API
- Same-Origin Security
- Benchmark Tests
- Experiments API
- Shared UI Components
- Decode & NMS
- Project State & Palette
- Agent Artifact Cache
- Migrations & Worker
- Agent End-to-End Tests
- TypeScript App Config
- Database & Migrations
- shadcn Components Config
- NDJSON Dataset Import
- Web Tooling Dependencies
- Web API Client
- Runs E2E Tests
- Logging & API Tests
- Agent Main Loop
- Confirm Dialog
- TypeScript Node Config
- Handoff Brief
- Web Runtime Dependencies
- Web Dev Dependencies
- Server Core & Events
- Runtime Runners
- Playwright & Vite Config
- README & Project Plan
- Server Client
- Device Fingerprint
- Phase 5 Pi Agent
- Smoke & WebSocket Tests
- NPM Scripts
- Process Crash Test
- Models E2E Tests
- Dataset Job Handlers
- Contrast Tests
- Dataset Archiving
- TypeScript Root Config
- Phase 0 Verdict
- Phase 2 Brief
- Phase 3 Brief
- Agent Package
- Server Package
- Phase 6 Brief
- Conversion Job Runner
- Charts & Families Brief
- Phase 0 Brief
- Phase 4 Brief
- Phase 8 Brief
- CPU Pinning
- Agent README
- ADR Agent Protocol
- Phase 9 Brief
- Converter README
- ADR Job Queue
- ADR Artifact Store
- ADR Statistics
- Upload Size Limit

## God Nodes (most connected - your core abstractions)
1. `services()` - 61 edges
2. `Services` - 59 edges
3. `Button()` - 55 edges
4. `get()` - 47 edges
5. `Settings` - 44 edges
6. `enqueue()` - 43 edges
7. `enrolled()` - 41 edges
8. `Variant` - 39 edges
9. `upload()` - 36 edges
10. `ImportProblem` - 35 edges

## Surprising Connections (you probably didn't know these)
- `Reuse` --references--> `decode()`  [INFERRED]
  phases/phase-2-models-conversion.md → agent/edgebench_agent/decode.py
- `Architecture` --references--> `PermanentError`  [INFERRED]
  CLAUDE.md → server/edgebench/worker.py
- `Architecture` --references--> `DatasetVersion`  [INFERRED]
  CLAUDE.md → server/edgebench/models.py
- `Traps that already cost time` --references--> `match_predictions()`  [INFERRED]
  CLAUDE.md → agent/edgebench_agent/evaluate.py
- `Decision` --references--> `cancel_requested()`  [INFERRED]
  docs/adr/0001-job-queue.md → server/edgebench/queue.py

## Import Cycles
- None detected.

## Communities (85 total, 10 thin omitted)

### Community 0 - "Dataset Import Scripts"
Cohesion: 0.05
Nodes (49): _attach_coco(), _attach_voc(), _bucket(), choose_calibration(), _coco_box(), _encode(), _find_coco_json(), import_directory() (+41 more)

### Community 1 - "Server Settings Tests"
Cohesion: 0.10
Nodes (54): server(), server_settings(), Acceptance, Build, From Phase 0 (binding; see `docs/phase-0-verdict.md`, `docs/adr/`), Not in this phase, Phase 1: Scaffold, database, health, frontend shell, Risks (+46 more)

### Community 2 - "Experiments UI"
Cohesion: 0.07
Nodes (62): Traps that already cost time, Insights(), ExperimentInfo, ExperimentStatus, NewExperiment, STATUS_WORDS, useCancelExperiment(), useExperiment() (+54 more)

### Community 3 - "Model Converter Ops"
Cohesion: 0.07
Nodes (43): first_output(), main(), need(), op_ncnn(), op_onnx_fp16(), op_onnx_fp32(), op_openvino(), op_torchscript() (+35 more)

### Community 4 - "Dataset Test Helpers"
Cohesion: 0.13
Nodes (41): commit_files(), folder_files(), make_dataset(), upload_file(), wait_version(), engine_of(), image_server(), _Images (+33 more)

### Community 5 - "Conversion Matrix"
Cohesion: 0.13
Nodes (23): cache_key(), Op, settings_for(), settings_key(), add_variant(), cancel_variant(), ensure_matrix(), _find_cached() (+15 more)

### Community 6 - "Agent Protocol Tests"
Cohesion: 0.14
Nodes (43): add_device(), bearer(), enrolled(), seed_dataset(), seed_model(), short_poll(), start_run(), test_a_baseline_run_names_the_checkpoint_itself() (+35 more)

### Community 7 - "Picture Inspector"
Cohesion: 0.12
Nodes (34): useConfirm(), Box, Boxed(), COLOURS, Inspection, PictureInspector(), Button(), buttonVariants (+26 more)

### Community 8 - "Dataset API"
Cohesion: 0.08
Nodes (37): CalibrationRequest, _check_commit(), _check_model(), Commit, create_dataset(), _dataset_or_404(), DatasetOut, download_version() (+29 more)

### Community 9 - "Checkpoint Pickle Scanner"
Cohesion: 0.09
Nodes (30): _allowed(), _Global, _read_pickles(), _Refused, scan_checkpoint(), ScanResult, _walk(), checkpoint() (+22 more)

### Community 10 - "Dataset Upload UI"
Cohesion: 0.12
Nodes (39): react, sonner, AddVariant(), OPS, SIZES, AddPictures(), commit(), ClassNameChoice() (+31 more)

### Community 11 - "Benchmark Run Process"
Cohesion: 0.12
Nodes (14): accuracy_pass(), main(), metrics_dict(), one_picture(), preview_boxes(), speed_pass(), stats(), Dataset (+6 more)

### Community 12 - "App Shell"
Cohesion: 0.09
Nodes (38): @base-ui/react, cn, lucide-react, react-router-dom, zustand, AppShell(), NavGroup(), PageSkeleton() (+30 more)

### Community 13 - "Dataset Versions & Builds"
Cohesion: 0.14
Nodes (19): _keep_predictions(), sha256_file(), _build_bundle_versions(), _collect_files(), diff(), _fail(), finish_build(), _ingest_folder() (+11 more)

### Community 14 - "Agent Test Fixtures"
Cohesion: 0.08
Nodes (9): cpu_freq_under_load(), power_plan(), sampler(), sampler_process_cost(), timers(), wmi_thermal(), get_settings(), sleepy() (+1 more)

### Community 15 - "Model Matrix UI"
Cohesion: 0.15
Nodes (29): ConverterBanner(), Cell(), FORMATS, groupKey(), ModelMatrix(), percent(), PRECISIONS, STATE (+21 more)

### Community 16 - "Agent API Endpoints"
Cohesion: 0.08
Nodes (30): artifact_bundle_file(), _artifact_dir(), artifact_file(), Beat, claim(), _claimed(), enroll(), EnrollRequest (+22 more)

### Community 17 - "Detection Evaluation Metrics"
Cohesion: 0.13
Nodes (19): Accumulator, box_iou(), compute_ap(), match_predictions(), _smooth(), test_a_box_survives_the_trip_into_the_model_and_back(), test_letterbox_fits_the_picture_and_pads_with_grey(), boxes() (+11 more)

### Community 18 - "Project Docs & Database"
Cohesion: 0.05
Nodes (64): Architecture, Commands, Project rules that are easy to miss, What this is, utcnow(), cancel_requested(), claim(), Claimed (+56 more)

### Community 19 - "Theme & Priority Settings"
Cohesion: 0.16
Nodes (17): react-dom, PriorityEditor(), ThemeChoiceGroup(), Toaster(), TooltipProvider(), apply(), readChoice(), resolve() (+9 more)

### Community 20 - "Runs API"
Cohesion: 0.14
Nodes (19): cancel_run(), check_cpu_settings(), create_run(), get_run(), list_runs(), NewRun, prepare_run(), Prepared (+11 more)

### Community 21 - "Agent Client Protocol"
Cohesion: 0.18
Nodes (3): kill_tree(), Cancelled, Rejected

### Community 22 - "Artifact Store"
Cohesion: 0.19
Nodes (9): read(), ArtifactStore, chunks(), test_a_bundle_is_identified_by_its_files_and_stored_once(), test_a_bundle_with_a_subfolder_is_refused(), test_a_stream_is_hashed_while_it_is_written(), test_a_stream_over_the_limit_is_stopped_and_leaves_no_file(), test_leftovers_from_a_killed_run_are_cleared_at_start_up_but_stored_artifacts_are_not() (+1 more)

### Community 23 - "Converter Client"
Cohesion: 0.13
Nodes (8): Converter, ConverterInfo, kill_tree(), _last_result(), Outcome, converter(), test_a_failing_log_callback_does_not_stop_the_converter_output_being_read(), test_a_hung_process_is_killed_at_the_timeout_and_the_end_of_its_output_is_kept()

### Community 24 - "Model API"
Cohesion: 0.12
Nodes (26): add_custom_variant(), archive_model(), _bundle_files(), cancel(), convert_model(), converter_status(), ConverterOut, download_all() (+18 more)

### Community 26 - "Benchmark Tests"
Cohesion: 0.22
Nodes (16): class_map(), run(), make_dataset(), Oracle, spec(), test_a_class_the_model_does_not_have_is_reported_and_left_out(), test_a_dataset_without_labels_runs_for_speed_and_says_accuracy_is_not_available(), test_a_dataset_without_names_is_matched_by_position_and_says_so() (+8 more)

### Community 27 - "Experiments API"
Cohesion: 0.11
Nodes (18): cancel_experiment(), _experiment_or_404(), ExperimentOut, get_experiment(), inspect_picture(), Item, list_experiments(), NewExperiment (+10 more)

### Community 28 - "Shared UI Components"
Cohesion: 0.20
Nodes (19): EmptyState(), Props, PageHeader(), Props, Section(), Skeleton(), UploadZone(), send() (+11 more)

### Community 29 - "Decode & NMS"
Cohesion: 0.13
Nodes (12): decode(), iou_one_to_many(), Letterbox, nms(), to_blob(), to_original(), raw_output(), test_decode_suppresses_duplicates_within_a_class_but_not_across_classes() (+4 more)

### Community 30 - "Project State & Palette"
Cohesion: 0.08
Nodes (37): class-variance-authority, Phase 0: spikes (2026-11-09) - done, with two gaps, Phase 1: scaffold, database, health, frontend shell (2026-11-09) - done, Phase 2 follow-up (2026-11-10): downloads, Phase 2: model upload and the conversion matrix (2026-11-10) - done, Phase 3: datasets, the PC agent and the first benchmark run (2026-11-10) - done, Phase 3 follow-up: the owner's review of 2026-11-10 - done, with the charts left for the brief, Quick add-ons (2026-11-10, later the same day) (+29 more)

### Community 31 - "Agent Artifact Cache"
Cohesion: 0.14
Nodes (3): bundle_hash(), Cache, sha256_file()

### Community 32 - "Migrations & Worker"
Cohesion: 0.17
Nodes (5): upgrade(), upgrade(), upgrade(), downgrade(), upgrade()

### Community 33 - "Agent End-to-End Tests"
Cohesion: 0.28
Nodes (15): fake_env(), make_agent(), queue_run(), status(), test_a_baseline_run_gets_the_checkpoint_under_a_name_ultralytics_understands(), test_a_crashing_benchmark_fails_one_run_and_the_agent_carries_on(), test_a_job_runs_end_to_end_and_the_result_reaches_the_app(), test_a_missing_runtime_is_reported_as_not_available() (+7 more)

### Community 34 - "TypeScript App Config"
Cohesion: 0.09
Nodes (22): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+14 more)

### Community 35 - "Database & Migrations"
Cohesion: 0.11
Nodes (13): _alembic_config(), downgrade(), make_engine(), migrate(), _pragmas(), create_app(), lifespan(), client() (+5 more)

### Community 36 - "shadcn Components Config"
Cohesion: 0.09
Nodes (21): aliases, components, hooks, lib, ui, utils, iconLibrary, menuAccent (+13 more)

### Community 37 - "NDJSON Dataset Import"
Cohesion: 0.19
Nodes (9): ImportProblem, _check_public(), expand_ndjson(), fetch_url(), _image_name(), _label_text(), _NoRedirect, _records() (+1 more)

### Community 38 - "Web Tooling Dependencies"
Cohesion: 0.11
Nodes (19): cmdk, eslint, @eslint/js, eslint-plugin-react-hooks, @fontsource/ibm-plex-sans, globals, prettier, shadcn (+11 more)

### Community 39 - "Web API Client"
Cohesion: 0.13
Nodes (24): @tanstack/react-query, getHealth(), Health, healthKey, LiveStatus, DeviceInfo, DeviceKind, devicesKey (+16 more)

### Community 40 - "Runs E2E Tests"
Cohesion: 0.15
Nodes (14): addDataset(), addModel(), finishJobs(), FIXTURES, FOLDER, Id, PREDICTIONS, read() (+6 more)

### Community 41 - "Logging & API Tests"
Cohesion: 0.13
Nodes (14): configure_logging(), JsonFormatter, _spa(), test_health_counts_queued_jobs(), test_health_degrades_instead_of_failing_when_the_database_breaks(), test_health_reports_database_queue_and_worker(), test_json_log_lines_carry_extra_fields_and_tracebacks(), test_requests_for_an_unknown_host_name_are_refused() (+6 more)

### Community 43 - "Confirm Dialog"
Cohesion: 0.24
Nodes (14): Confirm, ConfirmContext, ConfirmOptions, ConfirmProvider(), AlertDialog(), AlertDialogAction(), AlertDialogCancel(), AlertDialogContent() (+6 more)

### Community 44 - "TypeScript Node Config"
Cohesion: 0.12
Nodes (16): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+8 more)

### Community 45 - "Handoff Brief"
Cohesion: 0.15
Nodes (12): HANDOFF (updated 2026-11-10, after Phase 3 and the owner's review of it), Live data on this PC (in `data/`, git-ignored), Not verified, Owner decisions (2026-11-09), Phase 4 questions to settle with the owner before building, Run it, Security, Starter prompt for the new session (+4 more)

### Community 46 - "Web Runtime Dependencies"
Cohesion: 0.12
Nodes (16): dependencies, @base-ui/react, class-variance-authority, cmdk, cn, @fontsource/ibm-plex-sans, lucide-react, react (+8 more)

### Community 47 - "Web Dev Dependencies"
Cohesion: 0.12
Nodes (16): devDependencies, @axe-core/playwright, eslint, @eslint/js, eslint-plugin-react-hooks, globals, @playwright/test, prettier (+8 more)

### Community 48 - "Server Core & Events"
Cohesion: 0.09
Nodes (8): _db_health(), DbHealth, events(), Health, _same_origin(), EventHub, _mount_spa(), test_publishing_after_the_event_loop_closed_never_raises_into_the_worker()

### Community 49 - "Runtime Runners"
Cohesion: 0.14
Nodes (8): kind_for_op(), load_runner(), NcnnRunner, need(), OnnxRunner, OpenVinoRunner, Runner, TorchRunner

### Community 50 - "Playwright & Vite Config"
Cohesion: 0.15
Nodes (7): @axe-core/playwright, @tailwindcss/vite, vite, @vitejs/plugin-react, PATHS, TAGS, api

### Community 51 - "README & Project Plan"
Cohesion: 0.17
Nodes (11): Architecture (unchanged from the prompt, with the rules above), Constraints from this machine (checked 2026-11-09), Definition of done (every phase), EdgeBench, Owner decisions (2026-11-09), Phases, Rules that came out of the JonaRu code and were not in the prompt, Run it (state after Phase 3) (+3 more)

### Community 53 - "Device Fingerprint"
Cohesion: 0.31
Nodes (6): collect(), _cpu_name(), _gpu(), _pi_model(), package_versions(), key()

### Community 54 - "Phase 5 Pi Agent"
Cohesion: 0.22
Nodes (8): Acceptance, Build, Decide first (Plan agent + ADR), Decided (owner, 2026-11-09), From Phase 0 (binding; see `docs/phase-0-verdict.md`), Phase 5: Raspberry Pi agent and multi-device experiments, Risks, Skills

### Community 55 - "Smoke & WebSocket Tests"
Cohesion: 0.20
Nodes (3): @playwright/test, PAGES, Tracked

### Community 56 - "NPM Scripts"
Cohesion: 0.22
Nodes (9): scripts, build, dev, format, format:fix, lint, preview, test:e2e (+1 more)

### Community 57 - "Process Crash Test"
Cohesion: 0.29
Nodes (5): free_port(), healthy(), start_server(), test_a_server_killed_mid_job_is_replaced_by_one_that_finishes_the_job(), wait_until()

### Community 58 - "Models E2E Tests"
Cohesion: 0.32
Nodes (6): EVIL, FIXTURES, GOOD, payload(), upload(), uploadAndSettle()

### Community 59 - "Dataset Job Handlers"
Cohesion: 0.28
Nodes (5): make_build_handler(), make_bundle_handler(), register_dataset_handlers(), Cancelled, OwnershipLost

### Community 60 - "Contrast Tests"
Cohesion: 0.33
Nodes (5): BOUNDARY, css, luminance(), ratio(), TEXT

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

### Community 72 - "Charts & Families Brief"
Cohesion: 0.29
Nodes (6): 1. Charts and how to read them, 2. More model families, 3. More dataset formats and controls, 4. Controls for computer-vision engineers, 5. Suggested order, Brief: charts, more model families, more dataset formats, engineer controls

### Community 73 - "Phase 0 Brief"
Cohesion: 0.29
Nodes (6): Acceptance, Do, Output, Phase 0: Spikes (throwaway checks, no app code), Risks, Skills

### Community 74 - "Phase 4 Brief"
Cohesion: 0.29
Nodes (6): Acceptance, Build, From Phase 0 (binding; see `docs/phase-0-verdict.md`), Phase 4: Telemetry, sweeps, repeats, statistics, drift, INT8, Risks, Skills

### Community 75 - "Phase 8 Brief"
Cohesion: 0.29
Nodes (6): Acceptance, Build, Owner request, 2026-11-10: more model families and dataset formats, Phase 8: Generic ONNX plugins, polish, tests, README, demo seed, Risks, Skills

### Community 76 - "CPU Pinning"
Cohesion: 0.33
Nodes (3): pin_to_cpus(), Unavailable, test_pinning_to_no_cpus_means_not_pinned()

### Community 77 - "Agent README"
Cohesion: 0.33
Nodes (5): EdgeBench agent, Environments, How a benchmark is measured, Run it on this PC, Tests

### Community 78 - "ADR Agent Protocol"
Cohesion: 0.33
Nodes (5): ADR 0003: Agents poll over HTTP; the browser gets live updates over WebSocket, Alternatives rejected, Consequences, Context, Decision

### Community 79 - "Phase 9 Brief"
Cohesion: 0.33
Nodes (5): Acceptance, Build, Not allowed, Phase 9 (optional): JonaRu bridge, Skills

### Community 80 - "Converter README"
Cohesion: 0.40
Nodes (4): Rules the scripts follow, Set it up, The converter environment, Try it by hand

### Community 81 - "ADR Job Queue"
Cohesion: 0.40
Nodes (4): ADR 0001: Job queue is a SQLite table, not Redis, Consequences, Context, Decision

### Community 82 - "ADR Artifact Store"
Cohesion: 0.40
Nodes (4): ADR 0002: Content-addressed artifact store with a toolchain-aware cache key, Consequences, Context, Decision

### Community 83 - "ADR Statistics"
Cohesion: 0.40
Nodes (4): ADR 0004: How latency results and differences are reported, Consequences, Context, Decision

## Knowledge Gaps
- **11 isolated node(s):** `@fontsource/ibm-plex-sans`, `prettier`, `shadcn`, `tailwindcss`, `tw-animate-css` (+6 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 658 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Traps that already cost time` connect `Experiments UI` to `Detection Evaluation Metrics`, `Project Docs & Database`, `Project State & Palette`?**
  _High betweenness centrality (0.268) - this node is a cross-community bridge._
- **Are the 45 inferred relationships involving `Services` (e.g. with `_keep_predictions()` and `_check_commit()`) actually correct?**
  _`Services` has 45 INFERRED edges - model-reasoned connections that need verification._
- **What connects `@fontsource/ibm-plex-sans`, `prettier`, `shadcn` to the rest of the system?**
  _11 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Dataset Import Scripts` be split into smaller, more focused modules?**
  _Cohesion score 0.054336468129571575 - nodes in this community are weakly interconnected._
- **Why does `Architecture` connect `Project Docs & Database` to `Database & Migrations`, `Conversion Matrix`, `Dataset API`, `Checkpoint Pickle Scanner`, `Server Core & Events`, `Server Client`, `Same-Origin Security`?**
  _High betweenness centrality (0.195) - this node is a cross-community bridge._
- **Should `Server Settings Tests` be split into smaller, more focused modules?**
  _Cohesion score 0.10328638497652583 - nodes in this community are weakly interconnected._
- **Why does `match_predictions()` connect `Detection Evaluation Metrics` to `Experiments UI`?**
  _High betweenness centrality (0.144) - this node is a cross-community bridge._