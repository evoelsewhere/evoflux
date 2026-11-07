# 0009. Office files render natively in the engine; LibreOffice gives exact pages

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| ADD sections | [Crates](../README.md) |
| Related | Partly supersedes [0008](0008-optional-libreoffice-runtime.md) (its "the HTML fallback is not carried over"); [Office v3 parity spec](../../features/office-v3-parity/spec.md) |

## Context

ADR 0008 made LibreOffice → PDF the only Office preview. That drops what v3
built on its built-in renderer: shape ids and cell coordinates (area edits),
cheap re-renders on every save (live builds), and element geometry the agent can
check without looking at pixels (`document_preview`). The owner asked for v3's
behaviour with the same logic. v3's renderer was ~5 000 lines of Python in a
Python sidecar that v4 does not have.

## Decision

Port v3's built-in renderer to Rust in `evo-office` (`preview` module), keeping
its HTML contract (`data-preview-item`, `data-qa-label`, `data-shape-id`,
`data-cell`, `data-deck-live`, % geometry, the CSP). The engine serves it to the
desktop (`office_preview`) and to the agent (`document_preview`). LibreOffice
stays optional and becomes the "exact pages" mode (PPTX/DOCX when installed,
XLSX Print layout), as in v3. The engine also keeps Office document versions.

## Consequences

- No new runtime or language: rendering works offline, for headless chats and
  for the agent tool. The native render is an approximation of Office layout
  and the viewer says so when exact pages are available.
- Two renderers to keep consistent in the viewer (native HTML in an iframe,
  exact pages with pdf.js); the markup contract is shared by the viewer, the
  agent tool and area edits, and changes bump `CACHE_SCHEMA_VERSION`.
- `evo-office` gains XML/zip dependencies (`roxmltree`, `zip`) and a much larger
  surface; package preflight (v3 `security.py`) guards every parse.
- New persistent data: `<agent>/document-versions/` (copies of user files).

## Alternatives considered

| Option | Why not |
| --- | --- |
| Run v3's Python renderer with `uv` | Every preview needs `uv` and a first-run download; Python start per live save. |
| TypeScript renderer in the webview | The agent tool and headless chats would depend on the UI. |
| LibreOffice only (ADR 0008) | No shapes or cells, slow live builds, no geometry for the agent. |
