# scripts/ — Agent Instructions

Maintainer scripts for sidecar packaging, model registry updates, and release manifest generation.

## Tech stack

- Python scripts are run with the repo's `uv` environment unless the script explicitly documents otherwise.

## Scripts

```
build_sidecar.py          Build the desktop Python sidecar bundle
update_model_registry.py  Refresh bundled model metadata from models.dev
```

## Essential commands

```bash
uv run python scripts/build_sidecar.py --help
uv run python scripts/update_model_registry.py --help
make -C desktop sidecar
```

## Conventions

- Keep scripts non-interactive by default and safe to run from the repo root.
- Prefer argparse help text over separate usage comments.
- Do not embed signing keys, tokens, or machine-specific paths.
- Packaging scripts should preserve cross-platform behavior for macOS, Linux, and Windows.

## Checks

Run the script's `--help` and the smallest focused dry-run or target command available. For sidecar changes, also use `make -C desktop sidecar` when feasible.
