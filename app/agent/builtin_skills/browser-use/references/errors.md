# Errors and refusals

## Contents

- Reading an error
- Browser not available
- Finding elements
- Pages and waiting
- Policy refusals
- WebBridge

## Reading an error

Each failed action returns `Error (action): reason`. Through WebBridge the
call then stops and says how many actions were not run; in the in-app
browser the next actions still ran, so read their results too before
deciding what to redo. Never repeat a step before checking what the page
shows now: a timed-out click or submit may have gone through.

## Browser not available

| Message | Next step |
|---|---|
| `EvoFlux in-app browser is unavailable for this chat` | The chat is not open in EvoFlux Desktop. Say so; the user can open the task there or switch WebBridge on. |
| `The browser panel has no page yet: still opening the page` | The panel is still starting. `wait` a few seconds, then retry the same step once. |
| `Timed out creating browser WebView`, `Browser is not ready` | `start`, `wait`, then retry once; if it fails again, report it. |
| `No browser extension connected` | WebBridge lost its extension; the next call runs in the in-app browser. Tell the user if the task needs their browser. |

## Finding elements

| Message | Next step |
|---|---|
| `No element matches "…"` | Shorten the text to a distinctive fragment of the visible label, or `snapshot` and read the labels. |
| `No element matches selector …` | `snapshot` to see what is on the page; prefer a ref. |
| `Unknown ref`, or a ref that is no longer attached | The page changed. `snapshot` or `find` again and use the new ref. |
| `index targets only exist in the in-app browser` | Take a `snapshot` and use the element's ref. |
| A click result naming another element as covering the target | Close the covering banner or dialog with its own button, then retry. |

## Pages and waiting

| Message | Next step |
|---|---|
| `Timeout waiting for browser condition …` | The page is slower or different than expected. `snapshot` to see what it shows, then wait for something that is actually coming. |
| `Browser navigation did not commit` | The URL did not load: check it, `status`, and try `reload` once. |
| An empty `extract` or snapshot | The content has not rendered yet or lives in a frame; `wait` for it, then read again. |
| `Invalid tab index` | `get_tabs` and use a listed position. |

## Policy refusals

These are the user's settings. Report them; do not work around them.

| Message | Meaning |
|---|---|
| `… is disabled in Settings → Browser.` | JavaScript evaluate, storage, HTTP, clipboard, uploads or downloads are switched off for agents. |
| `Domain '…' is blocked in Settings → Browser.` / `… not in the built-in browser allowlist.` | The in-app browser's domain policy forbids that site. |
| `Agent browser navigation only allows http:// and https:// URLs.` | Use a web URL; local files are opened another way. |
| `Agent permission acceptance is disabled` | The user decides the page's permission prompt in the Browser panel. |
| `Domain '…' is blocked by WebBridge policy.` | The WebBridge domain policy forbids that site in the user's browser. |
| `… disabled by policy (webbridge.allow_evaluate=false)` | Script and full storage or cookie access are off for WebBridge; use DOM actions. |
| `Browser screenshots are disabled by WebBridge sharing policy.` | Read the page with `snapshot` and `extract` instead. |

## WebBridge

| Message | Next step |
|---|---|
| `not available while WebBridge is on — …` | The action is in-app only; use the alternative in [webbridge.md](webbridge.md). Nothing in the call was run. |
| `element screenshots only exist in the in-app browser` | Scroll the element into view and take a viewport screenshot, or `inspect` it. |
| `no browser tab to work in` | `navigate` to a URL to open the chat's tab. |
| `Human control is active for this tab` | The user is using the tab. Stop, say what you were about to do, wait for them. |
| `Bound browser tab expired` / `changed page scope` | The side panel's binding ended; ask the user to open the chat from the side panel again, or continue in a new tab with `navigate`. |
| `WebBridge is turned off for agent browsing` | From the `webbridge` tool: the user switched WebBridge off. Continue with `browser_use`, which now runs in the in-app browser. |
