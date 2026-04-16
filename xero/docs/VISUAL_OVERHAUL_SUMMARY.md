# Xero Sync Dashboard — Visual Overhaul Summary

> **Purpose**: This document captures all visual changes made to the Xero Sync Dashboard during the 2026-02 overhaul. It serves as a reference for:
> 1. Performing a similar style overhaul on another Frappe app
> 2. Making further visual changes to the Xero Integration app

---

## Files Edited

| File | Role | What Changed |
|------|------|-------------|
| [`xero_sync_dashboard.js`](../xero/page/xero_sync_dashboard/xero_sync_dashboard.js) | **Primary UI file** — all CSS, HTML templates, and JS logic | Complete visual overhaul of all 6 tabs |

> **Note**: This is the only file that needed to be changed. All styling, HTML structure, and UI logic for the dashboard lives in this single file. The `.html` file is a minimal root container; the `.css` file has minor overrides; the `.py` file is backend-only.

---

## Key Documents for UI Decisions

| Document | Purpose |
|----------|---------|
| [`VISUAL_OVERHAUL_SUMMARY.md`](VISUAL_OVERHAUL_SUMMARY.md) | This file — design decisions and patterns |
| [`CODEBASE_REFERENCE_SHEET.md`](CODEBASE_REFERENCE_SHEET.md) | Architecture overview, file locations, function index |
| [`CRITICAL_KNOWLEDGE_FOR_FUTURE_TASKS.md`](CRITICAL_KNOWLEDGE_FOR_FUTURE_TASKS.md) | Gotchas, sync logic rules, what NOT to do |
| [`xero_sync_dashboard.js`](../xero/page/xero_sync_dashboard/xero_sync_dashboard.js) lines 82–1371 | **The CSS design system** — all tokens, component styles |

---

## Design System — CSS Custom Properties

All colors and spacing are defined as CSS custom properties in `render_layout()` (lines ~89–133). These are the single source of truth for the entire dashboard's visual appearance.

```css
:root {
    /* Primary — dusty blue */
    --ch-primary:          #5B8AC4;
    --ch-primary-dark:     #4A78B0;
    --ch-primary-light:    #F0F4FA;

    /* Semantic — muted/dusty tones */
    --ch-success:          #5BA88A;   /* dusty green */
    --ch-success-bg:       #F0F8F4;
    --ch-success-border:   #C2E0D2;
    --ch-warning:          #C4923A;   /* dusty amber */
    --ch-warning-bg:       #FBF7F0;
    --ch-warning-border:   #EDDCB8;
    --ch-danger:           #B87D5A;   /* dusty terracotta */
    --ch-danger-alt:       #C45B5B;   /* muted red */
    --ch-danger-bg:        #FBF3EF;
    --ch-danger-border:    #E8CCBB;
    --ch-info:             #5B8AC4;

    /* Surfaces */
    --ch-bg:               #F7F9FB;   /* page background */
    --ch-surface:          #FFFFFF;   /* card background */
    --ch-border:           #ECEEF0;   /* card borders */

    /* Typography */
    --ch-text:             #1A1F26;
    --ch-text-muted:       #7F8A96;

    /* Radii */
    --ch-radius-md:        10px;
    --ch-radius-lg:        12px;
    --ch-radius-pill:      9999px;
}
```

**To change the color scheme**: Edit these variables. Everything else inherits from them.

---

## Icon System — Lucide CDN

**Before**: Font Awesome (`<i class="fa fa-*">`)  
**After**: Lucide icons (`<i data-lucide="icon-name">`)

### How It Works

1. Lucide is loaded from CDN on dashboard init:
   ```javascript
   script.src = 'https://unpkg.com/lucide@0.344.0/dist/umd/lucide.min.js';
   ```

2. After every dynamic HTML render, call:
   ```javascript
   this.create_lucide_icons();
   // which calls: lucide.createIcons();
   ```

3. Icons are declared as:
   ```html
   <i data-lucide="icon-name"></i>
   ```

### Icon Reference Used in This Dashboard

| Context | Lucide Icon Name |
|---------|-----------------|
| Overview tab | `layout-grid` |
| Manual Sync tab | `globe` |
| Last Sync tab | `clock` |
| Sync Logs tab | `file-text` |
| Analytics tab | `bar-chart-2` |
| Entity Status tab | `sliders-horizontal` |
| Connection icon | `globe` |
| Successful syncs | `check-circle` |
| Failed syncs | `alert-circle` |
| Active jobs | `clock` |
| Total entities | `database` |
| Recent errors | `alert-triangle` |
| Active jobs panel | `list-filter` |
| Arrow right (ERPNext→Xero) | `arrow-right` |
| Arrow left (Xero→ERPNext) | `arrow-left` |
| Refresh/sync | `refresh-cw` |
| Bulk operations | `refresh-cw` |
| Retry failed | `alert-triangle` |
| Clear logs | `trash-2` |
| Queue status | `list-filter` |
| Filter button | `filter` |
| Log details | `eye` |
| Analytics | `bar-chart-2`, `activity`, `timer`, `layers`, `percent` |
| Entity status | `sliders-horizontal` |
| Error state | `alert-circle` |
| Lightbulb/recommendations | `lightbulb` |

