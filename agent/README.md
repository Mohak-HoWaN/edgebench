# EdgeBench agent

Runs benchmarks on the machine it is installed on (this PC now, a Raspberry Pi in a later phase) and reports to the server. It makes
outbound HTTP calls only (ADR 0003): it enrols once with a one-time token, then long-polls the server for jobs, downloads the model and
dataset it needs (checksummed, resumable, cached by hash), runs each benchmark in **its own process**, and uploads the result. A native
crash (ncnn has crashed the interpreter before) fails that one run; the agent carries on.

## Run it on this PC
1. In the app, open **Devices**, choose **Get a connection command**.
2. `.\scripts\start-agent.ps1 -Token <token>` from the repository root. Afterwards `.\scripts\start-agent.ps1` is enough: the agent
   keeps its identity in `~\.edgebench-agent\agent.json`. Ctrl+C stops it.

The script picks the first of `.venv-converter`, `spikes\.venv` and `.venv-agent` that exists. A run for a runtime that is not installed
there (say OpenVINO) is reported as "not available on this device", not as a failure.

## Environments
| Environment | Holds | Used for |
|---|---|---|
| `.venv-agent` | numpy, Pillow, OpenCV (headless), ONNX Runtime, httpx, psutil, pytest, plus the server's dev requirements | the agent's tests; benchmarks of ONNX variants |
| `spikes\.venv` (the Phase 0 environment) + `httpx` | everything above plus OpenVINO, ncnn, PyTorch, Ultralytics | real benchmarks of every variant |

Create `.venv-agent`: `python -m venv .venv-agent` then
`.venv-agent\Scripts\pip install numpy==2.2.6 pillow==13.0.0 onnxruntime==1.25.1 httpx==0.28.1 psutil==7.2.2 pytest==9.2.0 opencv-python-headless==4.12.0.88 -r server\requirements-dev.txt`.

## How a benchmark is measured
* One shared path for every variant (`decode.py`): letterbox to the model's input size, run the runtime, decode, class-aware NMS
  (confidence 0.001, IoU 0.7, 300 detections, multi-label: Ultralytics' validator settings). Runtimes only turn a picture into the
  raw output. Drift between variants therefore measures the model, not the post-processing.
* Accuracy (`evaluate.py`): mAP50, mAP50-95, precision, recall, F1, per-class AP and a confusion matrix. Cross-checked against
  Ultralytics `model.val()` on COCO128 with `yolo11n.pt`: mAP50 0.6761 against 0.6753, mAP50-95 0.5076 against 0.5099.
* Threads and CPUs: the server only accepts a thread count up to what this machine reports (its logical CPUs), and a run can be pinned to chosen
  CPU numbers (`cpu_list`, set with psutil before the runtime starts its threads; the result records which CPUs were in force). A system without
  CPU affinity (macOS) reports such a run as not available.
* Speed (`bench.py`): after an accuracy pass, `warmup` untimed and `iterations` timed rounds over the pictures, with preprocess,
  inference and postprocess timed separately (`time.perf_counter_ns`). Model load time and first-inference time are recorded apart.
* Classes are matched by name, never by index. A class the model does not have is reported and left out.

## Tests
`.venv-agent\Scripts\python -m pytest agent\tests` (38 tests: AP maths on hand-built detections, letterbox and NMS, the benchmark
process with a runtime that knows the answers, and the real agent against the real server with a stand-in benchmark process).

## Repeats and telemetry (Phase 4)
A run is `repeats` timed rounds, each preceded by its own warm-up (`bench.py`). Beside the benchmark child the agent starts
`python -m edgebench_agent.telemetry` as a separate process (5 Hz, one JSON line per sample); when the child ends, `repeats.merge_telemetry`
attaches each repeat's window (CPU per core, RSS peak, clock, temperature, throttle flag, GPU), marks a repeat invalid when a throttle flag was up
or its clock averaged more than 10% below the run's start, pools the valid repeats, and records the environment (power plan or governor, cores).
A reading the machine cannot give is `null`. Windows: performance counters (`% Processor Performance` x `Processor Frequency`, ACPI thermal zone),
no administrator needed, no throttle flag. Linux and Pi: psutil, `/sys`, `vcgencmd get_throttled` (untested on a Pi). To find which sensor disturbs
a run, set `EDGEBENCH_TELEMETRY_SKIP=clock,temperature,gpu` for the sampler.
