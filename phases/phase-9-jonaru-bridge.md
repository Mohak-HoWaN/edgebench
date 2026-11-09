# Phase 9 (optional): JonaRu bridge

**Goal:** connect EdgeBench to the checkout product without making the generic tool depend on it. Everything here is behind a
profile (`profiles/jonaru.yaml`); with no profile EdgeBench is unchanged.

## Build
- **Class profile:** canonical class names from `project/pipeline/models/production/manifest.json` and the label-to-product map in
  `project/web/src/utils/static_data.ts`, plus an alias table for old names (`Dairy Milk` -> `cadbury_dairy_milk`,
  `chataka_pataka` -> `balaji_chataka_pataka_masala`, ...). A model with unmapped or duplicate classes cannot be marked promotable.
- **Cart-event scenes metric:** a scene set is videos or synthetic scenes (`tools/synth_scenes.py`) plus `expected.json` (what should
  be on the bill). Run through the real pipeline (`jonaru.FramePipeline`, zone and line modes); the metric is expected vs billed per
  scene per variant. This is the number the shopkeeper experiences; the detector, not the zone logic, is the known limit.
- **Promote to production:** shows the diff (classes, size, drift, scene results, golden-set run) and, only after a passing gate and
  a golden-set run, writes `manifest.json` and the variant files into a **staging copy** of `pipeline/models/production`; applying it
  to the real folder is a separate confirmed step. Previous manifests are kept so one click restores them. It never edits
  `static_data.ts`; it lists labels that table lacks.
- **Golden set:** a frozen dataset every candidate must be run on before promotion.
- **Hard-example export:** frames from the Phase 6 failure browser exported for the next annotation round (feeds the retraining loop).
- Import `project/raspberry/results/*.json` and `pi5.csv` as historical device runs, marked "imported", not measured by EdgeBench.

## Acceptance
- v_0.0.0 and v_0.0.0.2 compared by name despite different class orders.
- Promotion to a temp copy of the production folder produces a manifest the JonaRu pipeline loads (`pytest` in `project/pipeline`
  passes against it); rollback restores the original byte for byte.
- A scene set with `expected.json` reports expected vs billed for two models.

## Skills
`Explore` agent (read `project/pipeline`), `security-review` (it writes to the production folder), `code-review`, `simplify`, `run`.
Also update `project/docs/01-handoff/README.md` ("State" row) per that project's working agreement.

## Not allowed
Writing to the real production folder, the shop database, or the Pi without an explicit confirmation step.
