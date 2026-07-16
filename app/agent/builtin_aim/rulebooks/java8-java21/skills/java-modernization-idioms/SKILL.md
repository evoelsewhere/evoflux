---
name: java-modernization-idioms
description: Java 8 → 21 construct-level modernization idioms and the semantic traps in each one. Use when converting or reviewing a unit in a java8-java21 AIM migration project.
---

# Java 8 → 21 modernization idioms

## Overview

This is a same-language upgrade, so the temptation is to treat it as a mechanical find-and-replace. Most of the individual modernizations are safe — but a few of the "obviously equivalent" ones quietly change behavior at the edges, and those edges are exactly what test compare will catch if you get them wrong. This skill lists the common modernizations and, for each one, the specific case where equivalence isn't automatic.

## When to Use

While implementing or reviewing a unit in a `java8-java21` AIM project, once its mapping has been approved.

## When NOT to Use

**When NOT to use:** for cross-language migrations (COBOL→Java, VB6→.NET) — those need `aim-legacy-comprehension` and a stack-specific idiom skill of their own, not this one. Also not a substitute for the unit's approved mapping — this skill informs how you implement, not what you implement.

## Idioms and their traps

- **Anonymous inner class → lambda**: safe for stateless functional interfaces; not safe if the anonymous class held mutable instance state across multiple method calls, or referenced `this` meaning the outer class (lambdas capture differently).
- **`java.util.Date` / `Calendar` → `java.time.*`**: almost always an improvement, but check time zone handling explicitly — legacy code that implicitly used the default JVM time zone needs that made explicit in `java.time`, or behavior shifts across environments.
- **`Collections.unmodifiableList(...)` → `List.of(...)`**: not a drop-in replacement. `List.of()` rejects `null` elements (throws `NullPointerException` where the legacy list may have tolerated nulls) and its `equals`/iteration-order guarantees differ subtly. Check for nulls in the actual data before switching.
- **`switch` statement → `switch` expression / pattern matching switch (Java 21)**: safe when every legacy branch's fall-through behavior is preserved intentionally — dangerous if the legacy code relied on accidental fall-through (missing `break`), which the new syntax makes structurally impossible and will therefore change behavior, not just syntax.
- **`instanceof` + cast → pattern-matching `instanceof`**: purely syntactic, safe.
- **`StringBuffer` → `StringBuilder`**: only safe if the legacy usage was genuinely single-threaded; if it wasn't (rare, but check), this removes real synchronization.
- **Removed/deprecated APIs** (`SecurityManager` removed in later JDKs, `finalize()` deprecated for removal, some `javax.*` packages no longer bundled) — these force a real design change, not a mechanical swap; treat each as its own mapping decision, not a modernization idiom.
- **Records (Java 16+) for simple data carriers**: safe for genuine immutable data holders; check that no legacy subclassing or mutable-field access relied on the class being a regular class.
- **Sealed classes/interfaces, virtual threads**: opportunities to flag for the target design, not obligations — introducing them is an `aim-target-architect` decision (does the target base already use them?), not something a converter should introduce unilaterally per unit.

## Verification

Before treating a modernized construct as equivalent to the original: did you check the specific trap listed above for that construct, not just confirm it compiles? Does `aim_compare` still pass after the modernization, on cases that would actually exercise the trap (e.g. a null in the list, a legacy time-zone-dependent case, a fall-through case)? If a modernization changes behavior even slightly, is that documented as a deliberate ADR rather than an incidental side effect nobody decided on?
