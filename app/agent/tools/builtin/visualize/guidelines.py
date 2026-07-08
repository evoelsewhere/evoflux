"""Design guidelines for visualize widgets.

Lazy-loaded guidelines organized by module. Each module provides
specific design rules for different types of visualizations.

Based on Claude's generative UI design system.
"""

from typing import Literal

# Available modules
Module = Literal["interactive", "chart", "mockup", "art", "diagram", "gallery"]

AVAILABLE_MODULES: list[str] = ["interactive", "chart", "mockup", "art", "diagram", "gallery"]

# ── Core Design System ──────────────────────────────────────────────────────

CORE_GUIDELINES = """
# EvoFlux Widget Design System

## Philosophy
Widgets are inline visualizations that enhance the conversation flow.
They are NOT deliverables (use artifacts for that) — they are explanatory
tools that help users understand concepts, data, and relationships.

## Streaming-First Architecture
Widgets must be structured for progressive rendering:
1. `<style>` blocks first (short, minimal CSS)
2. HTML content (structure appears as tokens stream)
3. `<script>` blocks last (activate after content loads)

This ensures useful content appears early, even before scripts execute.

## Critical Rules
- **NO gradients, shadows, or blur** — they flash during streaming DOM diffs
- **NO `<!-- comments -->`** — waste tokens and break streaming
- **Two font weights only**: 400 (regular) and 500 (medium) — never 600 or 700
- **Sentence case everywhere** — never Title Case or ALL CAPS
- **CSS variables for all colors** — ensures dark mode compatibility
- **Dark mode is mandatory** — every color must work in both themes

## Color System
Use CSS variables for all colors:
```css
:root {
  --color-text-primary: #1a1a1a;
  --color-text-secondary: #666666;
  --color-background: #ffffff;
  --color-background-secondary: #f5f5f5;
  --color-border: #e0e0e0;
  --color-accent: #534ab7;
  --color-success: #1d9e75;
  --color-warning: #d85a30;
  --color-error: #d85a30;
}

.dark {
  --color-text-primary: #f5f5f5;
  --color-text-secondary: #a0a0a0;
  --color-background: #1a1a1a;
  --color-background-secondary: #2a2a2a;
  --color-border: #3a3a3a;
  --color-accent: #7f77dd;
  --color-success: #5dcaa5;
  --color-warning: #f0997b;
  --color-error: #f0997b;
}
```

## Typography
- Font stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- Base size: 14px
- Line height: 1.5
- Never use custom fonts unless absolutely necessary

## CDN Allowlist
Only load scripts from these CDNs:
- `cdnjs.cloudflare.com`
- `cdn.jsdelivr.net`
- `unpkg.com`
- `esm.sh`

## Widget Structure
```html
<style>
  /* Minimal CSS using variables */
  .widget { padding: 1rem; }
</style>

<div class="widget">
  <!-- HTML content -->
</div>

<script>
  // Scripts execute after content loads
</script>
```
"""

# ── Interactive Module ───────────────────────────────────────────────────────

INTERACTIVE_GUIDELINES = """
## Interactive Components

### Cards
```css
.card {
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
}
```

### Buttons
```css
.button {
  background: var(--color-accent);
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1rem;
  font-weight: 500;
  cursor: pointer;
}
.button:hover { opacity: 0.9; }
.button:active { transform: scale(0.98); }
```

### Form Elements
```css
input, select, textarea {
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 0.5rem;
  color: var(--color-text-primary);
}
```

### Sliders
```css
input[type="range"] {
  width: 100%;
  accent-color: var(--color-accent);
}
```

### Interactive Patterns
- Use `oninput` for real-time updates (sliders, text inputs)
- Use `onclick` for discrete actions (buttons, links)
- Debounce rapid updates to prevent performance issues
- Show loading states for async operations
"""

# ── Chart Module ────────────────────────────────────────────────────────────

