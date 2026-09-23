---
name: skill-creator
description: Designs, writes, and reviews Agent Skills for EvoFlux, covering use cases and evaluation scenarios, the SKILL.md frontmatter and description, body structure, progressive disclosure into references/, scripts/, and assets/, and self-validation against the Agent Skills specification. Use when the user asks to create or write a new skill, turn a repeated workflow into a skill, improve or review an existing SKILL.md, or fix a skill that never triggers or triggers too often. Not for installing a third-party skill bundle from a URL or archive (read the skill-installer skill) or for editing an agent's configuration.
---

# Skill Creator

A skill is a directory that gives an agent the procedural knowledge for one
kind of task. EvoFlux lists every skill's `name`, `description`, and the
absolute location of its `SKILL.md` in the system prompt; the agent reads
`SKILL.md` with the `read` tool when a task matches, and reads or runs bundled
files only when `SKILL.md` points to them.

```text
my-skill/
├── SKILL.md       required: YAML frontmatter + Markdown instructions
├── references/    optional: documentation read on demand
├── scripts/       optional: executable code, run with the shell tool
└── assets/        optional: templates, data, images used in output
```

Nothing else belongs in a bundle: no `agents/*.yaml`, no `.evoflux.json`, no
`evals/`, no `README.md`, no changelog. There is no mode scope; a skill is
available in both Work and Coding mode.

## Where to create the skill

Create new skills in the user skills directory; its absolute path is stated in
the Skills section of the system prompt. The skill is the direct child
`<user skills directory>/<name>/SKILL.md`. Create it under
`<workspace>/.evoflux/skills/<name>/` only when the user wants it shared with
a repository. Discovery refreshes automatically after the files are written;
no restart is needed.

To install an existing third-party bundle instead of writing one, read the
`skill-installer` skill.

## Workflow

Copy this checklist and track progress:

```text
- [ ] 1. Collect use cases and at least three evaluation scenarios
- [ ] 2. Record baseline behavior without the skill
- [ ] 3. Write the frontmatter
- [ ] 4. Write the minimal body that closes the observed gaps
- [ ] 5. Split detail into references/, scripts/, assets/
- [ ] 6. Self-validate (checklist below)
- [ ] 7. Run the scenarios with the skill, fix, repeat
```

### 1. Collect use cases and evaluation scenarios

Build evaluations before writing extensive documentation. Pin down with the
user, as **Trigger -> Steps -> Result**:

- the outcome the user wants, and the literal phrases they would type;
- the steps in order, the tools and scripts needed, and the domain knowledge
  the agent does not already have;
- adjacent requests that must *not* load the skill.

Write at least three scenarios in this shape:

```json
{
  "skills": ["my-skill"],
  "query": "Extract all text from this PDF file and save it to output.txt",
  "files": ["test-files/document.pdf"],
  "expected_behavior": [
    "Reads the PDF with an appropriate library or command-line tool",
    "Extracts text from every page without skipping any",
    "Saves the text to output.txt in a readable format"
  ]
}
```

