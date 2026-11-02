# P-001 mutation acceptance

Scope: `src/load.rs` and `src/value.rs`, using `cargo mutants` with nextest.
The checked-in tests retain the original 84-document PyYAML load corpus and
65-value dump corpus. Boundary and unit tests supplement those fixtures.

## Equivalent mutations

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

Equivalent mutations are reported as missed, not silently counted as caught
or excluded from the run. Final totals follow after the continuation shards.

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
