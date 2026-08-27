# EvoFlux 1.0.0 publication

Status: accepted

## Problem and outcome

The synchronized `1.0.0` sources are not a distributable release until the
change is committed, a matching immutable tag is pushed, curated release notes
are attached, and the tagged desktop workflow begins. The outcome is a
traceable `v1.0.0` release candidate that the existing multi-platform workflow
can build, sign, validate, and publish as EvoFlux's first stable release.

## Goals

- Generate a curated changelog and release overview that identify `1.0.0` as
  the first stable release.
- Commit only the version and release artifacts in scope.
- Create and push an annotated `v1.0.0` tag at the release commit.
- Seed a GitHub draft release with the curated overview and generated commit
  notes, then let the tagged workflow upload artifacts and publish it.
- Confirm the tag-triggered workflow run exists for the release commit.

## Non-goals

- Changing product behavior, schemas, dependencies, or supported platforms.
- Bypassing artifact validation, signing requirements, or updater checks.
- Force-pushing, replacing an existing tag, or publishing incomplete assets.
- Including unrelated local documentation or research work in the release
  commit.

## User flows and states

A maintainer reviews the release diff, commits it, creates `v1.0.0`, and pushes
the branch and tag. GitHub Actions starts the four-platform build. A curated
draft release exists while builds run; the workflow adds validated assets and
publishes it as the latest release only after all required jobs succeed.

If a build or signing gate fails, the workflow remains failed and the draft is
not presented as a completed stable release.

## Requirements and acceptance criteria

- **AC-1 — Curated history:** `CHANGELOG.md` and
  `documents/releases/v1.0.0.md` summarize the changes since `v0.0.8` and state
  that `1.0.0` is the first stable release.
- **AC-2 — Version integrity:** the five canonical version sources and two
  generated lockfile package entries equal `1.0.0`; the release workflow's tag
  validation contract remains satisfied.
- **AC-3 — Scope integrity:** the release commit contains only approved version,
  changelog, release-process, and release-specification files. Existing
  unrelated working-tree changes remain uncommitted.
- **AC-4 — Release identity:** annotated tag `v1.0.0` points exactly to the
  release commit locally and on `origin`.
- **AC-5 — Official notes:** a GitHub draft release for `v1.0.0` contains the
  curated first-stable note before the build workflow reaches its publication
  job.
- **AC-6 — Build trigger:** GitHub Actions reports a tag-push run of
  `Build desktop packages` whose head SHA is the release commit.
- **AC-7 — Publication truth:** completion is claimed only for observed states;
  a queued or running build is reported as triggered, not yet published.

## API, event, tool, and UI contracts

No product API, event, tool, or UI contract changes. The external release
contract is the existing `v*` tag workflow and its four desktop artifact sets,
checksums, updater manifest, and GitHub Release publication job.

## Data model, migration, and retention

No new data model or migration. The existing migration head and upgrade path
remain part of the release gates. Git history, the annotated tag, workflow run,
release notes, and published assets form the durable release record.

## Permissions, security, privacy, and trust

The push uses the configured `origin`; GitHub Actions alone reads signing and
updater secrets. No credential value is printed, stored in release notes, or
added to the repository. Branch and tag history are not rewritten.

## Concurrency, failure, recovery, and idempotency

Remote branch and tag existence are checked before push. The draft release is
created only after the tag is visible remotely. Re-running the workflow may
reuse an existing draft, but refuses to replace a published immutable release.
A failed workflow leaves inspectable logs and an unpublished draft for recovery.

## Observability and diagnostics

Evidence includes the release commit SHA, local and remote tag targets, GitHub
draft URL, Actions run URL, event, head SHA, status, and conclusion when known.

## Compatibility, rollout, and rollback

Rollout is performed by the existing tag workflow. Before publication, recovery
uses a follow-up commit and a new version/tag rather than rewriting a public
release identity. A published `v1.0.0` is not silently replaced or deleted.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1 | Changelog/release-note inspection against `git log v0.0.8..HEAD` |
| AC-2 | Five-source comparison, lockfile diff, focused package/build checks |
| AC-3 | `git status`, staged-name review, `git diff --cached --check` |
| AC-4 | `git rev-parse` plus local/remote tag comparison |
| AC-5 | `gh release view v1.0.0` body and draft-state inspection |
| AC-6 | `gh run list`/`gh run view` for the tag and release SHA |
| AC-7 | Final handoff distinguishes triggered, running, failed, and published |

## Ownership and source map

- Version sources and lockfiles: documented in
  `documents/plans/release-1.0.0-version-bump.md`.
- Curated history: `CHANGELOG.md` and `documents/releases/v1.0.0.md`.
- Release process: `documents/development/release-and-packaging.md`.
- Build and publication automation: `.github/workflows/desktop-packages.yml`.
