# Notifications — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | desktop UI, desktop shell |
| Created | 2026-11-06 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Agent tools for working with the person](../agent-tools/spec.md) (the agent's `notify` tool) |

## 1. Summary

The desktop app tells the person that something happened through one
pipeline. Every notification is kept in a notification center (the bell in
the title bar) and is also delivered on one channel chosen from where the
person is: a toast when they are in the app, an OS notification when they
are elsewhere. Do not disturb and muted sources silence the channels but
never the bell, so nothing is lost. Features use this pipeline instead of
building their own toasts, badges or OS notifications.

## 2. Scope

### 2.1 Goals

- One way for every feature to raise a notification.
- Every notification is kept in the bell, across restarts.
- The channel follows the person: toast when the app is focused, OS
  notification when it is not.
- Do not disturb and per-source mutes quiet the app without losing anything.
- A click on a notification goes where the person can act on it.
- Repeating events show as one entry with the latest state.

### 2.2 Non-goals

- Per-feature notification systems (toasts, badges or OS notifications built
  outside this pipeline).
- Notifying about things the person just did or can already see.

## 3. User scenarios

### US-1 Learn about an outcome while away (priority P1)

A person who switched to another app wants to know when a run finishes or
the agent needs their approval, so that they come back at the right time.

Acceptance scenarios:

1. **Given** the window is not focused, **when** a run finishes, **then** an
   OS notification appears and a click on the bell row opens that chat.
2. **Given** the window is not focused, **when** the agent asks for
   approval, **then** a warning notification appears and the bell row opens
   that chat.
3. **Given** the window is focused, **when** something worth notifying
   happens, **then** a toast appears at the bottom right instead of an OS
   notification.

### US-2 Review what happened (priority P1)

A person wants to see everything the app reported, read or unread, so that
they miss nothing.

Acceptance scenarios:

1. **Given** several notifications, **when** the person opens the bell,
   **then** they see them under All and Unread, and can mark all read or
   clear them.
2. **Given** an event that repeats with the same key, **when** it fires
   again, **then** the bell shows one entry, unread again, with the latest
   state.

### US-3 Quiet the app (priority P2)

A person wants to work without interruptions, so that they can focus.

Acceptance scenarios:

1. **Given** Do not disturb is on, **when** a notification is raised,
   **then** no toast and no OS notification appear, and the bell still
   records it.

### Edge cases

- A notification points to a chat that was deleted: the click opens the
  chat only if it still exists.
- Clicking an OS notification brings the app forward but does not yet open
  the target; the notification waits in the bell, unread.
- The first OS notification triggers the OS permission request; Windows
  grants it by default, macOS asks once.

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | A feature raises a notification through one shared entry point with a source, a level (`info`, `success`, `warning`, `error`; default `info`), a title, and optionally a body, a target and a key, and gets the new notification's id back. | Given a feature calls the entry point, when it returns, then an id is returned and the notification is in the bell. |
| FR-2 | Every notification is recorded in the notification center and kept across restarts (newest 200). | Given 201 notifications, when the app restarts, then the bell shows the newest 200. |
| FR-3 | A notification is delivered on one channel: a toast when the window is focused (unless the caller turned toasts off), an OS notification when it is not (unless the caller turned OS notifications off). | Given the window is unfocused, when a notification is raised, then an OS notification appears and no toast. |
| FR-4 | Do not disturb and muted sources silence both channels; the bell still records the notification. | Given Do not disturb is on, when a notification is raised, then it is in the bell and nothing else shows. |
| FR-5 | A quiet notification is recorded in the bell already read, with no toast and no OS notification. | Given a quiet notification, when it is raised, then the bell shows it as read and no channel fires. |
| FR-6 | A notification with the same key as an earlier one replaces it and is unread again. | Given a read notification with key K, when a new one with key K is raised, then the bell has one entry for K, unread, with the new content. |
| FR-7 | The level sets the icon and the toast duration: errors stay 10 s, warnings 8 s, others 5 s. | Given an error toast, when it shows, then it stays 10 s. |
| FR-8 | Clicking a toast or a bell row goes to the notification's target: open a chat (if it still exists), open a side panel tool, open Settings on a section, or open a link in the browser. | Given a notification targeting a chat, when it is clicked, then that chat opens. |
| FR-9 | The bell shows All / Unread, unread state, mark all read, clear, and the Do not disturb switch. | Manual check in the running app. |
| FR-10 | Toasts show at the bottom right, at most 3 at a time, and pause while hovered. | Given 4 toasts at once, when they show, then 3 are visible; hovering one keeps it open. |
| FR-11 | The app notifies when a run finishes while the window is unfocused (success, opens the chat), when the agent asks for approval while unfocused (warning, opens the chat), when the engine process stops (error, Settings › Engine) and when the engine fails to start (error, Settings › Engine). | Given the window is unfocused, when a run finishes, then a success notification targets that chat. |
| FR-12 | The OS notification permission is asked the first time an OS notification is sent, not at startup. | Given a fresh install, when the app starts, then no permission prompt appears until the first OS notification. |
| FR-13 | Settings › Notifications lists the sources and lets the person mute each one. | Given a source is muted there, when it raises a notification, then only the bell records it. |
| FR-14 | Notifications can carry actions (buttons such as **Approve** on the toast itself). | Given an approval notification, when the person clicks **Approve** on the toast, then the approval is given. |
| FR-15 | The dock / taskbar shows a badge with the unread count. | Given 3 unread notifications, when the person looks at the dock or taskbar, then the badge shows 3. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | OS notifications work on Windows, macOS and Linux; the browser preview uses the web Notification API. | Manual check on each platform and in the browser preview. |

## 5. Success criteria

- SC-1 A person away from the app learns that a run finished or needs them
  without checking the app.
- SC-2 Nothing raised is lost: every notification, including those raised
  during Do not disturb, can be found in the bell.
- SC-3 An event that repeats shows as one entry in the bell, not a pile of
  duplicates.

## 6. Clarifications

### 6.1 Open

n/a — no open questions.

### 6.2 Resolved

n/a — the original design records no decisions as questions.

## 7. History

- 2026-11-06 — Implemented; documented in the legacy single-file format.
- 2026-11-07 — Moved to the spec / plan / tasks format.
