---
name: skill-installer
description: Create, import, update, validate, or relocate portable Agent Skill bundles with SKILL.md, on-demand references, deterministic scripts, output assets, UI metadata, and EvoFlux mode settings. Use for explicit skill authoring or installation; do not use for invoking an existing skill, changing agent configuration, or installing MCP servers or plugins.
---

# Create or install a skill bundle

Treat a skill as a runtime bundle, not a standalone prompt file. Do not load an
existing bundle's references, scripts, or assets before the requested workflow
creates a concrete need for them.

## Resolve destination and identity

Use the first matching name in project EvoFlux, project OpenCode, user
EvoFlux, user OpenCode, then bundled roots. Default new user-owned skills to
`{SKILLS_DIR}` unless the user requests project-local sharing. Never overwrite
a higher-precedence variant without identifying the exact selected root.

Use a lowercase hyphenated name under 64 characters. `SKILL.md` frontmatter
contains only `name` and `description`; the description must explain both what
the skill does and which requests should trigger it.

## State machine

### 1. SPECIFY

Derive concrete positive and near-miss trigger examples. Choose the degree of
freedom: prose for judgment-heavy work, a state machine/decision table for
fragile workflows, and a script for repeated deterministic operations.

### 2. PLAN THE BUNDLE

Use only necessary paths:

```text
skill-name/
├── SKILL.md
├── agents/evoflux.yaml
├── references/
├── scripts/
├── assets/
└── evals/trigger-cases.json
```

Keep the core workflow, state transitions, stop conditions, and resource
routing in `SKILL.md`. Put detailed knowledge in `references/`, repeated exact
work in `scripts/`, and output material in `assets/`. Every optional resource
must be linked directly from `SKILL.md` with the evidence condition for reading
or running it. Do not add README, changelog, setup guide, or placeholder files.

Put UI fields and implicit-invocation policy in `agents/evoflux.yaml`. Keep
Work/Coding/Both and slash-menu preferences in EvoFlux runtime settings or the
supported `.evoflux.json` sidecar rather than adding non-portable frontmatter.

### 3. IMPORT OR UPDATE

For a URL, fetch to a temporary location, reject HTML masquerading as raw
content, inspect every archive/repository path, and reject absolute paths,
traversal, escaping symlinks, oversized content, and executable surprises.

For an existing destination, read the complete bundle inventory and show the
material diff before replacement. Preserve unrelated scripts/assets and never
silently turn a bundle update into a fresh minimal `SKILL.md`.

### 4. VALIDATE

Require matching directory/frontmatter names, non-empty body and description,
valid UI metadata, balanced positive/near-miss trigger evals, safe resource
paths, and existing direct links. Run every added or changed script on a safe
representative input. Ensure the body is concise and resources are not
duplicated in it.

### 5. VERIFY DISCOVERY

Read back the complete file list and changed files. Confirm the exact variant
appears in discovery with the requested mode, implicit invocation, and slash
menu settings. Refresh the Skills UI only when its cached catalog is stale.

## Stop conditions

Stop when trigger boundaries are concrete, the bundle has only necessary
files, every resource has conditional routing, scripts and eval schemas pass,
the exact discovered variant is verified, and no existing material was lost.

## Deliverable

Report bundle root, mode and invocation settings, files created/updated,
validation performed, discovery result, and any manual dependency or approval
still required.
