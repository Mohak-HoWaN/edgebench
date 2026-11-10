# Phase 0 verdict

Date: 2026-11-09. Machine: Windows 11, i7-13700HX (8P+8E cores, 24 threads), 15.7 GB RAM, RTX 4050 Laptop 6 GB, driver 621.01.
Model: `yolo11n.pt` (COCO, SHA-256 `0EBBC80D...4EE1`). Images: COCO128 (128 images, public). Spike scripts and raw results are in
`docs/phase-0/` (`spike-scripts/`, `results/`). Everything ran in an isolated venv with pinned versions (`results/pip-freeze.txt`).

**Status: Phase 0 is done except two items that could not be completed here: the TensorRT engine build (stopped by low system memory,
see "Not verified") and anything on a real Raspberry Pi.**

## 1. Conversion matrix: what works

"Works" means the file converted, loaded in its runtime, and produced detections. Drift is the share of reference detections
(ONNX FP32, 20 images, conf 0.25, NMS 0.5) that the variant also finds with the same class and IoU >= 0.5 (1.0 = identical).

| Variant | Converts | Runs | Drift agreement | Decision |
|---|---|---|---|---|
| PyTorch `.pt` baseline | n/a | yes (via ONNX FP32 as reference) | n/a | Keep. Baseline for drift is the FP32 ONNX through the shared decode (README rule 1). |
| TorchScript FP32 (CPU, CUDA) | yes, 1.5 s | yes | 1.0 | Keep; the CUDA run is the GPU baseline. |
| ONNX FP32 | yes, 5 s | yes | reference | Keep. |
| ONNX FP16 via `onnxconverter-common` | yes | **fails to load** in ONNX Runtime (type error at a `Resize` node), also with `Resize` blocked | n/a | **Do not use.** |
| ONNX FP16 via ONNX Runtime's own `convert_float_to_float16` | yes | yes | 1.0 | Keep. Use this converter. |
| ONNX INT8 dynamic | yes | yes, but about **12x slower** than FP32 | 0.812 | **Drop.** It is built from `ConvInteger` + `DynamicQuantizeLinear` nodes, which ORT's CPU runs on a slow generic path. |
| ONNX INT8 static QDQ, default | yes | runs, **returns zero detections** | 0.0 | **Never ship as exported.** The accuracy gate must catch this. |
| ONNX INT8 static QDQ, detect head excluded (84 nodes) | yes | yes, about 1.2x faster than FP32 | 0.812 | Keep as "experimental INT8 (ONNX)"; gate is mandatory. |
| OpenVINO FP32 | yes, 0.3 s | yes | 1.0 | Keep. |
| OpenVINO FP16 (weights compressed) | yes | yes, same speed as FP32 on CPU | 1.0 | Keep. It saves size (5.7 MB vs 10.9 MB), not time. |
| OpenVINO INT8 (NNCF), 128 calibration images | yes, 13 s | yes, about 2x faster than FP32 | 0.913 | Keep. Best x86 INT8 path. |
| OpenVINO INT8, one image repeated 10x (the old recipe) | yes | yes | 0.812 | Reproduces the direction of the repo's warning (worse than a real calibration set); see section 4. |
| ncnn FP32 / FP16 | yes (needs `ncnn` + `pnnx` pip packages) | yes | 1.0 / 1.0 | Keep. Slower than ORT/OpenVINO on x86 as expected; judge it on the Pi. |
| TensorRT FP16 / INT8 | **not built** (see section 5) | not run | not measured | Keep in the plan as NVIDIA-only; **unverified**. `tensorrt-cu12` 10.9 installs and its builder initialises (fast FP16 and INT8 reported). |
| TFLite | not tried | not tried | not measured | **Drop from the first release.** It pulls in TensorFlow, and the Pi's `tflite-runtime` has no Python 3.13 wheel (only cp311). Add later if asked. |

## 2. Benchmark numbers (this PC, one image, 10 warm-up + 100 timed runs, runtime call only)

Mean milliseconds. These are indicative: one machine, one image, a hybrid-core laptop CPU. They are not a result for the paper.

