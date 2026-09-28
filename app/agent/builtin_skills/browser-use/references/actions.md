# browser_use actions

## Contents

- Calling the tool
- Targets
- Observe
- Navigate and wait
- Interact
- Tabs
- Debug
- Viewport and output
- Permissions and clipboard
- How WebBridge runs each action

## Calling the tool

One call takes `actions`, an ordered list; each item has an `action` and its
fields. Results come back in the same order, separated by `---`. In the
in-app browser a failed action is reported and the next one still runs;
through WebBridge the call stops at the first failure and says how many
actions were not run. Either way, read every result line.

```json
{"actions": [
  {"action": "navigate", "url": "https://example.com/login"},
  {"action": "wait", "selector": "form"},
  {"action": "find", "query": "Email"}
]}
```

## Targets

Element actions take one of:

| Field | Meaning |
|---|---|
| `ref` | Handle from `snapshot`, `find` or `query` (`ref_12` in-app, `e12` through WebBridge). Stays bound to the same element while it is on the page. Prefer it. |
| `selector` | A CSS selector. Use when you know the markup. |
| `index` | Position in the last listing. In-app only, invalidated by the next listing; avoid. |

## Observe

| Action | Fields | Returns |
|---|---|---|
| `status` | — | whether a browser is connected, and its tabs |
| `snapshot` | `max_chars` | interactive elements with refs, labels and values |
| `find` | `query`, `limit`, `include_hidden` | elements whose role, name or label contains the text |
| `query` | `selector`, `limit`, `include_hidden` | elements matching a CSS selector (in-app only) |
| `extract` | `selector`, `attribute`, `max_chars` | page or element text |
| `html` | target, `outer`, `max_chars` | an element's HTML |
| `accessibility` | `include_hidden`, `max_chars` | the accessibility tree |
| `inspect` | target, `styles` | box, computed styles and attributes of one element |
| `screenshot` | target, `full_page` | an image; element targets are in-app only |
| `page_assets` | `limit` | images, scripts and styles the page loaded (in-app only) |

## Navigate and wait

| Action | Fields | Notes |
|---|---|---|
| `navigate` | `url` | `http://` and `https://` only |
| `back`, `forward`, `reload` | — | |
| `wait` | one of `selector` (+ `state`: attached, detached, visible, hidden), `text`, `url_contains`, `load_state` (loading, interactive, complete); `seconds` is the timeout, or the pause when nothing else is given | wait for what the next step needs |
| `scroll` | `direction` (up, down), `pixels` | |
| `scroll_into_view` | target, `block` | in-app only |

## Interact

| Action | Fields | Notes |
|---|---|---|
| `click` | target | |
| `click_at` | `x`, `y`, `button`, `coordinate_space` (screenshot, css) | screenshot coordinates are mapped to the page |
| `dblclick` | target | in-app only |
| `hover`, `focus` | target | |
| `fill` | target, `text`, `clear` | replaces the value and fires input events |
| `type` | target, `text` | appends with key events |
| `clear` | target | empties a field |
| `press` | target (optional), `key` (`Enter`, `Tab`, `Meta+K`) | |
| `select` | target, `value` | native `<select>`; value or visible label |
| `set_checked` | target, `checked` | |
| `set_files` | target, `paths` | workspace-relative files; needs file uploads allowed in Settings → Browser |
| `drag` | target, `target_ref` or `target_selector` | |
| `submit` | target | submits the element's form (in-app only) |
| `dispatch_event` | target, `event`, `detail` | in-app only |

## Tabs

| Action | Fields | Notes |
|---|---|---|
| `new_tab` | `url` | the chat works in the new tab |
| `get_tabs` | — | open tabs with their positions |
| `switch_tab` | `index` | the chat works in that tab |
| `close_tab` | `index` | close only tabs you opened |
| `start`, `stop` | — | open or close the in-app browser surface |

## Debug

| Action | Fields | Returns |
|---|---|---|
| `debug_summary` | `console_limit`, `network_limit` | console errors and warnings plus failed requests, in one call |
| `console` | `level`, `contains`, `limit` | console messages |
| `network` | `filter` (all, failed), `url_contains`, `method`, `limit` | requests |
| `performance` | `include_resources`, `limit` | load timing and resource costs |
| `storage` | `area`, `operation`, `key`, `value` | local or session storage (policy-gated) |
| `cookies` | `operation`, `include_values`, `name`, … | cookies; values are policy-gated |
| `evaluate` | `script`, `await_promise`, `timeout_ms` | run JavaScript in the page (policy-gated) |
| `http` | `method`, `url`, `headers`, `body` | a request from the page's origin (in-app only) |
| `dialogs`, `dialog_behavior` | `clear`; `behavior`, `prompt_text` | JavaScript alerts; `dialog_behavior` is in-app only |
| `popups`, `clear_logs` | — | in-app only |

Use `evaluate` to read state no other action exposes, not to click, type or
submit on the user's behalf behind the page's own controls.

## Viewport and output

| Action | Fields | Notes |
|---|---|---|
| `resize` | `preset` (mobile, tablet, desktop) or `width` + `height`, `color_scheme`, `device_scale_factor`, `mobile`, `touch`, `orientation` | responsive checks |
| `reset_viewport` | — | back to the window size |
| `zoom` | `percent` | in-app only |
| `print` | — | in-app only; opens the print dialog |
| `save_pdf` | `filename` | in-app only; the PDF is saved under `downloads/` |
| `download` | `url`, `filename` | in-app only; saved under `downloads/` in the workspace |

## Permissions and clipboard

In-app only. `permission_requests` lists what pages asked for (camera,
location, notifications); `resolve_permission` with `allow: false` denies
one, and allowing needs the Settings switch for agent permission accept —
otherwise the user decides in the Browser panel. `clipboard_read` and
`clipboard_write` follow the clipboard switches in Settings → Browser; do not
use the clipboard unless the task is about it.

## How WebBridge runs each action

Through WebBridge each action is rewritten for the extension before any of
them runs; one that cannot be rewritten fails the call with nothing done.

| browser_use | Runs as |
|---|---|
| `navigate` (first in the chat) | a new tab at the URL, then a wait for its load |
| `click` | `click_selector` on the ref or selector |
| `click_at` | a click at the point |
| `fill`, `clear` | `fill` with the text (empty for `clear`) |
| `type`, `press` with a target | `focus` on it, then `type` or `key` |
| `select` | `select_option` with that value |
| `set_files` | `upload_file` |
| `wait` | `wait_for_selector`, `wait_for_text`, `wait_for_url`, `wait_for_load` or a pause |
| `find`, `accessibility` | a full `snapshot` |
| `html` | `extract` as HTML |
| `new_tab` | `open_tab`, which becomes the chat's tab |
| `start`, `stop` | `status` |

Everything else in the "in-app only" notes above is refused through
WebBridge, with a message naming what to use instead.
