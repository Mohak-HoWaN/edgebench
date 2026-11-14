# Phase 6: Results Explorer

**Goal:** answer "which variant should I ship on which device" from the data, quickly and without leaving the page.

## Before charts
Load `dataviz` and write down the palette, series order and light/dark values once; use them for every chart here and in the Phase 7
figures. Colour must not be the only cue (marker shape or label too). Reuse the Phase 1 tokens.

## Build
- Filterable, sortable, groupable table (device / format / precision), virtualized (TanStack Table + virtual rows), debounced
  filters, saved views, CSV and Parquet export.
- Charts (Apache ECharts, memoized, code-split):
  - accuracy vs latency scatter with the **Pareto front highlighted** and a one-line explanation of how the front is computed;
  - latency box plots with confidence intervals;
  - threads vs FPS lines;
  - temperature over time with throttle events marked;
  - per-class AP heatmap, with a switch to split any accuracy view by **capture source** (`rpi-cam3-wide` vs `mobile`), so a model
    that is good on phone photos but weak on the Pi camera shows up;
  - model/variant by capture-source accuracy table (the headline view for a dataset built from real-world variation);
  - drift chart per variant against the baseline.
- Compare view: up to 4 runs side by side (config, metrics, differences marked significant or not).
- **Compare models (owner request, 2026-11-12; was missing from this brief):** pick two models (for example v_0.0.0.2 and v_0.0.0.3) and see them
  head to head on one dataset version and device: for each model its best variant under the owner's priority list (or chosen metrics), the
  per-class AP difference matched by class name, the pictures where they disagree, and a plain verdict ("A wins on the first two priorities;
  the speed difference is / is not significant"). It needs both models run on the same dataset version and settings; if not, it says what to run.
- **Failure browser:** for a chosen run, the images where it missed, mis-classified or hallucinated, ordered by severity, with
  ground truth and prediction boxes; select frames and export them as a folder for the next annotation round.
- Dashboard highlights: "fastest on Pi 5 within 1% mAP of baseline" computed from the data with the rule shown.
- Invalid-for-latency runs are visibly marked and excluded by default from speed charts.

## Acceptance
- A fixture of ~500 result rows renders in the table with smooth scrolling (virtualization verified in the browser).
- Pareto front test with hand-built points including ties and dominated points.
- Every chart has an accessible description and a data-table fallback; both themes pass contrast.
- Demo seed (finished in Phase 8, but a minimal seeded dataset is used here) shows all charts populated.

## Skills
`dataviz` (first), `frontend-design`, `claude-in-chrome` (look at every chart in both themes and at tablet width), `simplify`,
`code-review`, `run`. `/ponytail lite`.

## Risks
Overplotting with large sweeps: aggregate by configuration first, drill down second.

## Status
Built 2026-11-14 (see STATE.md): the Compare page (answer first, any runs, up to 12 and 3 models, 17 charts in question tabs), the failure browser with annotation export, the All runs table with saved views and CSV, and dashboard highlights. Not built: Parquet export, capture-source split for every accuracy view.

## Owner request, 2026-11-10: charts with interpretations
The full catalogue (17 charts, how to read each, the red flags the page must call out, the data each needs) is in `docs/brief-charts-and-families.md`, section 1. Build order and the interpretation-rule approach are there too. The experiment page already ranks runs by the owner's priority metrics (Settings) and marks the best in each column; the charts build on that.