CHART_GUIDELINES = """
## Chart.js Integration

### Setup
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

### Canvas Wrapper
```css
.chart-container {
  position: relative;
  height: 300px;
  width: 100%;
}
```

### Basic Chart
```javascript
const ctx = document.getElementById('chart').getContext('2d');
new Chart(ctx, {
  type: 'bar', // line, pie, doughnut, etc.
  data: {
    labels: ['Jan', 'Feb', 'Mar'],
    datasets: [{
      label: 'Sales',
      data: [10, 20, 30],
      backgroundColor: 'var(--color-accent)',
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false } // Build custom HTML legend
    }
  }
});
```

### Number Formatting
- Currency: `-$5M` not `$-5M`
- Percentage: `42%` not `0.42`
- Large numbers: `1.2K`, `3.4M`

### Dashboard Layout
```css
.dashboard {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}
.metric-card {
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 1rem;
  text-align: center;
}
.metric-value {
  font-size: 2rem;
  font-weight: 500;
  color: var(--color-accent);
}
.metric-label {
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}
```

### Chart Colors
Use the accent color palette:
- Primary: `var(--color-accent)`
- Secondary: `var(--color-success)`
- Tertiary: `var(--color-warning)`
- Quaternary: `var(--color-error)`

### Dark Mode
Chart.js respects CSS variables automatically when using the color system.
Ensure all colors use variables, not hardcoded values.
"""

# ── Mockup Module ───────────────────────────────────────────────────────────

MOCKUP_GUIDELINES = """
## UI Mockup Components

### Layout Patterns

#### Editorial Layout
```css
.editorial {
  max-width: 600px;
  margin: 0 auto;
  padding: 2rem;
}
.editorial h1 {
  font-size: 2rem;
  font-weight: 500;
  margin-bottom: 1rem;
}
.editorial p {
  color: var(--color-text-secondary);
  line-height: 1.6;
}
```

#### Card Grid
```css
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 1rem;
}
```

#### Sidebar Layout
```css
.sidebar-layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 1rem;
}
```

### Common Components

#### Metric Cards
```html
<div class="metric-card">
  <div class="metric-value">$12,345</div>
  <div class="metric-label">Total Revenue</div>
  <div class="metric-change positive">+12.5%</div>
</div>
```

#### Status Badges
```css
.badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
}
.badge.success { background: var(--color-success); color: white; }
.badge.warning { background: var(--color-warning); color: white; }
.badge.error { background: var(--color-error); color: white; }
```

#### Lists
```css
.list {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  overflow: hidden;
}
.list-item {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.list-item:last-child { border-bottom: none; }
```

### Skeleton Loading
```css
.skeleton {
  background: linear-gradient(
    90deg,
    var(--color-background-secondary) 25%,
    var(--color-background) 50%,
    var(--color-background-secondary) 75%
  );
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s infinite;
  border-radius: 4px;
}
@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```
"""

# ── Art Module ──────────────────────────────────────────────────────────────

ART_GUIDELINES = """
## SVG Illustration Guide

### Setup
```html
<svg viewBox="0 0 400 300" xmlns="http://www.w3.org/2000/svg">
  <!-- Content here -->
</svg>
```

### Basic Shapes
```svg
<!-- Rectangle -->
<rect x="10" y="10" width="100" height="50" fill="var(--color-accent)" rx="8"/>

<!-- Circle -->
<circle cx="50" cy="50" r="25" fill="var(--color-success)"/>

<!-- Line -->
<line x1="0" y1="0" x2="100" y2="100" stroke="var(--color-border)" stroke-width="2"/>

<!-- Path -->
<path d="M10 80 C 40 10, 65 10, 95 80 S 150 150, 180 80" stroke="var(--color-accent)" fill="none"/>
```

### Color Palette for Art
```css
.art-purple { fill: #534ab7; }
.art-teal { fill: #1d9e75; }
.art-coral { fill: #d85a30; }
.art-blue { fill: #3b82f6; }
.art-yellow { fill: #eab308; }
```

### Animation
```svg
<animate attributeName="opacity" from="0" to="1" dur="0.5s" fill="freeze"/>
<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="1s" repeatCount="indefinite"/>
```

### Illustration Patterns
- Use simple, flat shapes
- Limit color palette to 3-4 colors
- Add subtle animations for engagement
- Ensure readability at small sizes
"""

# ── Diagram Module ──────────────────────────────────────────────────────────

