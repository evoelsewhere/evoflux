# area-snippets NOTES

Python source: `app/api/routes/snippets.py`, `app/services/snippets.py`,
`app/api/schemas/snippets.py`; discovery helpers `_iter_md`, `_md_tree_signature` and
`_parse_frontmatter` are shared with `app/services/commands.py` (see
[`../area-commands/NOTES.md`](../area-commands/NOTES.md) for walk, frontmatter and
cache rules, which apply unchanged). Unit `edge-stateless`. Contract tests:
`contract-tests/snippets/test_snippets.py` (all pass against Python v3.1.1).

## Endpoints

| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `GET /api/snippets?workspace=` | `workspace` **required** | `200 {"snippets":[{name,description,source}]}` sorted by `name` (code point) | `422 {"detail":"Snippet workspace is required."}` when the parameter is absent; `422 {"detail":"Workspace does not exist or is not a directory: <resolved path>"}` |
| `POST /api/snippets/{name:path}/render?workspace=` | no body (a body is ignored) | `200 {"name","content"}` where `content` is the body after frontmatter, **no** `$ARGUMENTS` substitution | the two workspace `422`s (checked before the lookup); `404 {"detail":"Snippet '<name>' not found."}`; auth `401 {"detail":"Unauthorized — EvoFlux access key required."}` |

`workspace=` present but empty is not "absent": it resolves to the backend's cwd
and succeeds (`test_empty_workspace_param_resolves_to_the_backend_cwd`).

## State, files, side effects

No DB, events or writes. Two roots, first hit wins:

1. `{workspace}/.evoflux/snippets` → `project-EvoFlux`
2. `{EVOFLUX_CONFIG_DIR}/snippets` → `global-EvoFlux`

`.opencode` roots and the `commands` directories are not snippet roots. Nesting is one
level deep (`git/commit`), deeper files are skipped. There is no built-in snippet,
so `init` is a 404. Same lru cache keyed on the mtime signature as commands.

## Pins check

| Caller | Uses | Verdict |
|---|---|---|
| `app/api/routes/team/webbridge.py:1241,1308` | `discover_snippets` | reads the same files; Rust owns no state, **no adapter** |

## Test map

| Python test | Covered by |
|---|---|
| `tests/api/routes/test_snippets.py::test_list_requires_workspace` | `test_list_requires_workspace` |
| `::test_list_and_render_snippets` | `test_list_project_and_global_sorted_by_name`, `test_render_returns_body_without_frontmatter`, `test_render_nested_name_with_slash` |
| `tests/services/test_snippets.py::test_discover_snippets_requires_workspace_and_finds_project_and_global` | `test_list_requires_workspace`, `test_list_project_and_global_sorted_by_name` |
| `::test_project_snippet_wins_over_global` | `test_project_snippet_wins_over_global` |
| `::test_nested_snippet_names_use_slash` | `test_nested_folders_one_level_only`, `test_render_nested_name_with_slash` |

Extra contract cases: auth (missing, wrong, `?_token=`), workspace validation
(missing, a file, empty, `~`), unknown and too-deep names, URL-decoded and
case-sensitive names, no built-in `init`, commands are not snippets, other roots
ignored, frontmatter and CRLF cases, cache refresh, code-point sort, 405s and
concurrent reads.
