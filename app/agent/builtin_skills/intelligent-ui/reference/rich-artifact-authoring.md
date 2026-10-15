# Rich artifact authoring

## Contents

- [Dashboards and evidence](#dashboards-and-evidence)
- [Workbench HTML and theme](#workbench-html-and-theme)
- [Identity and saving](#identity-and-saving)

## Dashboards and evidence

Read or query the dashboard's data before building it. Cite successful source
tool calls in `sources` with their `tool_call_id` and a short `query_summary`;
the runtime validates each reference against active history. With no successful
source, label the dashboard illustrative in its visible content. Do not invent
retrieval timestamps. “Refresh with agent” starts a new chat turn; it does not
run a background refresh.

## Workbench HTML and theme

Dashboard HTML must be self-contained and stay within the tool's 200 KB source
limit. It runs in an isolated frame without same-origin, network, storage, or
privileged browser access. Use EvoFlux theme tokens and respect the reduced
motion value exposed by the frame. Include a visible title and concise summary.

Use `scene3d` only for a spatial view that benefits from inspection. Describe
the scene with supported declarative primitives; do not include scripts, URLs,
shaders, or remote assets. Keep labels meaningful so the static fallback still
explains the model.

## Identity and saving

Reuse a stable `artifact_id` when revising a Workbench artifact so the existing
view updates in place. The artifact opens in Workbench and remains in session
history. Do not write its source into a project just to display it; save or
download only when the user asks.
