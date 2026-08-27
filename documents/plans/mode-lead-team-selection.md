# Mode lead and member ownership

Status: implemented

## Problem and outcome

Each Work or Coding agent directory currently requires exactly one lead and
treats every member definition as a shared blueprint pool. Top-level sessions
often leave `agent_name` unset, while the roster endpoint can build a synthetic
default team unrelated to the open session. The UI therefore cannot explain
which lead owns which members, and cannot reliably select a different lead/team.

The outcome is an explicit mode-scoped roster: each mode may define multiple
lead agents, every member resolves to exactly one lead, each session persists
its selected lead, and the topbar switches the idle session between those teams.

## Goals

- Support multiple lead definitions in Work and Coding independently.
- Resolve every member to one lead through frontmatter or a deterministic
  backward-compatible default.
- Persist the selected lead on every top-level session.
- Build and report only the member blueprints owned by that session's lead.
- Provide a compact topbar selector showing the selected lead and owned members.
- Allow safe lead switching only while the session/team is idle.
- Expose ownership in Settings → Agents.

## Non-goals

- One member shared by multiple leads.
- Switching a lead during an active turn or migrating in-flight delegations.
- Rewriting historical messages or deleting prior member child sessions.
- Cross-mode teams or allowing a Work lead to own Coding members.
- Per-message lead selection inside one active turn.

## User flows and states

- The topbar lists only leads from the current mode.
- Below the small breakpoint the trigger becomes icon-only and the menu width is
  bounded by the viewport; lead/member names wrap without clipping other topbar
  controls.
- Each lead option shows its member count and member names.
- The persisted session lead is selected when a chat opens or reloads.
- Choosing another lead while idle updates the session, evicts the old live
  team, reloads history, and starts the selected team on the next action.
- While any team member is working, the selector is disabled with an explanatory
  tooltip.
- A member Agent form shows an **Owned by lead** selector scoped to the same
  mode. Omitting it assigns the member to the mode's deterministic default lead.
- Settings → Agents renders mode → lead team → nested members instead of a flat
  role list; lead groups are collapsible and bulk-selectable.
- Delegation cards identify both sides (`<lead> delegated → <member#N>`) so a
  task shown inside the lead transcript cannot be mistaken for lead execution.
- Existing configurations with one lead and no member owner continue unchanged.

## Requirements and acceptance criteria

- **AC-1:** `AgentConfig` accepts optional member `lead`; a lead cannot itself
  declare an owner.
- **AC-2:** A mode directory requires at least one lead, allows multiple leads,
  rejects duplicate names and unknown member owners, and deterministically picks
  `evoflux` or otherwise the first sorted lead as the default.
- **AC-3:** A member without `lead` belongs only to the default lead; a member
  with `lead` belongs only to that named lead. No member appears in two rosters.
- **AC-4:** Team loading and hot blueprint refresh select one lead and compile
  only its owned members.
- **AC-5:** `GET /api/team/leads?mode=work|coding` returns mode, default lead,
  lead metadata and the exact owned member summaries without starting a team.
- **AC-6:** New/resolved top-level sessions persist a valid selected lead in
  `ChatSession.agent_name`; legacy null rows bind to the resolved default.
- **AC-7:** Team resolution and `GET /api/team/agents` use the persisted session
  lead. The response identifies the lead and contains no member from another
  lead.
- **AC-8:** `PATCH /api/team/sessions/{id}/lead` validates same-mode ownership,
  rejects missing/running/member identities, persists first, then evicts the old
  cached team. Repeating the same selection is idempotent.
- **AC-9:** The Agent form exposes same-mode lead ownership for members and
  serializes/parses/preserves `lead` in YAML.
- **AC-10:** The topbar selector displays selected lead plus owned member count/
  names, is mode-scoped and working-disabled, and reloads the session roster
  after a successful switch.
- **AC-11:** Tests cover multi-lead validation, default ownership, explicit
  ownership, loader isolation, session persistence/switch rejection, session-
  aware roster API, form serialization and topbar interaction.
- **AC-12:** Current feature/architecture/API docs and in-app Help describe lead
  ownership, switching boundaries and backward compatibility.
- **AC-13:** Responsive tests preserve an icon-only compact trigger on narrow
  topbars and a viewport-bounded menu with wrapping member names.
- **AC-14:** Settings groups members under their owning lead, labels inherited
  default ownership, exposes member counts, and preserves per-agent/team bulk
  selection plus search.
- **AC-15:** Delegation task cards name the delegating lead and executing member
  while handoff/final synthesis remain visually distinct.

## API, event, tool, and UI contracts

Agent member frontmatter:

```yaml
name: coder
role: member
lead: engineering-lead
```

Lead discovery:

```text
GET /api/team/leads?mode=work|coding
```

Session resolution accepts optional `agent_name`; session switching uses:

```text
PATCH /api/team/sessions/{session_id}/lead
{ "lead_name": "engineering-lead" }
```

`GET /api/team/agents` accepts `session_id` and returns the live roster for that
session's persisted lead. Existing response fields remain additive-compatible.

## Data model, migration, and retention

No Alembic migration: `ChatSession.agent_name` already exists. Legacy null
top-level sessions are assigned the resolved default lead on their next resolve
or explicit switch. Existing member YAML without `lead` is retained and resolves
to the deterministic default lead.

Historical member child sessions remain attached to the chat after a lead
switch and render as offline history when they are not in the new live roster.

## Permissions, security, privacy, and trust

Only configured same-mode `role: lead` identities are selectable. Agent config
paths remain bounded by the existing Agents filesystem service. Switching does
not broaden workspace, project, sandbox, permission mode, provider or tool
access; the selected lead and its member configs are still compiled through the
normal mode-specific policy.

## Concurrency, failure, recovery, and idempotency

The switch endpoint checks durable and live running state before mutation. It
commits the new lead before evicting the old idle team; a failed commit leaves
the old team untouched. A failed post-commit eviction is diagnosable and the
next resolution still uses the durable lead. Re-selecting the current lead does
not rebuild the team.

## Observability and diagnostics

Team build/start logs include mode, session and selected lead. Switch logs include
session, old lead and new lead without prompts or message content. API errors
distinguish invalid mode, unknown lead, member-not-lead and active-team conflict.

## Compatibility, rollout, and rollback

Single-lead directories behave exactly as before except sessions now persist
that lead explicitly. Unowned legacy members attach to the default lead. Older
code ignores the additive member `lead` field through Pydantic's default extra
handling; rolling back reverts to the prior single-team interpretation without
database downgrade.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1–4 | config/loader/team-manager unit tests |
| AC-5–8 | focused team route/session API tests |
| AC-9–10, AC-13–15 | frontend form, query, topbar, hierarchy, delegation and responsive tests |
| AC-11–12 | focused/full gates, Help/docs review and live browser audit |

## Ownership and source map

- Config/rosters: `app/agent/config.py`, `app/agent/loader.py`
- Runtime selection/cache: `app/services/team_manager.py`,
  `app/agent/mode/team/member.py`
- Session/API: `app/api/routes/team/chat.py`, `app/api/schemas/sessions.py`,
  `app/services/chat_service.py`
- Agent CRUD: `app/api/routes/agents.py`, `app/api/schemas/agents.py`
- Frontend client/store: `web/src/api/`, `web/src/queries/`,
  `web/src/stores/useTeamStore/`
- UI: `web/src/components/workbench/WorkbenchBar.tsx`,
  `web/src/components/settings/AgentForm.tsx`
- Tests/docs/Help: `tests/`, `web/src/__tests__/`, `documents/`,
  `web/src/help/locales/`
