# EASD Specification: Embed code_context guidance in EASD skills

Status: proposed

Origin Run: 06a94358-dcda-7527-8000-d5274f55888a (session mismatch — persisted for future import)

---

## Problem and outcome

**Problem:** EASD skills (easd-specify, easd-plan, easd-implement, easd-review,
easd-verify) run in Coding-only mode where the `code_context` tool is already
injected as a deferred tool, yet the skill instructional files never reference
it. This forces EASD agents to rely on basic `read`/`grep`/`glob` for source
discovery, callers, callees, references, impact, and neighborhood traversal —
missing the richer code graph navigation that the 9 Coding skills already
leverage. The result is less accurate cross-repository code analysis during
EASD specify/plan/implement/review/verify phases.

**Outcome:** All 5 EASD skill SKILL.md files gain explicit `code_context` usage
guidance and the shared `references/code-context-contract.md` bundle, matching
the pattern established by the 9 Coding skills. EASD agents can leverage code
graph navigation (search, definition, callers, callees, references, impact,
neighborhood) during specification grounding, planning, implementation,
independent review, and verification — producing higher-fidelity source evidence
and reducing the need for rereading raw files. The validation test is updated to
reflect the expanded skill scope.

---

## Goals

1. Each EASD skill SKILL.md references `code_context` with phase-appropriate
   usage guidance.
2. Each EASD skill bundles `references/code-context-contract.md` matching the
   Coding skills pattern.
3. The validation test `test_native_code_context_contract_is_embedded_in_coding_workflows`
   is updated to cover EASD skills.
4. **easd-specify** uses `code_context` for repository discovery, ambiguity
   scanning, and source grounding.
5. **easd-plan** uses `code_context` for impact target identification,
   affected-path mapping, and cross-layer dependency tracing.
6. **easd-implement** uses `code_context` for caller/callee validation before
   and after edits, and for verifying symbol-level impact of changes.
7. **easd-review** uses `code_context` for independent source verification of
   implementation claims, references checking, and transitive impact assessment.
8. **easd-verify** uses `code_context` for evidence gate validation, checking
   AC coverage against actual code symbols, and verifying documentation
   reconciliation.

## Non-goals

- Changing the `code_context` tool runtime, API, or schema.
- Modifying the deferred-tool catalog or tool injection mechanism.
- Altering EASD lifecycle state transitions, run states, or convergence rules.
- Adding new backend services or database changes.
- Changing the skill resolution or scope enforcement logic.
- Altering the Coding skills' existing `code_context` patterns.
- Modifying the EASD knowledge-base index, specs, or features content.

---

## User flows and states

The affected flow is the EASD lifecycle when an agent loads an EASD skill:

1. User triggers an EASD phase (specify, plan, implement, review, verify).
2. EASD skill is loaded from `.evoflux/skills/easd-{phase}/SKILL.md`.
3. Agent follows SKILL.md instructions to perform the phase work.
4. **Current state:** Agent uses `read`, `grep`, `glob` for source discovery.
   `code_context` is available but never instructed.
5. **Target state:** Agent uses `code_context` for structured code graph
   navigation (search, definition, callers, callees, references, impact,
   neighborhood) alongside `read`/`grep`/`glob`, matching Coding skill behavior.

---

## Requirements and acceptance criteria

| AC | Statement | Required | Evidence |
|----|-----------|----------|----------|
| AC-1 | Each of the 5 EASD skill SKILL.md files contains a `code_context` usage guidance section that references the tool by name and describes phase-appropriate navigation actions. | Yes | machine + review |
| AC-2 | Each of the 5 EASD skill directories contains a `references/code-context-contract.md` file with identical content to the canonical contract. | Yes | machine |
| AC-3 | The test `test_native_code_context_contract_is_embedded_in_coding_workflows` is updated to include all 5 EASD skills in the expected set. | Yes | machine |
| AC-4 | easd-specify SKILL.md guidance covers `code_context(action=search)` for discovery and `action=definition|callers|references|impact` for grounding. | Yes | machine + review |
| AC-5 | easd-plan SKILL.md guidance covers `code_context` for impact targets (`action=impact|references`), affected-path mapping, and cross-layer dependency tracing. | Yes | machine + review |
| AC-6 | easd-implement SKILL.md guidance covers `code_context` for caller/callee validation before and after edits. | Yes | machine + review |
| AC-7 | easd-review SKILL.md guidance covers `code_context` for independent source verification, references checking, and transitive impact assessment. | Yes | machine + review |
| AC-8 | easd-verify SKILL.md guidance covers `code_context` for evidence gate validation and AC coverage cross-checking. | Yes | machine + review |
| AC-9 | No EASD skill modifies the `code_context` tool runtime, API, schema, catalog, or injection mechanism. | Yes | machine |
| AC-10 | All existing EASD skill tests (frontmatter, scope, content) pass without regression. | Yes | machine |

