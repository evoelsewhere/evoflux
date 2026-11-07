# README screenshots

Regenerates the images at the top of the repository README:
`docs/assets/readme/app-{light,dark}.png` (the app with sample data) and
`docs/assets/readme/banner-{light,dark}.png` (the banner that shows them).

The sample data lives only here. The desktop app always talks to a real
`evo-engine`; these scripts load its UI in a separate Chromium with a fake
Tauri IPC instead of opening the app.

| File | What it does |
| --- | --- |
| `mock-tauri.js` | Fake Tauri IPC and engine: two workspaces, a few chats, and one chat replayed from canned messages (grep, read, edit with a diff, `cargo test`). |
| `mock-fs.js` | A small fake repository for the Files tool: `crates/evo-web/src/fetch.rs` with its committed version for the git gutter. |
| `capture_app.py` | Opens the UI, unfolds the turn, opens `fetch.rs` and saves `app-light.png` / `app-dark.png`. |
| `render_banner.py` | Renders `docs/assets/readme/banner.html` to `banner-light.png` / `banner-dark.png`. |

## Requirements

- Python 3.12+ with [Playwright](https://playwright.dev/python/) and its
  Chromium (`python -m playwright install chromium`)
- The desktop app's Vite dev server: `bun run dev` in `apps/desktop`
  (port 1420)
- Internet access for Geist from Google Fonts in the banner

## Run

```sh
python scripts/readme-shots/capture_app.py
python scripts/readme-shots/render_banner.py
```

`capture_app.py` prints any IPC command the fake answered with `null`. When the
UI starts calling a new command and the capture looks wrong, add a handler for
it in `mock-tauri.js` (or `mock-fs.js` for files and git).

To change what the chat shows, edit `MESSAGES` in `mock-tauri.js`; the edited
file's contents are in `mock-fs.js`. To change the banner text or layout, edit
`banner.html` and run `render_banner.py` only.
