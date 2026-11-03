# Security follow-up mutation evidence

2026-11-03, DS3-003 / DS3-004 / SR-008, Windows.

The final changed-code tools inventory contains **47 mutants: 37 caught,
10 unviable, 0 missed**. Every final candidate was matched to a recorded
outcome by file/function/replacement (line numbers normalized after formatting).
No final candidate was skipped or left unresolved.

Commands ran with `--in-diff <git diff --relative=server origin/migrate/rust-v4>`,
`-p evoflux-area-tools`, `--in-place`, `--test-tool nextest`, a 120-second build
limit, a 50-second test limit, and a 590-second outer limit. General candidates
were split over shards 0/3, 1/3 and 2/3, excluding `src/fnmatch.rs`, and used
`-E 'not test(fnmatch::tests)'`. The three fnmatch candidates ran separately
with the cache tests and a 60-second test limit. Unmutated baseline passed.

Unviable candidates: four nonexistent `ControlFlow` constructors/conversions,
four `ToolOutput::default()` replacements, `Sandbox::default()` and
`Regex::default()`; these types provide no such constructors/Default impls.

A preliminary inventory had one additional equivalent: deleting the empty-map
arm in the policy reader. Empty maps already reach the missing-key default,
with identical results and logging. That redundant production arm was removed;
the equivalent is absent from the final inventory above.

Before implementation, the real chat-turn test read the hidden payload despite
a saved policy, and ls exposed the outside junction. Removing the existing
cache cap deliberately made the new eviction regression fail with 4,097 live
compiled regexes; restoring the cap passed. The cache was already bounded on
the supplied base, so SR-008 primarily strengthens the regression proof.

File-symlink tests print a skip notice on this Windows account (privilege absent).
Directory-junction tests run. No changed-code mutant is Unix-only or untestable.
Cross-platform file-symlink checks remain for CI; no existing test assertion or
snapshot was weakened.

The chat-core propagation change has a separate scoped mutation run: **1 caught,
0 missed**, replacing `Turn::agent_loop` with `Ok(())`, checked with the saved-policy
turn regression.
Tools are function calls, with no HTTP/OpenAPI router; the tools OpenAPI gate
is not applicable. Workspace FLOW/shared gates and both-target contracts apply.
