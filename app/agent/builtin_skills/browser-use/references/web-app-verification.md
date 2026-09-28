# Verifying a web app you are building

## Contents

- The loop
- Starting the server
- What to check on every pass
- Responsive and theme checks
- When the page is blank or stale
- What counts as done

## The loop

After every change to a web app:

1. `preview` `start` (with the configuration `name` when there are several).
   It reuses a server already listening on the port and ends with the URL to
   open.
2. `browser_use` `navigate` to that URL (or the route you changed), `wait`
   for the element the change is about, then `snapshot`.
3. `debug_summary`: console errors and warnings plus failed requests.
4. Read back the change itself: the text, the element's values, its box and
   styles with `inspect`, the behaviour by clicking through it.
5. Change the code, `reload`, and repeat from step 2 until the read-back
   matches and `debug_summary` shows nothing new.
6. End with a `screenshot` as visual proof of the final state.

The same loop works in either browser. Through WebBridge the page opens in
the chat's own tab of the user's browser, which also has the user's
extensions; the in-app browser is a clean profile.

## Starting the server

- `preview` reads `.evoflux/launch.json` (or `.claude/launch.json`) at the
  workspace root. When neither exists, write one with a configuration per
  server: `name`, `runtimeExecutable`, `runtimeArgs`, `port`, and optionally
  `cwd`, `env`, `dependsOn`, `reuseExisting`, `startupTimeoutSeconds`.
- A frontend that needs a backend names it in `dependsOn`; starting the
  frontend starts the backend first.
- `preview` `logs` (with `search` for a word such as `error`) shows the
  server's output when the page does not load or a request fails.
- `preview` `status` lists what is running; `stop` stops a server you
  started when the task is over.

## What to check on every pass

- **Console**: errors and warnings that appeared with your change. An error
  you did not cause is still worth naming in the report.
- **Network**: failed requests (status 4xx/5xx, blocked, aborted) and
  requests that should have happened but did not. `network` with
  `url_contains` narrows to one API.
- **The change**: read the page's own values, not a screenshot, for text,
  field values and states; `inspect` for layout and computed styles.
- **Neighbours**: what the change could have broken around it (the rest of
  the form, the list above, the navigation).
- **Interaction**: click through the flow you changed, including the error
  path (an empty field, a failed save), and read back after each step.

## Responsive and theme checks

- `resize` with `preset` (`mobile`, `tablet`, `desktop`) or an exact `width`
  and `height`; `color_scheme` checks dark and light. Read back layout with
  `inspect` (box, overflow) and a `screenshot` per size.
- `reset_viewport` when done, so the user's view is not left resized.

## When the page is blank or stale

- `debug_summary` first: a build error, a failing module or a crashed render
  usually shows there.
- `preview` `logs` for the server's own errors (compile failures, a port
  already in use, a crashed process).
- A page that does not show a change: `reload`; if it still does not, the
  server may not have rebuilt — check its logs — or the change is in a file
  the page does not use.
- A request to the backend failing with a connection error: the backend
  configuration is not running; `preview` `start` it.

## What counts as done

The page shows the change, the read-back matches what you wrote down before
starting, `debug_summary` reports no new errors or failed requests, and a
final screenshot shows the result. Report each of these, and anything you
could not check.
