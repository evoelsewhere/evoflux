# Output templates — asdd-plan

This phase writes two files. `design.md` only for `cross_layer` and `critical`.

## `changes/<change-id>/design.md`

```markdown
## Approach

The shape of the solution, specific enough that someone could build it two
different ways and recognize which one this is.

## Alternatives rejected

- **Encrypt the whole store file** — simpler, but loses per-note access, which
  the delta requires. An alternative with no reason is an omission.

## Boundaries

- Trust, process and data boundaries this crosses, and what guards each.
- Compatibility: what existing callers, files or schemas must keep working.

## Migration and rollback

- How existing state reaches the new shape, and how to get back if it fails.

## Decisions

- **PDF page size** — A4. Asked the user; they said the audience is Vietnamese.
- **Character encoding** — bundled TTF, so diacritics render without relying on
  a system font.

## Open questions

<!-- Empty. Anything here blocks the design gate: ask with `ask_user`, record
     the answer under Decisions, and move out-of-scope items to a follow-up
     change. -->
```

## `changes/<change-id>/tasks.md`

```markdown
## 1. Storage

- [ ] Add `NoteStore.search(query)`. -> Find a note by title
- [ ] Fold query and title before comparing. -> Search is case-insensitive

## 2. Verification

- [ ] Run the repository's checks and record the result under `evidence/`.
- [ ] Confirm every approved requirement has a scenario that was exercised.

## 3. Catalogue and documentation

- [ ] Record the storage choice as `architecture/decisions/0007-note-store.md`.
- [ ] Update `reference/api.md` for the new `search` parameter.
- [ ] Update the docs and changelog this repository expects.
```

Every task is one outcome, verifiable on its own, and `-> ` names the
requirement it serves. A task nothing traces to is either scope creep or a
requirement the delta is missing.

## Rejected if

- `## Open questions` is non-empty when `status: designed` is declared.
- A rejected alternative carries no reason.
- A task group has no requirement behind it.
- A decision that would be expensive to reverse has no task writing it up under
  `architecture/decisions/`, or a changed API, configuration, schema, event or
  CLI flag has no task updating `reference/`. Those pages ship with this
  change; only `specs/` waits for the archive.