| Variant | 1 thread | 4 threads | 4t p95 | 8 threads |
|---|---|---|---|---|
| ONNX FP32 | 64.6 | 20.8 | 21.7 | 17.6 |
| ONNX FP16 (ORT converter) | 62.5 | 18.8 | 19.8 | 15.7 |
| ONNX INT8 dynamic | 806.9 | 244.7 | 263.3 | 173.0 |
| ONNX INT8 static, head excluded | 42.9 | 16.9 | 18.1 | 15.4 |
| OpenVINO FP32 | 65.1 | 20.6 | 22.9 | 14.6 |
| OpenVINO FP16 | 64.3 | 20.1 | 20.9 | 20.3 |
| OpenVINO INT8 (128 images) | 30.5 | 10.5 | 11.1 | 10.8 |
| ncnn FP32 | 86.6 | 36.3 | 42.5 | 39.9 |
| ncnn FP16 | 79.9 | 34.7 | 40.3 | 38.4 |
| TorchScript CPU | 79.4 | 39.8 | 43.7 | 35.6 |
| TorchScript CUDA (incl. host-device copies) | 5.4 | n/a | n/a | n/a |

## 3. Findings that change the plan

1. **More threads do not mean faster on this CPU.** Going from 4 to 8 threads gave no gain, or a loss, for several variants (OpenVINO
   FP16 20.1 to 20.3, ncnn 36.3 to 39.9). On a hybrid CPU "max threads" is a poor default; the sweep needs 1, 2, 4, 8 and the physical-core
   count, and the environment manifest must record the core layout. (Phase 4)
2. **Never share a process between a converter and a benchmark, and set `YOLO_AUTOINSTALL=False` in converter processes.** Ultralytics
   silently installed `onnxruntime-gpu` over the pinned CPU `onnxruntime` mid-export. Every conversion runs in a subprocess with this variable
   set; missing dependencies are reported as a failed cell. (Phase 2)
3. **Hold the source array alive when building an `ncnn.Mat`.** `ncnn.Mat(arr[0].copy()).clone()` crashed the process (access violation,
   no traceback) because the temporary array is freed before `clone()` copies it. Keep the array in a variable until after `clone()`.
   Because a native crash cannot be caught, each runtime benchmark runs in its own subprocess so one crash marks one run failed. (Phase 3)
4. **The accuracy gate is not optional.** A default-exported INT8 ONNX model loaded, ran fast, and found nothing. Only the drift check
   exposed it. (Phase 4)
5. **Converter choice matters per format:** use ORT's converter for ONNX FP16; QDQ with the detect head excluded for ONNX INT8; NNCF for
   OpenVINO INT8. (Phase 2, 4)
6. **Packaging pins:** `typescript-eslint` 8.72 supports TypeScript below 6.1, so pin `typescript@~6.0` (6.0.3 worked), not 7. `create-vite`
   9 generates oxlint, so add ESLint explicitly. `shadcn init` puts the CLI in runtime dependencies; move it to `devDependencies` so
   `npm audit --omit=dev` is clean (it was, after the move). Pin the PyTorch and OpenCV builds in a constraints file: without it pip tried to
   replace the CUDA torch with a CPU one and Ultralytics pulled a second OpenCV. (Phase 1)
7. **The server image must not install `opencv-python` next to `opencv-python-headless`.** Ultralytics depends on the former. Install
   Ultralytics in the converter image only; the API image uses headless OpenCV.
8. **Pi requirements (from the package index, not tested on a Pi):** 64-bit OS only (`aarch64`; a browser reporting `armv8l` means 32-bit
   and the agent cannot run); glibc 2.35 or newer for OpenVINO (Pi OS Bookworm 2.36 and Trixie 2.41 qualify, Bullseye does not); Python 3.11
   or newer for ONNX Runtime 1.25. Pin versions per Python version: the newest `numpy` and `scipy` have no Python 3.11 ARM wheels, while the
   repo's pins (`numpy 2.2.6`, `scipy 1.16.3`, `onnxruntime 1.25.1`, `openvino 2026.1.0`, `ncnn 1.0.20261020`, `pnnx 20261020`) do. (Phase 5)
