//! Built-in `init` prompt from `_BUILTIN_INIT_BODY` in app/services/commands.py.

pub(crate) const INIT_BODY: &str = r#"Inspect the project at the current working directory and create or update `AGENTS.md` at the repo root, in each meaningful top-level subfolder, and in meaningful nested subfolders where a future coding agent would need local instructions to change or add features safely. Treat this as documentation work, not a code change.

1. Read any existing `AGENTS.md` first, including parent files. Preserve accurate human-authored notes; only revise stale or misleading sections.
2. Survey the repo: layout, nested feature areas, runtimes, build / test / lint commands (Makefile, package.json, pyproject.toml, Cargo.toml, CI), conventions, docs, and generated/vendor/cache/build folders to skip.
3. Add nested `AGENTS.md` only where it helps a future coding agent: where to look first, coupled files/docs/tests, focused commands, or local gotchas. Do not duplicate parent guidance.
4. Keep every file concise — ideally one screen. Root covers repo-wide context; children cover only what differs. Prefer sections: Summary, Where to look first, Common feature checks, Commands, Gotchas, Docs.
5. Do not invent commands or features. Document only what exists, and note expensive/optional checks separately from required focused checks.
6. Run the lint/test/type-check commands you documented when feasible. If a check fails because of environment or missing services, document the condition instead of changing code."#;
