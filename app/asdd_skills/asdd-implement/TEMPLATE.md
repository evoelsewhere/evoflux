# Output template — asdd-implement

This phase writes code, not a document. What it leaves behind in the change
folder is a ticked `tasks.md`; what it leaves behind in the chat is the report
below.

## In the change folder

`tasks.md`, with `- [ ]` becoming `- [x]` as each task lands. Tick a task only
when its outcome is real — the product reads these counts, and a box ticked
ahead of the work turns the verification gate into a formality.

Nothing else. Do not touch `approvals`, do not edit `specs/<capability>/spec.md`
in the catalogue, and do not write evidence — that is `asdd-verify`.

## In the chat

```markdown
Implemented 4 of 4 tasks for `add-note-search`.

**Changed**
- `src/notes/store.py` — added `search(query)`, folding both sides. -> Find a note by title
- `tests/test_store.py` — two cases covering the scenarios in the delta.

**Checks run**
- `pytest -q tests` — 6 passed.
- `lsp_diagnostics` on the changed files — clean.

**Not done**
- Nothing, or: the task and why, in one line each.
```

## Rejected if

- A file was changed that no task and no approved impact called for.
- A task is ticked whose outcome is not actually in the tree.
- The report describes intent rather than what the code now does.
