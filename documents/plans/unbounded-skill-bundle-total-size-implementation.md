# Unbounded aggregate Skill bundle size — implementation plan

Status: proposed

Specification:
[`unbounded-skill-bundle-total-size.md`](unbounded-skill-bundle-total-size.md)

## Scope and invariants

This plan implements AC-1–AC-10 by removing only aggregate byte accounting and
rejection. Per-file limits, entry limits, filesystem containment, symlink
rejection, bounded preview behavior, transaction staging and non-Skill upload
limits remain invariant.

## M1 — Service and API contract

ACs: AC-1, AC-2, AC-4, AC-5, AC-6, AC-7, AC-8

Owned paths:

- `app/services/agent_fs.py`
- `tests/services/test_agent_fs.py`
- `tests/api/routes/test_skills.py`

Changes:

- Remove `_MAX_SKILL_BUNDLE_BYTES`.
- Remove aggregate byte accumulation/rejection from update payload decoding.
- Remove aggregate byte accumulation/rejection from final staged-bundle
  validation.
- Replace the former rejection regression with create/update success coverage
  above a small monkeypatched historical threshold or a compact repeated-file
  fixture that proves no aggregate gate remains.
- Rerun retained per-file, entry, path, symlink, preview-budget and atomicity
  tests.

Evidence:

```bash
uv run pytest --no-cov -q tests/services/test_agent_fs.py tests/api/routes/test_skills.py
```

## M2 — Validator parity

ACs: AC-3, AC-4, AC-5, AC-6

Owned paths:

- `scripts/validate_skills.py`
- `tests/scripts/test_validate_skills.py`

Changes:

- Remove `MAX_BUNDLE_BYTES` and aggregate byte accumulation/rejection.
- Add a regression proving aggregate bytes alone do not invalidate a Skill.
- Retain bounded scandir, per-resource size and entry-count evidence.

Evidence:

```bash
uv run pytest --no-cov -q tests/scripts/test_validate_skills.py
uv run python scripts/validate_skills.py --help
```

## M3 — Current documentation and Help

ACs: AC-8, AC-9

Owned paths:

- `documents/features/tools-skills-mcp-and-plugins.md`
- `web/src/help/locales/en.ts`
- `web/src/help/locales/vi.ts`
- `web/src/help/locales/ja.ts`

Changes:

- Document that EvoFlux has no aggregate byte ceiling for Skill resources.
- State the retained per-file, entry-count, path/symlink and bounded-preview
  constraints.
- Explicitly distinguish Skill bundle resources from attachment/upload limits.

Evidence:

```bash
cd web && bun run lint && bun run typecheck && bun run build
```

## M4 — Integration and handoff

ACs: AC-1–AC-10

Checks:

```bash
uv run ruff check app/ scripts/ tests/
uv run ruff format --check app/ scripts/ tests/
uv run ty check app/
uv run pytest --no-cov -q tests/services/test_agent_fs.py tests/api/routes/test_skills.py tests/scripts/test_validate_skills.py
cd web && bun run lint && bun run typecheck && bun run build
git diff --check
```

Integration inspection:

- confirm no aggregate-size constant or error remains in the Skill CRUD or
  validator paths;
- confirm unrelated 20 MB attachment/message limits remain unchanged;
- validate an installed large Skill and confirm no `bundle-too-large` finding;
- restart EvoFlux only after the active presentation workflow reaches a safe
  stopping point, because editing `app/services/agent_fs.py` reloads the
  sidecar and interrupts active Work runs.

## Rollback

Restore the aggregate constants, accumulation checks, error messages and prior
rejection tests. No data migration or cleanup is required.
