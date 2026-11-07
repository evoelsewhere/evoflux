
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
