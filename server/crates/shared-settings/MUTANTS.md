# P-003 mutation results

Scope: the whole `evoflux-shared-settings` crate on the final code, using
`cargo mutants -p evoflux-shared-settings --timeout 60 --test-tool nextest`,
sharded so that every run is a separate command under 10 minutes.

## Totals

278 mutants: 251 caught, 22 unviable, 5 equivalent (listed below with
reasons), 0 other missed.

The first pass (20 shards) missed 22. Tests now cover them:

- `is_falsy` on scalar documents (`0`, `0.0`, `-0.0`, `1.5`, `false`,
  `true`, `''`, `[]`, a date), checked against Python's
  `yaml.safe_load(...) or {}`;
- `load_report` on a folder in the file's place (Python's `read_text`
  raises; only a missing file means defaults), and `save` returning the path
  it wrote;
- `provider`, `remove_provider` and `providers_by_id` against Python's
  `dict.get` and `dict.pop` on a loaded file;
- the `24 * 30` hour limit of `webbridge.sharing.artifact_retention_hours`
  (100, 720 and 721);
- non-finite floats for integer fields, and integer and float strings with
  signs, `_` and whitespace, all checked against pydantic through the
  Python fixtures.

The new float-string cases showed that `parse_float_str` followed Python's
`float(str)` instead of pydantic-core: pydantic accepts `1_.0`, `1._5`,
`+_15` and `i_nf`, and rejects `_` together with surrounding whitespace
(`' 1_5 '`). It now parses the trimmed text first and otherwise removes every
`_` from the untrimmed text unless the text starts or ends with `_` or holds
`__`. The unit test that expected `1_.0` to fail was corrected to pydantic's
answer (`TypeAdapter(float).validate_python("1_.0") == 1.0`, also through
`CodeReviewSettings`). After that change every `validate.rs` mutant was run
again on the final code (5 shards); the other files' code did not change.

## Equivalent mutations

- `write_atomic`, guard `!p.as_os_str().is_empty()` → `true`: a bare file
  name has the empty parent. `create_dir_all("")` is a no-op that returns
  `Ok`, and `tempfile_in("")` creates the temporary file relative to the
  current directory, which is the folder `"."` names, so the file is written
  and renamed in the same place.
- `Section::validate`, guard `errors.is_empty()` → `true`: `validate` starts
  with no errors, `model_at` returns `Some` only when validation added none,
  and a failing `after` returns `None`. `Some` therefore always comes with an
  empty error list.
- `is_plain_http_origin`, scheme test `&&` → `||`: the result requires the
  scheme to be `http` or `https`. A candidate that lowercases to either one
  passes both tests, so the mutant only changes schemes that are rejected
  either way.
- `Bound::display`, `f.abs() < 1e16` → `<=`: no float bound in the settings
  models has magnitude `1e16` (the largest is 86 400).
- `Fields::model` → `Default::default()`: the method has no caller; nested
  sections are validated through `nested` and `validate_at`.

The raw results are kept in the migration bridge (`cl-land-b-p003-00` to
`-19`, `cl-land-b-p003-retest-*` and `cl-land-b-p003-val-0` to `-4`).