DIAGRAM_GUIDELINES = """
## Diagram Creation Guide

### Diagram Types

#### Flowcharts
For processes and decision trees:
```svg
<svg viewBox="0 0 600 400">
  <!-- Start -->
  <rect x="250" y="10" width="100" height="40" rx="20" fill="var(--color-accent)"/>
  <text x="300" y="35" text-anchor="middle" fill="white">Start</text>
  
  <!-- Process -->
  <rect x="225" y="80" width="150" height="50" rx="8" fill="var(--color-background)" stroke="var(--color-border)"/>
  <text x="300" y="110" text-anchor="middle" fill="var(--color-text-primary)">Process</text>
  
  <!-- Decision -->
  <polygon points="300,160 375,200 300,240 225,200" fill="var(--color-warning)"/>
  <text x="300" y="205" text-anchor="middle" fill="white">Decision?</text>
  
  <!-- Arrow -->
  <line x1="300" y1="50" x2="300" y2="80" stroke="var(--color-border)" stroke-width="2" marker-end="url(#arrowhead)"/>
</svg>
```

#### Architecture Diagrams
For system architecture and components:
```css
.component {
  background: var(--color-background);
  border: 2px solid var(--color-accent);
  border-radius: 8px;
  padding: 1rem;
  text-align: center;
}
.connector {
  stroke: var(--color-border);
  stroke-width: 2;
  fill: none;
}
```

#### Sequence Diagrams
For interaction flows:
```svg
<svg viewBox="0 0 600 300">
  <!-- Actor boxes -->
  <rect x="50" y="10" width="100" height="40" fill="var(--color-accent)"/>
  <rect x="450" y="10" width="100" height="40" fill="var(--color-success)"/>
  
  <!-- Lifelines -->
  <line x1="100" y1="50" x2="100" y2="280" stroke="var(--color-border)" stroke-dasharray="5,5"/>
  <line x1="500" y1="50" x2="500" y2="280" stroke="var(--color-border)" stroke-dasharray="5,5"/>
  
  <!-- Messages -->
  <line x1="100" y1="80" x2="500" y2="80" stroke="var(--color-text-primary)" marker-end="url(#arrowhead)"/>
  <text x="300" y="75" text-anchor="middle" fill="var(--color-text-secondary)">Request</text>
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
1. **Check arrow intersections** — arrows should not cross elements
2. **Box width from label** — calculate width based on text length
3. **Max 4 boxes per horizontal tier** — prevent overcrowding
4. **≤5 words per subtitle** — keep labels concise
5. **Use consistent spacing** — 40px vertical, 60px horizontal

### Complexity Budget
- Simple: ≤5 elements
- Medium: 6-10 elements
- Complex: 11-15 elements (split into multiple diagrams)
"""

# ── Widget Gallery ──────────────────────────────────────────────────────────

