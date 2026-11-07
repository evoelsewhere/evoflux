//! Deck stylesheet and live-build skeletons (v3 `_render_pptx` CSS,
//! `_LIVE_SLIDE_CSS`, `_SKELETON_LINES`, `_pending_slide_skeletons`).

use super::super::DeckPlan;
use super::util::f;

/// v3 `_render_pptx` stylesheet (verbatim).
pub(super) const DECK_CSS: &str = r#"
    *{box-sizing:border-box}body{margin:0;padding:28px;background:#e8eaed;color:#202124;
    font-family:Arial,sans-serif}.slide-wrap{position:relative;width:min(1120px,94vw);
    margin:0 auto 30px}.slide{position:relative;width:100%;background:#fff;
    container-type:inline-size;
    overflow:hidden;box-shadow:0 3px 14px #0003}.slide-number{position:absolute;right:calc(100%
    + 8px);top:0;color:#6b7280;font-size:12px}.shape{position:absolute;overflow:hidden}
    .shape-group,.text-shape,.vector-shape{overflow:visible}.text-shape{padding:0}
    .shape-surface{position:absolute;inset:0;display:block;width:100%;height:100%;
    overflow:visible;pointer-events:none}.text-frame{position:relative;z-index:1;width:100%;height:100%;display:flex;
    flex-direction:column;overflow:hidden}.text-shape[data-default-text-align="center"] p{
    text-align:center!important}.text-shape[data-shape-font-color="theme"] .text-frame span{
    color:var(--shape-text-color)!important}.text-shape[data-text-unflip~="horizontal"] .text-frame{
    transform:scaleX(-1)}.text-shape[data-text-unflip~="vertical"] .text-frame{
    transform:scaleY(-1)}.text-shape[data-text-unflip~="horizontal"][data-text-unflip~="vertical"] .text-frame{
    transform:scale(-1,-1)}
    .text-shape p{margin:0 0 .2em;line-height:1.12;white-space:pre-wrap;
    overflow-wrap:normal;word-break:normal;break-inside:avoid}.bullet-marker{text-align:center}
    .text-shape.html-native{padding:0}.text-shape.html-native p{margin:0;
    height:1lh;min-height:1lh;flex:0 0 1lh}
    .picture-frame{overflow:hidden}.picture{position:absolute;display:block;max-width:none;
    max-height:none}.table-shape table{width:100%;height:100%;border-collapse:collapse;
    table-layout:fixed}.table-shape td{border:1px solid #b8bdc6;overflow:hidden}
    .table-shape p{overflow:hidden}.chart{display:flex;flex-direction:column;align-items:center;
    justify-content:flex-start;border:0;background:transparent;color:#374151;
    gap:.3cqw}.chart-title{font-size:1.875cqw;line-height:1.1}.chart-svg{width:100%;
    flex:1;min-height:0}.chart-empty,.chart-unsupported{font-size:1.1cqw;color:#6b7280}
    .vector-shape{pointer-events:none}.connector{overflow:visible;pointer-events:none}
    .object-placeholder{display:flex;flex-direction:column;align-items:center;
    justify-content:center;gap:.3cqw;border:1px dashed #9ca3af;background:#f9fafb;
    color:#4b5563;font-size:1.1cqw;text-align:center}.object-placeholder small{
    font-size:.9cqw;color:#6b7280}
    .slide-notes-metadata{display:none!important}
    "#;

/// v3 `_LIVE_SLIDE_CSS` (verbatim).
pub(super) const LIVE_SLIDE_CSS: &str = r#"
.slide-skeleton{display:flex;flex-direction:column;gap:3.2cqw;padding:6% 7%;
background:#fff;font-family:Arial,sans-serif}
.sk-head{display:flex;flex-direction:column;align-items:flex-start;gap:1.4cqw}
.sk-chip{display:inline-flex;align-items:center;gap:.8cqw;padding:.55cqw 1.3cqw;
border-radius:99px;font:600 1.25cqw/1 Arial,sans-serif;letter-spacing:.02em;
color:#5f6368;background:#f1f3f4}
.sk-body{flex:1;min-height:0;display:flex;flex-direction:column;justify-content:center;
gap:1.8cqw}
.slide-skeleton .bar{border-radius:.6cqw;background:#ececec;transform-origin:left}
.slide-skeleton .bar.title{height:3.8cqw;width:55%}
.slide-skeleton .bar.subtitle{height:2cqw;width:32%}
.slide-skeleton .bar.line{height:1.4cqw;width:var(--w)}
.sk-progress{position:absolute;left:0;right:0;bottom:0;height:.7cqw;background:#e8eaed;
display:flex}.sk-progress .done{background:#1a73e8}.sk-progress .now{
background:linear-gradient(90deg,#8ab4f8,#d2e3fc,#8ab4f8);background-size:200% 100%;
animation:sk-flow 1.2s linear infinite}

[data-slide-status="building"] .slide{outline:2px solid #1a73e8;outline-offset:3px;
animation:sk-glow 2.2s ease-in-out infinite}
[data-slide-status="building"] .slide-skeleton{background:
radial-gradient(#1a73e81f 1px,transparent 1.2px) 0 0/2.4cqw 2.4cqw,#fff}
[data-slide-status="building"] .slide-skeleton::after{content:"";position:absolute;
inset:0;pointer-events:none;background:linear-gradient(100deg,transparent 35%,
#1a73e814 50%,transparent 65%);animation:sk-scan 2.6s ease-in-out infinite}
[data-slide-status="building"] .sk-chip{color:#1967d2;background:#e8f0fe}
[data-slide-status="building"] .sk-spin{width:1.2cqw;height:1.2cqw;border-radius:50%;
border:.25cqw solid #1a73e84d;border-top-color:#1a73e8;animation:sk-spin .8s linear infinite}
[data-slide-status="building"] .bar{background:linear-gradient(90deg,#e3e6ea 0,
#f4f6f8 40%,#e3e6ea 80%) 0 0/300% 100%;animation:sk-grow .6s cubic-bezier(.2,.7,.2,1)
calc(.35s + var(--d,0) * .14s) both,sk-shimmer 1.6s ease-in-out 1.2s infinite}

[data-slide-status="pending"] .slide{opacity:.72}
[data-slide-status="pending"] .slide-skeleton{box-shadow:none;
outline:1.5px dashed #bdc1c6;outline-offset:-1px}

[data-slide-fresh] .slide{animation:sk-land .7s cubic-bezier(.2,.7,.2,1) both}
[data-slide-fresh]::after{content:"\2713  Added";position:absolute;top:10px;right:10px;
padding:4px 10px;border-radius:99px;font:600 12px/1.2 Arial,sans-serif;color:#fff;
background:#188038;box-shadow:0 2px 8px #0003;animation:sk-badge 2.6s ease both}

@keyframes sk-shimmer{0%{background-position:100% 0}100%{background-position:0 0}}
@keyframes sk-flow{0%{background-position:100% 0}100%{background-position:-100% 0}}
@keyframes sk-scan{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
@keyframes sk-spin{to{transform:rotate(360deg)}}
@keyframes sk-grow{from{transform:scaleX(0);opacity:0}to{transform:scaleX(1);opacity:1}}
@keyframes sk-glow{0%,100%{box-shadow:0 3px 14px #0003,0 0 0 0 #1a73e840}
50%{box-shadow:0 3px 14px #0003,0 0 0 10px #1a73e800}}
@keyframes sk-land{from{opacity:0;transform:translateY(14px) scale(.985)}
to{opacity:1;transform:none}}
@keyframes sk-badge{0%{opacity:0;transform:translateY(-6px)}12%,70%{opacity:1;
transform:none}100%{opacity:0}}
@media (prefers-reduced-motion:reduce){[data-deck-live] *,[data-deck-live] *::after{
animation:none!important}[data-slide-fresh]::after{display:none}}
"#;

/// Widths of a skeleton's text lines; every slide not added yet looks the
/// same, since the deck's design is unknown until the slide exists.
const SKELETON_LINES: [&str; 5] = ["88%", "80%", "92%", "64%", "74%"];

/// Loading skeletons for the slides an agent has not saved yet: the first
/// missing slide is the one being built (assembling bars and a progress bar),
/// the rest stay still.
pub(super) fn pending_slide_skeletons(plan: &DeckPlan, first: usize, ratio: &str) -> Vec<String> {
    let total = plan.total as usize;
    let lines: String = SKELETON_LINES
        .iter()
        .enumerate()
        .map(|(order, width)| {
            format!(
                "<div class=\"bar line\" style=\"--w:{width};--d:{}\"></div>",
                order + 2
            )
        })
        .collect();
    let mut skeletons = Vec::new();
    for index in first..total {
        let number = index + 1;
        let building = index == first;
        let state = if building { "building" } else { "pending" };
        let caption = if building {
            format!("Building slide {number} of {total}")
        } else {
            "Up next".to_string()
        };
        let label = format!("Slide {number}");
        let progress = if building {
            format!(
                "<div class=\"sk-progress\" aria-hidden=\"true\"><span class=\"done\" style=\"width:{}%\"></span><span class=\"now\" style=\"width:{}%\"></span></div>",
                f(100.0 * first as f64 / total as f64, 2),
                f(100.0 / total as f64, 2)
            )
        } else {
            String::new()
        };
        let spinner = if building {
            "<span class=\"sk-spin\"></span>"
        } else {
            ""
        };
        skeletons.push(format!(
            "<article class=\"slide-wrap\" data-preview-item data-preview-label=\"{label}\" data-slide-status=\"{state}\"><div class=\"slide-number\">{number}</div><section class=\"slide slide-skeleton\" style=\"aspect-ratio:{ratio}\" aria-label=\"{label}, {}\"><div class=\"sk-head\"><span class=\"sk-chip\">{spinner}{caption}</span><div class=\"bar title\"></div><div class=\"bar subtitle\" style=\"--d:1\"></div></div><div class=\"sk-body\">{lines}</div>{progress}</section></article>",
            caption.to_lowercase()
        ));
    }
    skeletons
}