9. **PC telemetry on Windows** (tested): `psutil` has no temperature API and reports a constant 2100 MHz; the ACPI WMI thermal query needs
   admin rights. Without admin, Windows performance counters work: `\Processor Information(_Total)\% Processor Performance` and
   `\Processor Frequency` give a real, changing clock, and `\Thermal Zone Information(*)\Temperature` gave 331 K (about 58 C; which sensor
   it is, is not guaranteed to be the CPU die). GPU temperature, utilisation, memory, clocks and throttle reasons work through NVML. A
   separate sampler process at 5 Hz works on Windows and used about 1.1% of one core. The UI must label the thermal zone as "ACPI zone".
   Timer resolution is 1 ms by default (0.5 ms best); the active power scheme is a custom "Acer" plan, so the manifest records it. (Phase 4)
10. **Reports:** all seven template classes compiled with Tectonic 0.17.0 from a minimal document (IEEEtran conference and journal, acmart
    sigconf, llncs, elsarticle, article, report). The first ACM compile took 140 s because packages were downloaded; the others took 0 to 17 s.
    The ACM log has 211 font warnings about Libertine at 9 pt. Layout and page counts were **not** inspected (Phase 7 does that). (Phase 7)

## 4. Regression targets, and what was and was not reproduced

- Repo claim: the shipped INT8 (calibrated on one image repeated 10x) drifts from FP32. **Reproduced in direction**: the same recipe gave
  agreement 0.812 against 0.913 for 128 real images. The repo's specific "0.22 mean score difference on 9 images" was **not** reproduced,
  because that used the JonaRu model and images. Phase 4's test should use the JonaRu model and its 9 sample frames when available.
- Repo claim: `v_0.0.0.2_int8_.onnx` is about 40x slower in ONNX Runtime. **Reproduced in direction and explained**: dynamic INT8 is about
  12x slower at 4 threads and 12.5x at 1 thread on this CPU, because of `ConvInteger` kernels. The factor differs from 40x; the model, CPU and
  thread count differ.
- Repo claim: INT8 OpenVINO about 2.1x faster than FP32. **Reproduced**: 20.6 ms to 10.5 ms (1.96x) at 4 threads.

## 5. Not verified

- **TensorRT engine build (FP16 and INT8).** The build was stopped by the system because memory ran critically low (15.7 GB total, 4.8 GB
  free with browsers and an IDE open). No engine was produced, so TensorRT latency and drift are unknown. To retry: close other
  applications, then run `spikes/scripts/s1_export.py trt_fp16 trt_int8` and `s2_bench.py trt_fp16 trt_int8`. Every other claim above is measured.
- **Anything on a Raspberry Pi** (installation, ncnn and OpenVINO performance on ARM, `vcgencmd` telemetry, throttle bits, ARM INT8 speed).
- **Accuracy on JonaRu data.** All numbers use COCO128 and a COCO model. mAP against Ultralytics `val()` is a Phase 3 check.
- Hybrid-core behaviour was seen but not investigated: under a 16-process burn only logical processors 16 to 23 reached 100% (these are
  probably the efficiency cores, from Intel's numbering; not confirmed). Core pinning was not tested.
- LaTeX output was compiled but not visually inspected.

## 6. Final supported matrix for the first release

PC: TorchScript (CPU, CUDA), ONNX FP32, ONNX FP16 (ORT converter), ONNX INT8 static QDQ (head excluded, experimental), OpenVINO FP32,
FP16, INT8 (NNCF), ncnn FP32 and FP16, TensorRT FP16 and INT8 (when the build is verified). Pi: ONNX FP32/FP16/INT8, OpenVINO, ncnn
(subject to Phase 5 measurement). Dropped: ONNX INT8 dynamic, ONNX FP16 via `onnxconverter-common`, TFLite.

Decision records: `docs/adr/0001` to `0004`.
