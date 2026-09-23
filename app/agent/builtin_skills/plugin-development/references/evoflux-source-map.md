# EvoFlux Plugin Platform source map

Use this map when changing the platform itself inside the EvoFlux repository,
or when package behavior must be checked against the implementation. Read the
owning source before editing; this reference is a router, not a substitute for
code. The `/api/plugins` OpenAPI schema is the exact HTTP request and response
contract.

## Backend ownership

- `app/plugin_platform/models.py` — manifest, MCP, credentials, validation result, installation, and runtime data models.
- `app/plugin_platform/validator.py` — package inventory, manifest, Skill, MCP, extension, path, URL, and failure-isolation validation.
- `app/plugin_platform/extensions.py` — EvoFlux extension namespaces and their compatibility aliases.
- `app/plugin_platform/installer.py` — safe extraction, deterministic packing, managed install/link/update/uninstall, and scaffold.
- `app/plugin_platform/registry.py` — installation identity, atomic registry persistence, enable state, and duplicate source rules.
- `app/plugin_platform/builtins.py` — discovery and stable virtual identities for immutable release-bundled packages.
- `app/plugin_platform/trust.py` — static trust disclosures derived from a package's declared credentials, MCP servers, and URLs.
- `app/services/document_preview/` — host-owned, read-only Office/PDF viewer backend.
- `app/plugin_platform/runtime.py` — plugin-scoped MCP adaptation, reconciliation, watchers, `${PLUGIN_ROOT}`/`${PLUGIN_DATA}` substitution, credentials, and last-known-good behavior.
- `app/plugin_platform/credentials.py` — schema projection, `0600` persistence, masking, required status, and environment injection.
- `app/plugin_platform/skills.py` — plugin Skill discovery and precedence integration.
- `app/plugin_platform/workspace.py` — safe editor tree/read/write/create/delete behavior.
- `app/plugin_platform/__init__.py` — public platform service composition.

Workspace editing is UTF-8 only, capped at 1 MiB per file and 2,000 tree entries, excludes repository/cache noise, rejects symlink editing, normalizes forward-relative paths, forbids deletion of `plugin.json`, and removes directories only when empty.

## Product surfaces

- `app/cli/commands/plugin.py` — `create`, `inspect`, `link`, `pack`, `install`, `list`, `show`, `disable`, `enable`, `uninstall`, and `update` CLI behavior.
- Plugin routes under the backend API — inspect/install/upload/update/create/pack, workspace, credentials, enable state, show, and uninstall. Locate the exact route module with `rg 'api/plugins' app`.
- Plugin Center frontend — create/import/link, compact installation cards, validation/runtime detail, editor, credentials, actions, and lifecycle feedback. Locate the owning components with `rg 'Plugin Center|plugin-center|credentials missing'` in the frontend tree.

The CLI `create` command takes a destination, a required `--name`, an optional
`--description`, and an optional `--skill`. The underlying scaffold service and
Plugin Center also accept version, author, license, and Skill fields; Plugin
Center defaults a blank Skill name to the plugin name. Automatic MCP
scaffolding is rejected because the platform cannot supply a portable
executable. CLI `inspect` accepts a directory; install/update accept a
directory or archive. Confirm the active surface before documenting commands.

## Platform regression suites

- `tests/plugin_platform/test_platform.py` — manifest warnings/failures, Skills, MCP isolation/placeholders, pack/install/update/uninstall, archive safety, and precedence.
- `tests/api/test_plugin_routes.py` — HTTP lifecycle, workspace, credentials, and runtime refresh.
- `tests/agent/tools/test_skill_loader.py` — built-in/plugin Skill discovery, metadata-only catalog, precedence, and tool grants.

Build portable third-party packages outside this repository. Use temporary
local fixtures in these suites to prove the public package and runtime
contracts without shipping a reference third-party plugin in the EvoFlux
source tree. Release-owned packages live under
`app/agent/builtin_plugins/<package>/` and use the same portable Skill/MCP
contract as managed packages.

Trusted in-process hooks are a separate source-owned contract under
`app/agent/plugins/loader.py`: flat `.py` files from the configured plugin
directories, not Plugin Center package directories.

Plugin Skills, release-bundled plugin Skills, and core built-in Skills all use
the same portable Agent Skills contract. None of them has a mode scope or a
host sidecar file; EvoFlux-specific behavior is expressed only through the
`disable-model-invocation` and `user-invocable` frontmatter keys.

## State and generated identity

Default platform-owned state lives below `DATA_DIR/agent-plugins`. Tests should replace the data root with an isolated temporary directory. Runtime and tool names are derived from installation UUID and server name plus hashes; assert stable suffixes and semantic fields, not full generated names.

Every lifecycle mutation that changes validity, credentials, enabled state, package content, or installation presence must reconcile runtime state and invalidate affected Skill discovery caches. Diagnose stale UI only after verifying the API returned a fresh installation snapshot.
