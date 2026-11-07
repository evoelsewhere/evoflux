
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
