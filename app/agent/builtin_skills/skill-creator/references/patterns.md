# Skill structure patterns

## Contents

- Degrees of freedom
- Progressive disclosure layouts
- Workflow checklist
- Feedback loop
- Plan, validate, execute
- Template pattern
- Examples pattern
- Conditional workflow
- Multi-tool orchestration
- Scripts
- MCP tool references
- Anti-patterns

## Degrees of freedom

Match how prescriptive the instructions are to how fragile the task is.

- **High freedom** (prose): many valid approaches, judgment matters. Example:
  "Review the code for correctness, readability, and missing tests."
- **Medium freedom** (pseudocode or a parameterized script): a preferred
  pattern exists but variation is fine.
- **Low freedom** (exact command, no variations): operations are fragile or
  must be consistent. Example: "Run exactly
  `python scripts/migrate.py --verify --backup`. Do not add flags."

## Progressive disclosure layouts

**High-level guide with references.** `SKILL.md` gives the quick start and
links each topic:

```markdown
## Advanced features
**Form filling**: read `references/forms.md` when the PDF has fillable fields.
**API reference**: read `references/api.md` for every method signature.
```

**Domain-specific files.** When the skill spans domains, give each its own
file so only the relevant one is read:

```text
bigquery-analysis/
├── SKILL.md
└── references/
    ├── finance.md
    ├── sales.md
    └── product.md
```

**Conditional details.** Keep the common path in `SKILL.md`; link rare cases:
"For tracked changes, read `references/redlining.md`."

In a real skill, write each pointer as a relative Markdown link to a file that
exists, so link resolution can be checked.

Keep every link one level deep from `SKILL.md`. A reference that sends the
agent to a second reference for essential information risks a partial read.

## Workflow checklist

For multi-step tasks, give a checklist the agent copies and ticks off:

```markdown
Copy this checklist and track progress:
- [ ] Step 1: Analyze the form (run scripts/analyze_form.py)
- [ ] Step 2: Create the field mapping (edit fields.json)
- [ ] Step 3: Validate the mapping (run scripts/validate_fields.py)
- [ ] Step 4: Fill the form (run scripts/fill_form.py)
- [ ] Step 5: Verify the output (run scripts/verify_output.py)
```

Then describe each step: its command, its input from the previous step, and
its expected output.

## Feedback loop

Validate, fix, repeat. This is the highest-leverage pattern for output
quality.

```markdown
1. Edit word/document.xml.
2. Run `python scripts/validate.py unpacked/`.
3. If validation fails, read the error, fix the XML, and run it again.
4. Continue only when validation passes.
5. Run `python scripts/pack.py unpacked/ output.docx`.
```

Without scripts, the validator can be a reference checklist the agent compares
its draft against.

## Plan, validate, execute

For batch or destructive operations, have the agent write a plan to a file,
validate the plan with a script, and only then execute it. The plan file is a
verifiable intermediate output that catches errors before anything changes.

```markdown
1. Write changes.json listing every field and its new value.
2. Run `python scripts/validate_changes.py changes.json`; fix every reported error.
3. Run `python scripts/apply_changes.py changes.json` only after validation passes.
```

## Template pattern

Provide the output shape. Be strict when format matters ("ALWAYS use this
exact structure") and flexible when adaptation helps ("a sensible default;
adjust sections to the content").

```markdown
# [Analysis title]
## Executive summary
[One paragraph]
## Key findings
- Finding with supporting data
## Recommendations
1. Specific, actionable item
```

## Examples pattern

When output quality depends on style, show input/output pairs:

```markdown
**Input:** Added user authentication with JWT tokens
**Output:**
feat(auth): implement JWT-based authentication

Add login endpoint and token validation middleware
```

## Conditional workflow

Route the agent at decision points:

```markdown
1. Determine the task:
   - Creating new content: follow "Creation workflow" below.
   - Editing existing content: follow "Editing workflow" below.
```

If a branch grows large, move it into its own reference file and link it.

## Multi-tool orchestration

For workflows that span several tools or services, separate phases, name the
data passed between them, and validate before advancing:

```markdown
## Phase 1: Export (design tool)
Export assets and write manifest.json.
## Phase 2: Upload (storage)
Upload every file in manifest.json; record the returned links.
## Phase 3: Track (issue tracker)
Create one task per asset with its link. Stop if any upload failed.
```

## Scripts

- **Solve, do not punt.** Handle expected errors inside the script (missing
  file, bad input) with a clear message instead of failing and leaving the
  agent to guess.
- **No magic numbers.** Explain every constant ("30 s timeout: requests over
  slow links normally finish within 30 s").
- **Run versus read.** State the intent: "Run `python scripts/analyze.py in.pdf`"
  or "See `scripts/analyze.py` for the algorithm." Running is preferred; only
  the output enters context.
- **Dependencies.** Name every package and use one invocation style, for
  example `uv run --with pypdf python scripts/extract.py in.pdf`. Do not assume
  a package is installed.
- **Output location.** Skill directories are read-only to the agent's tools.
  Scripts take an output path argument and write into the workspace.
- **Paths.** Forward slashes only; the agent resolves `scripts/x.py` against the
  skill directory.

## MCP tool references

Name MCP tools exactly. In EvoFlux, configured MCP tools are named
`mcp_<server>_<tool>`, for example `mcp_github_create_issue`. Plugin tools carry
a generated installation prefix; describe them by their stable suffix ("the
available tool ending in `release_api_status_get`").

## Anti-patterns

- Offering several equivalent approaches instead of one default.
- Explaining what the agent already knows (what a PDF is, how Git works).
- Time-sensitive statements ("before August use the old API").
- Mixing terms for one concept ("endpoint", "URL", "route").
- Deeply nested references or reference files without a `## Contents` list.
- Windows-style backslash path separators; always write `scripts/helper.py`.
- Control-plane files inside the bundle (`agents/`, `evals/`, `.evoflux.json`).
