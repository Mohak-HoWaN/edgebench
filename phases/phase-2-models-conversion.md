# Phase 2: Model upload and the conversion matrix

**Goal:** upload `yolo11n.pt` and watch a grid of format x precision cells convert, each with status, size, time, and an error log
when it fails. One failure never stops the others.

## Build
- **Upload:** drag-and-drop `.pt`; stream to disk, sha256, store at `data/artifacts/<sha256>`. Reject non-checkpoints. Read the model
  card (task, class names in order, parameter count, GFLOPs, input size) in a **subprocess** (loading a checkpoint runs pickle code,
  so treat uploaded `.pt` files as untrusted: run the reader in a separate process, never in the API process).
- **Conversion matrix** (final set comes from `docs/phase-0-verdict.md`; target list): TorchScript; ONNX FP32 / FP16 (+ onnxsim
  toggle); OpenVINO FP32 / FP16; ncnn FP32 / FP16. INT8 variants and TensorRT arrive in Phase 4 / 5.
- Each cell = a `jobs` row of type `convert` with params `(model_hash, format, precision, imgsz, settings)`. The cache key is that
  tuple; an existing artifact is reused and the cell shows "cached".
- Converters run in worker subprocesses (isolation + timeout + killable on cancel). They write to a temp dir and move into the
  artifact store only on success, so a crash leaves nothing half-written.
- Missing dependency or hardware gives a clear cell state, for example "TensorRT not available: no NVIDIA GPU detected", never a
  crash.
- Verify each converted artifact by running **one forward pass on a fixed image** and comparing the output with the `.pt` baseline
  within a tolerance; a conversion that loads but disagrees is marked "converted, mismatch" with the max difference.
- UI: Models list, model card, matrix grid, per-cell retry, per-cell log drawer, file size and conversion time.
- Class names are stored per model; a model whose names change between versions is compared by name later (README rule 2).

## Reuse
`project/pipeline/tools/export_models.py` (`export_onnx`, `export_openvino`, scratch-copy trick so Ultralytics never writes next to
the source) and `project/pipeline/jonaru/detector.py` (`letterbox`, `decode`) for the verification pass.

## Acceptance
- pytest: converter functions against a tiny fixture model; cache hit on second request; a deliberately broken converter leaves the
  other cells `ready`; cancel kills the subprocess.
- Real: upload `yolo11n.pt`; the grid reaches a final state for every cell; sizes match what `ls` shows; the forward-pass check
  passes for FP32 variants.
- Uploading a renamed text file is rejected with a readable message.

## Skills
`diagnosing-bugs` (conversion failures), `graphify` (first real code), `security-review` on the upload path, `simplify`,
`code-review`, `run`.

## Risks
FP16 on CPU runtimes can be slower than FP32; that is a result, not a bug (Phase 4 shows it). ncnn and pnnx tooling may need network
access on first use.
