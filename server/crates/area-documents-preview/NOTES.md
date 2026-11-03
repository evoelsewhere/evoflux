# area-documents-preview NOTES

Python source: `app/api/routes/team/{document_versions,motion_review,office_runtime}.py`,
the `media`, `document-preview` and `office-preview` routes of
`app/api/routes/team/files.py` (with `_session_workspace`, `_safe_resolve`,
`_resolve_workspace_entry`), `app/api/schemas/office_runtime.py`,
`app/services/document_preview/**`, `app/services/{document_versions,document_text,motion_review_service}.py`,
`app/services/office_runtime/{convert,installer,manifest}.py`. Contract tests:
`contract-tests/documents-preview/`.

**Status:** La (stub, NOTES, contract tests). The crate is not mounted. No API types stub.

## Routes

Every route answers `401 {"detail":"Unauthorized — EvoFlux access key required."}` before any
validation. Prefix `/api/team`.

| Endpoint | Behaviour | Errors |
|---|---|---|
| `GET /{sid}/media/{path}?download` | `FileResponse` of a file under the session workspace; `Content-Type` from the suffix (fallbacks for `.webp .avif .wasm`, else `application/octet-stream`); `inline` or, with `download=true`, `attachment`; ETag, `Accept-Ranges: bytes`, range requests (`206`, `416`) | `400 Invalid session id.` (not a UUID), `400 Empty media path.`, `400 Absolute media paths rejected.` (also an `X:` drive prefix), `400 Media path escapes session root.` (`..` or a link leading out), `404 Media file not found.` (missing or a directory), `422` bad `download` |
| `GET /{sid}/document-preview/{path}?renderer=native` | renders `.docx/.xlsx/.pptx` to one HTML file with the bundled read-only engine (exact PDF-page renderer when the Office runtime is installed; `native` skips it) and serves it as `text/html` with `Cache-Control: private, no-cache`, a CSP, `Referrer-Policy: no-referrer`, `nosniff`; a deck renders live only while its session's turn runs | same path errors as media, `415` unsupported or not-an-archive (message starts `This file has a .<ext> name`), `422` render failure or a `renderer` other than `native` |
| `GET /{sid}/office-preview/{path}` | deprecated alias of the above | same |
| `GET /{sid}/document-versions?path` | history of one Word/Excel/PowerPoint file; the baseline is recorded on first read | `400` session/path errors, `404 Document not found.` (also other letter case, directory), `415 Only Word, Excel and PowerPoint files keep versions.`, `422` empty `path` |
| `POST /{sid}/document-versions {path,action,label?,version_id?}` | `checkpoint` (labels the next change; unchanged content adds nothing; label cut to 200), `undo`, `redo`, `restore` (writes the chosen version back); a new change after undo drops the redo branch; at most 50 versions | `409` `DocumentVersionError` text, `422 version_id is required.`, body validation `422` |
| `POST /{sid}/motion-review/{job_id}` | a top-level session uploads 1 to 12 JPEG/WebP frames (<= 200 KiB each, <= 640x360, <= 2.4 MiB in total, base64) for a waiting motion job; the body is streamed and capped at 3 MiB | `422 Invalid motion job id.` (`motion-<32 hex>`), `413 Motion review request is too large.`, `404 Team session not found.` (no row, or a child session), `400` session id, `422` body validation (pydantic detail lists), `409` unknown or rejected request |
| `GET /office-runtime/status` | `{available, platform, version, download_bytes, install_bytes, installed_version, job}` | - |
| `POST /office-runtime/install`, `/install/cancel` | start or stop the download of the pinned LibreOffice archive; status body | `409` `RuntimeInstallError` text (for example no published runtime for this platform) |
| `POST /office-runtime/install/dismiss` | clears a failed job, `204` | - |
| `DELETE /office-runtime` | uninstalls, `204` | `409` while a job runs |

## Files, processes and state

| Resource | Used by |
|---|---|
| session workspace (`ChatSession.workspace` of a Coding session, else `<EVOFLUX_WORKSPACE_DIR>/<sid>`); a missing row is tolerated | media and previews read; document versions read and write back (`restore`, `undo`, `redo`) |
| `<EVOFLUX_STATE_DIR>/document-versions/<sid>/<sha256(path)[:32]>/` (manifest, `blobs/<sha256>`) | document versions; written atomically, one thread lock per history |
| `<EVOFLUX_DATA_DIR>/runtimes/<RUNTIME_ID>/` (installed LibreOffice tree, `.download-<sha>.part`, staging) | office runtime install, uninstall, conversion |
| LibreOffice child process (`soffice`, private profile dir, process-tree kill on timeout) | `convert_to_pdf`, used by the exact renderer and by the agent's `document_preview` tool |
| in memory: install job, pending motion-review requests, pending checkpoint labels, workspace watcher callbacks (`ensure_watching`) | the agent's visualize and `document_preview` tools, `shell` (`expose_to_tool_environment`), `filesystem` handlers (`record_version`) |

