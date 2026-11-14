# The converter environment

Reading an uploaded model and converting it need torch, Ultralytics, ONNX, OpenVINO and ncnn. They live in a **separate Python
environment**, never in the server's: the server starts a child process from it for every read and every conversion, so a bad or
huge model cannot take the API down, a conversion can be cancelled and killed, and nothing here can change the server's packages.

| File | Used for |
|---|---|
| `inspect_pt.py` | reads a model's card (task, class names, parameters, GFLOPs, input size) |
| `convert.py` | converts one model to one format and checks it against the original PyTorch model; `--probe` lists installed packages |
| `requirements.txt`, `constraints-*.txt` | the exact versions this was tested with |

## Set it up

Windows PowerShell, from the repository root (use `.venv-converter/bin/python` elsewhere):

```powershell
py -3.12 -m venv .venv-converter
# 1. torch from PyTorch's index: cu124 for an NVIDIA GPU, cpu otherwise (match the constraints file you use below)
.venv-converter\Scripts\python -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
# 2. everything else, with torch pinned so pip cannot replace it
.venv-converter\Scripts\python -m pip install -r converter\requirements.txt -c converter\constraints-cu124.txt
```

Tell the server where it is, then restart the server:

```powershell
$env:EDGEBENCH_CONVERTER_PYTHON = "$PWD\.venv-converter\Scripts\python.exe"
.venv\Scripts\python -m edgebench
```

Without it the server still runs; uploaded models are kept, and the Models page says that the converter is not set up.

## Rules the scripts follow

- `YOLO_AUTOINSTALL=False` always. Ultralytics would otherwise install packages in the middle of an export (it once replaced the CPU
  `onnxruntime` with the GPU build). A missing package is reported as "not available" for that format, never installed.
- The checkpoint is copied to a file called `model.pt` before Ultralytics opens it: the artifact store names files by hash, and Ultralytics
  decides what a file is from its extension.
- `ncnn.Mat` keeps no reference to the array it is built from. Hold the array in a variable until `clone()` is done.
- Exit code 0 = converted, 1 = failed, 3 = a needed package is missing. The last output line is always `RESULT {json}`.

## Try it by hand

```powershell
.venv-converter\Scripts\python converter\convert.py --op onnx_fp32 --pt model.pt --out out1 --imgsz 640
.venv-converter\Scripts\python converter\convert.py --op openvino_fp16 --pt model.pt --source out1\model.onnx --out out2
```

## INT8 (Phase 4)
`--op openvino_int8` (NNCF) and `--op onnx_int8` (ONNX Runtime static QDQ, the detect head, found as the highest `/model.N/` prefix, kept in
float: the default left a model that returns no detections) need `--source` (the ONNX FP32 file) and `--calibration FOLDER` with at least 50
**different** readable pictures (copies are counted once; one picture repeated gave a worse model than 128 real ones). The result's check is shape
and finiteness only: whether it is still good is decided by the accuracy check of an experiment with the `.pt` baseline.

## Upgrading a library in the converter

After upgrading (for example Ultralytics for a newer model family), press **Check the converter again** on the Settings page (or wait two
minutes). Models the converter was too old for can then be re-read with **Check again**, and conversions built before the change show
"Built by an older converter" with a **Rebuild** button. Use `spikes/constraints.txt` (or `constraints-*.txt`) so torch, numpy and OpenCV
stay pinned: `python -m pip install "ultralytics>=8.4" -c <constraints file>`.
