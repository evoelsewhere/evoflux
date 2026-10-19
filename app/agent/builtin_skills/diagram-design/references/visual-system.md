# Visual system and quality

## EvoFlux rendering contract

For an inline Work widget, call visualize_read_me(modules=["diagram"]) before show_widget. The widget accepts an HTML fragment, not a full HTML document. Put style before the content, then render the SVG. WidgetRenderer copies the current EvoFlux theme into the isolated iframe; use the actual app tokens so light/dark mode and the user's accent preference carry through:

- Surfaces: `--bg-page`, `--bg-card`, `--bg-key`, `--bg-muted`
- Text: `--color-text`, `--color-text-2`, `--color-text-muted`, `--color-text-on-accent`
- Lines: `--color-border`, `--color-border-strong`
- Emphasis: `--color-accent`, `--color-accent-soft`
- Optional status colors: `--accent-blue`, `--accent-green`, `--accent-amber`, `--accent-red`

Prefer these direct tokens over guessed aliases such as `--color-background` or `--color-text-primary`. The selected app accent is the diagram's editorial accent: reserve it for the primary route or up to two focal nodes. Use status colors only where their meaning applies. If a token is absent, fall back to `currentColor` or a neutral token instead of a hardcoded theme palette.

## Hierarchy and polish

- Make the headline relationship visible on first scan. Give the entry point, main path, exception path, and terminal state distinct visual weight where the diagram semantics support them.
- Use a compact eyebrow or section label, a clear title, one focal treatment, and short supporting labels. Omit ornamental chrome that competes with the data.
- Vary shape by role (actor, process, store, boundary, decision, outcome); do not put every item in an identical rounded card. Use thin borders and subtle surface steps from the theme tokens to create depth without shadows.
- Use sentence case and at most 400/500 font weights to match the existing widget design system. Avoid gradients, shadows, blur, remote fonts, scripts, and remote images.
- Design to the actual widget width. Keep labels inside their boxes with padding; enlarge or reflow the box when text does not fit. Do not shrink type to force a layout. Let a narrow-screen widget scroll locally rather than clip or scale down the entire drawing.

## Layout

- Put the key relationship in the first scan path; remove decoration that does not explain it.
- Keep node count near nine and connectors near twelve. Split a larger system into an overview and focused detail.
- Align origins, widths, gaps, and padding to a 4-pixel grid where practical.
- Before coding, assign each node a non-overlapping bounding box and reserve label/arrowhead clearance. Expand the SVG viewBox to contain every shape, stroke, label, marker, and legend; include stroke width in edge clearance.
- Mark node rectangles with a semantic checker class (`node`, `state`, `entity`, `participant`, `actor`, or `er-box`) and orthogonal connector paths with `class="edge"` (or `er-edge` for crow-foot relations). This lets the pre-render geometry check inspect the layout.
- Use clear hierarchy for system, process, store, external actor, and trust boundary.
- Route connections orthogonally. Keep arrow labels short and clear of lines and nodes. Give parallel connections distinct routes and attachment points.
- End directed connectors at the target node boundary, with the arrowhead fully visible outside the node fill. Never let a connector enter the node interior or hide its arrowhead under a node drawn later; route return paths around node outlines.
- Before drawing connectors, note each node's bounding box. Route every edge from a source boundary to a target boundary, checking the complete path against every other node box. Leave visible clearance between arrowheads and node fills; labels must not cover a node or another edge.
- Draw connector strokes first and nodes/labels afterward only when the path is already verified; painter's order must never conceal a wrong endpoint or a path through a box.
- Keep text readable at the rendered size. On narrow screens, let the diagram scroll inside its own container instead of shrinking labels or clipping the page.

## Accessible SVG

Every informative SVG needs role="img", an aria-labelledby that resolves to unique IDs, and a first-child title followed by a meaningful one-sentence desc. Use semantic labels for relationships; do not rely on color alone. Keep decorative shapes hidden from assistive technology.

## Final review

Before returning the diagram, check that:

- the selected type matches the relationship, and prose or a table would not do as well;
- every displayed component and edge is supported by the source or marked as an assumption;
- there is a clear focal point and no unnecessary node, connector, label, or legend;
- connectors, labels, and nodes do not overlap or clip;
- sibling node bounding boxes have a deliberate gap, text fits within each node with padding, and every visible element (including marker tips and strokes) sits inside the viewBox;
- every connector endpoint touches the correct target boundary, its marker tip remains visible, and the path avoids every non-endpoint node;
- the app theme tokens are the actual EvoFlux tokens above, so the user-selected light/dark appearance and accent remain visible;
- the diagram has one clear focal point and enough visual variation to distinguish roles without becoming a generic grid of cards;
- every directed edge has a visible arrowhead at the correct target boundary and its route does not pass through a node;
- the SVG accessibility names resolve and the theme tokens are used;
- any redraw omissions or merges are reported.

For a saved HTML/SVG file in a repository checkout, run `uv run python scripts/check_diagram_layout.py path/to/diagram.html`. The checker's geometry coverage is intentionally conservative: it verifies explicit rectangular node classes and absolute orthogonal `M`/`L`/`H`/`V` connector paths. Read every warning; unsupported/curved paths still need a visual or manual geometry check. Inline Work widgets receive the same preflight through `show_widget` before rendering.

The visual principles are distilled from [Diagram Design](https://github.com/cathrynlavery/diagram-design) at commit [550fd66](https://github.com/cathrynlavery/diagram-design/tree/550fd66edff058bc73056c3416b76d69cfe865ba), especially its style-guide.md, primitives-core.md, layout-budget.md, semantic-patterns.md, output-spec.md, and architecture/sequence/state references. EvoFlux-specific CSS, theme, and widget rules take precedence.