WIDGET_GALLERY = """
## Widget Gallery — Common Patterns

### 1. Metric Dashboard
```html
<style>
  .dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; padding: 1rem; }
  .metric { background: var(--color-background); border: 1px solid var(--color-border); border-radius: 8px; padding: 1rem; text-align: center; }
  .metric-value { font-size: 1.5rem; font-weight: 500; color: var(--color-accent); }
  .metric-label { color: var(--color-text-secondary); font-size: 0.875rem; margin-top: 0.25rem; }
  .metric-change { font-size: 0.75rem; margin-top: 0.5rem; }
  .metric-change.positive { color: var(--color-success); }
  .metric-change.negative { color: var(--color-error); }
</style>

<div class="dashboard">
  <div class="metric">
    <div class="metric-value">$12,345</div>
    <div class="metric-label">Revenue</div>
    <div class="metric-change positive">+12.5%</div>
  </div>
  <div class="metric">
    <div class="metric-value">1,234</div>
    <div class="metric-label">Users</div>
    <div class="metric-change positive">+8.2%</div>
  </div>
  <div class="metric">
    <div class="metric-value">89%</div>
    <div class="metric-label">Retention</div>
    <div class="metric-change negative">-2.1%</div>
  </div>
</div>
```

### 2. Interactive Slider
```html
<style>
  .slider-demo { padding: 1.5rem; }
  .slider-demo label { display: block; margin-bottom: 0.5rem; color: var(--color-text-secondary); }
  .slider-demo input[type="range"] { width: 100%; accent-color: var(--color-accent); }
  .slider-demo .value { font-size: 1.5rem; font-weight: 500; color: var(--color-accent); margin-top: 0.5rem; }
</style>

<div class="slider-demo">
  <label>Adjust compound interest rate</label>
  <input type="range" min="1" max="20" value="5" oninput="document.getElementById('rate-value').textContent = this.value + '%'">
  <div class="value" id="rate-value">5%</div>
</div>
```

### 3. Status Timeline
```html
<style>
  .timeline { padding: 1rem; }
  .timeline-item { display: flex; gap: 1rem; padding: 0.75rem 0; border-left: 2px solid var(--color-border); margin-left: 0.5rem; padding-left: 1.5rem; position: relative; }
  .timeline-item::before { content: ''; position: absolute; left: -6px; top: 1rem; width: 10px; height: 10px; border-radius: 50%; background: var(--color-accent); }
  .timeline-item.success::before { background: var(--color-success); }
  .timeline-item.warning::before { background: var(--color-warning); }
  .timeline-item.error::before { background: var(--color-error); }
  .timeline-content { flex: 1; }
  .timeline-title { font-weight: 500; margin-bottom: 0.25rem; }
  .timeline-time { font-size: 0.75rem; color: var(--color-text-muted); }
</style>

<div class="timeline">
  <div class="timeline-item success">
    <div class="timeline-content">
      <div class="timeline-title">Deployment completed</div>
      <div class="timeline-time">2 minutes ago</div>
    </div>
  </div>
  <div class="timeline-item">
    <div class="timeline-content">
      <div class="timeline-title">Tests passing</div>
      <div class="timeline-time">5 minutes ago</div>
    </div>
  </div>
  <div class="timeline-item warning">
    <div class="timeline-content">
      <div class="timeline-title">Build warnings</div>
      <div class="timeline-time">10 minutes ago</div>
    </div>
  </div>
</div>
```

### 4. Code Diff Viewer
```html
<style>
  .diff-viewer { font-family: monospace; font-size: 12px; padding: 1rem; background: var(--color-background); border: 1px solid var(--color-border); border-radius: 8px; overflow-x: auto; }
  .diff-line { padding: 0.25rem 0.5rem; white-space: pre; }
  .diff-line.added { background: rgba(29, 158, 117, 0.2); color: var(--color-success); }
  .diff-line.removed { background: rgba(216, 90, 48, 0.2); color: var(--color-error); }
  .diff-line.context { color: var(--color-text-muted); }
</style>

<div class="diff-viewer">
  <div class="diff-line context">@@ -10,6 +10,8 @@</div>
  <div class="diff-line context"> function calculateTotal(items) {</div>
  <div class="diff-line removed">-  return items.reduce((a, b) => a + b, 0);</div>
  <div class="diff-line added">+  const sum = items.reduce((a, b) => a + b, 0);</div>
  <div class="diff-line added">+  return sum * 1.1; // Apply 10% tax</div>
  <div class="diff-line context"> }</div>
</div>
```

### 5. Interactive Form
```html
<style>
  .form-demo { padding: 1.5rem; max-width: 400px; }
  .form-group { margin-bottom: 1rem; }
  .form-group label { display: block; margin-bottom: 0.5rem; color: var(--color-text-secondary); font-size: 0.875rem; }
  .form-group input, .form-group select { width: 100%; padding: 0.5rem; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-background); color: var(--color-text-primary); }
  .form-group input:focus, .form-group select:focus { outline: none; border-color: var(--color-accent); }
  .form-actions { display: flex; gap: 0.5rem; margin-top: 1.5rem; }
  .btn { padding: 0.5rem 1rem; border-radius: 6px; font-weight: 500; cursor: pointer; border: none; }
  .btn-primary { background: var(--color-accent); color: white; }
  .btn-secondary { background: var(--color-background-secondary); color: var(--color-text-primary); border: 1px solid var(--color-border); }
</style>

<div class="form-demo">
  <div class="form-group">
    <label>Email</label>
    <input type="email" placeholder="you@example.com">
  </div>
  <div class="form-group">
    <label>Role</label>
    <select>
      <option>Developer</option>
      <option>Designer</option>
      <option>Manager</option>
    </select>
  </div>
  <div class="form-actions">
    <button class="btn btn-primary">Save</button>
    <button class="btn btn-secondary">Cancel</button>
  </div>
</div>
```

### 6. Progress Indicator
```html
<style>
  .progress-demo { padding: 1.5rem; }
  .progress-bar { height: 8px; background: var(--color-background-secondary); border-radius: 4px; overflow: hidden; margin-bottom: 0.5rem; }
  .progress-fill { height: 100%; background: var(--color-accent); transition: width 0.3s ease; }
  .progress-label { display: flex; justify-content: space-between; font-size: 0.875rem; color: var(--color-text-secondary); }
</style>

<div class="progress-demo">
  <div class="progress-bar">
    <div class="progress-fill" style="width: 65%"></div>
  </div>
  <div class="progress-label">
    <span>65% complete</span>
    <span>13/20 tasks</span>
  </div>
</div>
```
"""

