# Agent runtime and teams

EvoFlux is a coding-agent/team harness: models are replaceable reasoning
engines, while EvoFlux owns configuration, context, tools, policy, execution,
streaming, persistence and verification.

## Agent configuration

An agent is a Markdown file with YAML frontmatter. The effective configuration
combines a code-owned Work or Coding base profile with user-owned additions:

- identity, role and optional visual metadata;
- `provider:model` and thinking level;
- Skills and tools plus explicit tool opt-outs;
- permission rules and runtime settings;
- optional team metadata and specialist roster.

Exactly one lead is required per team. First-party base behavior is not copied
into user files; edits remain compact and survive upgrades. Tracked agent/MCP
changes are detected at the next turn without stopping other running sessions.

See [Application harness](../architecture/application-harness.md) for the exact
frontmatter and precedence contract.

## Turn pipeline

The agent loop streams one provider request, assembles tool calls, executes
authorized calls, appends observations and continues until a final response.
Hooks add bounded behavior around the model and tools:

- workspace instructions, folder context and dynamic prompts;
- explicit/automatic Skill resolution and lazy Skill bodies;
- relevant scoped memory and wiki identity context;
- title generation, context compaction and continuation;
- streaming, session JSONL and OpenTelemetry events;
- post-edit diagnostics and Problems capture;
- usage accounting, Goal state and background memory extraction.
- active Coding EASD specification context and mission/evidence contracts.

Tool results are normalized and large outputs are offloaded. Provider-specific
wire formats stay behind a generic message/tool/usage schema.

## Lead and specialists

The lead decides whether to handle work directly or spawn specialists.
Specialists are lazy blueprints; `team_delegate` creates independent instances
named `blueprint#N`, each with its own history and lifecycle. They are activated
only when mailbox input exists and return to idle after draining it.

Team-native actions cover:

- delegate work with explicit objective, outputs and constraints;
- send peer messages through the shared mailbox;
- hand off evidence/results to the lead;
- reject a handoff and request targeted rework;
- manage team instances and shared state;
- create isolated Git worktrees for parallel Coding work;
- manage todos and durable delegation status.

The lead verifies handoffs before synthesizing the user-facing result. The
Monitor view exposes member state, activity and transcript without merging all
specialist context into the lead's model request.

## Concurrency and lifecycle

One member executes one turn at a time. Safe model-emitted tool calls may run in
bounded concurrent waves; stateful or unsafe batches run serially. Multiple
specialist instances can work in parallel, but there are no permanent
background agent loops.

Teams are cached by Work/session or Coding identity and evicted after an idle
window. Deletion and reload use lifecycle epochs/locks to prevent stale builders
from publishing old state.

## Streaming and failure behavior

All lead/member text, reasoning, tools, todos, handoffs and status events share
the parent session stream. Recoverable provider failures retry with bounded
backoff; interruption cancels active work and leaves a coherent persisted
boundary. Empty post-tool responses receive one continuation prompt instead of
silently abandoning completed tool work.

Questions, permissions and plan approval pause at explicit interaction points.
A specialist safety net reports failures back to the lead; terminal errors are
visible rather than converted into a successful handoff.

## Source and tests

Primary code: `app/agent/agent_loop/`, `app/agent/hooks/`,
`app/agent/mode/team/`, `app/agent/loader.py`,
`app/services/team_manager.py`, `app/services/memory_stream_store.py`.

Focused tests: `tests/agent/test_agent_*`, `tests/agent/hooks/`,
`tests/agent/mode/team/`, streaming API tests, and frontend team-store/activity
tests.
