---
name: skill-installer
description: >-
  Install new skills into the agent's skills directory by fetching from a URL
  or writing from scratch.
---

# Skill Installer

Use this skill when the user wants to add a **new skill body**. Do not use it
for changing models, tools, MCP servers, plugins, or other agent configuration.

## Discovery order

EvoFlux discovers skills from these roots, in order. The first skill with a
given `name` wins:

1. `{cwd}/.EvoFlux/skills/{skill-name}/SKILL.md`
2. `{cwd}/.opencode/skills/{skill-name}/SKILL.md`
3. `{SKILLS_DIR}/{skill-name}/SKILL.md`
4. `~/.config/opencode/skills/{skill-name}/SKILL.md`
5. Bundled EvoFlux operational skills — read-only fallback.

Default to `{SKILLS_DIR}` unless the user explicitly asks for a project-local or
opencode-shared skill. If the target name exists only as a bundled skill, install
a writable override; never edit bundled files.

## Skill file format

A skill is a directory containing at minimum a `SKILL.md` file with YAML
frontmatter and a Markdown body:

```markdown
---
name: skill-name
description: One-sentence description shown in the skill registry.
---

# Skill Title

Full instructions the agent reads when it calls skill("skill-name").
```

Rules:

- Directory name should match the `name` field for flat skills.
- Prefer lowercase kebab-case names unless the user intentionally wants a
  one-level namespace such as `oad/debug`.
- Keep `description:` short and trigger-oriented.
- Never overwrite an existing skill without reading it first and confirming with
  the user.

## How to install

### From a URL

1. Fetch the raw content with `web_fetch`.
2. If the response is HTML, ask for the raw URL and stop.
3. Parse the frontmatter `name` field; that is the skill name.
4. Write the content to the selected writable skill root.
5. Read it back to verify the file landed correctly.
6. Confirm the exact path and skill name.

### From scratch

1. Ask what the skill should do only if the request does not already specify it.
2. Write a `SKILL.md` following the format above to the selected writable skill
   root.
3. Add supporting files in the same directory only if they are useful.
4. Read it back to verify the file landed correctly.
5. Confirm the exact path and skill name.

A new skill can be loaded by exact name immediately. If a UI catalog looks stale,
refresh the Skills page or restart as a fallback.
