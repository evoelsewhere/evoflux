# Notifications — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [9. Cross-cutting concepts](../../architecture/README.md#9-cross-cutting-concepts) |
| ADRs | none |

## 1. Context and constraints

The pipeline lives in the desktop webview (`apps/desktop/src/`) with OS
notifications from the Tauri shell through `tauri-plugin-notification`.
Read this before adding a toast, a badge or an OS notification anywhere in
the app — there is one pipeline, and features should not build their own.

Platform constraints:

- **OS permission** is requested the first time an OS notification is sent,
  not at startup. Windows grants it by default; macOS asks once.
- **Windows** groups notifications under the app's identifier
  (`com.evoelsewhere.evo`); in a debug build they may show as coming from
  PowerShell until the app is installed.
- **Clicking an OS notification** brings the app forward but cannot run the
  target: the plugin has no click callback on desktop.
- In the **browser preview** (`bun run dev`), OS notifications use the web
  Notification API.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | The shell only provides OS notifications (a native feature); the webview decides what to notify about from engine events. |
| Layers point down; library crates stay free of engine/desktop concerns | n/a | No crate changes. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | n/a | No protocol change. |
| Models come from models.dev; no hardcoded model facts | n/a | No model data. |
| Real engine in the app; settings and credentials reload live | n/a | No engine settings; the store's state applies at once. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | Bodies are plain text (no markdown); notifications only point at places in the app or a link. See 3.7. |
| Desktop UI structure and `DESIGN.md` | ok | Features call `notify()`; components read the notification store through selectors. |

## 3. Design

### 3.1 Overview

Every notification is a record (`AppNotification`) in one store. It always
lands in the notification center and, on top of that, is delivered on one
channel chosen from where the user is:

| User is…                     | Channel                                     | Unless           |
| ---------------------------- | ------------------------------------------- | ---------------- |
| in the app (window focused)  | **toast**, bottom right                     | `toast: false`   |
| elsewhere (window unfocused) | **OS notification** (Windows, macOS, Linux) | `system: false`  |

```text
feature ──notify()──► notification store ──► bell (always, persisted)
                         │
                         ├─ focused & not muted   ──► toast
                         └─ unfocused & not muted ──► OS notification
```

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| desktop UI | `apps/desktop/src/features/notifications/notify.ts` | `notify()`, `windowFocused()`, channel choice, OS notifications | FR-1, FR-3, FR-4, FR-5, FR-12, NFR-1 |
| desktop UI | `apps/desktop/src/stores/notification-store.ts` | records, unread state, toasts on screen, Do not disturb, muted sources (persisted as `evo.notifications`, newest 200); `NotificationTarget` | FR-2, FR-4, FR-6, FR-13 |
| desktop UI | `apps/desktop/src/features/notifications/notification-center.tsx` | the bell and its popover (All / Unread, mark all read, clear, Do not disturb) | FR-9 |
| desktop UI | `apps/desktop/src/features/notifications/toaster.tsx` | in-app toasts (max 3 visible, pause on hover), mounted in `apps/desktop/src/app/app.tsx` | FR-7, FR-10 |
| desktop UI | `apps/desktop/src/features/notifications/open-target.ts` | what a click does (`openNotification()`) | FR-8 |
| desktop UI | `apps/desktop/src/features/notifications/notification-icon.tsx` | level icons, relative time | FR-7 |
| desktop UI | `apps/desktop/src/stores/engine-store.ts` (`notifyFromEngine`, `onExit`, `start`) | the built-in agent and engine notifications | FR-11 |
| desktop shell | `apps/desktop/src-tauri` — `tauri-plugin-notification` | OS notifications; permission `notification:default` in `apps/desktop/src-tauri/capabilities/default.json` | FR-3, FR-12, NFR-1 |

### 3.3 Interfaces

`notify()` is a plain function: call it from stores, event handlers or
effects — no hook, no provider needed. It returns the new notification's id.

```ts
import { notify } from "@/features/notifications/notify";

notify({
  source: "scheduler",            // required: who raised it
  level: "success",               // info | success | warning | error (default info)
  title: "Nightly tests finished",
  body: "42 passed, 0 failed",    // optional, keep it to a line or two
  target: { type: "panel", id: "scheduler" }, // optional: where a click goes
  key: "scheduler:nightly-tests", // optional: replace the previous one with this key
});
```

Options:

