# Mutation results (area-settings-providers)

Run on 2026-11-03 with cargo-mutants 27.1.0, scoped to this crate and to the
DS2-001 (`/api/auth/**`, request-body validator) and P-008 (settings section
routes) diff against `origin/migrate/rust-v4` at ced7ee86:

```
cargo mutants --in-diff <(git diff --relative=server origin/migrate/rust-v4) \
  -p evoflux-area-settings-providers --shard k/12 -j 6 --baseline skip --timeout 60
```

| Shards | Mutants | Caught | Unviable | Timeouts | Missed |
|---|---|---|---|---|---|
| 0..11 of 12 | 345 | 285 | 60 | 0 | 0 |

No equivalents and no Windows-untestable mutants. The one mutant outside the
crate in that diff, `crates/server/src/units.rs` `router -> Default::default()`,
is shared wiring and not in this lane's scope.
