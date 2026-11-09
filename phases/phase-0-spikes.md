# Phase 0: Spikes (throwaway checks, no app code)

**Goal:** find out which parts of the conversion matrix actually work on this PC and on ARM64 before designing around them. The
prompt lists ~20 variants; some will not work. Better to know now than in Phase 2.

## Do
In `spikes/` (git-ignored scratch, deleted after the verdict), with `yolo11n.pt` from `../new_arch/models/production/`:

1. ONNX FP32 export, then FP16 conversion (`onnxconverter-common`) and static INT8 (`onnxruntime.quantization` QDQ with 50 images).
   Time each on ORT CPU. Expected from the repo: INT8 ONNX can be ~40x slower; confirm and record the reason.
2. OpenVINO IR FP32, FP16 (`compress_to_fp16`), INT8 (NNCF). Reuse `project/pipeline/tools/export_models.py` functions.
3. ncnn: does `pip install ncnn` have a wheel for Windows x64 and for Raspberry Pi OS aarch64 (Python 3.11/3.12)? Does Ultralytics
   `export(format="ncnn")` need to download `pnnx`, and does that work offline?
4. TensorRT on the RTX 4050 (6 GB): is a pip `tensorrt` wheel available for Python 3.12 and this CUDA (torch is cu124)? Can an
   FP16 and an INT8 engine be built for yolo11n at 640 within memory?
5. TorchScript export, and whether TFLite is worth keeping (it drags TensorFlow in; likely drop to "optional/later").
6. OpenVINO on Pi 5: is there an aarch64 `openvino` wheel for the Pi's Python version? (Check the package index; do not install
   anything on the Pi in this phase.)
7. LaTeX: install Tectonic (single binary), compile a minimal IEEEtran document, note first-run package download needs internet.
8. Node 26: `npm create vite@latest`, install React, Tailwind, shadcn/ui, TanStack Query/Table, ECharts, Zustand; note any package
   that refuses Node 26.
9. Telemetry: does `psutil.sensors_temperatures()` return anything on this Windows laptop? (Probably not; decide what "temperature"
   means on the PC: GPU via pynvml, CPU via a vendor tool or not available.)

## Output
`spikes/VERDICT.md` copied to `docs/phase-0-verdict.md` (kept): a table `variant | works here | works on Pi | size | notes`, plus the
final supported-matrix list with reasons for anything dropped, and ADRs for: queue backend, artifact store layout, agent protocol,
statistics method. Update the matrix in `README.md` accordingly.

## Acceptance
- Every row in the verdict has an observed result or "not checked, because ...".
- The reproduced INT8 slowdown and the drift finding from the JonaRu README are explained, not just repeated.
- A written decision for each of the open questions in `README.md` that Phase 1 to 3 depend on.

## Skills
`architecture` (ADRs), `diagnosing-bugs` (INT8 slowdown), `Plan` agent for the agent-protocol design, `Explore` agent to read
`project/pipeline/tools/*`.

## Risks
Wheels change; record exact versions. Do not install packages into the shared `.venv` or `new_arch/.venv`; make a fresh venv.