| Option   | Default | Use |
| -------- | ------- | --- |
| `source` | —       | The feature's id (`engine`, `agent`, `scheduler`, `plugins`, …). Shown in the bell; mutes go by it. |
| `level`  | `info`  | Icon and toast duration (errors stay 10 s, warnings 8 s, others 5 s). |
| `title`  | —       | Short and specific: "Reply ready", "Approval needed", not "Notification". |
| `body`   | —       | One or two lines of detail. |
| `target` | —       | Where clicking it (toast or bell row) goes. See below. |
| `key`    | —       | Dedupe: a new notification with the same key replaces the old one (and is unread again). Use it for anything that can repeat — a status, a job, a chat. |
| `toast`  | `true`  | `false` when the user is already looking at the result in the app. |
| `system` | `true`  | `false` for things not worth pulling the user back for. |
| `quiet`  | `false` | Record it in the bell, already read, with no toast or OS notification — a log entry. |

`windowFocused()` (exported next to `notify`) tells whether the user is
looking at the app.

Targets are plain data (they are persisted), handled in
`features/notifications/open-target.ts`:

| `target`                          | Click does |
| --------------------------------- | ---------- |
| `{ type: "session", id }`         | opens that chat (if it still exists) |
| `{ type: "panel", id: PanelId }`  | opens that side panel tool |
| `{ type: "settings", section? }`  | opens Settings on that section |
| `{ type: "url", href }`           | opens the link in the browser |

To add a kind of target, extend `NotificationTarget` in
`stores/notification-store.ts` and handle it in `openNotification()`.

Rules for callers:

- **Notify about outcomes the user would otherwise miss**: a run finished
  while they were away, something needs their decision, something broke. Do
  not notify about things they just did or can already see.
- **Check focus when it matters** with `windowFocused()`. The engine only
  notifies about finished runs and approvals when the window is *not*
  focused — focused, the thread already shows them.
- **Always use a `key` for repeating events** so the bell shows the latest
  state instead of a pile of duplicates.
- **Errors get a target** that helps fix them (Settings › Engine, a log, a
  docs URL).
- Titles are sentence case, no trailing period; bodies are plain text (no
  markdown).

### 3.4 Data and storage

The notification store is persisted under the key `evo.notifications` and
keeps the newest 200 records (`AppNotification`), with their read state, the
Do not disturb flag and `mutedSources`. Toasts on screen are in-memory only.

### 3.5 Behaviour

`notify()` adds the record to the store, then picks one channel: a toast if
the window is focused, an OS notification if not, each unless turned off by
the caller. `quiet`, Do not disturb and a muted source skip both channels.

Built-in notifications:

| Source   | When                                         | Level   | Target            |
| -------- | -------------------------------------------- | ------- | ----------------- |
| `agent`  | a run finishes while the window is unfocused | success | the chat          |
| `agent`  | the agent asks for approval while unfocused  | warning | the chat          |
| `engine` | the engine process stops                     | error   | Settings › Engine |
| `engine` | the engine fails to start                    | error   | Settings › Engine |

### 3.6 Errors and edge cases

- An OS notification click only brings the app forward (no click callback on
  desktop); the notification stays in the bell, unread, for the user to
  open.
- A `session` target opens the chat only if it still exists (3.3).
- In a Windows debug build OS notifications may show as coming from
  PowerShell until the app is installed.

### 3.7 Security and trust

Notifications run no tools and hold no credentials. Titles and bodies are
shown as plain text (no markdown), and targets only open a chat, a panel,
Settings or a link in the browser. The agent's `notify` tool goes through
this pipeline, with its own rate limit (see
[agent tools](../agent-tools/plan.md)). OS notifications need the
`notification:default` capability.

### 3.8 Configuration

| Setting | Type | Default | Stored | Edited in |
| --- | --- | --- | --- | --- |
| Do not disturb | boolean | off | notification store (`evo.notifications`) | the bell's menu |
| Muted sources | list of source ids | empty | notification store (`mutedSources`, `setSourceMuted()`) | no UI yet (planned: Settings › Notifications) |

Both apply at once.

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| Each feature builds its own toasts, badges or OS notifications | There is one pipeline; features should not build their own. |

## 5. As-built notes

- Clicking an OS notification does not yet run the target (no click
  callback in the plugin on desktop).
- Per-source mutes exist in the store (`mutedSources`, `setSourceMuted()`)
  but have no UI yet.
- Checked against the code on 2026-11-07: `engine-store.ts` has no function
  named `notifyFromEngine`; the agent and engine notifications are `notify()`
  calls in its event handling, `onExit` and `start`. The "engine stopped"
  notification there targets the chat (not Settings › Engine) and is raised
  for the active chat or a busy run. Other features (scheduler, providers,
  code intelligence, shell) also call `notify()`.
