# Commit and release discipline

## Atomic commit criteria

A commit is atomic when the working tree passes its narrow check at that
commit, it represents one logical change, and reverting it alone would not
leave the tree in a broken intermediate state. Commit after each passing
narrow check during a multi-step change so a bad step is one revert away,
not buried inside a larger diff.

## Branch lifetime

Prefer trunk-based development: short-lived branches merged in one to a few
days, with a feature flag or default-off code path for work that cannot
finish in one reviewable slice. A branch held open for weeks accumulates
merge conflicts and makes review harder, not easier, the longer it waits.

## Versioning as a consumer promise

A version number is a promise to whoever depends on it, not a counter
derived from commit history. Once a behavior is observable, a change to it
is a major change in that consumer's terms even if it looks like a "patch"
internally (Hyrum's Law). Write the changelog entry with the change itself,
not reconstructed from `git log` at release time — the author who made the
change knows its consumer-facing meaning better than a log message written
for a different purpose.

## PR description as an anti-scope-creep artifact

State explicitly what the change did not touch when the diff could
plausibly have included more. This protects both the reviewer (who does not
have to guess what was deliberately excluded) and the author (whose scope
decision is now visible and defensible) rather than silently narrowing scope
with no record.