# ── Guidelines Registry ─────────────────────────────────────────────────────

MODULE_SECTIONS: dict[str, list[str]] = {
    "interactive": [INTERACTIVE_GUIDELINES],
    "chart": [CHART_GUIDELINES],
    "mockup": [MOCKUP_GUIDELINES],
    "art": [ART_GUIDELINES],
    "diagram": [DIAGRAM_GUIDELINES],
    "gallery": [WIDGET_GALLERY],
}


def get_guidelines(modules: list[str]) -> str:
    """Return combined design guidelines for requested modules.
    
    Args:
        modules: List of module names (interactive, chart, mockup, art, diagram)
        
    Returns:
        Combined guidelines text with core + module-specific sections
    """
    content = CORE_GUIDELINES
    seen: set[str] = set()
    
    for mod in modules:
        if mod not in MODULE_SECTIONS:
            continue
        for section in MODULE_SECTIONS[mod]:
            if section not in seen:
                seen.add(section)
                content += "\n\n" + section
    
    return content


# ── Widget Gallery ──────────────────────────────────────────────────────────

WIDGET_GALLERY = """
## Widget Gallery — Common Patterns

### 1. Metric Dashboard
```html
<style>
  .dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; padding: 1rem; }
  .metric { background: var(--color-background); border: 1px solid var(--color-border); border-radius: 8px; padding: 1rem; text-align: center; }
  .metric-value { font-size: 1.5rem; font-weight: 500; color: var(--color-accent); }
  .metric-label { color: var(--color-text-secondary); font-size: 0.875rem; margin-top: 0.25rem; }
  .metric-change { font-size: 0.75rem; margin-top: 0.5rem; }
  .metric-change.positive { color: var(--color-success); }
  .metric-change.negative { color: var(--color-error); }
</style>

<div class="dashboard">
  <div class="metric">
    <div class="metric-value">$12,345</div>
    <div class="metric-label">Revenue</div>
    <div class="metric-change positive">+12.5%</div>
  </div>
  <div class="metric">
    <div class="metric-value">1,234</div>
    <div class="metric-label">Users</div>
    <div class="metric-change positive">+8.2%</div>
  </div>
  <div class="metric">
    <div class="metric-value">89%</div>
    <div class="metric-label">Retention</div>
    <div class="metric-change negative">-2.1%</div>
  </div>
</div>
```

### 2. Interactive Slider
```html
<style>
  .slider-demo { padding: 1.5rem; }
  .slider-demo label { display: block; margin-bottom: 0.5rem; color: var(--color-text-secondary); }
  .slider-demo input[type="range"] { width: 100%; accent-color: var(--color-accent); }
  .slider-demo .value { font-size: 1.5rem; font-weight: 500; color: var(--color-accent); margin-top: 0.5rem; }
</style>

<div class="slider-demo">
  <label>Adjust compound interest rate</label>
  <input type="range" min="1" max="20" value="5" oninput="document.getElementById('rate-value').textContent = this.value + '%'">
  <div class="value" id="rate-value">5%</div>
</div>
```

### 3. Status Timeline
```html
<style>
  .timeline { padding: 1rem; }
  .timeline-item { display: flex; gap: 1rem; padding: 0.75rem 0; border-left: 2px solid var(--color-border); margin-left: 0.5rem; padding-left: 1.5rem; position: relative; }
  .timeline-item::before { content: ''; position: absolute; left: -6px; top: 1rem; width: 10px; height: 10px; border-radius: 50%; background: var(--color-accent); }
  .timeline-item.success::before { background: var(--color-success); }
  .timeline-item.warning::before { background: var(--color-warning); }
  .timeline-item.error::before { background: var(--color-error); }
  .timeline-content { flex: 1; }
  .timeline-title { font-weight: 500; margin-bottom: 0.25rem; }
  .timeline-time { font-size: 0.75rem; color: var(--color-text-muted); }
</style>

<div class="timeline">
  <div class="timeline-item success">
    <div class="timeline-content">
      <div class="timeline-title">Deployment completed</div>
      <div class="timeline-time">2 minutes ago</div>
    </div>
  </div>
  <div class="timeline-item">
    <div class="timeline-content">
      <div class="timeline-title">Tests passing</div>
      <div class="timeline-time">5 minutes ago</div>
    </div>
  </div>
  <div class="timeline-item warning">
    <div class="timeline-content">
      <div class="timeline-title">Build warnings</div>
      <div class="timeline-time">10 minutes ago</div>
    </div>
  </div>
</div>
```

### 4. Code Diff Viewer
```html
<style>
  .diff-viewer { font-family: monospace; font-size: 12px; padding: 1rem; background: var(--color-background); border: 1px solid var(--color-border); border-radius: 8px; overflow-x: auto; }
  .diff-line { padding: 0.25rem 0.5rem; white-space: pre; }
  .diff-line.added { background: rgba(29, 158, 117, 0.2); color: var(--color-success); }
  .diff-line.removed { background: rgba(216, 90, 48, 0.2); color: var(--color-error); }
  .diff-line.context { color: var(--color-text-muted); }
</style>

<div class="diff-viewer">
  <div class="diff-line context">@@ -10,6 +10,8 @@</div>
  <div class="diff-line context"> function calculateTotal(items) {</div>
  <div class="diff-line removed">-  return items.reduce((a, b) => a + b, 0);</div>
  <div class="diff-line added">+  const sum = items.reduce((a, b) => a + b, 0);</div>
  <div class="diff-line added">+  return sum * 1.1; // Apply 10% tax</div>
  <div class="diff-line context"> }</div>
</div>
```

### 5. Interactive Form
```html
<style>
  .form-demo { padding: 1.5rem; max-width: 400px; }
  .form-group { margin-bottom: 1rem; }
  .form-group label { display: block; margin-bottom: 0.5rem; color: var(--color-text-secondary); font-size: 0.875rem; }
  .form-group input, .form-group select { width: 100%; padding: 0.5rem; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-background); color: var(--color-text-primary); }
  .form-group input:focus, .form-group select:focus { outline: none; border-color: var(--color-accent); }
  .form-actions { display: flex; gap: 0.5rem; margin-top: 1.5rem; }
  .btn { padding: 0.5rem 1rem; border-radius: 6px; font-weight: 500; cursor: pointer; border: none; }
  .btn-primary { background: var(--color-accent); color: white; }
  .btn-secondary { background: var(--color-background-secondary); color: var(--color-text-primary); border: 1px solid var(--color-border); }
</style>

<div class="form-demo">
  <div class="form-group">
    <label>Email</label>
    <input type="email" placeholder="you@example.com">
  </div>
  <div class="form-group">
    <label>Role</label>
    <select>
      <option>Developer</option>
      <option>Designer</option>
      <option>Manager</option>
    </select>
  </div>
  <div class="form-actions">
    <button class="btn btn-primary">Save</button>
    <button class="btn btn-secondary">Cancel</button>
  </div>
</div>
```

### 6. Progress Indicator
```html
<style>
  .progress-demo { padding: 1.5rem; }
  .progress-bar { height: 8px; background: var(--color-background-secondary); border-radius: 4px; overflow: hidden; margin-bottom: 0.5rem; }
  .progress-fill { height: 100%; background: var(--color-accent); transition: width 0.3s ease; }
  .progress-label { display: flex; justify-content: space-between; font-size: 0.875rem; color: var(--color-text-secondary); }
</style>

<div class="progress-demo">
  <div class="progress-bar">
    <div class="progress-fill" style="width: 65%"></div>
  </div>
  <div class="progress-label">
    <span>65% complete</span>
    <span>13/20 tasks</span>
  </div>
</div>
```
"""
