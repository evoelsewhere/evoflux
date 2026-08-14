# Image intelligence for slides

Inspect images before committing to a slide layout. Images are evidence and
story material, not generic decoration.

## Decide whether imagery is required

Imagery is usually essential for a named product, interface, person, place,
event, physical object, historical subject, visual comparison, or case study.
It may be unnecessary for a purely conceptual, textual, or data-led argument.
When removing an image would not reduce meaning, reconsider using it.

For a recognizable brand, prioritize assets in this order:

1. official logo or mark;
2. real product photography or renders;
3. current UI screenshots;
4. charts, diagrams, and documentary evidence;
5. palette and typography cues;
6. decorative photography.

Do not replace a required product, interface, person, or place with a generic
CSS silhouette or invented SVG illustration.

## Build an image profile

For each candidate, inspect and record enough information to make a layout
decision:

- semantic subject and intended narrative role;
- focal point, faces, product/UI region, and important embedded text;
- negative space suitable for copy;
- native dimensions, aspect ratio, alpha, sharpness, and effective resolution
  at the intended crop size;
- safe crops for the target frame and what each crop would remove;
- dominant colors, contrast, lighting, and compatibility with adjacent images;
- source, license or permission, capture date, and version freshness;
- quality and confidence, including any reason not to use it.

Select fewer strong images instead of filling every slide. Two images used
together should share a defensible color, lighting, crop, or documentary logic.
Do not reuse the same image across slides by default; repetition needs a clear
narrative purpose such as before/after, zoom, or a recurring anchor.

## Read screenshots and visual references

Treat a reference image as design context. Identify:

- grid, margins, alignments, reading order, and dominant silhouette;
- type hierarchy and density, not merely font names;
- palette roles and where contrast is concentrated;
- image focal point, crop behavior, and text-safe negative space;
- repeated anchors, dividers, numbering, captions, and source treatment;
- which details are structural and which are incidental content.

Recreate that logic in the HTML/SVG source and materialize eligible copy,
images, and simple geometry as native PowerPoint objects. Do not paste a
reference screenshot as the entire slide when editable text is expected. OCR
or transcribed reference text is source material and must be verified before
reuse.

## Crop and placement rules

- Choose the frame after inspecting focal point and negative space.
- Prefer `object-fit: cover` only when the crop is intentional; set
  `object-position` explicitly for off-center subjects.
- Preserve logos, UI controls, chart labels, and product geometry.
- Do not stretch an image to fit a placeholder.
- Match the frame to the source aspect ratio and place the focal point
  deliberately; never rely on a centered crop for an off-center subject.
- Reject visibly soft, over-compressed, distorted, stale, or mismatched assets.
- Inspect the final rendered crop at full-slide size, not only as a thumbnail.

List every external visual in the slide's `[Sources]` speaker notes block.
