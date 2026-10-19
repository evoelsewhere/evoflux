## Contents

- Choose by relationship
- Common software diagram types
- Semantic patterns
- Keep or redraw

## Choose by relationship

Choose the type that carries the main claim. If a 3-column table or short explanation conveys the same thing, use that.

| What the reader needs to see | Diagram type |
|---|---|
| Components, boundaries, and connections at one point in time | Architecture |
| Requests or events moving between actors in time order | Sequence |
| State changes, guards, retries, waits, or terminal outcomes | State machine |
| Decisions and alternative paths | Flowchart |
| Owners or teams handing work across stages | Swimlane or process |
| Data entities, fields, and relations | ER diagram |
| Source-to-transform-to-consumer movement | Data flow |
| Runtime zones, hosts, processes, and deployed artifacts | Deployment |
| Changes between two system topologies | Before/after architecture |
| Events in chronological order | Timeline |
| Quantities split and recombined | Sankey |
| Ranked stages or conversion drop-off | Funnel |
| Two measures used to position items | Quadrant |
| Rows and columns where cell value is the message | Heatmap |
| User actions, visible service steps, and hidden operations | Service blueprint |

Use one visual grammar per diagram. If two types seem useful, select the one that best explains the main relationship; split into overview and detail when the combined drawing becomes dense.

## Semantic patterns

When behavior or risk is the point, choose the semantic pattern before its layout:

| Context | Pattern to make explicit |
|---|---|
| One request crosses trust zones | Trust boundaries and allowed paths |
| Retries, waits, cancellation, and terminal outcomes | Lifecycle phases |
| Similar stages repeat question/input/governance/output fields | Repeated stage framework |
| Two policy traces must be compared | Paired pass/fail traces and first divergence |
| Input becomes a durable artifact through several steps | Unstructured input to structured artifact |
| A hierarchy needs stable IDs and traceability | Block decomposition tree |

## Keep or redraw

- Keep Mermaid when the diagram is short, source-controlled, and expected to change with code.
- Use an EvoFlux widget for a one-off explanation whose layout and visual hierarchy materially improve understanding.
- Redraw Mermaid, draw.io, or Excalidraw only when asked to improve or transform it. Preserve its semantics, not its coordinates or renderer quirks.
- For an import, decide audience, output size, and detail level first. Keep a short change ledger of anything merged, collapsed, or omitted.
- When the source comes from a repository, distinguish observed code from inferred intent in the labels or accompanying explanation.
