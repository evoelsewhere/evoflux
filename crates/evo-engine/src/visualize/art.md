
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
