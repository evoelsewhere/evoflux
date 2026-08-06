# seed/ — Agent Instructions

Default agents, optional skills, and MCP config copied into a user's config directory by `EvoFlux init`.

## Layout

```
agents/   Seed agent `.md` files; exactly one per team directory has `role: lead`
skills/   One skill per directory, each with `SKILL.md`
mcp.json  Empty default MCP server config
README.md Maintainer notes; not copied by init
```

## Conventions

- Treat these files as public templates for new installs; never include secrets.
- Existing users keep their copies, so seed changes affect only new installs or users who manually copy updates.
- `EvoFlux init` rewrites agent `model:` values to the user's selected provider/model.
- Keep skill directories self-contained with any helper scripts/templates they need.
- Keep agent prompt bodies tool-agnostic; runtime capabilities can change.
- The wheel build bundles this tree as `app/_seed/` (`force-include` in `pyproject.toml`) so pip/uv installs seed offline; the repo `seed/` still wins in dev checkouts.

## Checks

```bash
uv run ruff check app/ tests/
uv run pytest --no-cov -q tests/cli
```

Run focused CLI/init tests when changing seed install behavior or validation logic.

## Documentation pointers

- Maintainer notes: `README.md`.
- Harness/frontmatter contract: `../documents/architecture/application-harness.md`.
- Coding navigation contract: `../documents/architecture/coding-agent-code-navigation.md`.
