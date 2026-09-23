# Dashboards

Build a source-backed dashboard or monitoring view — a reusable surface, not a one-time report. Settle metric definitions and decision logic first (`references/kpi-design.md`) when they are not already agreed.

## Contents

- Choose a surface
- Workflow
- Self-contained HTML dashboard
- Streamlit dashboard
- BI platform dashboard
- QA and handoff

## Choose a surface

Honor the user's destination. Otherwise pick the simplest surface that works:

- **Existing BI or product-analytics platform** (Tableau, Looker, Power BI, Databricks, Metabase, Mode, ...) when the user wants a governed, broadly shared dashboard there and a tool for it is available.
- **Streamlit** when Python execution fits, the dashboard needs custom interactivity, Python-side transforms, file inputs, or multiple sources, or the user wants version-controlled app code.
- **Self-contained HTML** for a portable local dashboard that opens without a server.

Do not require React, Vite, Recharts, or widget runtimes.

## Workflow

1. Define audience, operating decision, monitoring cadence, and the questions the dashboard answers.
2. Define each metric: formula, numerator and denominator, unit, grain, window, filters, exclusions, owner, source, freshness expectation.
3. Validate joins, completeness, duplicates, missingness, comparability, and refresh status (`references/data-quality.md`) before presenting metrics as trustworthy.
4. Lay out the hierarchy: headline KPIs first, then trends, then driver and diagnostic cuts, guardrails and risks, and detail tables or drill-downs last.
5. Add only decision-relevant filters. Make default date range, segments, comparison period, and current filter state visible.
6. Build each chart per `references/visualization.md`; keep exact values reachable in tables.
7. Show data freshness, sources, definitions, and material caveats on the dashboard.
8. Implement and test the real artifact, including representative, empty, partial, and error states when feasible.

## Self-contained HTML dashboard

- Semantic HTML, CSS, inline SVG or canvas, and small vanilla JavaScript; readable without JavaScript.
- Visible title, purpose, date range, filter state, data freshness, and source notes.
- CSS custom properties for color, spacing, typography, and light/dark appearance.
- Accessible form controls, keyboard focus states, sufficient contrast, and table alternatives for charts.
- Bound embedded data: aggregate before embedding large datasets or document an external data-loading step.
- No remote scripts or fonts unless the user accepts the dependency.
- Verify by opening the file with `browser_use` when available: desktop and narrow widths, controls, empty and error states, labels, table overflow, console errors.

## Streamlit dashboard

Structure:

- Call `st.set_page_config(...)` at the top of the entrypoint. Default to one entrypoint and one page.
- Summary first: KPI cards (`st.metric`), then trends, then diagnostic breakdowns, then detail tables or drill-downs.
- Global filters in the sidebar or a top control row.

Implementation:

- Keep page code thin; put data access and expensive transforms in helper functions or modules.
- Use `st.cache_data` only for deterministic reads and transforms; keep `st.session_state` for UI state.
- Bound default queries and lazy-load heavy detail views; make loading, empty, and error states visible.
- Keep number formatting consistent across axes, labels, legends, and tooltips; prefer direct labels over long legends.
- Altair charts and `st.dataframe` need `pyarrow`. If native Arrow dependencies are unreliable in the environment, use Plotly charts and `st.table` or bounded HTML tables.
- Declare added dependencies in the project and confirm a clean install.

Run and smoke-test:

```bash
uv run --with streamlit --with pandas --with plotly streamlit run path/to/app.py
```

Exercise main filters, tabs, uploads, and drill-downs; confirm the default state is useful before any clicks, reruns raise no exceptions or wasteful reloads, and at least one real chart and one table render (renderer dependency failures appear only when data-backed components draw). Unit-test extracted helpers when UI behavior is hard to test.

Deployment is not implied. For a live shared app, pin down hosting target, auth model, network access to the data backend, secrets and environment variables, dependency installation, and start command before calling it done.

## BI platform dashboard

- Preserve the requested audience, metrics, filters, sources, ownership, and publication target. Switch to Streamlit or HTML only when the user wants a prototype or local artifact, or the platform cannot support the need.
- Use modeled production tables or views; never finalize a dashboard that depends on scratch or temporary tables.
- Use the platform's standard widgets and the same hierarchy: headline metrics, trend, diagnosis, detail.
- Validate SQL and inspect sample rows and partition freshness before wiring widgets.
- Hand off the dashboard or draft URL and any unresolved permission, publishing, or sharing constraints. Publishing or changing a shared dashboard needs the user's explicit approval.

## QA and handoff

- Reconcile displayed totals and KPIs against reviewed source results.
- Test filters, date boundaries, sorting, responsive layout, and refresh behavior.
- Check chart labels, units, legends, accessibility, and table readability.
- Expose no secrets, credentials, unnecessary personal data, or temporary local paths.
- Deliver the artifact or platform link plus metric definitions, source or query files, the run or refresh instructions, and known limitations.
