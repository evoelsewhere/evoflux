# Skill metadata reference (EvoFlux)

EvoFlux keeps `SKILL.md` frontmatter portable and puts every host-specific
setting in a sibling file. Only the frontmatter is loaded eagerly, so it alone
decides whether the skill is ever activated.

## SKILL.md frontmatter — exactly two fields

```yaml
---
name: skill-name-in-kebab-case
description: What the skill is for, when to apply it, and when not to.
---
```

Anything else in the frontmatter is a contract violation: the bundled-skill
test asserts the key set is exactly `name` and `description`. Licence text,
version numbers, platform lists, and tool restrictions belong outside the
frontmatter.

### name

- One to sixty-four characters, lowercase letters, digits, and single hyphens.
- Must equal the directory name.

### description

- Under 1024 characters, and no XML angle brackets — it is injected into the
  prompt catalogue.
- States what the skill is for and, explicitly, what it is not for. The
  negative half is what stops a skill firing on every adjacent request.
- Written for the router, not for a human browsing a list. Name the artifacts,
  file types, and decisions that identify the task.

House phrasing: *Use this skill to … Apply it to … ; do not use it for … .*

## agents/evoflux.yaml — interface and policy

```yaml
interface:
  display_name: "Human-readable name"
  short_description: "One line shown in Settings"
  default_prompt: "Use $skill-name to ..."
policy:
  allow_implicit_invocation: true
dependencies:
  tools:
    - type: builtin
      value: shell
```

`display_name` and `short_description` are required once the file exists.
`allow_implicit_invocation: false` keeps the skill out of implicit routing so
it only runs when the user asks for it by name — use it for long, interrupting,
or side-effectful workflows, and keep the same rule stated in the description
and body so the skill still behaves if the flag is ever removed.

A missing `agents/evoflux.yaml` is a warning, not an error: runtime defaults
apply. Ship one anyway for anything a user will see in Settings.

## evals/trigger-cases.json — activation evidence

```json
[
  { "query": "a request that must load the skill", "should_trigger": true },
  {
    "query": "an adjacent request that must not",
    "should_trigger": false,
    "near_miss": "why this one is out of scope"
  }
]
```

Both a positive and a negative case are required; the validator rejects a
one-sided set. Near misses are the point — they encode the boundary the
description promises.

## .evoflux.json — mode scope

```json
{ "modes": ["coding"] }
```

Scopes a user or project skill to Work mode, Coding mode, or both. Bundled
skills do not use this file: their scope lives in
`app/agent/builtin_skills/catalog.py`, which must list every bundled skill.

## Bundle layout

```
skill-name/
├── SKILL.md            required
├── agents/evoflux.yaml interface and policy
├── evals/              trigger-cases.json
├── references/         loaded on demand, never eagerly
├── scripts/            deterministic helpers
└── assets/             templates and output material
```

Recognised resource directories are `agents`, `assets`, `evals`, `evaluations`,
`examples`, `reference`, `references`, `scripts`, and `templates`. Symlinks are
rejected, links must stay inside the bundle, and every relative markdown link
in the body must resolve to a file that exists.

## Validate

```bash
python scripts/validate_skills.py app/agent/builtin_skills
python scripts/validate_skills.py path/to/skills --require-evals
```

Fix every ERROR; treat each WARNING as a review prompt. A body over roughly
five hundred lines warns — that is a signal to move conditional detail into
`references/`, not to compress the prose.

## Description examples

Weak, because it never triggers reliably:

```yaml
description: Helps with projects.
```

Weak, because nothing tells the router when to stay out:

```yaml
description: Creates sophisticated multi-page documentation systems.
```

Strong, because it names the artifact, the trigger, and the boundary:

```yaml
description: Use this skill to build, edit, or inspect a spreadsheet file when
  that file is the deliverable — models, formula-driven summaries, template
  fills, messy-data repair, and workbook audits. Do not use it when the
  spreadsheet is only source material for an analysis whose real output is
  something else.
```
