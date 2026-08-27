# EvoFlux 1.0.0 version bump

Status: implemented

## Problem and outcome

EvoFlux is preparing a `1.0.0` release, while its package and application
metadata still identify the product as `0.0.8`. The outcome is a mechanical,
traceable version synchronization across every canonical source and generated
lockfile without claiming that unpublished `v1.0.0` artifacts already exist.

## Goals

- Set every release-validated application version source to `1.0.0`.
- Regenerate Python and Rust lock metadata so local package identities agree.
- Preserve the currently published stable-download links until release assets
  for `v1.0.0` have actually been published.
- Verify package metadata, migrations, frontend compilation, and the desktop
  Rust crate after the bump.

## Non-goals

- Creating or pushing a `v1.0.0` Git tag.
- Publishing GitHub releases, installers, updater manifests, checksums, or
  signed artifacts.
- Changing dependency versions, schemas, runtime behavior, or feature status.
- Rewriting historical release evidence or tests whose version strings are
  scenario fixtures rather than application metadata.

## User flows and states

Maintainers build packages from a checkout whose Python project, sidecar
version marker, web package, Rust package, Tauri bundle, and lockfiles all
identify `1.0.0`. Until the release workflow publishes immutable artifacts,
the README continues to advertise the last actually available stable release.

## Requirements and acceptance criteria

- **AC-1 — Canonical alignment:** `pyproject.toml`, `app/version.txt`,
  `web/package.json`, `desktop/src-tauri/Cargo.toml`, and
  `desktop/src-tauri/tauri.conf.json` all equal `1.0.0`.
- **AC-2 — Lock alignment:** the editable EvoFlux entry in `uv.lock` and the
  `evoflux-desktop` package entry in `Cargo.lock` equal `1.0.0` and no unrelated
  dependency versions change.
- **AC-3 — Published-release truth:** README download links remain on `v0.0.8`
  until `v1.0.0` assets exist.
- **AC-4 — Verification:** release-version validation, schema-head/migration
  checks, frontend type/build checks, and `cargo check` pass.
- **AC-5 — Scope integrity:** historical evidence and unrelated user-owned
  documentation changes remain untouched.

## API, event, tool, and UI contracts

No API, event, tool, or UI shape changes. Version-reporting surfaces return
`1.0.0` after restart or packaging from the updated checkout.

## Data model, migration, and retention

No schema or data migration is introduced. Existing migration head remains
authoritative and must still pass its alignment and fresh-upgrade tests.

## Permissions, security, privacy, and trust

No permission, secret, signing, updater-key, sandbox, or trust-boundary change.
No signing material is created or read.

## Concurrency, failure, recovery, and idempotency

The bump is deterministic and idempotent. A failed verification leaves only
reviewable text metadata changes; rollback is the inverse version change before
tagging. Published release assets are outside this change.

## Observability and diagnostics

Health, diagnostics, Python package metadata, and desktop bundle metadata must
report the synchronized version after their respective runtime/build restart.

## Compatibility, rollout, and rollback

Semantic-version compatibility is declared by the user-requested `1.0.0`
identity only; this task does not make additional behavioral compatibility
claims. Rollout occurs later through the tagged release workflow. Before that
tag, the bump can be reverted as an ordinary source change.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1 | release-workflow-equivalent five-source comparison |
| AC-2 | focused lockfile diff plus package-manager checks |
| AC-3 | README diff inspection |
| AC-4 | schema-version/migration pytest, web typecheck/build, `cargo check` |
| AC-5 | `git status`, scoped diff review, `git diff --check` |

## Ownership and source map

- Python package: `pyproject.toml`, `uv.lock`.
- Runtime sidecar marker: `app/version.txt`.
- Web package: `web/package.json`.
- Desktop crate/bundle: `desktop/src-tauri/Cargo.toml`, `Cargo.lock`, and
  `tauri.conf.json`.
- Release validation: `.github/workflows/desktop-packages.yml` and focused
  release/schema tests.
