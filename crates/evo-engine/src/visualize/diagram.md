
## Diagram Creation Guide

### Diagram Types

#### Flowcharts
For processes and decision trees:
```svg
<svg viewBox="0 0 600 400">
  <!-- Start -->
  <rect class="node" x="250" y="10" width="100" height="40" rx="20" fill="var(--color-accent)"/>
  <text class="node-label" x="300" y="35" text-anchor="middle" fill="var(--color-text-on-accent)">Start</text>
  
  <!-- Process -->
  <rect class="node" x="225" y="80" width="150" height="50" rx="8" fill="var(--bg-card)" stroke="var(--color-border)"/>
  <text class="node-label" x="300" y="110" text-anchor="middle" fill="var(--color-text)">Process</text>
  
  <!-- Decision -->
  <polygon points="300,160 375,200 300,240 225,200" fill="var(--accent-amber)"/>
  <text x="300" y="205" text-anchor="middle" fill="var(--color-text-on-accent)">Decision?</text>
  
  <!-- Arrow -->
  <path class="edge" d="M300 50 V80" stroke="var(--color-text-muted)" stroke-width="1.5" marker-end="url(#arrowhead)"/>
</svg>
```

#### Architecture Diagrams
For system architecture and components:
```css
.component {
  fill: var(--bg-card);
  stroke: var(--color-border);
  stroke-width: 1;
  text-align: center;
}
.connector {
  stroke: var(--color-text-muted);
  stroke-width: 1.5;
  fill: none;
}
```

#### Sequence Diagrams
For interaction flows:
```svg
<svg viewBox="0 0 600 300">
  <!-- Actor boxes -->
  <rect class="node" x="50" y="10" width="100" height="40" fill="var(--bg-card)" stroke="var(--color-border)"/>
  <rect class="node" x="450" y="10" width="100" height="40" fill="var(--bg-card)" stroke="var(--color-border)"/>
  
  <!-- Lifelines -->
  <line x1="100" y1="50" x2="100" y2="280" stroke="var(--color-border)" stroke-dasharray="5,5"/>
  <line x1="500" y1="50" x2="500" y2="280" stroke="var(--color-border)" stroke-dasharray="5,5"/>
  
  <!-- Messages -->
  <path class="edge" d="M150 80 H450" stroke="var(--color-text-muted)" marker-end="url(#arrowhead)"/>
  <text class="edge-label" x="300" y="70" text-anchor="middle" fill="var(--color-text-2)">Request</text>
</svg>
```

### Arrow Markers
```svg
<defs>
  <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
    <polygon points="0 0, 10 3.5, 0 7" fill="var(--color-border)"/>
  </marker>
</defs>
```

### Diagram Rules
1. **Plan boxes first** — set each node's x/y/width/height and keep sibling nodes separated; include padding for the longest label.
2. **Route and check edges** — use orthogonal `path.edge` routes from the source boundary to the facing target boundary; avoid every non-endpoint box and keep labels clear.
3. **Fit the viewBox** — include node strokes, labels, arrowheads, and legends; a node or label outside it is a layout error.
4. **Add hierarchy** — distinguish roles by shape and surface; reserve the app accent for the focal path or one/two key nodes instead of tinting every box.
5. **Use app tokens** — prefer `--bg-page`, `--bg-card`, `--color-text`, `--color-text-2`, `--color-text-muted`, `--color-border`, and `--color-accent` so light/dark and accent preferences carry through.
6. **Run the render loop** — `show_widget` rejects detected geometry errors before rendering. Fix its returned diagnostics and retry; after a successful render, inspect the preview for visual issues that a geometry check cannot see.

### Complexity Budget
- Simple: ≤5 elements
- Medium: 6-10 elements
- Dense diagrams — simplify or split when labels and paths no longer have clear room.
