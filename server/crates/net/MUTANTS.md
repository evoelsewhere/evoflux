# P-006 mutation gate

Changed production code is `src/pinned.rs`; existing general-client behavior is
unchanged. Generate the diff from the repository base with server-relative paths:

```sh
git diff --relative=server origin/migrate/rust-v4 > net.diff
cargo mutants --in-place --in-diff net.diff -p evoflux-net \
  --test-workspace false --test-tool nextest --timeout 30 --build-timeout 120 \
  --shard 0/2
cargo mutants --in-place --in-diff net.diff -p evoflux-net \
  --test-workspace false --test-tool nextest --timeout 30 --build-timeout 120 \
  --shard 1/2
```

Shards are zero-based. Each command is wrapped in `timeout 600`.
The first exploratory run missed redirect-counter multiplication and a reversed
content-length comparison. Regressions now require refusal of a third redirect,
allow a body smaller than its cap, and reject an oversized advertised length
before reading an incomplete body.

Final Windows results (2026-11-03), 46 mutations: **40 caught, 2 timeouts,
4 unviable, 0 missed; no equivalents**. Shard 0/2: 19 caught, 4 unviable;
shard 1/2: 21 caught, 2 timeouts. Timeouts count as caught under the worker rules.
No Unix-only code is involved.

The four unviable mutations substitute `Default::default()` for `Resolving`
(SystemResolver/NoDns), `PinnedClient` or `Url`, none of which implements Default.
The timeouts invert the initial-origin comparison or redirect-limit comparison;
both break the real TLS tests. The 25-test net suite also passes independently.

## Request builder (2026-11-04)

Same commands with `--shard 0/3`, `1/3`, `2/3`. 49 mutations: **32 caught,
2 timeouts, 15 unviable, 0 missed; no equivalents.** The first pass missed the
two arithmetic mutations of `DEFAULT_RESPONSE_LIMIT` and the credential-name guard
of `public_header` (reqwest's own `accept: */*` hid it); tests now pin the 8 MiB
default, and require a custom public header to survive a cross-origin redirect.
A focused re-run of those 6 mutations caught all 6. The timeouts invert the
initial-origin and redirect-limit comparisons. Unviable ones substitute
`Default::default()` for types without `Default`. The net suite is 42 tests.
