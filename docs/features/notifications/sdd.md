# Notifications

How the desktop app tells the user that something happened, and how a feature
plugs into it. Read this before adding a toast, a badge or an OS notification
anywhere in the app — there is one pipeline, and features should not build
their own.

File paths below are relative to `apps/desktop/`.

## The model

Every notification is a record (`AppNotification`) in one store. It always
lands in the **notification center** — the bell in the title bar — and on top
of that it is delivered on **one channel**, chosen from where the user is:

| User is…                     | Channel                                  | Unless             |
| ---------------------------- | ---------------------------------------- | ------------------ |
| in the app (window focused)  | **toast**, bottom right                  | `toast: false`     |
| elsewhere (window unfocused) | **OS notification** (Windows, macOS, Linux) | `system: false` |

**Do not disturb** (the bell's menu) and **muted sources** silence both
channels. The bell still collects everything, so nothing is lost.

```
feature ──notify()──► notification store ──► bell (always, persisted)
                         │
                         ├─ focused & not muted   ──► toast
                         └─ unfocused & not muted ──► OS notification
```

## Using it from a feature

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

`notify()` returns the new notification's id. It is a plain function: call it
from stores, event handlers or effects — no hook, no provider needed.

### Options

| Option   | Default | Use                                                                                     |
| -------- | ------- | --------------------------------------------------------------------------------------- |
| `source` | —       | The feature's id (`engine`, `agent`, `scheduler`, `plugins`, …). Shown in the bell; mutes go by it. |
| `level`  | `info`  | Icon and toast duration (errors stay 10 s, warnings 8 s, others 5 s).                    |
| `title`  | —       | Short and specific: "Reply ready", "Approval needed", not "Notification".              |
| `body`   | —       | One or two lines of detail.                                                             |
| `target` | —       | Where clicking it (toast or bell row) goes. See below.                                  |
| `key`    | —       | Dedupe: a new notification with the same key replaces the old one (and is unread again). Use it for anything that can repeat — a status, a job, a chat. |
| `toast`  | `true`  | `false` when the user is already looking at the result in the app.                      |
| `system` | `true`  | `false` for things not worth pulling the user back for.                                 |
| `quiet`  | `false` | Record it in the bell, already read, with no toast or OS notification — a log entry.   |

### Targets

A target is plain data (it is persisted), handled in
`features/notifications/open-target.ts`:

| `target`                                   | Click does                         |
| ------------------------------------------ | ---------------------------------- |
| `{ type: "session", id }`                  | opens that chat (if it still exists) |
| `{ type: "panel", id: PanelId }`           | opens that side panel tool         |
| `{ type: "settings", section? }`           | opens Settings on that section     |
| `{ type: "url", href }`                    | opens the link in the browser      |

To add a kind of target, extend `NotificationTarget` in
`stores/notification-store.ts` and handle it in `openNotification()`.

## Guidelines

- **Notify about outcomes the user would otherwise miss**: a run finished while
  they were away, something needs their decision, something broke. Do not
  notify about things they just did or can already see.
- **Check focus when it matters.** `windowFocused()` (exported next to
  `notify`) tells you whether the user is looking at the app. The engine only
  notifies about finished runs and approvals when it is *not* focused — focused,
  the thread already shows them.
- **Always use a `key` for repeating events** so the bell shows the latest state
  instead of a pile of duplicates.
- **Errors get a target** that helps fix them (Settings › Engine, a log, a docs URL).
- Titles are sentence case, no trailing period; bodies are plain text (no markdown).

## Built in today

| Source   | When                                           | Level   | Target                |
| -------- | ---------------------------------------------- | ------- | --------------------- |
| `agent`  | a run finishes while the window is unfocused   | success | the chat              |
| `agent`  | the agent asks for approval while unfocused    | warning | the chat              |
| `engine` | the engine process stops                       | error   | Settings › Engine     |
| `engine` | the engine fails to start                      | error   | Settings › Engine     |

These live in `stores/engine-store.ts` (`notifyFromEngine`, `onExit`, `start`).

## Where things are

| File                                                   | Role                                                         |
| ------------------------------------------------------ | ------------------------------------------------------------ |
| `src/features/notifications/notify.ts`                 | `notify()`, `windowFocused()`, channel choice, OS notifications |
| `src/stores/notification-store.ts`                     | records, unread state, toasts on screen, Do not disturb, muted sources (persisted as `evo.notifications`, newest 200) |
| `src/features/notifications/notification-center.tsx`   | the bell and its popover (All / Unread, mark all read, clear, Do not disturb) |
| `src/features/notifications/toaster.tsx`               | in-app toasts (max 3 visible, pause on hover), mounted in `app/app.tsx` |
| `src/features/notifications/open-target.ts`            | what a click does                                            |
| `src/features/notifications/notification-icon.tsx`    | level icons, relative time                                   |
| `src-tauri` — `tauri-plugin-notification`              | OS notifications; permission `notification:default` in `capabilities/default.json` |

## Platform notes

- **OS permission** is requested the first time an OS notification is sent, not
  at startup. Windows grants it by default; macOS asks once.
- **Windows** groups notifications under the app's identifier
  (`com.evoelsewhere.evo`); in a debug build they may show as coming from
  PowerShell until the app is installed.
- **Clicking an OS notification** brings the app forward but does not yet run
  the target (the plugin has no click callback on desktop). The notification is
  in the bell, unread, for the user to open.
- In the **browser preview** (`bun run dev`), OS notifications use the web
  Notification API.

## Not built yet

- Per-source mute UI. The store has `mutedSources` and `setSourceMuted()`; a
  Settings › Notifications section should list sources and toggle them.
- Notification actions (buttons such as "Approve" on the toast itself).
- A dock / taskbar badge with the unread count.
