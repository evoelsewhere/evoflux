---
name: plugin-installer
description: Install or update a trusted single-file EvoFlux agent-loop plugin from a raw Python URL into the user plugin directory. Use only when the user explicitly supplies a URL for a legacy hook plugin; do not use for plugin authoring, package/archive installation, skills, MCP servers, or project dependencies.
---

# Install a single-file EvoFlux plugin

Plugins run in-process with agent permissions. Treat installation as executable
code review, not ordinary file download. The supported runtime contract is one
`.py` file under `{EVOFLUX_CONFIG_DIR}/plugins/` exporting either
`async def plugin()` or `class Plugin(BaseAgentHook)`.

## State machine

### 1. FETCH

Require an explicit `https://` raw Python URL. Fetch read-only into a temporary
location. Reject redirects or responses that produce HTML, an archive,
multiple files, a dependency manifest, an absolute/traversal filename, a
leading-underscore filename, or a non-`.py` basename.

### 2. INSPECT

Read the complete file. Require one supported entry point and inspect imports,
top-level execution, subprocess/network/file access, secret handling, dynamic
evaluation, persistence, and hook mutations. Show the user the source URL,
target filename, entry point, material capabilities, and suspicious behavior;
do not reduce review to checking one string.

Do not install code that downloads additional executable content, embeds
credentials, disables permission boundaries, or cannot be understood as a
single-file hook. Do not author or repair untrusted plugin code inside this
workflow.

### 3. RESOLVE COLLISION

If the target exists, read it and show the material diff. An explicit request
to “update” authorizes replacement only after the fetched code and diff have
been shown; an ambiguous install collision requires confirmation. Preserve the
existing file when validation or approval fails.

### 4. INSTALL

Write exactly one file to
`{EVOFLUX_CONFIG_DIR}/plugins/<validated-basename>.py`. Do not create package
directories, install dependencies, or touch unrelated plugins.

### 5. VERIFY

Read the installed file back, confirm its hash/content matches the reviewed
payload, and validate that the entry point remains present. Legacy hook plugins
are cached per agent/role, so report that a runtime restart is required before
the new or replaced hook is reliably active. Never claim activation merely
from a successful write.

## Other operations

- List: inspect `.py` files in `{EVOFLUX_CONFIG_DIR}/plugins/`, excluding
  leading-underscore disabled files.
- Disable/remove: perform only when explicitly requested, identify the exact
  file first, and prefer a recoverable leading-underscore rename when suitable.

## Stop conditions

Stop when the URL and target are exact, the complete code has been reviewed,
collision handling is resolved, the installed bytes match the approved source,
and activation timing is accurately reported.

## Deliverable

Report URL, exact target path, entry point, reviewed capabilities, collision
decision, verification, and restart requirement. If refused, name the concrete
contract or safety violation.
