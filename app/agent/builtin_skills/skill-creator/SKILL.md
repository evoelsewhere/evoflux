---
name: skill-creator
description: "Use this skill to design the content of an Agent Skill: pinning down its use cases, writing a description that triggers on the right requests and stays quiet otherwise, structuring progressive disclosure across the body and its references, and diagnosing a skill that never fires or fires too often. Use the skill-installer workflow instead to create, validate, install, or relocate the bundle on disk."
---

# Skill Creator

A skill is a folder that teaches an agent how to handle a specific task or workflow:

```
your-skill-name/
├── SKILL.md       # Required — YAML frontmatter + Markdown instructions
├── scripts/       # Optional — executable code (Python, Bash, ...)
├── references/    # Optional — docs loaded only when needed
└── assets/        # Optional — templates, fonts, icons used in output
```

Skills rely on **progressive disclosure**: the frontmatter is always in context (so it decides *when* the skill loads), the SKILL.md body loads when relevant, and linked files load only on demand. Keep each level as small as it can be.

## Workflow: Creating a New Skill

### Step 1: Define 2-3 concrete use cases

Before writing anything, pin down with the user:

- What does the user want to accomplish? (outcome, not feature)
- What triggers it? Collect literal phrases users would say.
- What steps does the workflow require, in order?
- Which tools are needed (built-in, scripts, MCP servers)?
- What domain knowledge or best practices must be embedded?

Write each use case as: **Trigger → Steps → Result**. If the user is vague, propose use cases and confirm rather than guessing silently.

Identify the category — it shapes the structure:

1. **Document & asset creation** — embed style guides, templates, quality checklists.
2. **Workflow automation** — step-by-step process with validation gates.
3. **MCP enhancement** — orchestrate MCP tool calls in sequence with domain expertise.

### Step 2: Plan the folder structure

- Folder name: kebab-case only (`my-skill` — no spaces, capitals, or underscores) and it must match the frontmatter `name`.
- `SKILL.md` must be named exactly that, case-sensitive.
- Never put a `README.md` inside the skill folder.
- Keep the body under roughly 500 lines; move conditional detail to
  `references/` and link to it with a relative link that resolves.
- Recognised resource directories: `agents`, `assets`, `evals`, `examples`,
  `references`, `scripts`, `templates`. No symlinks, no links outside the
  bundle.
- For critical validations, prefer a bundled script over prose — code is deterministic, language interpretation isn't.

### Step 3: Write the frontmatter

The frontmatter is the single most important part — it alone decides whether the skill ever loads.

```yaml
---
name: your-skill-name
description: [What it does] + [When to use it, with literal trigger phrases] + [negative triggers if needed]
---
```

Rules (hard requirements in EvoFlux):

- The frontmatter carries exactly two keys, `name` and `description`. Any other
  key is a contract violation; licence, version, platform, and tool-restriction
  metadata belongs outside it.
- `name` is 1–64 characters of lowercase letters, digits, and single hyphens,
  and equals the directory name.
- `description` states what the skill is for and, explicitly, what it is not
  for, under 1024 characters, with no XML angle brackets.
- Name the artifacts, file types, and decisions that identify the task. The
  negative half is what stops the skill firing on every adjacent request.

Weak: `description: Helps with projects.`
Strong: `description: Use this skill to build, edit, or inspect a spreadsheet
when that file is the deliverable — models, template fills, messy-data repair,
workbook audits. Do not use it when the spreadsheet is only source material for
an analysis whose real output is something else.`

Everything host-specific lives beside `SKILL.md`: interface labels and
`policy.allow_implicit_invocation` in `agents/evoflux.yaml`, activation cases
in `evals/trigger-cases.json`, and mode scope in `.evoflux.json` for user and
project skills or in `app/agent/builtin_skills/catalog.py` for bundled ones.
Set `allow_implicit_invocation: false` for a long, interrupting, or
side-effectful workflow whose timing the user should own, and keep the same
rule stated in the description and body.

