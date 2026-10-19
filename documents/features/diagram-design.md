# Diagram design

The built-in diagram-design Skill helps agents draw or redraw diagrams when a reader benefits from a purposeful visual layout. Its description is included in the normal Skill catalog on each run, so matching requests can load its instructions and focused references without a new router or always-loaded diagram prompt.

In Work, the Skill uses the existing visualize_read_me diagram module and show_widget HTML-fragment renderer. WidgetRenderer copies the active EvoFlux surface, text, border, accent, semantic-color, and font tokens into its isolated iframe, and syncs them when app appearance changes. This keeps inline diagrams aligned with the user's light/dark and accent preferences.

The Skill plans node bounds and connector routes before writing SVG. Before streaming a widget, `show_widget` checks explicit rectangular nodes, label fit, absolute orthogonal connector endpoints/routes, overlaps, and viewBox bounds. It returns geometry errors without rendering so the agent can correct the SVG and try again. Paths outside the checker’s supported geometry are returned as warnings for manual review. For saved files, run `uv run python scripts/check_diagram_layout.py path/to/diagram.html`. The first successful render is still a preview: correct visible contrast, spacing, clipping, or alignment issues before calling the diagram finished. Accessible SVG labels remain required. Short diagrams maintained alongside code can stay Mermaid. Coding agents can produce a project HTML/SVG file when the user asks for one.

The Skill distills type selection, semantic patterns, sparse focal emphasis, orthogonal connectors, and complexity limits from cathrynlavery/diagram-design. It includes a small EvoFlux-ready SVG widget fragment and does not vendor the upstream gallery, icon library, fonts, or conversion scripts.

Primary code: app/agent/builtin_skills/diagram-design/, app/agent/skills/registry.py, app/agent/hooks/skills.py, app/agent/tools/builtin/visualize/read_me.py, app/agent/tools/builtin/visualize/show_widget.py.

Research and source/licensing notes: [Diagram Design integration research](../research/diagram-design-evoflux-integration-2026-10-19.md).
