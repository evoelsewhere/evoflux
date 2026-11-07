
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