**Pins check** (`rg "document_versions|motion_review_service|office_runtime|document_preview|document_text"` outside
the unit): `app/agent/tools/builtin/{document_preview,shell,web,filesystem/handlers,visualize/motion_review}.py`,
`app/agent/loader.py`, `app/services/agent_service.py`, `app/services/document_text.py`. **Needs adapter** per
`server/AGENTS.md` before cutover: the agent records versions (`record_version`), waits for motion samples
(`wait_for_motion_samples`), calls the preview engine and reads the runtime path in-process, so a Rust unit
would not see the agent's side of this state. `adapter:documents-preview` must bridge it. La adds none.

## Odd behaviour and findings

- **S1: no session authorization.** Any well-formed UUID addresses `<EVOFLUX_WORKSPACE_DIR>/<uuid>`; a session id
  without a row is not refused (pinned by a test). Whoever holds the access key reads any session's files, of any type
  and including dot-files. Path confinement is `resolve()` plus a containment check, not a race-free open (TOCTOU, same
  class as the tools lane). Needs security review at Lb.
- **S2: the preview engine parses untrusted Office/zip content in process** (about 5.3k lines of XML, formula and xlsx
  parsing in `service.py`, bounds in `security.py`). Limits and sanitising must be ported exactly, and a parser panic
  must not take the server down. Needs security review at Lb.
- **S3: the runtime installer follows HTTP redirects** (`follow_redirects=True`) for a pinned URL. The archive is checked
  by size and SHA-256 and every tar member is validated (<= 60 000 entries, <= 4 GiB, only `soffice/`, links and
  traversal refused), but the redirect target is not restricted (host pinning to decide at Lb). `install` starts a
  large download from one authenticated call with no confirmation.
- **S4: conversion starts an external process on untrusted documents** (`soffice` with a private profile); the
  environment, timeout and kill-tree rules are Lb work. La never starts a converter.
- **B1: `POST motion-review` with a body that is not JSON answers `500`, not `422`.** The `json_invalid` error from
  `exc.errors()` holds the raw bytes in `input`, which cannot be serialised. The contract test accepts 422 or 500; the
  Rust port should answer 422 (record in `KNOWN_DIFFERENCES.md` at Lb).
- A rooted path without a drive: `document-versions` answers `Path must be relative.` on POSIX but
  `Path escapes workspace root.` on Windows (not absolute there); `C:/x` is `Path must be relative.` on both. The tests
  are OS-aware.
- Media errors say "Media" even for previews (shared `_safe_resolve`); versions use `_resolve_workspace_entry` with other texts.

## Test status and test map

77 cases against Python v3.1.1 (`TARGET=python`, Windows, `-n 4`): 76 pass, 1 skip (creating a symlink needs privileges).
`TARGET=rust` is not applicable until Lb mounts the crate. No converter, no network install and no real runtime are used.

| Behaviour | Test |
|---|---|
| auth on all 11 routes, no and wrong key | `test_contract.py::test_auth_before_validation` |
| session id, empty/absolute/escape paths, missing files, headers, ranges, content types, unknown-session fallback, symlink escape | `test_contract.py`, `test_media_motion_runtime.py::test_media_*` |
| previews: unsupported suffix, corrupt archive, `renderer` values | `test_contract.py`, `test_media_motion_runtime.py::test_document_preview_*` |
| versions: baseline, undo/redo, branch drop, checkpoint labels, restore, per-path history, storage under the state dir, path errors | `test_versions.py` |
| motion review: job id, body validation, size limit, session and child-session checks | `test_media_motion_runtime.py::test_motion_review_*` |
| office runtime: status shape, install without a published runtime, wrong methods | `test_media_motion_runtime.py::test_office_runtime_*`, `test_runtime_wrong_methods` |

Not covered: a successful preview render (needs a document corpus; the Rust port of `service.py` brings its own golden
files), live deck rendering, the exact PDF renderer, a successful motion sample upload (needs a waiting agent job),
installer download, extraction and uninstall of an installed runtime.

## Lb: size and dependencies

By far the largest piece is `document_preview/service.py` (docx, xlsx formulas and features, pptx, live deck, CSP) with
`security.py`. Then the media proxy (small; needs `core::paths` and range-capable file responses), the version store
(small), motion review (small), and the runtime installer and converter (process supervision shared with `area-tools`,
an HTTPS client with address pinning). Needs the session and workspace table, `core::paths`, zip and XML parsers and the
owner's decisions on S1 to S4. Slices: media and versions, office runtime, motion review, previews.
