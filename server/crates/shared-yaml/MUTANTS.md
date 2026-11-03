# P-001, P-002 and SR-009 mutation acceptance

Scope: the whole `evoflux-shared-yaml` crate (`src/load.rs`, `src/value.rs`,
`src/dump.rs`, `src/lib.rs`) on the final code, using `cargo mutants -p
evoflux-shared-yaml --shard k/40 --timeout 60 --test-tool nextest`, every
shard a separate run. The checked-in tests retain the 84-document PyYAML load
corpus; the dump corpus is 115 values, each dumped by PyYAML 6.0.3 in all four
option combinations. Boundary and unit tests supplement those fixtures.

## Totals

624 mutants: 567 caught (3 of them timeouts), 30 unviable, 27 equivalent
(listed below with reasons), 0 other missed. The 41 dump mutants first missed
by shards 0 to 17 were re-run after the dump corpus gained new cases:
19 are now caught (2 of them as timeouts) and 22 are the equivalents listed
later. The added cases:

- 122- and 123-character string keys (the `!!str` tag counts towards the
  128-character simple-key limit);
- sequence values after a quoted key, a long key and a multi-line key
  (indentless sequences and the `indention` flag);
- single-quoted scalars folded two or more times;
- double-quoted scalars mixing allowed Unicode with escapes, and starting past
  the width after a long key;
- forty widths (60 to 99) of single- and double-quoted scalars folded at every
  column near the 80-column limit, with spaces and escapes at the fold;
- mixed naive and aware datetime keys (Python cannot sort them), mixed
  bool/int/float keys, and same-day and cross-day timestamp keys.

## Equivalent mutations

### Loader and values

- `Composer::add`, `anchor > 0` → `anchor >= 0`: this additionally stores
  unanchored nodes under anchor ID 0. Parser-issued anchors and aliases have
  positive IDs, so that entry is never looked up; overwriting it cannot change
  document values or errors.
- `Mapping::remove_value`, surviving slot `> at` → `>= at`: the index entry
  at `at` has already been removed, and every remaining indexed key has a
  distinct slot. No surviving slot equals `at`, so both predicates update
  exactly the same entries, including maps containing unhashable entries.
- `python_float_repr` and `json_key`, infinity sign `> 0.0` → `>= 0.0`:
  these branches run only for positive or negative infinity, neither zero.
  Both comparisons therefore select the same sign.
- `python_float_repr`, exponent `< 0` → `<= 0`: exponent-sign formatting
  is reached only outside `-4..16`. Exponent zero uses positional formatting
  and never reaches this comparison.

### Emitter (`src/dump.rs`)

- `represent_float`, infinity sign `> 0.0` → `>= 0.0`: reached only for
  infinities, never zero.
- `prepare_tag` → `"xyzzy"`: `safe_dump` never writes a tag (every scalar it
  represents resolves implicitly to its own tag when plain, and quoted styles
  only occur for `!!str`), so the tag only counts towards the simple-key
  limit. `"xyzzy"` has the length of `!!str` and `!!int`; null, bool, float
  and timestamp keys are at most about 40 characters with any tag.
- `analyze`, `leading_break` `index == 0` → `!=` and `trailing_break`
  `index == len - 1` → `!=`, `len + 1`, `len / 1`: both flags only clear the
  two plain permissions, which `line_breaks` already clears for any break.
  PyYAML has the same redundancy.
- `write_indent`, `column < indent` → `<=`: without a line break,
  `column == indent` implies `whitespace` is already true (otherwise the break
  condition fired); after a break the column is 0 and `whitespace` is true.
  Setting it again changes nothing.
- `node`, `flow_level > 0` → `< 0` (sequence and mapping): `flow_level` is a
  `usize` and is 0 whenever `node` runs; only empty collections enter flow
  context, and they emit no nodes.
- `ordered`, `entries.len() > 1` → `>= 1`: sorting one entry returns it.
- `choose_style`, `simple_key && (empty || multiline)` → `&&`: a node is
  emitted as a simple key only after `is_simple_key` rejected empty and
  multi-line scalars, so both conditions are false.
- `choose_style`, `flow_level > 0` → `<`, `==`, `>=` and the following `&&` →
  `||`: `flow_level` is 0 for every scalar (above), and `analyze` never
  forbids block plain without also forbidding flow plain (every place that
  sets `block_indicators` sets `flow_indicators`). Each mutant therefore
  reduces to `allow_block_plain`, the original condition at flow level 0.
- `write_plain`, the three mutations in the `breaks` branch (`delete !` and
  both `== '
'` → `!=`): plain style is never chosen for a scalar containing
  a line break (`line_breaks` forbids it), so the branch is unreachable.
- `write_single_quoted`, `&& start < end` → `||` and `start < end` →
  `start <= end`: the first writes pending text one character earlier, before
  any width check reads `column`, so the output and the columns at each check
  are identical; the second only adds empty writes when `start == end`.
- `write_double_quoted`, both `start < end` → `<=`: with `start == end` the
  guarded write is empty and `start = end` is already true.

Equivalent mutations are reported as missed by `cargo mutants`, not silently
counted as caught or excluded from the run. The raw shard results are kept in
the migration bridge (`cx-land-b-yaml-final-00` to `-12`,
`cl-land-b-yaml-13` to `-39` and the `cl-land-b-yaml-retest-*` runs).

## Quoted token ownership

The original `!quoted` sort tiebreaker was not equivalent: a quoted mapping
key may share its start with a mapping/key token, and valid tabs in that
scalar were rejected. The tiebreaker now puts scalar ownership last, so the
partition lookup accepts a tab inside any quoted/block token at that start.
The new regression covers quoted keys, flow collections, root scalars and
block mapping values; existing invalid plain/separator-tab tests are retained.

## Depth boundary

`yaml-rust2` 0.10.4 uses a `u8` flow level in `Scanner::increase_flow_level`:
256 nested flow collections fail there with `recursion limit exceeded` before
the EvoFlux composer sees that depth. Block sequences/mappings accept exactly
256 levels with a scalar inside, and reject 257 with `TooDeep`. Alias chains
test constructed depth independently of the scanner's flow ceiling.
Supporting 256 fully nested flow collections requires changing the dependency;
the acceptance tests exercise the public depth limit using block collections.
