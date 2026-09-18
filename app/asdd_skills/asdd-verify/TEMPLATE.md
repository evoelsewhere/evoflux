# Output template — asdd-verify

One page per check under `changes/<change-id>/evidence/<id>.md`, plus a report.

## `changes/<change-id>/evidence/<id>.md`

```markdown
---
id: pytest-store
kind: machine
result: passed
requirement: Find a note by title
recorded: 2026-09-17T10:04:00Z
---

`pytest -q tests/test_store.py` — 3 passed.

    tests/test_store.py::test_a_title_match_is_returned PASSED
    tests/test_store.py::test_a_non_match_is_not PASSED
```

- `kind` — `machine` for a command result, `review` for a human-or-agent
  reading of the work, `manual` for something a person exercised by hand.
- `result` — `passed`, `failed` or `inconclusive`. `inconclusive` is a real
  answer; recording a guess as `passed` is not.
- `requirement` — exactly as the delta spells it. Omit only for a check that
  covers the change as a whole.
- The body leads with the command and its outcome, then the part of the output
  that shows it. A page with no citation is an opinion.

A `cross_layer` or `critical` change also needs a `kind: review` page with
`result: passed`, written by someone who did not implement the work, naming who
reviewed it.

## In the chat

```markdown
Verified `add-note-search` against 2 approved requirements.

| Requirement | Verdict | Evidence |
|---|---|---|
| Find a note by title | passed | `evidence/pytest-store.md` |
| Search is case-insensitive | inconclusive | `evidence/case-fold.md` |

**Before this can be archived**
- `Search is case-insensitive` has no test that exercises a non-ASCII title.
```

## Rejected if

- A requirement has a verdict but no evidence page.
- A page says `passed` and cites nothing that was run or read.
- The verdict describes the diff rather than the integrated behaviour.
