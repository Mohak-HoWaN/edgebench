# Phase 7: Research-paper report

**Goal:** pick experiments and sections, edit the text, and export an IEEE two-column PDF, a LaTeX zip, and a raw-data zip with a
one-command reproduce script.

## Build
- **Template library (owner decision).** The export dialog asks which template the user wants; each is a folder
  `templates/<id>/` with `meta.json` (name, columns, citation style, page limit if any, required packages), a Jinja front-matter
  file (title, authors, abstract, keywords differ per class), and shared section content. Section text is template-independent, so
  switching template re-renders without losing edits. Initial library: **IEEE conference (IEEEtran, two-column)**, **IEEE journal
  (IEEEtran journal mode)**, **ACM (acmart, sigconf)**, **Springer LNCS (llncs)**, **Elsevier (elsarticle)**, **arXiv-style single
  column (article)**, and a **plain project report** (article, 11 pt, with title page and table of contents) for coursework. Each
  template must compile in Tectonic in the acceptance test; any that does not is dropped, not shipped broken. A user-supplied template
  upload is not in the first version (it would run arbitrary LaTeX); it can be added later with shell-escape disabled.
- **Engine:** Jinja2 templates to LaTeX, compiled with Tectonic; fallback HTML to PDF with WeasyPrint when Tectonic is
  missing, with a visible note in the UI that the layout differs. Escape all user and data text for LaTeX (dataset names, class names
  and model names contain underscores and special characters).
- **Sections:** Title; Abstract (auto-drafted from results); Introduction; Related Work (editable placeholder references, a BibTeX
  field); Methodology (hardware, software versions, dataset, conversion settings, measurement protocol with warm-up, repeats and the
  CI method from the Phase 4 ADR); Results (tables and vector figures, auto-numbered, referenced in the text); Discussion
  (auto-generated observations with the numbers inserted, for example "INT8 OpenVINO gave 2.3x speedup on Pi 5 with 0.8 mAP drop",
  only when the difference is significant, otherwise worded as "no significant difference"); Threats to Validity (throttling events,
  sample size, catalogue-vs-camera dataset, the PC noise note); Conclusion; Reproducibility appendix (full environment manifest and the
  exact commands to rerun).
- **Editing:** text sections editable in the UI with live preview (rendered PDF page images) before export; edits are stored with the
  report, auto-generated parts can be regenerated without losing manual edits (keep them as separate fields).
- **Figures:** matplotlib vector PDF/SVG using the Phase 6 palette so figures match the dashboard.
- **Exports:** PDF; LaTeX zip (source, figures, `.bib`); raw data zip (CSV/Parquet, environment manifests, logs). Each zip includes
  `reproduce.sh` and `reproduce.ps1` that recreate the environment from the lockfile, fetch the model/dataset by hash and rerun.
- Model card: a one-page export from the same data.

## Acceptance
- pytest: LaTeX escaping with nasty strings (`_ % & # { } \ ^ ~`), numbering and cross-references resolve, auto-drafted sentences
  match the numbers in the tables, significant vs not-significant wording.
- Real: generate a report from the seeded experiments, compile with Tectonic, inspect with the `pdf` skill (two columns, page count,
  no overfull boxes, figures vector, text extractable). Run `reproduce.ps1` in a clean temp folder and confirm it reproduces one
  result within the CI.
- Fallback path tested by forcing Tectonic off (the fallback has one generic layout, so the template choice is disabled with a note).
- Every template in the library compiles from the same seeded experiment and its PDF is inspected; the same text edit appears in all.

## Skills
`pdf` (inspect output), `dataviz` (same palette in matplotlib), `claude-in-chrome` (the preview UI), `frontend-design`, `simplify`,
`code-review`, `run`. `/ponytail lite`.

## Risks
Tectonic downloads LaTeX packages on first compile (needs internet once); vendor a package bundle if the machine will be offline.
Auto-generated prose must never state a claim the data does not support: every generated sentence is tied to a number and a test.

## From Phase 0 (binding; see `docs/phase-0-verdict.md`)
- Tectonic 0.17.0 compiled all seven template classes (IEEEtran conference/journal, acmart sigconf, llncs, elsarticle, article, report) from a
  minimal document. First compile downloads packages (ACM took 140 s); vendor a bundle if the machine will be offline.
  Layout and page counts were not inspected yet; the acceptance test must.

