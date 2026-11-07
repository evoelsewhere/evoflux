
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
