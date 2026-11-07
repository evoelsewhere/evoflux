# 0004. bun is the only JavaScript package manager for the desktop

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-06 |
| ADD sections | [3. Architectural drivers](../README.md#3-architectural-drivers) |
| Related | none |

## Context

Mixing package managers in `apps/desktop` rewrote `node_modules` (pnpm once
replaced it with its own layout) and produced lockfiles that disagreed.

## Decision

`apps/desktop` uses bun only: `bun install --frozen-lockfile`, `bun run …`,
and `bun.lock` is the lockfile. npm, pnpm and yarn are not used there.

## Consequences

- CI uses `oven-sh/setup-bun` and `bun install --frozen-lockfile`.
- Scripts may use Bun APIs (`scripts/prepare-sidecar.ts`).

## Alternatives considered

| Option | Why not |
| --- | --- |
| npm or pnpm | the lockfile and scripts already rely on bun; mixing broke installs |
