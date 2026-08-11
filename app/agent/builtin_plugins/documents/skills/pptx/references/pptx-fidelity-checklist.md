# PPTX authoring and render fidelity checklist

Read this checklist for every candidate revision before final delivery. Store a
project-local QA ledger with exactly one row per scorecard dimension and
slide-specific evidence paths where applicable. Never award points from intent,
source code, or a successful ZIP/OpenXML reopen alone.

## Gate 0 — DNA completeness

- [ ] Instantiate `slide-dna.json` from the built-in PowerPoint DNA.
- [ ] Record audience, narrative outcome, aspect ratio, type roles, semantic
      colors, spacing, layout family, editability expectations, and known gaps.
- [ ] Assign every slide a takeaway, archetype, dominant object, reading order,
      density, source IDs, representation intent, and risk flags.
- [ ] Confirm every requested Office feature has a capability status.

Fail this gate when visual direction, representation, or fidelity evidence is
implicit. Do not begin HTML or template edits until the contract is complete.

## Gate 1 — Authoring integrity

- [ ] Verify the exact canvas and safe area on every slide.
- [ ] Use one slide root, local declared assets, deterministic CSS, and no
      executable or network content for the HTML lane.
- [ ] Check source hashes, slide mapping, object IDs, and omitted-slide coverage
      for the inherited-template lane.
- [ ] Confirm titles state takeaways, body copy fits its density budget, and no
      placeholder or production note is audience-visible.
- [ ] Check font availability, glyph coverage, fallback choice, line count,
      bullet indentation, numeric formats, and locale-specific punctuation.
- [ ] Verify image resolution at final crop size and preserve intended aspect
      ratios, transparency, and focal points.
- [ ] Reconcile every chart/table label, unit, series, legend, axis, total, and
      source against the underlying data.

## Gate 2 — WebView source preview

Render every slide at 1280 × 720 and inspect it individually at 100% scale.
Use a contact sheet only for deck rhythm.

- [ ] No clipping, overflow, missing asset, blank region, title wrap, accidental
      overlap, or content outside the canvas.
- [ ] Reading order, hierarchy, contrast, alignment, and whitespace remain clear
      without zooming.
- [ ] Adjacent slide silhouettes vary without breaking the deck's grid, title,
      footer, or source-note anchors.
- [ ] Thin lines, small labels, gradients, shadows, masks, and transparency are
      visible at presentation size.
- [ ] Every externally sourced claim and asset has a `[Sources]` notes entry.

Treat any error-severity renderer finding as a hard failure.

## Gate 3 — Shell and editable-overlay parity

Inspect the shell image and editable layout manifest for every slide.

- [ ] The shell is exactly 2560 × 1440 for a 1280 × 720 project and covers the
      complete slide.
- [ ] Every native overlay has one matching DNA `editable_intent`; no native
      object exists only to inflate an editability count.
- [ ] Editable text uses one export-safe font, uniform styling, solid color, and
      supported alignment without filter, mask, shadow, mixed runs, or semantic
      bullets.
- [ ] Editable raster images use plain rectangular fill geometry without crop,
      mask, radius, transform, opacity, or blend effects.
- [ ] Removing native overlays reveals no duplicate visible text or image in the
      shell; restoring them leaves no holes, halos, seams, or changed stacking.
- [ ] Overlay bounds, rotation, line height, and z-order match the source
      preview and stay within the canvas.

When an object fails these rules, flatten it and record the loss of native
semantics instead of accepting visible drift.

## Gate 4 — Reopened PPTX render

After Gates 0–3 and structural preflight pass, publish the immutable candidate
to a `.pptx`. Call `artifact(action="inspect", format="pptx",
source_path="...pptx")` on that exact output so the built-in Documents preview
engine renders every slide again. This is a separate evidence set from the HTML
preview.

- [ ] Slide count, order, size, backgrounds, notes, and expected editable-object
      count survive reopen.
- [ ] Compare `source-preview` and `reopened-plugin-preview` side by side at the
      same pixel size.
- [ ] Inspect title and body baselines, line breaks, image placement, alpha,
      borders, fills, rotations, and layer order.
- [ ] Confirm no shell/overlay duplication, missing editable content, fallback
      font, substituted glyph, or crop drift appears.
- [ ] Record a visual-difference artifact or a manual reasoned verdict for every
      slide; never mark an unrendered slide as passed.

For deterministic same-size rasters, use the declared
`normalized-rgb-rmse-similarity-v1` metric and require ≥ 0.90 per slide and
≥ 0.95 for the deck median. A slide below either threshold requires visual
inspection and correction; it cannot pass on the aggregate score alone. Do not
label this metric SSIM. If the built-in renderer cannot evaluate a requested
Office feature, mark it `unverified` and surface that limitation rather than
treating absence from the preview as proof.

## Gate 5 — OpenXML and Office behavior

- [ ] Reopen the package successfully and confirm the expected slide count,
      dimensions, relationships, media, notes, and object types.
- [ ] Verify no external relationships, unresolved placeholders, corrupt media,
      duplicate visible objects, or orphaned edit targets remain.
- [ ] For inherited decks, preserve master → layout → slide lineage, theme
      references, transitions, animations, charts, tables, SmartArt, OLE/media,
      hyperlinks, and custom XML unless an explicit typed edit changes them.
- [ ] If Microsoft PowerPoint is available, render representative high-risk
      slides there and record differences separately from the built-in preview.

PowerPoint reference rendering improves confidence but does not excuse a failed
built-in preview. Structural round-trip is mandatory and carries no visual
fidelity points by itself.

## Score and accept

Use the weights in `templates/powerpoint-slide-dna.json` and score only verified
evidence. Require at least 90/100 overall and satisfy every hard failure rule.
Record the following for each dimension: score, evidence path, observed gap,
owner, and disposition (`fixed`, `flattened`, `preserved`, `unsupported`, or
`unverified`).

Treat the project ledger as manual evidence, not the acceptance decision. The
runtime always replaces `canvas-and-geometry` and `reopened-render-parity` with
scores from the current WebView, shell, and reopened-PPTX rasters, sums the six
dimensions, and rejects the candidate when `observedScore < targetScore`.

Reject the revision regardless of score when any slide is blank, wrong-ratio,
clipped, missing a required asset, materially unreadable, visually duplicated,
corrupt after reopen, mapped to the wrong template slide, or not rendered on
the reopened-PPTX surface.

Deliver only after every slide has an accepted source preview and reopened PPTX
preview. Report native editable counts and known gaps without claiming that a
flattened object is semantically editable or that structural validation proves
Microsoft PowerPoint pixel parity.
