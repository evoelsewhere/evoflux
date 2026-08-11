# EvoFlux Plugin Platform source map

Use this map when changing the platform itself or when package behavior must be checked against current implementation. Read the owning source before editing; this reference is a router, not a substitute for code.

## Product and architecture

- `documents/architecture/agent-plugins.md` — current supported behavior and architecture.
- `documents/analysis/agent-plugins-evoflux-adoption-2026-08-09.md` — standards evaluation and rationale; prefer current source when older deferred decisions differ.
- `/api/plugins` OpenAPI — exact current HTTP request and response contract.

## Backend ownership

- `app/plugin_platform/models.py` — manifest, MCP, credentials, validation result, installation, and runtime data models.
- `app/plugin_platform/validator.py` — package inventory, manifest, Skill, MCP, extension, path, URL, and failure-isolation validation.
- `app/plugin_platform/installer.py` — safe extraction, deterministic packing, managed install/link/update/uninstall, and scaffold.
- `app/plugin_platform/registry.py` — installation identity, atomic registry persistence, enable state, and duplicate source rules.
- `app/plugin_platform/builtins.py` — discovery and stable virtual identities for immutable release-bundled packages.
- `app/plugin_platform/native.py` — private native-provider loading restricted to matching bundled package namespaces.
- `app/plugin_platform/previews.py` — format-neutral document-preview provider selection.
- `app/plugin_platform/runtime.py` — plugin-scoped MCP adaptation, reconciliation, watchers, placeholders, credentials, and last-known-good behavior.
- `app/plugin_platform/credentials.py` — schema projection, `0600` persistence, masking, required status, and environment injection.
- `app/plugin_platform/skills.py` — plugin Skill discovery and precedence integration.
- `app/plugin_platform/workspace.py` — safe editor tree/read/write/create/delete behavior.
- `app/plugin_platform/__init__.py` — public platform service composition.

Workspace editing is UTF-8 only, capped at 1 MiB per file and 2,000 tree entries, excludes repository/cache noise, rejects symlink editing, normalizes forward-relative paths, forbids deletion of `plugin.json`, and removes directories only when empty.

## Product surfaces

- `app/cli/commands/plugin.py` — `create`, `inspect`, `link`, `pack`, `install`, `list`, `show`, `disable`, `enable`, `uninstall`, and `update` CLI behavior.
- Plugin routes under the backend API — inspect/install/upload/update/create/pack, workspace, credentials, enable state, show, and uninstall. Locate the exact route module with `rg 'api/plugins' app`.
- Plugin Center frontend — create/import/link, compact installation cards, validation/runtime detail, editor, credentials, actions, and lifecycle feedback. Locate current owners with `rg 'Plugin Center|plugin-center|credentials missing'` in the frontend tree.

The CLI Create command currently exposes destination, required name,
description, and optional Skill. The underlying scaffold service and Plugin
Center also expose version, author, license, and MCP starter fields. CLI
`inspect` accepts a directory; install/update accept a directory or archive.
Confirm the active surface before documenting commands.

## Platform regression suites

- `tests/plugin_platform/test_platform.py` — manifest warnings/failures, Skills, MCP isolation/placeholders, pack/install/update/uninstall, archive safety, and precedence.
- `tests/api/test_plugin_routes.py` — HTTP lifecycle, workspace, credentials, and runtime refresh.
- `tests/agent/tools/test_skill_loader.py` — built-in/plugin Skill discovery, mode scope, metadata-only catalog, precedence, and tool grants.

Build portable third-party packages outside this repository. Use temporary
local fixtures in these suites to prove the public package and runtime
contracts without shipping a reference third-party plugin in the EvoFlux
source tree. Release-owned packages live under
`app/agent/builtin_plugins/<package>/` and must keep native entrypoints inside
that matching Python namespace.

When adding a core built-in workflow, keep mode scope in
`app/agent/builtin_skills/catalog.py`. A release-bundled plugin instead keeps
host-only mode scope in each Skill's `.evoflux.json`; neither form adds
EvoFlux-only fields to portable `SKILL.md` frontmatter.

## State and generated identity

Default platform-owned state lives below `DATA_DIR/agent-plugins`. Tests should replace the data root with an isolated temporary directory. Runtime and tool names are derived from installation UUID and server name plus hashes; assert stable suffixes and semantic fields, not full generated names.

Every lifecycle mutation that changes validity, credentials, enabled state, package content, or installation presence must reconcile runtime state and invalidate affected Skill discovery caches. Diagnose stale UI only after verifying the API returned a fresh installation snapshot.