---

## API, event, tool, and UI contracts

No API, event, or UI changes. The `code_context` tool is already injected in
Coding mode via the `DeferredToolCatalog` with `tiers=("coding",)`. EASD skills
already have `"modes": ["coding"]` in their `.evoflux.json` scope files. Only
skill instructional content changes.

---

## Data model, migration, and retention

No data model, migration, or retention changes.

---

## Permissions, security, privacy, and trust

- `code_context` is bounded by the Shared coding-context-contract: Read-only
  indexed queries, no mutation. EASD skills must cite the same contract.
- Cross-repository edges resolve from the current authorized snapshot, not a
  stale central edge table. No new trust boundary is introduced.
- No new PII, secrets, or untrusted-data paths are opened.

---

## Concurrency, failure, recovery, and idempotency

No concurrency, failure recovery, or idempotency concerns. The change is
instructional content only.

---

## Observability and diagnostics

No new telemetry is needed. Existing `code_context` observability (deferred
tool metrics, routing counters) covers the new usage automatically.

---

## Compatibility, rollout, and rollback

- **Compatibility:** Additive. Existing skill behavior is unchanged for agents
  that do not use `code_context`. Agents that do use it gain richer navigation.
- **Rollout:** Skills are loaded at runtime from `.evoflux/skills/`. Changes
  take effect on next skill load.
- **Rollback:** Remove the `references/` directories and revert SKILL.md files.
  No database or state cleanup needed.

---

## Verification matrix

```bash
uv run pytest tests/agent/tools/test_skill_loader.py -k test_native_code_context_contract_is_embedded_in_coding_workflows
uv run pytest tests/agent/tools/test_skill_loader.py -k test_easd_skill_files_have_correct_frontmatter
uv run pytest tests/agent/tools/test_skill_loader.py -k test_easd_skill_scope_files
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
```

---

## Ownership and source map

| Artifact | Path |
|----------|------|
| EASD implement skill | `.evoflux/skills/easd-implement/SKILL.md` |
| EASD plan skill | `.evoflux/skills/easd-plan/SKILL.md` |
| EASD review skill | `.evoflux/skills/easd-review/SKILL.md` |
| EASD verify skill | `.evoflux/skills/easd-verify/SKILL.md` |
| EASD specify skill | `.evoflux/skills/easd-specify/SKILL.md` |
| Canonical contract | `app/agent/builtin_skills/coding-investigation/references/code-context-contract.md` |
| Validation test | `tests/agent/tools/test_skill_loader.py` |
| Architecture ref | `documents/architecture/coding-agent-code-context.md` |
| Audit ref | `documents/analysis/builtin-skill-context-audit-2026-08-06.md` |

---

## Delivery flow recommendation

**Planned** — although the change is low-risk (instructional content only, no
runtime/API/schema changes), it spans 10 new files, 5 existing SKILL.md edits,
and 1 test file update across a consistent pattern. A plan phase is warranted to:

1. Define the exact `code_context` guidance text per EASD skill phase, ensuring
   each skill's guidance is tailored (not copy-pasted verbatim).
2. Confirm the shared `code-context-contract.md` content is identical across all
   10 skill bundles.
3. Verify the test expansion covers the new expected set without breaking existing
   assertions.

**Conditions requiring Plan:**

- Multi-boundary change (5 skills + 10 reference files + 1 test)
- Pattern must be consistent but phase-specific across 5 skills
- Test logic change (expected set expansion)

---

## Risk tier

**Standard** — instructional content changes with no runtime, schema, or
security boundary impact.
