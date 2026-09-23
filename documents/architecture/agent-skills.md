# Agent Skills

EvoFlux implements the Agent Skills architecture described in Anthropic's
[Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview),
[authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices),
and the open [Agent Skills specification](https://agentskills.io/specification).
A Skill is a directory on the filesystem. The model discovers it from
metadata in the system prompt and then reads the files with its ordinary
file tools. There is no skill tool, no router model call, and no sidecar file.

## Contents

- Skill format
- Progressive disclosure
- Discovery and precedence
- Validation
- Activation paths
- Runtime integration
- Settings and API
- Authoring rules for bundled Skills

## Skill format

```text
pdf/
├── SKILL.md          required: YAML frontmatter + Markdown instructions
├── forms.md          optional reference, loaded when SKILL.md points to it
├── references/       optional documentation
├── scripts/          optional executable code, run with the shell tool
└── assets/           optional templates, data, images
```

`SKILL.md` frontmatter:

| Field | Required | Meaning in EvoFlux |
|---|---|---|
| `name` | yes | 1–64 lowercase letters, digits and single hyphens; must match the directory name; must not contain `anthropic` or `claude`. |
| `description` | yes | 1–1,024 characters, third person, states what the Skill does and when to use it. No XML tags. |
| `license` | no | Displayed in Settings. |
| `compatibility` | no | ≤500 characters of environment requirements. Displayed in Settings and visible to the model when it reads `SKILL.md`. |
| `metadata` | no | String-to-string map. Displayed in Settings; not interpreted. |
| `allowed-tools` | no | Displayed in Settings. EvoFlux permissions are not changed by it. |
| `disable-model-invocation` | no | `true` hides the Skill from the model catalog. Users can still invoke it with `$name`. |
| `user-invocable` | no | `false` removes the Skill from the `$` picker and ignores `$name` for it. |

Any other key is ignored and reported as a warning. Skills are available in
both Work and Coding mode; there is no mode scope.

## Progressive disclosure

| Level | Content | When it enters context |
|---|---|---|
| 1. Metadata | `name`, `description`, absolute `location` of `SKILL.md` | Every model call, in the system prompt |
| 2. Instructions | The complete `SKILL.md` | When the model reads `location` with `read`, or the user types `$name` |
| 3. Resources | Reference files, scripts, assets | When the instructions point to them; scripts run through `shell` and only their output enters context |

The Level 1 block appended to the system prompt is:

```text
## Skills
The following skills provide specialized instructions for specific tasks.
When a task matches a skill's description, use the `read` tool to load the
SKILL.md at the listed location before proceeding. ...

<available_skills>
  <skill>
    <name>pdf</name>
    <description>Extracts text and tables from PDF files ...</description>
    <location>/abs/path/pdf/SKILL.md</location>
  </skill>
</available_skills>
```

Entries are sorted by name and XML-escaped, so the block is byte-stable
between turns. The section also states two absolute paths that bundled
installer and configuration Skills rely on instead of placeholders: the
EvoFlux configuration directory and the user skills directory. When no Skill
is visible, the whole section is omitted.

## Discovery and precedence

A Skill is a **direct child** of a skills root: `<root>/<name>/SKILL.md`.
Deeper `SKILL.md` files are ordinary bundle files. Directories whose name
starts with `.` are skipped. Roots in precedence order:

1. Project roots: for every authorized workspace, from the workspace up to its
   Git root (deepest first): `.evoflux/skills`, `.agents/skills`,
   `.claude/skills`.
2. User roots: `{CONFIG_DIR}/skills` (`SKILLS_DIR`), `~/.agents/skills`,
   `~/.claude/skills`.
3. Enabled Agent Plugins: `<plugin>/skills/`.
4. Built-in: `app/agent/builtin_skills/`.

The first Skill found for a name wins; lower-precedence Skills with the same
name are recorded as shadowed and surfaced in Settings. Discovery is bounded
(entries per root) and cached by a file-signature key; writes through EvoFlux
invalidate the cache.

## Validation

Validation is lenient at runtime and strict when authoring:

- **Errors** (the Skill is not loaded): unreadable or non-UTF-8 `SKILL.md`,
  file larger than 512 KiB, missing or malformed frontmatter, missing `name`,
  a `name` outside `[a-z0-9-]` form, missing or empty `description`, empty
  body.
- **Warnings** (the Skill still loads): name longer than 64 characters, name
  not matching its directory, reserved words, description longer than 1,024
  characters, XML tags, `compatibility` longer than 500 characters,
  non-string `metadata`, unknown fields, a body longer than 500 lines, and a
  `SKILL.md` that does not fit in one `read` result (20,000 characters
  including line-number prefixes).
- **Strict mode** is used by Settings create/update, Conductor sync and
  `scripts/validate_skills.py`: every warning except the body-length and
  read-window warnings becomes an error.

`scripts/validate_skills.py` additionally checks bundle hygiene: relative
links resolve inside the bundle, no nested `SKILL.md`, no symlinks, no
backslash paths in links, and reference files over 100 lines start with a
table of contents.

## Activation paths

- **Model-driven.** The model reads `location` with `read`. Nothing else is
  required; the read result is the activation.
- **User-driven.** `$skill-name` anywhere in the user message (outside quoted
  context lines and code fences) activates each named user-invocable Skill.
  The harness inserts a `read` tool-call/result pair for that `SKILL.md` right
  after the user message, produced by the real `read` tool, so the model sees
  exactly what a model-driven read would have produced. A Skill already read
  in the conversation is not inserted again.
- **Agent-configured.** The `skills:` list in an agent definition preloads
  those Skills: their full `SKILL.md` text is appended to that agent's system
  prompt inside `<skill_content name="…" location="…">` blocks, and they are
  omitted from its `<available_skills>` catalog.

Disabled Skills take part in none of these paths.

## Runtime integration

`app/agent/hooks/skills.py` owns the whole runtime contract:

- discovers the catalog once per run for the authorized workspaces;
- adds every enabled Skill directory (and the root of a plugin that
  contributes a Skill) to the sandbox read-only roots, so `read`, `glob`,
  `grep`, `ls` and `shell` can access bundled files without prompts;
- inserts `$name` activations;
- appends the Level 1 catalog and preloaded Skills to the system prompt
  (team runs append it after the cache boundary through
  `SkillsPromptFinalizerHook`);
- grants a plugin's MCP tools when the model reads a `SKILL.md` contributed
  by that plugin, and re-grants them on later runs from history.

Compaction keeps the newest successful full read of each `SKILL.md` out of
summarization (bounded to 100,000 bytes), and tool-result offload and context
projection never rewrite such a result. The chat UI renders a read of a
known `SKILL.md` as a Skill activation.

## Settings and API

`/api/skills` lists every discovered Skill (valid or not), returns bundle
content, creates and edits Skills in the user root, deletes editable Skills,
and toggles a Skill on or off. The on/off state lives in
`{CONFIG_DIR}/skill-settings.json`:

```json
{"version": 2, "disabled": ["pdf"]}
```

Built-in, plugin, symlinked and Conductor-managed Skills are read-only in
Settings; they can still be disabled.

## Authoring rules for bundled Skills

Bundled Skills in `app/agent/builtin_skills/` follow the best-practices
checklist and are enforced by `tests/agent/skills/test_builtin_skills.py`:

- description in third person, with both what the Skill does and when to use
  it, including the key terms a user would mention;
- `SKILL.md` under 500 lines and within one `read` result; details move into
  reference files linked directly from `SKILL.md` (one level deep);
- reference files over 100 lines start with a `## Contents` list;
- relative forward-slash paths only; no host placeholders, no
  time-sensitive statements, one consistent term per concept;
- scripts are run, not read, and the instructions say which (`Run
  scripts/fill_form.py …` versus `See scripts/fill_form.py for …`);
  dependencies are stated explicitly;
- no `agents/`, `evals/`, `README.md` or other control-plane files inside a
  bundle. Evaluation scenarios live in `tests/fixtures/skill-evals/`.
