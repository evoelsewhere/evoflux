# 0008. Office documents use an optional, pinned LibreOffice runtime downloaded on demand

| | |
| --- | --- |
| Status | Accepted (its "no HTML fallback" part superseded by [0009](0009-native-office-preview-renderer.md)) |
| Date | 2026-11-07 |
| ADD sections | [Crates](../README.md) |
| Related | [Office documents spec](../../features/office/spec.md), [Code intelligence spec](../../features/code-intelligence/spec.md) |

## Context

People ask the agent to read, create and check Word, PowerPoint and Excel files
and want to see them as Office lays them out. v3 solved this with a trimmed
LibreOffice bundle the user installs on request, plus an HTML re-implementation
as a fallback. The bundle is ~190 MB to download and ~630 MB installed, and is
already published as release `office-runtime-26.8.0` for four platforms.

## Decision

Add a leaf crate `evo-office` that owns the pinned manifest, the verified
install and the headless conversion. The engine holds the single runtime and
exposes it through RPC and the agent shell environment. The runtime is a
user-initiated download, pinned by URL, size and SHA-256 compiled into the
binary; the HTML fallback is not carried over. Preview is PDF-based (pdf.js in
the desktop UI).

## Consequences

- Exact previews and one conversion path; without the runtime there is an
  install prompt instead of an approximate rendering.
- A new persistent location (`<agent>/runtimes`, `<agent>/cache/office`) and a
  new network call (only on user action), both listed in the SDD's trust section.
- A new leaf crate in the ADD; `evo-tools` gains a dynamic shell-env hook.
- Releasing a new LibreOffice version means publishing assets and changing the
  pins in `manifest.rs`.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep the HTML fallback | Two renderers to keep equal; approximate output. |
| Bundle in the installer | Size for every user. |
| Depend on a system LibreOffice | Unpredictable versions and paths. |
