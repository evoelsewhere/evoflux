---
name: skill-installer
description: Install or create portable skill bundles in the agent's skills directory. Use when the user asks to add, import, author, or update a skill, including skills with references, scripts, assets, or UI metadata.
---

# Skill Installer

Treat a skill as a directory bundle, not a single Markdown file.

## Discovery order

The first matching skill name wins:

1. `{cwd}/.evoflux/skills/{skill-name}/`
2. `{cwd}/.opencode/skills/{skill-name}/`
3. `{SKILLS_DIR}/{skill-name}/`
4. `~/.config/opencode/skills/{skill-name}/`
5. Bundled EvoFlux skills (read-only fallback)

Default to `{SKILLS_DIR}` unless the user requests project-local or opencode
sharing. A writable skill may intentionally override a bundled skill.

## Bundle contract

```text
skill-name/
├── SKILL.md              # required
├── agents/openai.yaml    # optional UI metadata
├── references/           # optional docs loaded on demand
├── scripts/              # optional deterministic helpers
└── assets/               # optional output templates/media
```

`SKILL.md` frontmatter contains only:

```yaml
---
name: skill-name
description: What the skill does and the requests that should trigger it.
---
```

Keep the core workflow in `SKILL.md`. Put detailed schemas, examples, policies,
and variant-specific guidance in `references/`; repeated deterministic work in
`scripts/`; and output resources in `assets/`. Link every relevant resource
directly from `SKILL.md` and state when to read or run it.

## Install from a URL

1. Determine whether the URL identifies one file or a bundle archive/repository.
2. Fetch to a temporary location. Reject HTML returned in place of raw content.
3. Inspect every extracted path before writing; reject absolute paths, `..`, and
   symlinks that escape the bundle.
4. Validate `SKILL.md`, the directory/name match, and all referenced resources.
5. On collision, read the existing bundle and show the material differences
   before overwriting.
6. Copy the complete bundle to the selected writable root.

## Create or update

1. Derive concrete trigger examples from the request.
2. Plan which content belongs in `SKILL.md`, `references/`, `scripts/`, and
   `assets/`.
3. Read the existing bundle before modifying it.
4. Write the minimum complete bundle. Do not add README, changelog, or setup
   documents that the agent does not need at runtime.
5. Test added scripts and remove placeholders.

## Verification

- Parse `SKILL.md`; require non-empty `name`, `description`, and body.
- Confirm the skill name matches its directory.
- Confirm every resource referenced by `SKILL.md` exists.
- Read back the complete file list and report the bundle root.
- Confirm the skill appears in discovery; refresh the Skills page only if its
  cached catalog is stale.

## Boundaries

Do not use this skill to change agent models/tools, install MCP servers, or
install plugins. Use the corresponding configuration skill instead.
