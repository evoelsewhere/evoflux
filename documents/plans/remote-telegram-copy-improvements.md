# Remote Telegram: command names and messages are unclear — proposed copy

Status: proposed (feedback only — not implemented, not scheduled)

## Problem

None of the existing or planned specs ([`remote-channel-telegram.md`](remote-channel-telegram.md),
[`remote-telegram-response-ui.md`](remote-telegram-response-ui.md)) address command
naming or message wording — they cover formatting, live status, and new
surfaces (`/settings`, guided picker), not clarity of what's already there.
Direct user feedback on the current bot:

- "What does 'type to chat with agent' mean? Give me an actual command."
- "`/new` — start a new task — doesn't mean anything to me."
- "`/stop` doesn't mean anything when I don't know what's running."
- "`/actions` also doesn't mean anything to me."
- "`Connected to EvoFlux on {label}.`" reads as a raw log line, not a
  confirmation a person sent from their phone.

The current copy assumes the reader already understands EvoFlux's
task/turn model (a "task" is a chat session; "stop" interrupts the agent's
current turn; "actions" is a menu, not an action). A first-time phone user
doesn't have that model yet — the copy needs to teach it, not just label it.

## Scope

Copy only. No command is renamed, added, or removed; no behavior changes.
Every string below is a literal replacement in the same two files:

- `app/remote/actions.py` — `_HELP_TEXT` (`actions.py:87`)
- `app/remote/runtime.py` — pairing confirmation (`runtime.py:401`)
- `app/remote/telegram/adapter.py` — Telegram's native "/" command-menu
  descriptions (`_register_commands`, `adapter.py:324-330`)

## Proposed copy

### 1. `/help` text

**Current:**
```
Available commands:

/help — Show this help
/status — Show connection and current task status
/new — Start a new task (clears current task)
/stop — Stop the current running task
/unpair — Unpair this phone from EvoFlux
/actions — Show more actions (Workflows, Projects, Scheduler)

Or just type a message to chat with your agent.
```

**Proposed:**
```
👋 You're paired with EvoFlux. Just type a message to send it to your
agent — no command needed. It'll pick up your current task, or start a
new one if there isn't one yet.

Commands:
/status — What's my agent doing right now?
/new — Set aside the current task and start a fresh one
/stop — Interrupt the agent while it's working on your last message
/actions — Run a saved workflow, open a coding project, or fire a
    scheduled task
/settings — See the connected model, permissions, and notification prefs
/unpair — Disconnect this phone from EvoFlux

Send /help any time to see this again.
```

Rationale per line:
- Leads with the free-text behavior first, since that's the primary way
  to use the bot and the thing users were most confused about — it's not
  buried as an afterthought at the bottom.
- `/status` reframed as a question a person would actually ask, not a
  description of a feature.
- `/new`/`/stop` each state the before/after in plain terms instead of
  repeating the command's own name back at the reader.
- `/actions` replaced with concrete examples of what's behind it, instead
  of "more actions" (which is an empty label — more than what?).
- `/settings` line added pre-emptively for when Task 7 ships, so this
  rewrite doesn't need to be revisited twice. Remove it now if the copy
  change lands before `/settings` does.

### 2. Pairing confirmation

**Current:**
```
Connected to EvoFlux on {label}.
```

**Proposed:**
```
✅ Paired! This phone ("{label}") is now connected to EvoFlux.

Type anything to start working with your agent, or send /help to see
what else you can do.
```

Rationale: the current line reads like a debug log (no punctuation
rhythm, no next step). The rewrite confirms success in plain language and
immediately tells the reader what to do next, since pairing is the very
first thing a new user sees.

### 3. Telegram's native "/" menu descriptions

These show up in Telegram's own command-picker UI (tap "/" in the message
box) — separate from `/help`'s text, and space-constrained (Telegram
truncates around 256 chars, but the picker UI itself is only comfortable
with much shorter one-liners).

**Current** (`adapter.py:324-330`):
```python
("help", "Show available commands"),
("status", "Show connection and current task status"),
("new", "Start a new task"),
("stop", "Stop the current running task"),
("unpair", "Unpair this phone from EvoFlux"),
("actions", "Show more actions (Workflows, Projects, Scheduler)"),
```

**Proposed:**
```python
("help", "What can I do here?"),
("status", "What's my agent doing right now?"),
("new", "Set aside this task, start a new one"),
("stop", "Interrupt the agent mid-task"),
("actions", "Run a workflow, project, or schedule"),
("unpair", "Disconnect this phone"),
```

(`/settings` intentionally omitted from this list until Task 7 actually
ships it — Telegram's menu should never advertise a command that doesn't
work yet.)

## Out of scope / open question for a follow-up

The user also asked "what does type to chat with agent mean... give me an
actual command." The copy above answers this by explaining free-text
inline rather than introducing a command — free-text-first is the
existing, intentional design (confirmed by both accepted specs), and
adding e.g. `/chat <message>` as a required wrapper would be a behavior
change, not a copy fix, and would fight the "guided picker" work already
planned in Task 8. If clearer wording still isn't enough in practice,
that's worth its own brainstorming pass — flagging it here rather than
deciding it unilaterally.

## Verification

Since this is copy-only: no new tests needed beyond confirming
`_HELP_TEXT`'s existing byte-length assumptions still hold (Telegram
messages are HTML-escaped and length-limited; nothing here approaches
that limit). Manual read-through in a Telegram client to confirm line
wrapping looks right on a phone screen would be the only real check.
