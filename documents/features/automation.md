# Goals and scheduler

EvoFlux provides two complementary automation levels: a durable autonomous
Goal attached to one conversation and a time-based Scheduler that dispatches
prompts to a target team.

## Durable Goal mode

`/goal <objective>` creates or replaces the session's durable objective. The
goal stores status, optional token budget, used tokens, active elapsed time,
pause reason, blocker fingerprint/streak, version and completion time.

Commands include status, budget, pause, resume and stop. After a normal turn,
the lead can continue through hidden internal turns until it completes the
goal, reaches a token budget, the user pauses/stops it, or the same concrete
blocker is reported on three consecutive goal turns. Optimistic versions
prevent concurrent controls from overwriting newer state.

Goal mode never expands the session's permission, sandbox, model or workspace
scope. Progress is persisted and streamed to the UI.

## Scheduler

Scheduled tasks support:

- one-time `at` timestamps;
- fixed `every` intervals;
- five-field cron expressions;
- explicit IANA timezones;
- Work targets, Coding workspace targets, or compatible Coding projects;
- pause, resume, manual trigger, update and delete.

Each enabled task owns an asyncio sleeper until `next_fire_at`, then dispatches
its prompt to the matching team lead and records session/run/error status. A
Coding target is validated at create/update/fire time so deleted or hidden
projects do not receive work. Windows ships `tzdata` so browser-selected IANA
zones work in the sidecar.

Agents can manage tasks through the built-in `schedule` tool; users can use the
standalone Scheduler page or workbench panel.

## Source and tests

Primary code: goal model/service/hooks and `app/agent/mode/team/team.py`;
`app/scheduler/`, scheduler routes and Scheduler React surfaces.

Focused suites: `tests/agent/mode/team/test_goal_*`, goal service/hook tests,
`tests/scheduler/`, and scheduler API/frontend tests.
