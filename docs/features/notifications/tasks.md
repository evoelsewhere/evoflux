# Notifications — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

### Phase 1 — One pipeline

Done when: a feature calls `notify()` and the notification lands in the bell
and on the right channel, with Do not disturb, mutes, keys and targets
working.

- [x] T1 [FR-2, FR-4, FR-5, FR-6] Notification store: records, unread state, toasts on screen, Do not disturb, muted sources, key replacement, persisted as `evo.notifications` (newest 200) — `apps/desktop/src/stores/notification-store.ts` — check: manual check in the running app
- [x] T2 [FR-1, FR-3, FR-4, FR-5] `notify()`, `windowFocused()` and the channel choice — `apps/desktop/src/features/notifications/notify.ts` — check: manual check in the running app, focused and unfocused
- [x] T3 [P] [FR-9] The bell and its popover (All / Unread, mark all read, clear, Do not disturb) — `apps/desktop/src/features/notifications/notification-center.tsx` — check: manual check in the running app
- [x] T4 [P] [FR-7, FR-10] In-app toaster (max 3 visible, pause on hover, duration by level), mounted in the app — `apps/desktop/src/features/notifications/toaster.tsx`, `apps/desktop/src/app/app.tsx` — check: manual check in the running app
- [x] T5 [P] [FR-7] Level icons and relative time — `apps/desktop/src/features/notifications/notification-icon.tsx` — check: manual check in the running app
- [x] T6 [P] [FR-8] Click targets (`session`, `panel`, `settings`, `url`) — `apps/desktop/src/features/notifications/open-target.ts` — check: manual check, one click per target type
- [x] T7 [FR-3, FR-12, NFR-1] OS notifications through `tauri-plugin-notification`, permission `notification:default`, permission asked on first send, web Notification API in the browser preview — `apps/desktop/src-tauri/Cargo.toml`, `apps/desktop/src-tauri/capabilities/default.json`, `apps/desktop/src/features/notifications/notify.ts` — check: manual check on Windows, macOS, Linux and `bun run dev`

### Phase 2 — Built-in notifications

Done when: finished runs and approvals notify while the window is
unfocused, and engine stops and start failures notify with a target.

- [x] T8 [FR-11] Agent and engine notifications (`notifyFromEngine`, `onExit`, `start`) — `apps/desktop/src/stores/engine-store.ts` — check: manual check in the running app with the window unfocused

### Phase 3 — Not built yet

Done when: mutes have a settings UI, toasts can carry actions, and the dock
or taskbar shows the unread count.

- [ ] T9 [FR-13] Settings › Notifications section that lists sources and toggles their mute through `setSourceMuted()` — `apps/desktop/src/features/settings/` — check: manual check, a muted source only reaches the bell
- [ ] T10 [FR-14] Notification actions (buttons such as **Approve** on the toast) — `apps/desktop/src/features/notifications/` — check: manual check in the running app
- [ ] T11 [FR-15] Dock / taskbar badge with the unread count — `apps/desktop/src-tauri`, `apps/desktop/src/stores/notification-store.ts` — check: manual check on each platform

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | Manual check: a feature's `notify()` call returns an id and the bell shows the notification | not run |
| FR-2 | Manual check: the bell keeps the newest 200 across an app restart | not run |
| FR-3 | Manual check: toast when focused, OS notification when unfocused, each off with `toast: false` / `system: false` | not run |
| FR-4 | Manual check: Do not disturb and a muted source silence both channels; the bell records | not run |
| FR-5 | Manual check: a `quiet` notification is recorded as read with no channel | not run |
| FR-6 | Manual check: a repeated `key` replaces the entry and marks it unread | not run |
| FR-7 | Manual check: icons per level; toasts stay 10 s / 8 s / 5 s | not run |
| FR-8 | Manual check: each target type opens the right place | not run |
| FR-9 | Manual check: bell popover All / Unread, mark all read, clear, Do not disturb | not run |
| FR-10 | Manual check: at most 3 toasts, hover pauses | not run |
| FR-11 | Manual check: finished run and approval while unfocused; engine stop and start failure | not run |
| FR-12 | Manual check: no permission prompt at startup; prompt on the first OS notification (macOS) | not run |
| FR-13 | Not built (T9) | not run |
| FR-14 | Not built (T10) | not run |
| FR-15 | Not built (T11) | not run |
| NFR-1 | Manual check on Windows, macOS, Linux and the browser preview | not run |