**Full icon library**: https://lucide.dev/icons/

---

## Component Patterns

### 1. Section Header Card
Used at the top of each tab to label the section.

```html
<div class="logs-header-card">
    <i data-lucide="icon-name"></i> Section Title
</div>
```

CSS class: `.logs-header-card` — white card, 15px bold text, Lucide icon in muted color.

---

### 2. Stat Cards Grid (4-column)
Used in Overview and Analytics for key metrics.

```html
<div class="overview-stats-grid">
    <div class="overview-stat-card">
        <div class="stat-text">
            <div class="stat-label-top">Label</div>
            <div class="stat-value">42</div>
        </div>
        <div class="stat-icon-circle icon-success">
            <i data-lucide="check-circle"></i>
        </div>
    </div>
</div>
```

Icon circle variants: `icon-success`, `icon-danger`, `icon-info`, `icon-primary`

---

### 3. Chip/Pill Buttons (Sync Entity Buttons)
Used in Manual Sync Operations for entity trigger buttons.

```html
<button class="sync-chip-btn" data-entity="Sales Invoice"
        onclick="dashboard.trigger_sync('Sales Invoice')">
    <i data-lucide="file-text" class="chip-icon chip-icon-blue"></i>
    <span class="sync-chip-label">Sales Invoice</span>
</button>
```

Icon color classes: `chip-icon-blue`, `chip-icon-green`, `chip-icon-orange`, `chip-icon-purple`, `chip-icon-red`, `chip-icon-teal`, `chip-icon-violet`, `chip-icon-gray`, `chip-icon-crimson`, `chip-icon-indigo`

---

### 4. Direction Section Cards
Used in Manual Sync Operations for ERPNext→Xero and Xero→ERPNext sections.

```html
<div class="sync-direction-card">
    <div class="sync-direction-header">
        <div class="sync-direction-icon to-xero">
            <i data-lucide="arrow-right"></i>
        </div>
        <div class="sync-direction-info">
            <h3>ERPNext → Xero</h3>
            <p>Push data from ERPNext to Xero</p>
        </div>
    </div>
    <div class="sync-chips-grid">
        <!-- chip buttons here -->
    </div>
</div>
```

Direction icon variants: `.to-xero` (dusty blue `#7BA3CC`), `.from-xero` (dusty sage `#7BB89E`)

---

### 5. Status Badges
All status badges use the outlined pill style.

```html
<span class="badge badge-success">Success</span>
<span class="badge badge-danger">Error</span>
<span class="badge badge-warning">Warning</span>
<span class="badge badge-info">Info</span>
<span class="badge badge-secondary">Category</span>
```

---

### 6. Error List Items (Overview Recent Errors)
```html
<div class="error-list-item">
    <div class="error-dot"></div>  <!-- red dot top-right -->
    <div class="error-top-row">
        <span class="error-doc-title">Document Name</span>
        <span class="error-time">16 minutes ago</span>
    </div>
    <div class="error-message">Error description text</div>
    <span class="badge badge-secondary">Category</span>
</div>
```

---

### 7. Sync Attempt Blocks (Last Sync Attempts)
Uses left-border accent instead of solid colored headers.

```html
<div class="sync-attempt-block attempt-success">  <!-- or attempt-failed, attempt-partial, etc. -->
    <div class="sync-attempt-header">
        <!-- direction icon + label + timestamp + status badge -->
    </div>
    <div class="sync-attempt-body">
        <!-- entities, issues, recommendations, item table -->
    </div>
</div>
```

Accent classes: `attempt-success`, `attempt-failed`, `attempt-partial`, `attempt-warnings`, `attempt-info`

---

### 8. Bulk Operation Buttons
Three distinct styles for the three bulk actions.

```html
<button class="bulk-btn bulk-btn-danger" onclick="...">
    <i data-lucide="alert-triangle"></i> Retry All Failed Jobs
</button>
<button class="bulk-btn bulk-btn-primary" onclick="...">
    <i data-lucide="refresh-cw"></i> Sync All Entities
</button>
<button class="bulk-btn bulk-btn-ghost" onclick="...">
    <i data-lucide="trash-2"></i> Clear Old Logs
</button>
```

---

### 9. Queue Stat Cards
4-column grid with centered icon + number + label.

```html
<div class="queue-stats-grid">
    <div class="queue-stat-card">
        <div class="queue-stat-icon icon-queued">
            <i data-lucide="clock"></i>
        </div>
        <div class="queue-stat-value">0</div>
        <div class="queue-stat-label">Queued</div>
    </div>
</div>
```

