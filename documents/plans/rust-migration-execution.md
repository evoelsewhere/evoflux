# EvoFlux v4: execution model (owner decision, 2026-10-30)

Replaces the "one task = one PR" flow from `server/AGENTS.md` §1–§2 for all
remaining work. The design, the gates, the test rules (§3–§6) and ADR 0001
stay as they are.

## Why

One PR per task meant a fresh agent session per PR: every session re-read the
plans, re-ran checks and waited for a remote reviewer. The context refreshes
and PR plumbing cost more than the code. Work now lands directly on
`migrate/rust-v4`. Review happens locally, done by the owner and by a second agent.

## Who works

| Agent | Role | Default model |
|---|---|---|
| **Claude (desktop, main)** | Orchestrates: picks the next task, writes briefs, lands commits, keeps the board current. Implements only critical-path or cross-cutting tasks. | Opus |
| **Claude CLI** (second account) | Main implementer. | Sonnet; Haiku for mechanical work |
| **Codex CLI** | Second implementer for Rust-heavy tasks, and local reviewer of Claude's work. | Codex default |
| **Owner** | Reviews locally (`git log -p`, `git diff`) and decides open questions. | — |

## Model choice per task

Choose the cheapest model that can do the task in one pass. A failed pass on a cheaper model costs more than one pass on the right model.

| Task kind | Model | Examples |
|---|---|---|
| Mechanical: docs, board rows, fixtures, rebases, CHANGELOG, renames | **Haiku** | T13 board updates, trimming #54 |
| Normal implementation with a clear plan | **Sonnet** | T5, T9, T14, T15, T12, most Phase 1–2 lane ports |
| Hard Rust: concurrency, streaming, process control, unsafe-adjacent FFI, auth/security parity | **Opus** or **Codex** | T8, T10, T11, the auth port, the agent loop |
| Local diff review | a different tool from the author, at the **cheapest model that understands the area** (Sonnet or Codex; Opus only for auth, sandbox, db and gateway) | — |
| Orchestration and owner questions | **Opus**, in short turns | — |

## How a task lands (no PR)

1. **Claim:** set the task's row in `server/MIGRATION_BOARD.md` to `claimed:<agent>` in a direct commit on `migrate/rust-v4`.
2. **Work:** in your own worktree on a local branch `wip/<agent>/<task>` cut from `migrate/rust-v4`. Git doesn't allow one branch in two worktrees, and this keeps agents off each other's files. Never push `wip/*`.
3. **Test first, then implement**, with the same task steps and gates as before: `bash scripts/migration/gates.sh <area>`, the contract tests, and Python "no new failures vs base".
4. **Local re-review by the other tool.** Pass it the diff and the task section. Use the review prompt below; don't open a PR.
   ```bash
   git diff migrate/rust-v4...HEAD > review.diff
   ```
   Fix the findings, and repeat until the reviewer replies `APPROVE`.
5. **Land:** `git rebase migrate/rust-v4`, rerun the gates, then
   `git switch migrate/rust-v4 && git merge --ff-only wip/<agent>/<task> && git push`.
   If the push is rejected, rebase and repeat. Never force-push `migrate/rust-v4`.
6. **Mark done:** set the board row to `merged` and add a one-line entry to `server/LANDED.md`: date, task, agent, reviewer, and the commit range. The owner reviews from that log.

**Commit rules are unchanged:** Conventional Commits, a CHANGELOG addition under `[Unreleased]`, UTF-8, no AI trailers, and never weaken a test or gate.

## Usage budget (owner decision, 2026-10-30)

There are three separate pools. Spend each one on what it does best, and never let one pool sit idle while another runs out.

| Pool | Spend on | Never on | Model ladder |
|---|---|---|---|
| **Desktop Claude** (orchestrator account) | decisions, short briefs, landing commits, owner questions | implementation, test runs, long reviews | Opus, in short turns; keep **≥ 40 % in reserve** |
| **Claude CLI** (Team org account) | most implementation, plus fix rounds | — | Haiku: mechanical · Sonnet: default · Opus: gateway, server binary, auth, agent loop |
| **Codex CLI** | Rust-heavy implementation, plus reviews of Claude's work | long multi-task threads | Luna/low: reviews and mechanical · Terra/medium: default · Sol or Terra/high: hardest Rust only |

**Who reviews whom:** reviews go to the *other* pool's cheapest capable model. Codex Luna reviews Claude's Sonnet work. Claude CLI Sonnet reviews Codex's work. The desktop Opus reviewer is used only for auth, sandbox, the database lanes and the gateway.

**Thread hygiene, the biggest saving:**
- One **fresh** Codex thread or Claude CLI conversation per task. Resume (`codex exec resume`, `claude --continue`) only for that task's own fix rounds.
- Never chain unrelated tasks onto one long thread, because each turn re-sends the whole history.

**Brief and report limits:**
- Briefs are at most 25 lines, and point to plan sections instead of copying them.
- Reports are at most 5 lines. Logs, benchmarks and diffs go to files in `D:\evoelsewhere\codex-bridge\`.

**Test runs:** focused tests while iterating, and the full gate once before review and once after the final rebase. Never rerun a suite whose inputs didn't change.

**Thresholds** (the owner checks each pool's usage page):
- At **50 %** left in a pool, that pool starts no new tasks; it only finishes what's in flight.
- At **20 %** left, pause the pool and move its queue to another pool. The work stays in its worktree.
- The orchestrator pauses at **40 %** left, leaving only status replies.

**Parallelism cap:** at most 2 implementers per pool at once. More than that adds coordination turns faster than it adds finished work.

## Keeping context (token budget)

- One long-lived CLI session per agent and lane, fed tasks one after another (Codex: `codex exec resume <id>`; Claude CLI: `claude --continue`). No new session per task.
- Briefs are short: name the task section and files instead of restating the plan.
- Agents report in five lines or fewer: what landed, the commit range, the commands run with their results, and open questions.
- Large outputs (test logs, benchmarks) go to files under `D:\evoelsewhere\codex-bridge\` or the task's notes, never into chat.

## Local review prompt (for the reviewing agent)

```text
Review this diff for EvoFlux v4 task <Tn> against documents/plans/rust-migration-phase-0-plan.md
(task <Tn>, Global Constraints) and the server/AGENTS.md §6 checklist. Run the task's verification
commands. Reply APPROVE, or a list of blocking findings as file:line + expected behaviour.
Max 15 lines.
```

## Open PRs at the switch

Existing PRs are finished in the new way. Each one gets a local review, is
landed with `git merge --ff-only` (or a merge commit if it's already
diverged), and the PR is closed with a link to the commit. Order: #52 (T7), #53 (T8), #48 (T1), #55 (regroup), then #54 (T4, trimmed first).
