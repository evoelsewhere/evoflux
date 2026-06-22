# Arc Browser Design System

A comprehensive guide to building interfaces aligned with Arc Browser's minimalist, keyboard-first design philosophy. This system emphasizes calm, distraction-free design with vertical organization, ample whitespace, and context-aware customization.

---

## Table of Contents

1. [Overview](#overview)
2. [Color System](#color-system)
3. [Typography](#typography)
4. [Spacing & Layout](#spacing--layout)
5. [Components](#components)
6. [Elevation & Shadows](#elevation--shadows)
7. [Animations & Transitions](#animations--transitions)
8. [Accessibility](#accessibility)
9. [Dark Mode](#dark-mode)
10. [Code Examples](#code-examples)

---

## Overview

### Design Philosophy

Arc Browser represents a fundamental reimagining of browser UI, departing from 15+ years of tab-based conventions. The design system prioritizes:

- **Minimalism**: Aggressive whitespace, reduced chrome, content-first
- **Calm UI**: Soft corners, muted colors, distraction-free browsing
- **Keyboard-First**: Power users drive design; shortcuts and commands matter
- **Vertical Organization**: Sidebar replaces horizontal tabs for scalability
- **Context Awareness**: Spaces separate work/personal/project contexts
- **Gestalt Principles**: Figure-ground contrast between browser chrome and content

### Core Principles

| Principle | Application |
|-----------|---|
| **Figure-Ground** | Browser controls are "background"; web content is "foreground" |
| **Whitespace** | Breathing room between elements; 16-24px gaps standard |
| **Consistency** | Predictable spacing scale, type hierarchy, interaction patterns |
| **Accessibility** | Always visible focus states, high contrast, keyboard navigation |
| **Customization** | Users can inject CSS/JS (Boosts), create Spaces, organize tabs |

---

## Color System

### Light Mode Palette

#### Surface & Background Colors

```
Primary Background:     #FAFAFA
Surface 1:              #F5F5F5
Surface 2:              #EEEEEE
Surface Hover:          #E8E8E8
Border/Subtle:          #E4E5F1
```

#### Text Colors

```
Text Primary:           #1D1D1D
Text Secondary:         #717171
Text Disabled:          #717171 @ 50% opacity
```

#### Space Gradient Colors

```
Work Space:             #667EEA → #764BA2 (Purple)
Personal Space:         #F093FB → #F5576C (Pink)
Project Space:          #4FACFE → #00F2FE (Cyan)
```

### Dark Mode Palette

#### Surface & Background Colors

```
Primary Background:     #1a1a1a
Surface 1:              #383C4A
Surface 2:              #404552
Surface Hover:          #4a4f5d
Border/Subtle:          #4b5162
```

#### Text Colors

```
Text Primary:           #FFFFFF
Text Secondary:         #9394A5
Text Disabled:          #9394A5 @ 50% opacity
```

### Color Usage Guidelines

| Color | Usage |
|-------|-------|
| **Primary Background** | Page background, main container |
| **Surface 1** | Cards, panels, neutral containers |
| **Surface 2** | Hover states, secondary containers, input backgrounds |
| **Text Primary** | Headlines, body text, primary information |
| **Text Secondary** | Descriptions, metadata, timestamps, hints |
| **Space Gradients** | Tab indicators, Space switcher dots, accent elements |
| **Border/Subtle** | Dividers, input borders, subtle separations |

### Implementation

**CSS Variables (Light Mode)**:
```css
:root[data-theme="light"] {
  --color-bg-primary: #FAFAFA;
  --color-surface-1: #F5F5F5;
  --color-surface-2: #EEEEEE;
  --color-surface-hover: #E8E8E8;
  --color-border: #E4E5F1;
  
  --color-text-primary: #1D1D1D;
  --color-text-secondary: #717171;
  
  --color-gradient-work: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  --color-gradient-personal: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  --color-gradient-project: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
}
```

**CSS Variables (Dark Mode)**:
```css
:root[data-theme="dark"] {
  --color-bg-primary: #1a1a1a;
  --color-surface-1: #383C4A;
  --color-surface-2: #404552;
  --color-surface-hover: #4a4f5d;
  --color-border: #4b5162;
  
  --color-text-primary: #FFFFFF;
  --color-text-secondary: #9394A5;
  
  --color-gradient-work: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  --color-gradient-personal: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  --color-gradient-project: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
}
```

### Contrast Requirements

All text must meet **WCAG AA minimum** (4.5:1 contrast ratio):

- Light mode: #1D1D1D text on #FAFAFA = **11.6:1** ✓ (Excellent)
- Dark mode: #FFFFFF text on #1a1a1a = **16:1** ✓ (Maximum)
- Secondary text: #717171 on #FAFAFA = **7.3:1** ✓ (Accessible)

---

## Typography

### Font Stack

**Recommended System Font**:
```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif;
```

**For Code/Monospace**:
```css
font-family: "SF Mono", Monaco, "Cascadia Code", monospace;
```

**For Serif Accents** (Optional branding):
```css
font-family: "Georgia", "Times New Roman", serif;
```

### Type Scale

| Level | Size | Weight | Line Height | Use Case |
|-------|------|--------|-------------|----------|
| **Display** | 28px | 600 | 1.2 | Large headings, page titles |
| **Heading 1** | 24px | 600 | 1.2 | Section titles, modal titles |
| **Heading 2** | 20px | 600 | 1.3 | Subsection titles |
| **Heading 3** | 18px | 600 | 1.4 | Component titles |
| **Body** | 16px | 400 | 1.5 | Primary content text |
| **Body Small** | 14px | 400 | 1.5 | Tab titles, labels |
| **Caption** | 13px | 400 | 1.5 | Secondary descriptions |
| **Label** | 12px | 500 | 1.4 | Form labels, hints |
| **Tiny** | 11px | 400 | 1.4 | Metadata, timestamps |

### Font Weights

```css
--font-weight-regular: 400;
--font-weight-medium: 500;
--font-weight-semibold: 600;
--font-weight-bold: 700;
```

### Usage Examples

```css
/* Heading Hierarchy */
h1 { font: 600 24px / 1.2 var(--font-stack); }
h2 { font: 600 20px / 1.3 var(--font-stack); }
h3 { font: 600 18px / 1.4 var(--font-stack); }
h4 { font: 600 16px / 1.5 var(--font-stack); }
h5 { font: 500 14px / 1.5 var(--font-stack); }
h6 { font: 500 13px / 1.5 var(--font-stack); }

/* Body Text */
body { font: 400 16px / 1.5 var(--font-stack); color: var(--color-text-primary); }

/* Secondary Text */
.text-secondary { font: 400 14px / 1.5 var(--font-stack); color: var(--color-text-secondary); }

/* Labels */
label { font: 500 12px / 1.4 var(--font-stack); text-transform: uppercase; letter-spacing: 0.5px; }

/* Code */
code { font: 400 14px / 1.5 "SF Mono", monospace; background: var(--color-surface-2); padding: 0 4px; border-radius: 2px; }
```

---

## Spacing & Layout

### Spacing Scale

Arc uses a **4px base unit** for consistent, predictable spacing:

```
Base Unit: 4px
Scale: 4, 8, 12, 16, 20, 24, 32, 40, 48, 56, 64px
```

### CSS Variables

```css
:root {
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 20px;
  --space-2xl: 24px;
  --space-3xl: 32px;
  --space-4xl: 40px;
  --space-5xl: 48px;
  
  /* Shortcuts */
  --gap-tight: 8px;
  --gap-normal: 16px;
  --gap-loose: 24px;
}
```

### Common Patterns

| Pattern | Value | Use Case |
|---------|-------|----------|
| **Button Padding** | 8px vertical, 12px horizontal | All button types |
| **Input Padding** | 10px vertical, 12px horizontal | Form inputs |
| **Card Padding** | 16px-24px | Modal content, containers |
| **Section Gap** | 20-24px | Between major sections |
| **Item Gap** | 8px | Between list items, tabs |
| **Divider Margin** | 12px top/bottom | Section separators |
| **Sidebar Item Gap** | 8px | Between sidebar tabs |
| **Modal Internal** | 24px minimum | Padding inside modals |

### Grid System

**Desktop Layout**:
```
┌─────────────┬─────────────────────────────────┐
│   Sidebar   │       Content Area (Fluid)      │
│   240px     │   Remaining width, full height  │
│  (fixed)    │                                 │
└─────────────┴─────────────────────────────────┘
```

**Sidebar Dimensions**:
- Expanded: 240px fixed width
- Collapsed: 48px (icon-only mode)
- Transition: 0.2s ease-out
- Always visible (never fully hidden)

**Responsive Breakpoints**:

```css
/* Desktop */
@media (min-width: 1024px) {
  .sidebar { width: 240px; }
  .content { margin-left: 240px; }
}

/* Tablet */
@media (min-width: 768px) and (max-width: 1023px) {
  .sidebar { width: 240px; }
  .content { margin-left: 240px; }
}

/* Mobile (Future) */
@media (max-width: 767px) {
  .sidebar { position: fixed; left: 0; z-index: 1000; transform: translateX(-100%); }
  .sidebar.open { transform: translateX(0); }
}
```

### Content Margins

| Area | Margin | Notes |
|------|--------|-------|
| **Main content** | 16-24px horizontal | Depends on viewport width |
| **Vertical padding** | 12-16px top/bottom | Section separation |
| **Between tabs** | 8px | Tight grouping |
| **Between sections** | 24px | Strong separation |

---

## Components

### Button Component

#### Primary Button

Visual appearance for main actions (submit, confirm, primary CTA).

**Anatomy**:
- Background: Gradient (Space color or accent)
- Text: White, semibold
- Padding: 8px vertical, 12px horizontal
- Border Radius: 6-8px
- Min Height: 36-40px
- Border: None

**States**:

| State | Effect |
|-------|--------|
| **Normal** | Full opacity gradient, cursor pointer |
| **Hover** | Opacity 0.9 or gradient brightened 10% |
| **Active/Pressed** | Gradient darkened 20%, slight inset shadow |
| **Focus** | 2px solid outline (accent color), 2px offset |
| **Disabled** | 50% opacity, cursor not-allowed, no hover effect |

**HTML**:
```html
<button class="button button-primary">
  Save Changes
</button>
```

**CSS**:
```css
.button {
  padding: 8px 12px;
  border: none;
  border-radius: 6px;
  font: 600 14px / 1 var(--font-stack);
  cursor: pointer;
  transition: all var(--transition-fast);
  min-height: 40px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.button-primary {
  background: var(--color-gradient-work);
  color: white;
}

.button-primary:hover {
  opacity: 0.9;
}

.button-primary:active {
  filter: brightness(0.8);
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.2);
}

.button-primary:focus-visible {
  outline: 2px solid var(--color-text-secondary);
  outline-offset: 2px;
}

.button-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

#### Secondary Button

For secondary actions, confirmations, or less emphasized CTAs.

**Anatomy**:
- Background: Surface 2
- Text: Primary text color, semibold
- Padding: 8px vertical, 12px horizontal
- Border Radius: 6px
- Border: 1px solid border color (optional)

**States**:

| State | Effect |
|-------|--------|
| **Normal** | Surface 2 background |
| **Hover** | Background shifts to Surface 1 (brightens) |
| **Active** | Background darkens, slight shadow |
| **Focus** | 2px outline (accent), 2px offset |
| **Disabled** | 50% opacity |

**HTML**:
```html
<button class="button button-secondary">
  Cancel
</button>
```

**CSS**:
```css
.button-secondary {
  background: var(--color-surface-2);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
}

.button-secondary:hover {
  background: var(--color-surface-1);
}

.button-secondary:active {
  background: var(--color-surface-1);
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.1);
}

.button-secondary:focus-visible {
  outline: 2px solid var(--color-text-secondary);
  outline-offset: 2px;
}

.button-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

#### Tertiary/Ghost Button

For minimal, text-only actions.

**Anatomy**:
- Background: Transparent
- Text: Accent color or secondary text
- Padding: 8px vertical, 12px horizontal
- Border: 1px solid (optional, subtle)
- Border Radius: 6px

**HTML**:
```html
<button class="button button-tertiary">
  Learn More
</button>
```

**CSS**:
```css
.button-tertiary {
  background: transparent;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.button-tertiary:hover {
  background: rgba(0, 0, 0, 0.05);
}

.button-tertiary:focus-visible {
  outline: 2px solid var(--color-text-secondary);
  outline-offset: 2px;
}
```

#### Icon Button

Compact, square buttons for icon-only actions.

**Size**: 32-40px square
**Icon Size**: 20-24px, centered
**Padding**: 0 (icon fills space)

**HTML**:
```html
<button class="button button-icon" aria-label="Close menu">
  <svg><!-- icon --></svg>
</button>
```

**CSS**:
```css
.button-icon {
  width: 40px;
  height: 40px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: transparent;
}

.button-icon:hover {
  background: var(--color-surface-2);
}
```

### Card Component

**Container** for content with subtle elevation and padding.

**Anatomy**:
- Background: Surface 1
- Padding: 16px-24px
- Border Radius: 8-12px
- Border: 1px subtle (optional)
- Shadow: Soft elevation

**HTML**:
```html
<div class="card">
  <h3 class="card-title">Card Title</h3>
  <p class="card-content">Card content goes here.</p>
</div>
```

**CSS**:
```css
.card {
  background: var(--color-surface-1);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  transition: all var(--transition-fast);
}

.card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

.card-title {
  font: 600 18px / 1.3 var(--font-stack);
  margin-bottom: 12px;
}

.card-content {
  font: 400 14px / 1.5 var(--font-stack);
  color: var(--color-text-secondary);
}
```

### Input Field Component

**Text Input**:
- Height: 36-40px
- Padding: 10px vertical, 12px horizontal
- Border: 1px solid border color
- Border Radius: 6px
- Focus: 2px outline, accent color

**HTML**:
```html
<div class="form-group">
  <label for="email" class="form-label">Email Address</label>
  <input type="email" id="email" class="input" placeholder="you@example.com" />
</div>
```

**CSS**:
```css
.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.form-label {
  font: 500 12px / 1.4 var(--font-stack);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--color-text-primary);
}

.input {
  height: 40px;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-2);
  color: var(--color-text-primary);
  font: 400 14px / 1.5 var(--font-stack);
  transition: all var(--transition-fast);
}

.input:hover {
  border-color: var(--color-text-secondary);
}

.input:focus {
  outline: none;
  border-color: var(--color-text-secondary);
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.1);
}

.input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input::placeholder {
  color: var(--color-text-secondary);
  opacity: 0.6;
}
```

**Textarea**:
```css
.textarea {
  padding: 12px;
  min-height: 100px;
  resize: vertical;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-2);
  font: 400 14px / 1.5 var(--font-stack);
}

.textarea:focus {
  outline: none;
  border-color: var(--color-text-secondary);
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.1);
}
```

### Modal/Dialog Component

**Purpose**: Overlay content requiring user interaction or focus.

**Anatomy**:
```
Backdrop (semi-transparent overlay)
  ↓
Modal Container
  ├─ Title (20px, semibold)
  ├─ Description (14px, secondary)
  ├─ Content (varies)
  └─ Actions (buttons, right-aligned)
```

**HTML**:
```html
<div class="modal-backdrop">
  <div class="modal">
    <h2 class="modal-title">Confirm Action</h2>
    <p class="modal-description">
      Are you sure you want to proceed? This action cannot be undone.
    </p>
    <div class="modal-content">
      <!-- Additional content -->
    </div>
    <div class="modal-actions">
      <button class="button button-secondary">Cancel</button>
      <button class="button button-primary">Confirm</button>
    </div>
  </div>
</div>
```

**CSS**:
```css
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn var(--transition-normal);
}

.modal {
  background: var(--color-surface-1);
  border-radius: 12px;
  padding: 24px;
  max-width: 90vw;
  width: 400px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  animation: slideUp var(--transition-normal);
  max-height: 90vh;
  overflow-y: auto;
}

.modal-title {
  font: 600 20px / 1.2 var(--font-stack);
  margin-bottom: 8px;
}

.modal-description {
  font: 400 14px / 1.5 var(--font-stack);
  color: var(--color-text-secondary);
  margin-bottom: 20px;
}

.modal-content {
  margin-bottom: 20px;
}

.modal-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}
```

### Form Checkbox

**HTML**:
```html
<label class="checkbox-label">
  <input type="checkbox" class="checkbox" />
  <span>I agree to the terms</span>
</label>
```

**CSS**:
```css
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font: 400 14px / 1.5 var(--font-stack);
  color: var(--color-text-primary);
}

.checkbox {
  width: 20px;
  height: 20px;
  border: 1.5px solid var(--color-border);
  border-radius: 4px;
  cursor: pointer;
  appearance: none;
  background: var(--color-surface-2);
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.checkbox:hover {
  border-color: var(--color-text-secondary);
}

.checkbox:checked {
  background: var(--color-gradient-work);
  border-color: var(--color-gradient-work);
  background-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="white"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" /></svg>');
  background-position: center;
  background-repeat: no-repeat;
  background-size: 100%;
}

.checkbox:focus-visible {
  outline: 2px solid var(--color-text-secondary);
  outline-offset: 2px;
}
```

### Toggle Switch

**HTML**:
```html
<label class="toggle-label">
  <input type="checkbox" class="toggle" />
  <span class="toggle-bg"></span>
  Dark Mode
</label>
```

**CSS**:
```css
.toggle-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font: 400 14px / 1.5 var(--font-stack);
}

.toggle {
  appearance: none;
  width: 44px;
  height: 24px;
  background: var(--color-surface-2);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  position: relative;
  transition: background var(--transition-normal);
}

.toggle::before {
  content: '';
  position: absolute;
  width: 20px;
  height: 20px;
  background: white;
  border-radius: 50%;
  top: 2px;
  left: 2px;
  transition: left var(--transition-normal);
}

.toggle:checked {
  background: var(--color-gradient-work);
}

.toggle:checked::before {
  left: 22px;
}

.toggle:focus-visible {
  outline: 2px solid var(--color-text-secondary);
  outline-offset: 2px;
}
```

### Sidebar Navigation

**Tab Card** (individual navigation item):

**HTML**:
```html
<div class="sidebar">
  <div class="sidebar-section">
    <h3 class="sidebar-section-title">PINNED</h3>
    <div class="sidebar-tabs">
      <a href="#" class="sidebar-tab sidebar-tab-active">
        <img src="favicon.ico" alt="" class="sidebar-tab-icon" />
        <span class="sidebar-tab-label">Gmail</span>
        <button class="sidebar-tab-menu" aria-label="Menu">⋮</button>
      </a>
      <a href="#" class="sidebar-tab">
        <img src="favicon.ico" alt="" class="sidebar-tab-icon" />
        <span class="sidebar-tab-label">Calendar</span>
        <button class="sidebar-tab-menu" aria-label="Menu">⋮</button>
      </a>
    </div>
  </div>
</div>
```

**CSS**:
```css
.sidebar {
  width: 240px;
  background: var(--color-bg-primary);
  border-right: 1px solid var(--color-border);
  overflow-y: auto;
  transition: width var(--transition-normal);
}

.sidebar-section {
  padding: 16px;
  border-bottom: 1px solid var(--color-border);
}

.sidebar-section-title {
  font: 500 11px / 1.2 var(--font-stack);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--color-text-secondary);
  margin-bottom: 12px;
}

.sidebar-tabs {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-primary);
  text-decoration: none;
  cursor: pointer;
  transition: all var(--transition-fast);
  border: none;
  min-height: 36px;
}

.sidebar-tab:hover {
  background: var(--color-surface-2);
}

.sidebar-tab-active {
  background: var(--color-surface-2);
  border-left: 3px solid var(--color-gradient-work);
  padding-left: 9px;
}

.sidebar-tab-icon {
  width: 16px;
  height: 16px;
  border-radius: 2px;
  flex-shrink: 0;
}

.sidebar-tab-label {
  font: 400 14px / 1.5 var(--font-stack);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-tab-menu {
  background: transparent;
  border: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.sidebar-tab:hover .sidebar-tab-menu {
  opacity: 1;
}
```

---

## Elevation & Shadows

### Shadow System

Arc uses subtle, soft shadows to convey depth without visual heaviness.

| Level | Shadow | Use Case |
|-------|--------|----------|
| **None** | None | Flat, no elevation |
| **Subtle** | `0 2px 8px rgba(0, 0, 0, 0.08)` | Hover states, slight lift |
| **Elevated** | `0 4px 16px rgba(0, 0, 0, 0.12)` | Cards, panels at rest |
| **High** | `0 8px 32px rgba(0, 0, 0, 0.3)` | Modals, dropdowns, overlays |
| **Maximum** | `0 16px 48px rgba(0, 0, 0, 0.4)` | Rare; tooltips, priority modals |

**CSS Variables**:
```css
:root {
  --shadow-subtle: 0 2px 8px rgba(0, 0, 0, 0.08);
  --shadow-elevated: 0 4px 16px rgba(0, 0, 0, 0.12);
  --shadow-high: 0 8px 32px rgba(0, 0, 0, 0.3);
  --shadow-max: 0 16px 48px rgba(0, 0, 0, 0.4);
}
```

### Border Radius System

Consistent rounding creates cohesive, modern appearance.

| Size | Value | Use Case |
|------|-------|----------|
| **Sharp** | 0px | Rare; very subtle borders |
| **Small** | 4px | Input borders, small UI |
| **Medium** | 6px | Buttons, tabs, most controls |
| **Large** | 8-12px | Cards, panels |
| **Extra Large** | 16px+ | Modals, major containers |
| **Full** | 50% | Avatar circles, badges |

**CSS Variables**:
```css
:root {
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-full: 50%;
}
```

---

## Animations & Transitions

### Timing Functions

```css
:root {
  --transition-fast: 0.15s ease-out;
  --transition-normal: 0.2s ease-out;
  --transition-smooth: 0.3s ease-in-out;
  --transition-slow: 0.5s ease-in-out;
}
```

### Common Transitions

| Pattern | Duration | Easing | Purpose |
|---------|----------|--------|---------|
| **Hover** | 0.15s | ease-out | Button/link hover states |
| **Focus** | 0.1s | ease-out | Focus outline appearance |
| **State Change** | 0.2s | ease-out | Active/inactive toggle |
| **Modal In** | 0.2s | ease-out | Backdrop fade + modal slide |
| **Modal Out** | 0.15s | ease-in | Quick disappear |
| **Sidebar Collapse** | 0.2s | ease-out | Width shrink, title fade |
| **Space Switch** | 0.3s | ease-in-out | Smooth cross-fade |

### Animation Examples

**Fade In**:
```css
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.element { animation: fadeIn var(--transition-fast); }
```

**Slide Up**:
```css
@keyframes slideUp {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.element { animation: slideUp var(--transition-normal); }
```

**Scale & Fade** (Modal appearance):
```css
@keyframes scaleIn {
  from { transform: scale(0.95); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.modal { animation: scaleIn var(--transition-normal); }
```

**Rotate** (Loading spinner):
```css
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.spinner { animation: spin 1s linear infinite; }
```

### Respecting Motion Preferences

Always respect user preferences for reduced motion:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## Accessibility

### Color Contrast

All text must meet **WCAG AA minimum** (4.5:1 for body text, 3:1 for large text).

**Testing**:
- Use contrast checking tools (WebAIM, Contrast Ratio)
- Test both light and dark modes
- Verify with colorblind simulators

### Focus Management

#### Visible Focus Indicators

**Always visible**, never removed or hidden:

```css
:focus-visible {
  outline: 2px solid var(--color-text-secondary);
  outline-offset: 2px;
}
```

#### Focus Order

- Logical top-to-bottom, left-to-right flow
- Use `tabindex` sparingly (prefer semantic HTML)
- Modals should trap focus (focus cycles within modal only)

#### Focus Trap Implementation

```javascript
function trapFocus(modal) {
  const focusableElements = modal.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  const firstElement = focusableElements[0];
  const lastElement = focusableElements[focusableElements.length - 1];

  modal.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
      if (e.shiftKey && document.activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
      } else if (!e.shiftKey && document.activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
      }
    }
  });
}
```

### Semantic HTML

Use proper semantic elements for screen readers:

```html
<!-- Good -->
<nav aria-label="Main Navigation">
  <ul>
    <li><a href="/">Home</a></li>
    <li><a href="/about">About</a></li>
  </ul>
</nav>

<!-- Good -->
<button aria-label="Close menu">✕</button>

<!-- Bad -->
<div onclick="...">Click me</div>
```

### ARIA Labels

Provide context for screen readers:

```html
<!-- Button with icon needs label -->
<button aria-label="Save document">
  <svg><!-- save icon --></svg>
</button>

<!-- Section with accessible name -->
<section aria-label="Featured Posts">
  ...
</section>

<!-- Form errors -->
<input aria-describedby="email-error" />
<span id="email-error">Invalid email format</span>
```

### Keyboard Navigation

**Keyboard Shortcuts**:

```
Cmd+T        Open Command Bar
Cmd+1-9      Switch Spaces
Cmd+Shift+\  Split View
Tab          Navigate to next element
Shift+Tab    Navigate to previous element
Enter        Activate button/submit form
Escape       Close modal/dropdown
Arrow Keys   Navigate lists/menus
```

### Screen Reader Testing

- Test with NVDA (Windows), JAWS (Windows), or VoiceOver (macOS)
- Verify heading hierarchy
- Ensure all interactive elements are reachable
- Test form labels and error messages

---

## Dark Mode

### Implementation Strategy

**Detect System Preference**:
```javascript
// Check system preference
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
const theme = prefersDark ? 'dark' : 'light';

// Store preference
localStorage.setItem('theme', theme);
document.documentElement.setAttribute('data-theme', theme);
```

**User Toggle**:
```javascript
function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme');
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
  
  document.documentElement.setAttribute('data-theme', newTheme);
  localStorage.setItem('theme', newTheme);
}
```

### Color Adjustments

#### Light → Dark Conversions

| Light | Dark | Adjustment |
|-------|------|------------|
| #FAFAFA (bg) | #1a1a1a (bg) | ~90% darker |
| #F5F5F5 (surface-1) | #383C4A (surface-1) | ~80% darker |
| #EEEEEE (surface-2) | #404552 (surface-2) | ~75% darker |
| #1D1D1D (text) | #FFFFFF (text) | Inverted |
| #717171 (secondary) | #9394A5 (secondary) | Lighter gray |

#### Gradient Preservation

Space gradients remain consistent across modes:
```css
--color-gradient-work: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
/* Same in both light and dark modes */
```

### CSS Implementation

```css
:root[data-theme="light"] {
  --color-bg-primary: #FAFAFA;
  --color-surface-1: #F5F5F5;
  --color-text-primary: #1D1D1D;
}

:root[data-theme="dark"] {
  --color-bg-primary: #1a1a1a;
  --color-surface-1: #383C4A;
  --color-text-primary: #FFFFFF;
}

body {
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  transition: background var(--transition-smooth), color var(--transition-smooth);
}
```

---

## Code Examples

### Complete CSS Variables Template

```css
/* ============================================
   ARC BROWSER DESIGN SYSTEM - CSS VARIABLES
   ============================================ */

:root[data-theme="light"] {
  /* Colors - Light Mode */
  --color-bg-primary: #FAFAFA;
  --color-surface-1: #F5F5F5;
  --color-surface-2: #EEEEEE;
  --color-surface-hover: #E8E8E8;
  --color-border: #E4E5F1;
  
  --color-text-primary: #1D1D1D;
  --color-text-secondary: #717171;
  
  --color-gradient-work: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  --color-gradient-personal: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  --color-gradient-project: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  
  /* Shadows */
  --shadow-subtle: 0 2px 8px rgba(0, 0, 0, 0.08);
  --shadow-elevated: 0 4px 16px rgba(0, 0, 0, 0.12);
  --shadow-high: 0 8px 32px rgba(0, 0, 0, 0.3);
}

:root[data-theme="dark"] {
  /* Colors - Dark Mode */
  --color-bg-primary: #1a1a1a;
  --color-surface-1: #383C4A;
  --color-surface-2: #404552;
  --color-surface-hover: #4a4f5d;
  --color-border: #4b5162;
  
  --color-text-primary: #FFFFFF;
  --color-text-secondary: #9394A5;
  
  --color-gradient-work: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  --color-gradient-personal: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  --color-gradient-project: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  
  /* Shadows */
  --shadow-subtle: 0 2px 8px rgba(0, 0, 0, 0.3);
  --shadow-elevated: 0 4px 16px rgba(0, 0, 0, 0.4);
  --shadow-high: 0 8px 32px rgba(0, 0, 0, 0.5);
}

/* Shared Tokens (both modes) */
:root {
  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 20px;
  --space-2xl: 24px;
  --space-3xl: 32px;
  
  /* Typography */
  --font-stack: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif;
  --font-mono: "SF Mono", Monaco, "Cascadia Code", monospace;
  
  --font-weight-regular: 400;
  --font-weight-medium: 500;
  --font-weight-semibold: 600;
  
  --font-size-lg: 20px;
  --font-size-base: 16px;
  --font-size-sm: 14px;
  --font-size-xs: 12px;
  
  /* Border Radius */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-full: 50%;
  
  /* Transitions */
  --transition-fast: 0.15s ease-out;
  --transition-normal: 0.2s ease-out;
  --transition-smooth: 0.3s ease-in-out;
  --transition-slow: 0.5s ease-in-out;
}

/* ============================================
   GLOBAL STYLES
   ============================================ */

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  font: var(--font-weight-regular) var(--font-size-base) / 1.5 var(--font-stack);
  transition: background var(--transition-smooth), color var(--transition-smooth);
}

/* ============================================
   FOCUS MANAGEMENT
   ============================================ */

:focus-visible {
  outline: 2px solid var(--color-text-secondary);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### React Component Example

**Button Component**:
```jsx
import React from 'react';

export function Button({
  variant = 'primary',
  size = 'md',
  disabled = false,
  children,
  ...props
}) {
  return (
    <button
      className={`button button-${variant} button-${size}`}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}

// Usage:
<Button variant="primary">Save</Button>
<Button variant="secondary">Cancel</Button>
<Button variant="tertiary" disabled>Learn More</Button>
```

**Card Component**:
```jsx
export function Card({ title, children, ...props }) {
  return (
    <div className="card" {...props}>
      {title && <h3 className="card-title">{title}</h3>}
      <div className="card-content">{children}</div>
    </div>
  );
}

// Usage:
<Card title="Settings">
  <p>Configure your preferences here.</p>
</Card>
```

**Modal Component**:
```jsx
import React, { useEffect, useRef } from 'react';

export function Modal({ isOpen, title, onClose, children, ...props }) {
  const modalRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleEscape = (e) => {
      if (e.key === 'Escape') onClose();
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} {...props}>
      <div className="modal" onClick={(e) => e.stopPropagation()} ref={modalRef}>
        <h2 className="modal-title">{title}</h2>
        {children}
      </div>
    </div>
  );
}

// Usage:
const [isOpen, setIsOpen] = React.useState(false);

<button onClick={() => setIsOpen(true)}>Open</button>
<Modal isOpen={isOpen} title="Confirm" onClose={() => setIsOpen(false)}>
  <p>Are you sure?</p>
  <div className="modal-actions">
    <button onClick={() => setIsOpen(false)}>Cancel</button>
    <button>Confirm</button>
  </div>
</Modal>
```

### Tailwind Configuration

If using Tailwind CSS, extend the config:

```javascript
module.exports = {
  theme: {
    extend: {
      colors: {
        // Light mode
        'bg-primary': '#FAFAFA',
        'surface': {
          1: '#F5F5F5',
          2: '#EEEEEE',
        },
        'text': {
          primary: '#1D1D1D',
          secondary: '#717171',
        },
        'gradient': {
          work: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          personal: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
          project: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
        },
      },
      spacing: {
        xs: '4px',
        sm: '8px',
        md: '12px',
        lg: '16px',
        xl: '20px',
        '2xl': '24px',
        '3xl': '32px',
      },
      borderRadius: {
        sm: '4px',
        md: '6px',
        lg: '12px',
        xl: '16px',
      },
      boxShadow: {
        subtle: '0 2px 8px rgba(0, 0, 0, 0.08)',
        elevated: '0 4px 16px rgba(0, 0, 0, 0.12)',
        high: '0 8px 32px rgba(0, 0, 0, 0.3)',
      },
      transitionDuration: {
        'fast': '150ms',
        'normal': '200ms',
        'smooth': '300ms',
      },
    },
  },
};
```

**Tailwind Utility Classes**:
```html
<!-- Button -->
<button class="px-3 py-2 bg-gradient-to-r from-purple-500 to-purple-700 text-white rounded-md hover:opacity-90 transition-opacity duration-fast">
  Save
</button>

<!-- Card -->
<div class="bg-surface-1 rounded-lg p-6 shadow-elevated hover:shadow-high transition-shadow duration-fast">
  <h3 class="font-semibold text-lg text-text-primary">Title</h3>
  <p class="text-text-secondary text-sm mt-2">Description</p>
</div>

<!-- Input -->
<input
  type="email"
  class="w-full px-3 py-2.5 bg-surface-2 border border-border rounded-md text-text-primary placeholder-text-secondary focus:outline-none focus:border-text-secondary focus:ring-2 focus:ring-offset-2"
  placeholder="Enter email"
/>
```

---

## Best Practices

### Do's ✓

- ✓ Use semantic HTML and proper heading hierarchy
- ✓ Always provide visible focus indicators
- ✓ Test in both light and dark modes
- ✓ Use CSS variables for consistent theming
- ✓ Keep animations brief (0.15-0.3s) and smooth
- ✓ Provide keyboard shortcuts for power users
- ✓ Test color contrast with accessible tools
- ✓ Include alt text on all images and icons
- ✓ Use proper ARIA labels for screen readers
- ✓ Respect `prefers-reduced-motion` setting

### Don'ts ✗

- ✗ Don't rely on color alone to convey information
- ✗ Don't remove focus outlines (they're accessibility features)
- ✗ Don't use excessive animations or motion
- ✗ Don't create keyboard traps
- ✗ Don't use generic button text ("Click here")
- ✗ Don't ignore dark mode support
- ✗ Don't use hard-coded colors (use CSS variables)
- ✗ Don't make hover states indistinguishable from normal states
- ✗ Don't forget about mobile/touch interactions
- ✗ Don't break tab order or logical focus flow

---

## Reference Files

- **Figma Community**: Arc Browser Interface (editable components)
- **Official Docs**: The Browser Company website
- **Source Analysis**: Blake Crosley's Design Principles Guide
- **CSS Frameworks**: Tailwind CSS, CSS Grid, Flexbox

---

**Last Updated**: June 22, 2026  
**Version**: 1.0  
**Status**: Production Ready

For questions or contributions, refer to the project's design repository or design team.
