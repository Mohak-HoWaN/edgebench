# Phase 4: Telemetry, sweeps, repeats, statistics, drift, INT8

**Goal:** trustworthy numbers. An experiment sweeps parameters, repeats, reports confidence intervals, flags real differences, and
checks every variant for accuracy drift against the `.pt` baseline. INT8 works with a proper calibration set.

## Build
- **Experiment wizard (backend + UI):** models -> variants -> devices -> sweep (threads 1/2/4/max, core pinning, input size
  320/416/512/640, batch 1/4/8, governor recorded) -> warm-up 20, iterations 200, repeats 3. Shows the **run count and estimated
  duration before launch**; "quick" (small subset) and "full" modes. Invalid combinations (a runtime without batch support, an
  input size the model was not exported for) are removed with the reason shown, not run.
- **Telemetry:** separate sampling process at 5 Hz (configurable) that never shares the measurement loop. CPU % overall and per core,
  RAM peak, GPU % and memory (pynvml), temperature, CPU clock, throttle flags. Samples are stored per run as a time series.
  Where a sensor does not exist on a platform (probably CPU temperature on this laptop), the UI says "not available", not 0.
- **Statistics:** per configuration, mean, p50/p95/p99, std, FPS, and a 95% confidence interval across repeats. With 3 repeats a
  t-interval is wide; say so in the UI and offer 5 or more. Significance between two variants uses Welch's t-test on per-repeat
  means; a difference inside the interval is labelled "not significant". Write the method as an ADR (it is quoted in the report).
- **Drift:** run each variant on identical inputs as the `.pt` baseline; report mAP delta, mean box IoU agreement, per-class AP delta,
  class flips; flag above a configurable threshold (default set in Settings).
- **INT8:** OpenVINO via NNCF and ONNX static QDQ, calibrated on the seeded subset from Phase 3. Refuse under 50 images. The drift
  check is the gate: an INT8 variant that fails is marked, not hidden.
- **Throttling:** if the throttle flag or a clock drop is seen during a run, mark the run "invalid for latency" and show why.

## Acceptance
- pytest: CI maths against known samples, Welch's test, drift maths on hand-built detections, run-count estimator, invalid
  combination pruning, telemetry process is a separate PID.
- **Regression reproductions:** (a) the shipped `v_0.0.0.2_int8.xml` calibrated on one repeated image shows large drift against FP32,
  consistent with the repo's recorded 0.22 mean score difference; (b) INT8 ONNX being much slower than FP32 in ORT on this CPU is
  reproduced and explained in the UI note for that variant.
- Real: a 24-run sweep completes; cancel mid-sweep keeps finished runs; resume continues without repeating them.
- Measurement overhead check: latency with telemetry on vs off differs by less than the confidence interval (record the numbers).

## Skills
`architecture` (stats ADR), `diagnosing-bugs` (any latency number that looks wrong), `simplify`, `code-review`, `run`.

## Risks
Laptop CPUs boost and throttle unpredictably, so PC latencies are noisy; the report must say so. Windows timer resolution and power
plan affect results; record the power plan in the environment manifest.

## From Phase 0 (binding; see `docs/phase-0-verdict.md`)
- Statistics method: ADR 0004.
- Thread sweep: 1, 2, 4, 8 and the physical-core count. On the dev PC (hybrid i7-13700HX) 8 threads gave no gain or a loss over 4 for several
  variants, so "max" is not a sensible default; record the core layout in the manifest.
- INT8: OpenVINO via NNCF (about 2x faster, drift agreement 0.913 with 128 images). ONNX INT8 only as static QDQ **with the detect head
  excluded** (`/model.23/*`, 84 nodes; default QDQ returned zero detections). The drift gate must fail the zero-detection model; add that as a test.
- Regression targets: calibration on one repeated image gives lower agreement than on 128 real images (0.812 vs 0.913, COCO); the JonaRu
  "0.22 score difference" figure still needs the JonaRu model and its 9 sample frames.
- PC telemetry without admin rights: Windows performance counters (`% Processor Performance`, `Processor Frequency`, `Thermal Zone Information`);
  `psutil` temperature does not exist on Windows and its clock is constant. NVML for the GPU. Sampler is a separate process (about 1% of one core at 5 Hz).
  Label the thermal zone as an ACPI zone. Record the Windows power plan.

