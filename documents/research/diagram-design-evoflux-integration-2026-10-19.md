# Diagram Design research for EvoFlux

**Date:** 2026-10-19
**Upstream:** [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design), inspected at commit [550fd66](https://github.com/cathrynlavery/diagram-design/tree/550fd66edff058bc73056c3416b76d69cfe865ba)
**EvoFlux base:** origin/main at e109338457113f8129b34cffb16137d8e5291e3e

## Findings

Diagram Design is an Agent Skill for editorial, branded diagrams built as standalone HTML with inline SVG. Its useful design ideas are semantic type selection, focused content, explicit size/detail/audience, sparse accents, orthogonal connectors, accessible SVG names, and a layout complexity budget. It includes reference grammars for architecture, sequence, state, data flow, and many other types; templates, worked examples, icons, and scripts for Mermaid/draw.io/Excalidraw import and export.

Its upstream README advertises 45 diagram types, while the GitHub repository About metadata still says 44. Treat the live skill's type table as authoritative for taxonomy and recheck upstream before future syncs. The repository is MIT-licensed. Third-party icon assets have separate licenses and brand-mark conditions; do not copy them without their provenance and license records. Templates may request Google Fonts, so they are not a suitable unmodified dependency for a local-first EvoFlux widget.

## EvoFlux source comparison

The worktree was created from fetched origin/main, not the previously open feat/intelligent-ui checkout.

- Agent Skills are discovered from app/agent/builtin_skills/; their name and description are present in the run's Skill catalog. Matching work should cause the model to read SKILL.md using the normal read tool. There is no separate Skill tool or semantic router.
- In Work, visualize_read_me loads the diagram guidance on demand and show_widget renders an HTML fragment inline. The widget must call visualize_read_me first. The design module already has diagram search aliases.
- show_widget supports the app theme tokens and requires CSS-first streaming, dark-mode compatibility, restrained typography, and no gradients/shadows/blur. Diagram Design's Google Fonts, full-page templates, and 45-type gallery do not map directly.
- The explored source did not contain visual_artifact; that capability was present on the dirty feature branch, but using it would violate the requested origin/main base.

## Integration

Add a focused built-in diagram-design Skill. Its Level 1 description names user intents and diagram terms so the existing catalog can match it without loading detailed references into every prompt. It should not use an unmerged tool-preload metadata contract or add a new router. Its body routes simple maintained Markdown diagrams to Mermaid and editorial inline diagrams to the existing Work widget contract; references supply type selection and design quality. A small theme-aware SVG fragment is the only bundled starter asset. For Coding or explicit file output, create a project file only when requested.

The authored guidance and starter asset are EvoFlux adaptations, not copied upstream files. Do not bundle upstream code, icon packs, fonts, import/export scripts, or the gallery. The source links and commit are recorded above; if a future change copies a substantial upstream portion, include its MIT notice. Any third-party icon or font needs its own license/provenance review.

## Follow-up review of upstream `main`

Rechecked upstream `main` on 2026-10-19; it still resolves to `550fd66edff058bc73056c3416b76d69cfe865ba`. Its current Skill is version 2.6 and documents 45 visual types. The technical review emphasizes orthogonal routes, 6–10 px label clearance, distinct connector attachment points, a 4 px layout grid, and running both accessible-SVG/viewBox self-checks and a geometry verifier. EvoFlux now applies the compatible part at the `show_widget` boundary: explicit rectangle-node/orthogonal-path classes receive a pre-render check, and detected errors are returned for a model retry before rendering. Curved/unsupported routes remain flagged for manual review. The Skill also requires a post-render preview correction pass when a visual preview is available.

## References

- [Upstream Skill](https://github.com/cathrynlavery/diagram-design/blob/550fd66edff058bc73056c3416b76d69cfe865ba/skills/diagram-design/SKILL.md)
- [Diagram type examples](https://github.com/cathrynlavery/diagram-design/tree/550fd66edff058bc73056c3416b76d69cfe865ba/skills/diagram-design/references)
- [Upstream license](https://github.com/cathrynlavery/diagram-design/blob/550fd66edff058bc73056c3416b76d69cfe865ba/LICENSE)
- [Third-party asset licenses](https://github.com/cathrynlavery/diagram-design/blob/550fd66edff058bc73056c3416b76d69cfe865ba/THIRD_PARTY_LICENSES.md)
- [Upstream privacy notes](https://github.com/cathrynlavery/diagram-design/blob/550fd66edff058bc73056c3416b76d69cfe865ba/PRIVACY.md)