Icon color classes: `icon-queued` (muted), `icon-processing` (primary), `icon-completed` (success), `icon-failed` (danger)

---

### 10. Logs Filter Bar
```html
<div class="logs-filters-card">
    <select id="status-filter">...</select>
    <select id="entity-filter">...</select>
    <input type="text" id="message-filter" placeholder="Search message...">
    <button class="logs-filter-btn" onclick="...">
        <i data-lucide="filter"></i> Filter
    </button>
</div>
```

---

### 11. Table Action Links
```html
<!-- Retry (only for Error rows) -->
<a class="logs-action-link retry-link" onclick="...">Retry</a>

<!-- Details (all rows) -->
<a class="logs-action-link details-link" onclick="...">
    <i data-lucide="eye"></i> Details
</a>
```

---

### 12. Empty State
```html
<div class="empty-state">
    <i data-lucide="list-filter"></i>
    <p>No active jobs</p>
</div>
```

---

## Tab Navigation

Tabs use borderless pill style. Active tab gets solid primary background.

```html
<a class="nav-link active" data-tab="overview" href="#overview">
    <i data-lucide="layout-grid"></i> Overview
</a>
```

CSS: `.xero-dashboard-container .nav-tabs .nav-link` — transparent background, no border, inline-flex with gap for icon.

---

## How to Apply This Style to Another Frappe App

### Step 1: Copy the CSS Design System
Copy the entire `<style>` block from `render_layout()` (lines 82–1371) into the new app's page JS file. Adjust the `:root` color variables to match the new app's brand.

### Step 2: Load Lucide CDN
Add the `load_lucide()` and `create_lucide_icons()` methods to the new app's dashboard class:

```javascript
load_lucide() {
    return new Promise((resolve) => {
        if (window.lucide) { resolve(); return; }
        const script = document.createElement('script');
        script.src = 'https://unpkg.com/lucide@0.344.0/dist/umd/lucide.min.js';
        script.onload = () => resolve();
        script.onerror = () => resolve();
        document.head.appendChild(script);
    });
}

create_lucide_icons() {
    if (window.lucide) {
        try { lucide.createIcons(); } catch(e) {}
    }
}
```

Call `this.load_lucide().then(() => { /* init */ })` in `init()`.

Call `this.create_lucide_icons()` at the end of every render method.

### Step 3: Use the Component Patterns
Replace Font Awesome icons with `<i data-lucide="icon-name">` throughout all HTML templates.

Use the component patterns documented above (stat cards, chip buttons, section headers, etc.) for consistent UI.

### Step 4: Key Rules
- **Always call `create_lucide_icons()`** after injecting HTML with `data-lucide` attributes
- **Use CSS variables** (`var(--ch-primary)`, etc.) instead of hardcoded colors
- **No solid colored headers** — use left-border accents or outlined badges for status
- **White cards with subtle borders** — `background: var(--ch-surface); border: 1px solid var(--ch-border); border-radius: var(--ch-radius-lg);`
- **Dusty/muted colors** — avoid saturated greens, blues, yellows

---

## What NOT to Change

1. **Backend methods** — `xero_sync_dashboard.py` contains all API endpoints. Do not modify.
2. **Sync logic** — `api/xero_*.py` files. Do not modify for visual changes.
3. **`trigger_sync()` method** — Contains polling logic. Only the button text selector was updated (`'.sync-chip-label, .sync-button-title'`).
4. **`apply_log_filters()` / `view_filtered_logs()`** — Filter logic. Only the HTML structure of the filter bar changed.

---

## Further Visual Changes — Quick Reference

| What to change | Where |
|----------------|-------|
| Color scheme | `:root` CSS variables in `render_layout()` |
| Tab icons | `render_layout()` HTML — `<i data-lucide="...">` in nav items |
| Overview stats | `render_overview()` — `overview-stats-grid` section |
| Connection banner | `render_overview()` — `xero-connection-banner` section |
| Sync entity buttons | `render_sync_chip_buttons()` — entity array with `lucide` and `color` properties |
| Direction section colors | CSS `.sync-direction-icon.to-xero` and `.from-xero` |
| Bulk button styles | CSS `.bulk-btn-danger`, `.bulk-btn-primary`, `.bulk-btn-ghost` |
| Queue stat cards | `render_queue_status()` |
| Sync attempt appearance | CSS `.sync-attempt-block` and `.attempt-*` classes |
| Log table actions | `render_logs_table()` — action cell HTML |
| Analytics stats | `render_analytics()` — `overview-stats-grid` section |
| Entity cards | `render_entity_status()` and CSS `.entity-card` |

---

*Visual Overhaul Summary v3.0 — 2026-02-21*  
*Author: AI Assistant (Kilo Code)*
