# seed/

Default agents, optional skills, and file-based configuration shipped to first-time users.

When a user runs `evoflux init`, the CLI copies the contents of this
directory (locally if running from a source checkout, otherwise from the
published GitHub release / `main` branch) into
`{EVOFLUX_CONFIG_DIR}/`.

Updating these files affects every **new** install. Existing users keep
their own copies untouched — once `evoflux init` has populated their
config dir, those files are theirs to edit. Users who want the newest
prompts or skills can browse this directory and copy what they want
into their own `{EVOFLUX_CONFIG_DIR}/`.

## Layout

```
seed/
├── agents/                # default global/coding agent descriptors
├── skills/                # optional user-editable skills; currently empty
├── aim-kb-template/       # scaffold + operating/rulebook guidelines for AIM KB repos
└── mcp.json               # empty MCP server config
```

> Summarisation, title generation, and Dream prompts are built in and are not
> seeded as editable prompt files. Runtime choices such as enable/model/schedule
> live in `{EVOFLUX_CONFIG_DIR}/settings.yaml`, which the app creates from
> the known schema instead of copying from `seed/`. `multimodal.yaml` is also
> generated from a known schema rather than copied from GitHub seed content.

`README.md` (this file) is the only top-level item not copied — every
other top-level entry ships, but `init` skips files the user already
has, so re-running `init` after a release won't clobber edits.

## Conventions

- **Lead agent first.** `agents/EvoFlux.md` is the lead; the others are members.
- **Model placeholder.** Every agent's `model:` field is rewritten by
  `evoflux init` to match the provider/model the user picked. The same
  selected model is written into generated `settings.yaml` for title generation
  and Dream defaults.
  Individual member models can then be changed in Settings → Agents (for
  example, give the executor a faster model than the lead).
- **No secrets, ever.** These files are public. `mcp.json` should
  reference env vars (`${VAR}`) for any auth headers, never inline
  values.
- **Keep skills self-contained.** Each `skills/<name>/` should run with no
  outside files. Bundle reference scripts and templates in the same dir.
- **Top-level configs are fill-in-gap defaults.** `mcp.json` only lands if the
  target file doesn't exist. Generated configs (`settings.yaml`,
  `multimodal.yaml`) follow the same no-overwrite rule.
