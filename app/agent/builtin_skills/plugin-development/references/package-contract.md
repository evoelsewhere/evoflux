# Portable package contract

Use this reference for package structure, validation, packing, installation, and update semantics. The current EvoFlux implementation follows the portable core of Agent Plugins 1.0 and adds only declared EvoFlux extensions.

## Canonical package

The package root contains `plugin.json`. It may also contain immediate-child Skills and one `mcp.json`:

```text
plugin-root/
├── plugin.json
├── skills/
│   └── release-audit/
│       ├── SKILL.md
│       ├── scripts/       # optional
│       ├── references/    # optional
│       └── assets/        # optional
└── mcp.json               # optional
```

`.evoplugin` is a deterministic ZIP wrapper, not a different package format. A regular `.zip` with the same safe layout is also accepted. The archive may contain one wrapper directory; managed installation normalizes the package root.

## `plugin.json`

Use the canonical schema identifier:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "release-audit",
  "version": "0.1.0",
  "description": "Audit a release with a guided Skill and read-only tools.",
  "author": {
    "name": "Example Team"
  },
  "license": "MIT",
  "keywords": ["release", "audit"],
  "extensions": {}
}
```

Only these root fields are recognized: `$schema`, `name`, `version`, `description`, `author`, `homepage`, `repository`, `license`, `keywords`, and `extensions`. Unknown root fields generate warnings and are ignored. Put platform-specific declarations under `extensions`.

Plugin names:

- contain 1–64 lowercase ASCII letters, digits, hyphens, or dots;
- start and end with a letter or digit;
- contain neither `--` nor `..`.

Use semantic versions. Keep `author` an object, not a string. A valid manifest with no Skills or MCP server is allowed.

## Skill contract

Discover only immediate directories under `skills/`. Each directory must contain `SKILL.md` with:

```yaml
---
name: release-audit
description: Audit a release when the user asks for a readiness or evidence review.
---
```

The frontmatter name must equal the directory name and use lowercase hyphen-case. The description must be nonempty and no longer than 1024 characters. The instruction body must be nonempty. `SKILL.md` is limited to 512 KiB.

An invalid Skill is skipped without invalidating healthy sibling Skills or the package manifest. Plugin Skills enter the normal metadata-only catalog and are loaded on demand. Name precedence is deterministic:

```text
project/user/admin Skills > plugin Skills > built-in Skills
```

## Validation and isolation

Current limits:

- `plugin.json`: 512 KiB;
- `mcp.json`: 2 MiB;
- each `SKILL.md`: 512 KiB;
- package inventory: at most 2,000 files and 200 MiB expanded;
- compressed archive input: at most 50 MiB;
- suspicious entries larger than 1 MiB are rejected above a 200:1 compression ratio.

Managed extraction rejects absolute paths, traversal, duplicate or case-fold-colliding paths, symlinks, and unsafe archive entries. Developer links may contain symlinks only when their resolved targets stay inside the linked root.

Failure boundaries:

- a fatal manifest error rejects the package;
- unknown root fields and non-object extensions warn and are ignored;
- an invalid Skill disables only that Skill;
- an invalid top-level `mcp.json` disables plugin MCP;
- an invalid or failed individual MCP server disables only that server;
- disabling a plugin removes its Skills and stops its runners.

## Pack, install, update, and uninstall

Pack only after inspection passes:

```bash
evoflux plugin inspect ./release-audit
evoflux plugin pack ./release-audit --output ./dist/release-audit.evoplugin
evoflux plugin install ./dist/release-audit.evoplugin
```

Write the artifact outside the plugin root. Packing is deterministic and uses a fixed ZIP timestamp. It excludes `.git`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `__pycache__`, `.DS_Store`, `.pyc`, and `.pyo` files and rejects symlinks.

Every installation receives a UUID independent of package name/version. EvoFlux prevents installing the same package name from the same source twice, but installation ID—not name—is runtime identity.

Managed update accepts a new local package for a managed installation only. The new manifest name must match. It preserves installation ID, installation data, and enabled state. A linked installation reads changes from its source and does not use managed update.

Uninstall preserves installation data by default. Use `--remove-data` only when deletion is intended:

```bash
evoflux plugin update <installation-id> ./release-audit
evoflux plugin uninstall <installation-id>
evoflux plugin uninstall <installation-id> --remove-data
```

## Storage ownership

EvoFlux stores platform state under its data directory:

```text
agent-plugins/
├── registry.json
├── installed/<installation-id>/<version>/
└── data/<installation-id>/
```

The registry uses atomic persistence. Staging and cache directories are implementation details; plugins must not depend on them. Plugins may write only installation-scoped mutable data provided through `${PLUGIN_DATA}`.

## Current boundary

Current supported surface includes local archive import, local developer links, validation, scaffold, workspace editing, credentials, enable/disable, pack, managed update, uninstall, Skills, and MCP.

Do not claim support for Git/registry import, signatures/provenance, custom commands or agents, arbitrary host code, rich connection types beyond declared credentials, or a plugin storage SDK.
