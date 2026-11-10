# Brief: charts, more model families, more dataset formats, engineer controls

Requested by the owner on 2026-11-10 ("I want multiple charts and their interpretations ... put it in the brief"; "more model variants, support
for various models and datasets"). None of this is built yet except where marked **done**. It belongs to Phase 4 (sweeps and telemetry,
which produce the data), Phase 6 (the results explorer, which draws it) and Phase 8 (plugins). Order of work at the end.

## 1. Charts and how to read them

Every chart gets three things on the page, not in a manual: a one-sentence **question it answers**, a **"how to read it"** line, and an
**automatic interpretation** sentence computed from the data ("ONNX FP16 is 0.2 points less accurate than FP32 and 2% faster: no reason to
prefer it on this CPU"). The interpretation must say when the data is too thin ("one run each: repeat before concluding"). Colour is never
the only carrier of meaning (marker shapes and labels too), and each chart has a table view of the same numbers.

| # | Chart | Question | How to read it | Red flags the interpretation should call out | Needs |
|---|---|---|---|---|---|
| 1 | **Accuracy against speed** (scatter, one dot per variant, Pareto front drawn) | Which variant gives the best accuracy for its speed? | Up is more accurate, left is faster. Dots on the front are the only sensible choices; a dot with another up and to its left is dominated. | A dominated variant that is the current production choice. Differences smaller than the repeat spread. | accuracy + median time (Phase 3) |
| 2 | **Latency distribution** (box or violin per variant, per-image ms) | How steady is the speed? | The box is the middle half of images; the whiskers the rest. A tall box means unpredictable time. | Outliers far above the whisker (one slow image in twenty); p99 more than twice the median. | per-image samples (stored: `total_ms`) |
| 3 | **Latency over the run** (line, time per image against round number) | Does it slow down as it warms up? | A flat line is steady. A climb is heat; a staircase is the operating system moving the work. | Rising trend after round 20 (throttling); a high start (warm-up too short). | per-round samples (stored), temperature (Phase 4) |
| 4 | **Where the time goes** (stacked bar: preprocess, model, postprocess) | Is it the model that is slow? | Each bar is one image's time split in three. | Postprocess bigger than the model: the decode and NMS are the bottleneck, so a faster format will not help. | stage timings (stored) |
| 5 | **Speed against threads** (line per variant) | How many threads are worth using? | Where the line flattens, extra threads buy nothing. | A peak then a fall (too many threads on a hybrid CPU); no gain from 4 to 8. | thread sweep (Phase 4) |
| 6 | **Speed-up over the baseline** (bars with confidence intervals) | How much faster than FP32 is each variant? | 1.0 is the baseline; the whisker is the doubt about the number. | A whisker that crosses 1.0 (not provably faster); INT8 slower than FP32. | repeats and intervals (Phase 4, ADR 0004) |
| 7 | **Accuracy drift** (bars of mAP change against the baseline, with the allowed band shaded) | Did converting or quantizing hurt accuracy? | Bars inside the band are harmless. | Any bar outside the band; zero detections (the Phase 0 INT8 failure). | baseline run + variants (Phase 4 gate) |
| 8 | **Accuracy per class** (heat map: class by variant) | Which products break, and under which format? | Dark is good. Look down a column for a class that fades. | A class that drops with FP16 or INT8 while the average hides it; a class with very few examples (shown with its count). | per-class AP (stored) |
| 9 | **Confusion matrix** (heat map, the top confusions listed in words) | What is mistaken for what? | Rows are the truth, columns the answer; the diagonal is right. The last row and column are "nothing". | Two look-alike packs confused with each other; many "missed" (last column) for one class. | confusion matrix (stored) |
| 10 | **Precision against recall** (curve per class or variant) | How does the trade-off move with the confidence cut-off? | The curve closer to the top right is better. | A steep fall: a small change in the cut-off changes a lot. View only: thresholds are never tuned to hide a weak detector. | per-detection scores (needs storing) |
| 11 | **F1 against confidence** (curve) | Where is the best operating point? | The peak is the cut-off where false alarms and misses balance. | A peak far from the cut-off the shop uses. | per-detection scores |
| 12 | **Score distribution** (histogram of detection confidences per variant) | Did quantization change how sure the model is? | Compare the shapes. | The whole histogram shifted left after INT8 (a fixed cut-off then drops real items). | per-detection scores |
| 13 | **Temperature and clock** (two lines over the run, throttle moments marked) | Did the device overheat or slow itself? | Temperature up while clock down is throttling. | Any throttle flag during a timed run (the run is flagged, not hidden). | telemetry (Phase 4 and 5) |
| 14 | **Device comparison** (paired bars, PC against Pi, same variant) | How much slower is the Pi? | Pairs of bars; the ratio is written on top. | A ranking that differs between devices (the best format on the PC is not the best on the Pi). | Pi agent (Phase 5) |
| 15 | **Accuracy by capture source** (bars per source: Pi camera, phone, other) | Does it work as well on the shop's camera as on phone photos? | Bars of one variant side by side. | A large gap between sources: the data you trained on is not the data you deploy on. | per-source accuracy (needs adding to the evaluator) |
| 16 | **Size against accuracy** and **size against speed** (scatter) | Is a smaller file worth it? | Same reading as chart 1 with file size on the other axis. | A big saving with a visible accuracy loss. | file sizes (stored) |
| 17 | **Scorecard** (table with a bar in each cell, ordered by the owner's priorities in Settings) | Which variant wins for *my* priorities? | Row order follows the priority list; best in each column is marked. | Winner changes when the first two priorities swap (the choice is sensitive). | **done** in a simple form: the experiment page ranks by the first priority and marks the best per column |

Build notes. Draw with plain SVG or a small library already needed elsewhere (Phase 6 decides; keep the bundle small). Every chart is a
component taking rows in, so the paper (Phase 7) can render the same data to vector files. Interpretation sentences are generated from
rules in one tested file, never hand-written per chart, and each rule has a test with a case that triggers it and one that does not.

## 2. More model families

**Done:** Ultralytics YOLO detection `.pt` (class names read, converted to ONNX FP32/FP16, TorchScript, OpenVINO FP32/FP16, ncnn FP32/FP16,
at any input size that is a multiple of 32, ONNX with or without simplification).

| Family | What changes | Notes |
|---|---|---|
| Ultralytics segment, pose, classify, OBB | Different output tensors; different metrics (mask AP, OKS keypoint AP, top-1 and top-5, rotated IoU) | Same upload and converter; the decode and the evaluator get a "task" switch. Read the task from the model card (already stored). |
| An ONNX file uploaded directly | No `.pt` to convert from | The generic plugin of Phase 8: the person says where the boxes and scores are in the output. Allows models from any framework. |
| RT-DETR and other transformer detectors | No NMS (set prediction) | Decode differs; the shared-path rule still holds: one decode per family. |
| torchvision detectors (Faster R-CNN, SSD, RetinaNet), YOLOv5/YOLOX legacy | Other export routes and output layouts | Via the ONNX plugin first; native later if asked. |
| TFLite, TensorRT engines | Device-specific builds | TensorRT was never built here (out of memory in Phase 0); TFLite was dropped for Python 3.13 reasons. |
| Quantized variants (INT8) | Needs the calibration subset (exists, seeded, at least 50, mixes sources) | Phase 4: OpenVINO NNCF first (about 2x faster in Phase 0); ONNX static QDQ with the detect head excluded; mandatory accuracy gate. |

## 3. More dataset formats and controls

**Done:** YOLO (txt + data.yaml), COCO JSON (boxes), Pascal VOC XML, loose photos with or without annotations, folders, zips, versions with
history, restore, download, share bundles, capture-source tags, seeded calibration subset.

Next, in order of usefulness: LabelMe JSON; CVAT XML; classification folders (one folder per class) for classify models; CSV annotation files
(Open Images style); COCO segmentation and keypoints for the segment/pose families; HEIC photos (needs `pillow-heif`); video files turned into
frames at a chosen rate, remembering which video each frame came from; train/validation/test split tags per image and per source, so a run
can use "validation only"; filters ("only phone photos", "only images with class X") that make a subset saved as a version; an annotation
check that lists boxes outside the picture, empty labels and duplicate boxes before a dataset is used.

## 4. Controls for computer-vision engineers

Most of these are server settings that already exist and only need a place in an "Advanced" section of the experiment form; the rest are new.

* **Detection settings:** confidence and overlap limits and the detection cap (exist in the API, not in the form); class-agnostic NMS;
  letterbox against stretch; input normalisation (0-1, mean and standard deviation, BGR/RGB); batch size.
* **Runtime settings:** inter-op and intra-op threads; execution provider (CPU, CUDA, DirectML, TensorRT, OpenVINO GPU or NPU, CoreML);
  graph optimisation level; memory arena on or off.
* **Export settings:** opset, dynamic axes, half precision, NMS baked into the graph or not, simplification (**done** for ONNX).
* **Quantization recipes:** static or dynamic, per-channel or per-tensor, symmetric or not, calibration size and seed, excluded layers;
  every recipe is a named, saved, repeatable thing, and every quantized variant passes the accuracy gate.
* **Measurement:** thread count (**done**, limited to what the device has), pinning to chosen CPUs (**done**; for a fast-and-slow-core laptop
  the fast cores are usually the lowest numbers: check before trusting a comparison), repeats and confidence intervals (Phase 4), warm-up policy,
  fixed CPU frequency where the system allows it, a note when the system was not idle.

## 5. Suggested order

1. Phase 4: repeats, intervals, thread sweep, INT8 with the gate, telemetry. These produce the data charts 3, 5, 6, 7, 13 need. Also store
   per-detection scores (charts 10 to 12) and per-source accuracy (chart 15).
2. Phase 6: charts 1, 2, 4, 6, 7, 8, 9 first (they need only data that exists or Phase 4 produces), with the interpretation rules and tests;
   then 10 to 12, 14, 15, 16.
3. Phase 8: the ONNX plugin, then segment/pose/classify, with their metrics.
4. Dataset formats and the Advanced section of the form: as asked; none depends on the others.
