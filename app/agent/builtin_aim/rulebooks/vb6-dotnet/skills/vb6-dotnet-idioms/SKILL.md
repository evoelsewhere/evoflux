---
name: vb6-dotnet-idioms
description: VB6 → .NET construct-level idioms and the redesign-worthy traps in each one (error handling, global state, Variant, fixed-length strings, COM controls). Use when converting or reviewing a unit in a vb6-dotnet AIM migration project.
---

# VB6 → .NET modernization idioms

## Overview

Unlike a same-language upgrade, most VB6 → .NET construct mappings are not mechanical substitutions — they're redesign decisions that happen to be informed by what the legacy code did. Getting the "obvious" mapping wrong here doesn't just look unidiomatic, it silently changes behavior in ways test compare has to catch. This skill lists the recurring constructs and what actually needs deciding, not just translating, for each.

## When to Use

While implementing or reviewing a unit in a `vb6-dotnet` AIM project, once its mapping has been approved by `aim-target-architect`.

## When NOT to Use

**When NOT to use:** for the UI layer specifically — screen conversion follows `ui-patterns/vb6-to-dotnet-ui-patterns.md` and the `aim-ui-conventions` skill, not this one. This skill covers the code behind the forms (modules, class modules, business logic), plus the error-handling and state-management decisions that also affect form code-behind.

## Constructs and what they actually require

- **`On Error GoTo <label>` / `Resume` / `Resume Next`** — VB6's resumable error handling has no direct .NET equivalent (`try/catch` cannot resume execution at the failing statement). Don't attempt a literal translation; this needs an explicit redesign decision (typically: catch, log, and either abort the operation or retry the specific step deliberately) recorded as an ADR once, not reinvented per unit.
- **Standard modules (`.bas`) as global state** — VB6 code frequently reads and writes module-level variables from anywhere in the app. In .NET this becomes explicit dependency injection (scoped/singleton services) or explicit parameter passing — decide the target shape once at the project level; don't let each converted unit invent its own way of avoiding "a global."
- **`Variant`** — implicitly holds any type and coerces silently (numeric strings compare as numbers, empty string vs. `Null` vs. `0` behave differently in different contexts). Map to the narrowest concrete .NET type the actual usage requires, and specifically check what happens on empty/null input in the legacy code before assuming a type.
- **Fixed-length strings (`Dim s As String * 20`)** — if legacy behavior (or a file format, or a screen field) depends on the fixed padding, the target needs to reproduce that padding explicitly; a plain `string` silently drops it.
- **`Currency` type** — VB6's `Currency` is a fixed-point type with specific rounding behavior; map to `decimal`, but verify the target's rounding matches — this is exactly the kind of thing that shows up as a "tiny" diff in test compare and needs a cited reason either way.
- **Date serial numbers** — VB6 dates are floating-point day counts with known quirks (the 1900 leap-year bug, negative dates). Map to `DateOnly`/`DateTime`, but check date arithmetic against the legacy behavior explicitly rather than assuming standard calendar math matches.
- **COM/ActiveX controls (OCX)** — third-party or custom controls with no .NET equivalent are a design decision, not a mapping: flag them for `aim-target-architect` rather than guessing a replacement.
- **`Collection` object** — maps to `List<T>` or `Dictionary<TKey,TValue>` depending on usage (`Collection` supports both indexed and keyed access); check which one the legacy code actually relies on before picking.
- **`DoEvents` / modal message loops** — these have no direct .NET equivalent and usually indicate the legacy code was working around synchronous blocking; this is a concurrency-model decision (async/await, background work), not a line-for-line translation.

## Verification

Before treating a mapping as done: for error handling and global state, does the unit follow the project-level ADR rather than improvising its own approach? For `Variant`/`Currency`/date fields, did you check actual data for the specific values that would expose a coercion or rounding difference, not just the happy path? Does `aim_compare` still pass on cases that would exercise these traps?