Keep scenarios and their test files **outside** the bundle (for example in the
session workspace or the user's repository); never add an `evals/` directory
to the skill. For scenario design, trigger testing, and iteration, read
[references/evaluation.md](references/evaluation.md).

### 2. Record baseline behavior

Run the scenarios without the skill and note what the agent gets wrong, asks
about, or does inefficiently. The skill exists to close those gaps and nothing
more.

### 3. Write the frontmatter

```yaml
---
name: processing-pdfs
description: Extracts text and tables from PDF files, fills PDF forms, and merges documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.
---
```

Hard rules:

- `name`: 1-64 characters, lowercase letters, digits, and single hyphens;
  equals the directory name; must not contain `anthropic` or `claude`; no XML
  tags.
- `description`: 1-1,024 characters, third person, states **what** the skill
  does and **when** to use it with concrete trigger terms (file types, phrases
  users say). No XML tags, no "I" or "you". An optional short "Not for ..."
  sentence stops near-miss triggering.
- Optional: `license`, `compatibility` (at most 500 characters of environment
  requirements), `metadata` (string-to-string map), `allowed-tools` (displayed
  only; it does not change EvoFlux permissions).
- EvoFlux keys: `disable-model-invocation: true` hides the skill from the
  catalog so it runs only when the user types `$name` (use it for long,
  interrupting, or side-effectful workflows); `user-invocable: false` removes
  it from the `$` picker.
- Any other key is ignored and reported as a warning.

For every field with examples, the error and warning rules, and description
rewrites, read [references/frontmatter.md](references/frontmatter.md).

### 4. Write the minimal body

The agent is already capable; add only what it does not know. For each
paragraph ask whether the agent needs it and whether it justifies its tokens.

- Match specificity to fragility: prose for judgment-heavy work, exact steps or
  a checklist for fragile sequences, a script for deterministic operations.
- Put must-not-skip rules first. Number steps that must run in order and state
  what each step needs from the previous one.
- Add a feedback loop where quality matters: run the validator, fix, repeat
  until it passes.
- Give one default approach with an escape hatch, not a menu of options.
- Use one term per concept throughout; give concrete input/output examples.
- No time-sensitive statements ("currently", "as of", pinned model names). Put
  superseded behavior in a clearly labeled legacy section if it must stay.
- Refer to other skills by name ("read the `pdf-processing` skill"); do not
  route with `$other-skill` inside a body.

For structural patterns (workflows, feedback loops, templates, examples,
conditional workflows, plan-validate-execute, MCP tool references), read
[references/patterns.md](references/patterns.md).

### 5. Split detail with progressive disclosure

- Keep the `SKILL.md` body under 500 lines and the whole file readable in one
  `read` result (keep it well under 20,000 characters).
- Link every reference file **directly** from `SKILL.md` with a one-line
  condition saying when to read it. Reference files must not depend on further
  links for essential information (one level deep).
- Start any reference file longer than 100 lines with a `## Contents` list of
  its sections.
- Use relative paths with forward slashes (`references/api.md`), never
  backslashes, absolute paths, or `../` escaping the bundle.
- Say whether each script is to be **run** ("Run
  `python scripts/validate.py form.json`") or **read** ("See
  `scripts/validate.py` for the algorithm"). Use one invocation style and
  state required packages (`uv run --with pypdf python scripts/extract.py`).
- Skill directories are read-only to the agent's tools, so scripts must write
  output to the workspace, not into the bundle. The agent derives the absolute
  script path from the `SKILL.md` location.

### 6. Self-validate

Check every item before handing over. Use `shell` or `read` to confirm, do not
assume.

```text
- [ ] Directory name equals frontmatter name; name matches ^[a-z0-9]+(-[a-z0-9]+)*$, <= 64 chars, no anthropic/claude
- [ ] Frontmatter is valid YAML between --- lines; only allowed keys; metadata values are strings
- [ ] description <= 1,024 chars, third person, what + when, no XML tags
- [ ] compatibility (if present) <= 500 chars
- [ ] Body is non-empty, < 500 lines; whole SKILL.md well under 20,000 chars
- [ ] Every relative link resolves to a file inside the bundle; forward slashes only
- [ ] Every reference file is linked from SKILL.md with a when-to-read condition
- [ ] Reference files over 100 lines start with ## Contents
- [ ] No nested SKILL.md, no symlinks, no agents/, evals/, .evoflux.json, README.md
- [ ] Every script runs on a representative input; dependencies are stated
- [ ] No time-sensitive statements, placeholders, or machine-specific paths
```

Count lines and characters with the shell (for example `wc -lc SKILL.md`)
rather than estimating. After writing, confirm the skill appears in the
catalog on the next turn, or under Settings, Skills.

### 7. Run the scenarios and iterate

Run each scenario in a fresh conversation with the skill available. Observe
which files the agent reads, which steps it skips, and where it hesitates.
Fix the specific gap, re-run, and repeat. When the user brings failures from
real sessions, encode the fix as an explicit instruction, troubleshooting
entry, or validation step.

## Reviewing an existing skill

1. Read its `SKILL.md` and list the bundle files.
2. Run the self-validation checklist and report every failed item.
3. Diagnose behavior:
   - **Never triggers**: the description is generic or lacks the words users
     say. Rewrite it with concrete file types and phrases.
   - **Triggers too often**: add a "Not for ..." boundary and narrow the scope.
   - **Loads but instructions are ignored**: rules are buried or verbose. Move
     critical rules to the top; replace prose validation with a script.
   - **Slow or context-heavy**: `SKILL.md` is too large. Move conditional
     detail into linked reference files.
4. Propose concrete before/after edits, not general advice. Remove legacy
   control-plane files (`agents/`, `evals/`, `.evoflux.json`) and move their
   meaning into the frontmatter (`disable-model-invocation`) or out of the
   bundle (evaluation scenarios).
