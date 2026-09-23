# Notebooks

Create, edit, or validate reproducible SQL/Python Jupyter notebooks that are easy to skim, rerun, and hand off. A notebook is a reader-facing analysis artifact, not a scratchpad dump, and is not done until it executes top-to-bottom or the execution gap is stated with the exact steps to reproduce.

## Contents

- Workflow
- Structure
- Reproducibility and hygiene
- Execute and validate

## Workflow

1. **Lock the mode and scope.** Analysis report, experiment log, diagnostic, data-quality check, market-sizing calculation, model exploration, tutorial, or report companion. Identify the reader, decision, required inputs, and whether this is a new notebook or targeted edits.
2. **Use notebook-safe tooling.** Prefer `nbformat` (or JupyterLab) to create and edit notebooks rather than hand-editing JSON. When editing, preserve the notebook's intent, minimize JSON churn, and avoid reordering cells unless it clearly improves the story. If raw JSON edits are unavoidable, validate the structure afterwards (`nbformat.validate`).
3. **Build a clear computation path.** Separate setup and imports, parameters, data loading, preparation, calculations, visualizations, and interpretation. Keep complex SQL in SQL cells or query files, not large Python strings, with a one-line goal comment.
4. **Use data sources deliberately.** Confirm table choice, schema, partition filters, sample rows, and query rules before heavy queries. Filter by needed partitions, cohorts, or windows instead of broad scans. Record query links or IDs, table names, source paths, spreadsheet tabs, dashboard links, extract versions, or input file locations for every result the analysis relies on.
5. **Keep cells readable and bounded.** A short action header before most code cells (`### 1. Load Data`, `### 2. Validate Inputs`, `### 3. Plot Results`). Several short focused cells beat one large one; one table or chart per cell. Explain purpose, assumptions, and expected result, not each line.
6. **Validate before concluding.** Key numbers, charts, and takeaways must match executed outputs. Add a reasonableness check, small sample inspection, or reconciliation before promoting a surprising result to the summary.

## Structure

Analytical notebooks:

1. `## tl;dr`
2. `## Context & Methods` (with `### Key Assumptions` when assumptions affect correctness)
3. `## Data`
4. `## Results`
5. `## Takeaways`

Write `tl;dr` and takeaways last, from executed outputs, with concrete observed values. Never promote unexecuted or unverified calculations into the `tl;dr`.

Tutorials and walkthroughs: `## Goal`, `## Setup`, `## Steps`, `## Checks`, `## Next Steps`.

## Reproducibility and hygiene

- Parameters, date ranges, filters, cohorts, assumptions, and source references sit near the top.
- Deterministic computation: no hidden state, manually edited intermediate values, out-of-order dependencies, or unexplained cached outputs.
- Note nonstandard packages, kernels, credentials, or local files in a setup cell.
- Separate data preparation from presentation; do plotting and light shaping in Python after preparation.
- Descriptive variable names; no cryptic temporary names in reader-facing notebooks.
- Bounded outputs: small previews, explicit limits, focused charts; no raw debug dumps or noisy logs.
- Label caveats, incomplete checks, missing source access, and known validation gaps.

## Execute and validate

Run top-to-bottom:

```bash
uv run --with jupyter --with nbclient --with ipykernel jupyter nbconvert --execute --to notebook --inplace path/to/notebook.ipynb
```

Add the notebook's own dependencies with more `--with` flags (for example `--with pandas --with matplotlib`). If execution is impossible, say so and give the exact command plus the missing dependency, credential, data access, or kernel.

Checklist:

- section order matches the notebook mode;
- executes without errors, or the failure is stated;
- outputs present and not dominated by debug dumps;
- `tl;dr`, results, and takeaways match executed cells;
- source references preserved; tables and charts labeled and bounded;
- the final response gives the notebook path, and mentions execution status only when it was partial or not run.

When notebook results support a shared claim or decision, run `references/pre-share-review.md`.
