# area-commands NOTES

Python source: `app/api/routes/commands.py`, `app/services/commands.py`,
`app/api/schemas/commands.py`. Unit `edge-stateless`. Contract tests:
`contract-tests/commands/test_commands.py` (all pass against Python v3.1.1).

## Endpoints

| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `GET /api/commands?workspace=` | `workspace` optional | `200 {"commands":[{name,description,source}]}` sorted by `name` (code point). Built-in `init` is **not** listed. | `422 {"detail":"Workspace does not exist or is not a directory: <resolved path>"}` |
| `POST /api/commands/{name:path}/render?workspace=` | JSON `{"arguments": str = ""}` | `200 {"name","content"}` | workspace `422` as above (checked before the name lookup); `404 {"detail":"Command '<name>' not found."}`; body validation `422` (FastAPI/pydantic list `detail`: `string_type` at `["body","arguments"]`, `missing` at `["body"]`, `json_invalid`, `model_attributes_type`); auth `401 {"detail":"Unauthorized — EvoFlux access key required."}` |

`{name:path}` matches slashes: `git/commit` works, `a/b/c` is discovered nowhere
(404). The name is URL-decoded and case-sensitive. Unknown body fields are ignored.

## State, files, side effects

No DB, no in-memory state that matters, no events, nothing written. Reads
`*.md` files from four roots, first hit wins on a name:

1. `{workspace}/.evoflux/commands` → `project-EvoFlux` (only with `workspace`)
2. `{workspace}/.opencode/commands` → `project-opencode` (only with `workspace`)
3. `{EVOFLUX_CONFIG_DIR}/commands` → `global-EvoFlux`
4. `~/.config/opencode/commands` → `global-opencode` (`Path.home()`: `HOME`, or `USERPROFILE` on Windows)

Python caches discovery per `(roots, mtime signature)` with `lru_cache(16)`; the
signature is the max mtime_ns of each root, its direct entries and the `*.md`
inside its subdirectories. Observable: edits, additions and removals show up on
the next request; a change whose mtime is not above the existing maximum is not
seen (contract test pushes mtimes into the future to avoid depending on that).
Rust may re-read on every request as long as the visible result is the same.

## Behaviour to port as-is

- Walk: `sorted(root.rglob("*.md"))`, regular files only, name = relative path
  without `.md` using `/`; **more than two path parts are skipped**; `a.b.md` is `a.b`;
  a directory called `x.md` is ignored. Within one root, files are visited in
  sorted path order (matters only for the same name, which cannot repeat in a root).
- Files are read as UTF-8 with universal newlines (`\r\n` becomes `\n`); an
  unreadable file (`OSError`) is skipped. Invalid UTF-8 raises `UnicodeDecodeError`, not
  caught, so the request is a 500 (not pinned by a test; a suspected Python bug, see below).
- Frontmatter regex `^---\s*\n(.*?)\n---\s*\n(.*)$` with DOTALL: a fence line may
  have trailing whitespace, the closing fence **needs a newline after it** (a
  file ending in `---` without `\n` has no frontmatter and the whole text is the
  body), leading blank line before `---` means no frontmatter, the first closing
  fence wins. No match: meta `{}`, body `text.strip()`. Match: body is group 2 stripped.
- Frontmatter YAML: `yaml.safe_load`; non-dict result becomes `{}`;
  `description` that is not a string becomes `""`, otherwise `.strip()`.
  YAML block scalars are real YAML (`|` keeps inner newlines).
- Render: if the body contains `$ARGUMENTS` every occurrence is replaced by the
  stripped arguments (replacement is not re-expanded); otherwise non-empty
  stripped arguments are appended after `\n\n`; empty arguments leave the body.
- Lookup order for render: disk commands first, then the built-in. A disk
  `init.md` shadows the built-in. Built-in `init` has `source="builtin"` but is
  never listed; its exact text is in `contract-tests/commands/snapshots/init-render.json`.
