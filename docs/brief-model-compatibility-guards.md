# Brief: guards against "the tool misread a good model" (owner request, 2026-11-14)

## What happened
`v_0.0.1.3_.pt` (YOLO26n, trained with Ultralytics 8.4.208, works on the Ultralytics Platform: mAP50-95 0.995 on the 8 labelled
Center_Fruit pictures, 51 of 52 test pictures right) went through EdgeBench with the converter on Ultralytics 8.3.248, which has no YOLO26
support. It loads the file without an error and decodes the head wrongly (precision 0.18, best confidence 0.50, 45 of 52 pictures
"nothing found"). EdgeBench said **ready** for the model and **ready, verified** for all seven variants, then the runs looked broken.
A developer seeing that would blame the model and may throw it away. Upgrading the converter to 8.4.212 fixed it (the exported ONNX is
`(1, 12, 8400)` and the existing decode reads it: 6 of 6 Dairy Milk pictures right at 0.88 to 0.95).

## Why nothing warned
1. **Upload** reads the model card but not which library made the file or whether this converter can read its architecture.
2. **Conversion verification** compares each variant with PyTorch *as the same converter loads it*. If the converter reads the model wrongly,
   every variant matches the wrong reading, so "verified" proves nothing about the model.
3. **Results** show a silent model as a failed result, with no hint that the tool, not the model, may be at fault.
4. **After an upgrade** the old variants stay "ready" although they were built by the old converter.

Status 2026-11-14: **G1 to G5 built, G6 not** (see STATE.md).

## Guards, in build order
| # | Guard | Where | Effect |
|---|---|---|---|
| G1 | **Compatibility check at upload.** `converter/inspect_pt.py` also reports the checkpoint's `version` and `train_args.model` (architecture family, for example yolo26n) and head traits (`reg_max`, one-to-one head), next to the converter's own library version. Rule: trained with a newer minor version than the converter, or head traits this library does not know, means *blocked*. | `inspect_pt.py`, `model_jobs.py`, model card | Model shows "Needs a newer converter: trained with 8.4.208, converter has 8.3.248. Nothing is wrong with your model." Conversion cells say the same (state `unavailable`, never `ready`). Names the exact upgrade command. |
| G2 | **Silent-model diagnosis on results.** When a run's `.pt` baseline finds nothing, or far fewer objects than the labels hold, the run and experiment pages show a diagnosis before any number: probable causes in order (converter older than the model, dataset class names do not match the model's, wrong image size, wrong dataset) with the evidence for each. Never says "your model is bad" unless the checks pass. | `drift.py`/`api_experiments.py`, `ExperimentDetail.tsx`, `RunDetail.tsx` | A weak detector and a misread detector look different to the developer. No threshold is tuned to hide anything. |
| G3 | **Honest wording for "verified".** The conversion check reads "matches PyTorch as this converter loads it. It does not prove the converter reads your model correctly; run it on labelled pictures." | `ModelMatrix.tsx`, README | Stops "verified" being read as "good". |
| G4 | **Stale variants after a converter change.** A variant records the converter versions that built it; if they differ from the current ones it shows "Built with an older converter (8.3.248). Rebuild." and the experiment wizard refuses stale variants with the reason. | `models.py` (store versions), `model_jobs.py`, `ModelMatrix.tsx`, `NewExperiment.tsx` | The four old v_0.0.1.3 variants (built under 8.3.248) are flagged instead of silently "ready". |
| G5 | **Converter panel.** Settings shows the converter's library versions and the newest model families it can read, and the model card shows "trained with / converted with". | `Settings.tsx`, `ModelDetail.tsx` | A mismatch is visible before anything runs. |
| G6 (optional) | **Reference accuracy.** A model can carry the owner's own reference result (for example the Platform's mAP on a named dataset version). If the baseline measured here is far below it, say "the Platform reports 0.995, this environment measures 0.48: the environment disagrees with your reference". | `models` table (migration), model page, run page | The only check that can catch a misread that both the converter and the decoder share. |

## Acceptance
- A checkpoint made by a newer Ultralytics than the converter is blocked at upload with the message above (stand-in converter test, since the
  real converter is now new enough; the real file is still checked with the real converter that it *passes*).
- A baseline that finds nothing on a labelled dataset shows the diagnosis; one that works does not.
- A variant built before a converter change shows as stale and cannot be put into an experiment until rebuilt.
- Both themes pass the contrast and axe checks on the new banners.

## Not covered
Models whose architecture the converter reads wrongly *without* a newer version stamp (for example a hand-edited head), and the Pi's
runtime versions (the agent reports them; a mismatch rule for the Pi comes with Phase 5).