For every field, the bundle layout, and more good and bad examples, read
[references/frontmatter.md](references/frontmatter.md).

### Step 4: Write the instructions

Recommended body structure:

```markdown
# Skill Name

## Instructions
### Step 1: [First major step]
Exact commands / tool calls, with expected output described.

## Examples
User says X → actions → result.

## Troubleshooting
Error → cause → fix.
```

Best practices:

- Be specific and actionable: give exact commands with flags and expected output, not vibes ("validate the data").
- Put critical instructions at the top; use `## Important` headers for must-not-skip rules.
- Include error handling for the failures users will actually hit.
- Reference bundled resources explicitly ("Before writing queries, read the API-patterns file in references/").
- Number steps that must happen in order; state data dependencies between steps.

For proven structural patterns (sequential orchestration, multi-MCP coordination, iterative refinement, context-aware tool selection, domain-specific intelligence), read `references/patterns.md`.

### Step 5: Validate

Run the repository validator over the skills root that holds the bundle:

```bash
python scripts/validate_skills.py app/agent/builtin_skills
python scripts/validate_skills.py path/to/skills --require-evals
```

It checks the name and description contract, interface metadata, relative
resource links, activation-eval balance, and bundle resource limits. Fix every
ERROR; treat each WARNING as a review prompt.

A bundled skill is not finished until it is also registered in
`app/agent/builtin_skills/catalog.py` with its mode scope, because the catalogue
and the discovered set are asserted to match.

### Step 6: Test and iterate

Iterate on a single challenging task until it succeeds, then extract the winning approach into the skill — this gives faster signal than broad testing. Then cover:

1. **Triggering**: obvious phrasing loads it, paraphrases load it, unrelated queries don't. Encode both sides in `evals/trigger-cases.json`, with a `near_miss` note on every negative case.
2. **Function**: outputs correct, tool calls succeed, edge cases handled.
3. **Baseline comparison**: fewer corrections / tool calls / tokens than without the skill.

Debugging trick: ask the agent "When would you use the [name] skill?" — it will paraphrase the description back; fix what's missing.

Full test-case templates and iteration signals are in `references/testing.md`.

## Workflow: Reviewing an Existing Skill

When asked to review or improve a skill:

1. Read its SKILL.md and run the repository validator over the skills root that holds it.
2. Diagnose against the common failure modes:
   - **Never triggers** → description too generic or missing user-facing trigger phrases. Rewrite with literal phrases and keywords.
   - **Triggers too often** → add negative triggers ("Do NOT use for...") and narrow the scope.
   - **Loads but instructions ignored** → instructions too verbose, buried, or ambiguous. Move critical rules to the top, replace prose validations with a script.
   - **Slow / degraded responses** → SKILL.md too large; move detail into `references/`.
3. Propose concrete edits (before/after for the description), not general advice.
4. If the user brings failure examples from real sessions, encode the fix as an explicit instruction or troubleshooting entry — that is the highest-value iteration loop.

## Quick Checklist

Before delivering a skill, verify:

- [ ] Folder is kebab-case and matches frontmatter `name`
- [ ] `SKILL.md` exact filename; no `README.md` inside the folder
- [ ] Frontmatter has `---` delimiters and exactly `name` plus a scope-setting `description` under 1024 chars
- [ ] No XML angle brackets in frontmatter
- [ ] Instructions specific and actionable, with examples and error handling
- [ ] Every referenced `scripts/`, `references/`, `assets/` file actually exists
- [ ] The repository validator reports the bundle valid with 0 errors
- [ ] `agents/evoflux.yaml` and `evals/trigger-cases.json` present, with positive and near-miss cases
- [ ] Bundled skills registered in `app/agent/builtin_skills/catalog.py` with their mode scope
- [ ] Triggering tested: fires on target phrasings, silent on unrelated ones