- `workspace` is `Path(..).expanduser().resolve()` (so `~/x` expands, relative
  paths resolve against the process cwd, `""` becomes the cwd); a non-directory
  is the 422 above and the message carries the **resolved** path. On Windows the
  resolved path has no `\\?\` prefix.
- `workspace=` present but empty: resolves to the cwd; it is not the "absent" case.

## Suspected Python bugs (raise per §9, do not fix in the port)

- Malformed YAML in a command's frontmatter (or invalid UTF-8) makes `GET /api/commands`
  and every render 500, so one bad file hides all commands. Not covered by a contract test.

## Pins check (callers of the service outside its routes)

| Caller | Uses | Verdict |
|---|---|---|
| `app/agent/mode/team/team.py:98,128,1739`, `app/api/routes/team/chat.py:631` | `parse_slash_invocation` (pure string parsing, no I/O) | in-process; stays Python, **no adapter**: it never reads state Rust owns and `/api/team/chat/**` is another unit |
| `app/api/routes/team/webbridge.py:1207,1283-1289` | `discover_commands`, `get_builtin_command`, `render_command` | reads the same files; Rust does not own any state or cache, **no adapter** |

## Test map

| Python test | Covered by |
|---|---|
| `tests/api/routes/test_commands.py::test_list_empty` | `test_list_empty_state` |
| `::test_list_without_workspace_ignores_project_local_commands` | `test_list_project_roots_need_workspace` |
| `::test_list_returns_discovered` | `test_list_global_sources_sorted_by_name` |
| `::test_render_substitutes_arguments` | `test_render_substitutes_arguments` |
| `::test_render_nested_command` | `test_render_nested_command_name_with_slash` |
| `::test_create_subcommand_file_list_and_render_roundtrip` | `test_nested_folders_one_level_only`, `test_render_nested_command_name_with_slash` |
| `::test_render_unknown_returns_404` | `test_render_unknown_command_is_404` |
| `::test_builtin_init_mentions_subfolder_agents_md` | `test_builtin_init_render_is_exact` (snapshot) |
| `::test_precedence_is_local_before_global_and_EVOFLUX_before_opencode` | `test_precedence_follows_the_four_roots` |
| `::test_local_opencode_wins_over_global_EvoFlux` | `test_precedence_follows_the_four_roots` (`b`) |
| `::test_workspace_local_commands_do_not_leak_between_projects` | `test_workspace_commands_do_not_leak_between_projects` |
| `::test_render_uses_workspace_local_command` | `test_render_uses_workspace_local_command` |
| `::test_global_commands_are_available_for_each_workspace` | `test_list_project_roots_need_workspace` (global entry beside project ones) |
| `::test_list_rejects_missing_workspace` | `test_list_rejects_missing_workspace` |
| `tests/services/test_commands.py::test_discover_returns_empty_when_no_roots` | `test_list_empty_state` |
| `::test_discover_finds_command_in_each_root` | `test_list_global_sources_sorted_by_name`, `test_list_project_roots_need_workspace` |
| `::test_precedence_project_EVOFLUX_wins_over_global` | `test_precedence_follows_the_four_roots` |
| `::test_nested_folders_become_slashed_names` | `test_nested_folders_one_level_only` |
| `::test_missing_frontmatter_yields_empty_description_and_full_body` | `test_description_parsing`, `test_body_parsing` |
| `::test_non_dict_frontmatter_is_ignored_gracefully` | `test_description_parsing` (list and scalar cases) |
| `::test_render_substitutes_arguments_placeholder` | `test_render_substitutes_arguments` |
| `::test_render_appends_arguments_when_no_placeholder` | `test_render_appends_arguments_without_placeholder` |
| `::test_render_with_no_arguments_leaves_body_unchanged` | `test_render_without_arguments_leaves_body` |
| `::test_render_substitutes_all_occurrences` | `test_render_substitutes_every_occurrence_and_strips_arguments` |
| `::test_parse_slash_invocation_supports_subcommands_and_quoted_args` | n/a: Python-only helper, stays in-process (no HTTP surface) |
| `::test_parse_slash_invocation_supports_colon_subcommands` | n/a: same |
| `::test_parse_slash_invocation_ignores_plain_chat` | n/a: same |
| `::test_commands_two_levels_deep_are_silently_ignored` | `test_nested_folders_one_level_only` |
| `::test_commands_one_level_deep_is_discovered` | `test_nested_folders_one_level_only` |
| `::test_commands_only_one_level_when_both_present` | `test_nested_folders_one_level_only` |
| `::test_commands_three_levels_deep_ignored` | `test_nested_folders_one_level_only` |

Extra contract cases beyond the Python tests: auth (missing, wrong, `?_token=`),
validation bodies, `~` workspace, workspace that is a file, URL-decoded and
case-sensitive names, CRLF and frontmatter edge cases, cache refresh, built-in
shadowing, code-point sort, 405s and concurrent reads.

Rust unit tests for L3b (not yet written): frontmatter regex cases, `render_command`
cases and the two-level walk, ported from the rows above.
