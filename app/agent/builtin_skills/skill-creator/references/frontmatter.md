# SKILL.md frontmatter reference

## Contents

- Field table
- name
- description
- Optional fields
- EvoFlux invocation keys
- Errors and warnings
- Description examples

`SKILL.md` starts with YAML frontmatter between two `---` lines, followed by a
non-empty Markdown body. The frontmatter is the only part of a skill that is
always in context, so it alone decides whether the skill is ever read.

## Field table

| Field | Required | Constraint |
|---|---|---|
| `name` | yes | 1-64 lowercase letters, digits, single hyphens; equals the directory name; no `anthropic` or `claude`; no XML tags |
| `description` | yes | 1-1,024 characters; third person; what the skill does and when to use it; no XML tags |
| `license` | no | License name or a pointer to a bundled license file |
| `compatibility` | no | At most 500 characters of environment requirements |
| `metadata` | no | Map of string keys to string values |
| `allowed-tools` | no | Space-separated tool list; displayed only |
| `disable-model-invocation` | no | `true` hides the skill from the model catalog |
| `user-invocable` | no | `false` removes the skill from the `$` picker |

Any other key is ignored and reported as a warning.

## name

- Pattern `^[a-z0-9]+(-[a-z0-9]+)*$`: no capitals, underscores, spaces, or
  leading, trailing, or doubled hyphens.
- Must equal the name of the directory that holds `SKILL.md`.
- Must not contain the reserved words `anthropic` or `claude`.
- Prefer a gerund or noun phrase that names the activity:
  `processing-pdfs`, `analyzing-spreadsheets`, `release-checklist`. Avoid vague
  names such as `helper`, `utils`, or `tools`.

## description

The description is how the agent picks one skill out of many. Write it in the
third person because it is injected into the system prompt.

- Say **what** the skill does: the artifacts, file types, and operations.
- Say **when** to use it: "Use when ..." followed by the phrases and contexts
  users actually mention.
- Add a short "Not for ..." sentence when an adjacent request would otherwise
  trigger it, and name the skill that handles that request.
- No "I can help you", no "You can use this", no "Use this skill to ...".
- No XML tags or angle-bracket markup.

## Optional fields

```yaml
---
name: processing-pdfs
description: Extracts text and tables from PDF files. Use when working with PDFs or document extraction.
license: Apache-2.0. LICENSE.txt has complete terms
compatibility: Requires Python 3.10+ and the pypdf package; needs network access only for OCR downloads.
metadata:
  author: example-team
  version: "1.2.0"
allowed-tools: read shell
---
```

- `license`: when the bundle ships a license file, name the SPDX identifier and
  the real filename.
- `compatibility`: state only real requirements (runtimes, packages, network,
  operating system). The agent sees it when it reads `SKILL.md`.
- `metadata`: every value must be a string; quote version numbers.
- `allowed-tools`: informational in EvoFlux; permissions are not changed by it.

## EvoFlux invocation keys

- `disable-model-invocation: true`: the skill is not listed in the model
  catalog, so the model never activates it on its own. The user can still type
  `$name`. Use it for long, interrupting, or side-effectful workflows whose
  timing the user should own (installers, configuration changes, database
  queries). State the same boundary in the description.
- `user-invocable: false`: the skill disappears from the `$` picker and `$name`
  is ignored for it. Use it for skills that only make sense when the model
  selects them, or that an agent definition preloads.

## Errors and warnings

Errors (the skill is not loaded): unreadable or non-UTF-8 `SKILL.md`, a file
larger than 512 KiB, missing or malformed frontmatter, missing `name`, a `name`
outside the lowercase/digit/hyphen form, missing or empty `description`, an
empty body.

Warnings (the skill loads): `name` longer than 64 characters, `name` not
matching the directory, reserved words, `description` longer than 1,024
characters, XML tags, `compatibility` longer than 500 characters, non-string
`metadata`, unknown keys, a body longer than 500 lines, and a `SKILL.md` that
does not fit in one `read` result (20,000 characters including line-number
prefixes).

Skills created or edited through Settings are validated strictly: every warning
except body length and the read-window limit becomes an error. Author to the
strict rules so a skill never depends on lenient loading.

## Description examples

Weak, because it never triggers reliably:

```yaml
description: Helps with documents.
```

Weak, because it is not third person and names no trigger:

```yaml
description: I can help you process Excel files.
```

Strong, because it names the artifact, the operations, and the triggers:

```yaml
description: Analyzes Excel spreadsheets, creates pivot tables, and generates charts. Use when analyzing .xlsx files, spreadsheets, tabular data, or when the user asks for a workbook summary.
```

Strong, with a boundary against a near miss:

```yaml
description: Generates descriptive commit messages by analyzing git diffs. Use when the user asks for help writing a commit message or reviewing staged changes. Not for writing pull request descriptions.
```
