"""Built-in visual systems for the HTML-first presentation pipeline.

The presets adapt the style taxonomy published by ningzimu/codex-ppt-skill
into deterministic CSS design systems.  They are intentionally not fixed
slide masters: one visual identity supports several content-driven layout
archetypes so adjacent slides can vary without drifting stylistically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HtmlStylePreset:
    id: str
    name: str
    best_for: str
    visual_direction: str
    density: str
    palette: dict[str, str]
    typography: str
    archetypes: tuple[str, ...]
    avoid: tuple[str, ...]
    css: str

    def to_catalog(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "best_for": self.best_for,
            "visual_direction": self.visual_direction,
            "density": self.density,
            "palette": self.palette,
            "typography": self.typography,
            "recommended_archetypes": list(self.archetypes),
            "avoid": list(self.avoid),
        }


COMMON_PRESET_CSS = r"""
.preset-tag {
  display: inline-flex; align-items: center; gap: 8px; width: max-content;
  padding: 7px 11px; border: 1px solid currentColor; font-size: 14px;
  line-height: 1; font-weight: 760; letter-spacing: .09em; text-transform: uppercase;
}
.preset-display {
  margin: 0; font-family: var(--font-display); font-size: 112px; line-height: .86;
  font-weight: 800; letter-spacing: -.065em;
}
.preset-micro { font-size: 13px; line-height: 1.25; letter-spacing: .08em; text-transform: uppercase; }
.preset-stage { position: relative; min-height: 420px; }
.preset-panel { position: relative; padding: 28px; border: 1px solid var(--line); }
.preset-panel h2, .preset-panel h3 { margin: 0 0 12px; font-size: 24px; line-height: 1.15; }
.preset-panel p, .preset-panel li { font-size: 20px; line-height: 1.35; }
.preset-note { padding: 18px 20px; border-left: 5px solid var(--accent); }
.preset-number { font-family: var(--font-display); font-size: 74px; line-height: .9; font-weight: 800; }
.preset-rule { height: 2px; width: 100%; background: var(--line); }
.preset-grid { display: grid; gap: 24px; }
.preset-axis { position: absolute; background: var(--line); }
.preset-axis.horizontal { left: 0; right: 0; height: 1px; }
.preset-axis.vertical { top: 0; bottom: 0; width: 1px; }
"""


STYLE_PRESETS: dict[str, HtmlStylePreset] = {
    "clean-professional": HtmlStylePreset(
        id="clean-professional",
        name="Clean Professional",
        best_for="Project reviews, technical sharing, work summaries, defenses, and promotion cases.",
        visual_direction="Calm, evidence-driven, pragmatic, bright, and crisply structured.",
        density="medium",
        palette={
            "paper": "#F8FAFC",
            "ink": "#172033",
            "primary": "#2563EB",
            "accent": "#F59E0B",
            "muted": "#64748B",
        },
        typography="Modern sans-serif with decisive titles and highly legible body copy.",
        archetypes=(
            "hero-split",
            "claim-evidence",
            "process-ribbon",
            "architecture",
            "metric-story",
        ),
        avoid=(
            "poster decoration",
            "random stock photography",
            "cute stickers",
            "dense unreadable tables",
        ),
        css=r"""
.slide.style-clean-professional { --paper:#F8FAFC; --ink:#172033; --muted:#64748B; --primary:#2563EB; --accent:#F59E0B; --line:#DCE5F1; background:linear-gradient(145deg,#fff 0 70%,#EEF4FF 100%); }
.style-clean-professional .kicker { color:#2563EB; }
.style-clean-professional .preset-panel,.style-clean-professional .panel { background:#fff; border-color:#DCE5F1; box-shadow:0 14px 36px rgba(37,99,235,.08); }
.style-clean-professional .preset-tag { color:#2563EB; background:#EFF6FF; }
.style-clean-professional .preset-display { color:#164EC4; }
""",
    ),
    "creative-magazine": HtmlStylePreset(
        id="creative-magazine",
        name="Creative Magazine",
        best_for="Creative proposals, brand stories, portfolios, cultural events, and launches.",
        visual_direction="Premium editorial spread with bold asymmetry, crop tension, and one vivid accent.",
        density="low-to-medium with deliberate dense/open contrast",
        palette={
            "paper": "#F7F7F4",
            "ink": "#0B0B0D",
            "primary": "#0B0B0D",
            "accent": "#FF2E72",
            "muted": "#62626B",
        },
        typography="Oversized display sans or editorial serif paired with small aligned sans-serif annotations.",
        archetypes=(
            "editorial-hero",
            "typographic-statement",
            "claim-evidence",
            "comparison",
        ),
        avoid=(
            "generic corporate icons",
            "perfect symmetry",
            "multiple accent colors",
            "weak contrast",
        ),
        css=r"""
.slide.style-creative-magazine { --paper:#F7F7F4; --ink:#0B0B0D; --muted:#62626B; --primary:#0B0B0D; --accent:#FF2E72; --line:rgba(11,11,13,.28); background:#F7F7F4; }
.style-creative-magazine .title { font-size:76px; line-height:.92; letter-spacing:-.055em; max-width:1450px; }
.style-creative-magazine .preset-display { font-size:154px; color:#0B0B0D; text-transform:uppercase; }
.style-creative-magazine .preset-tag { color:#fff; background:#FF2E72; border-color:#FF2E72; transform:rotate(-2deg); }
.style-creative-magazine .preset-panel { background:#fff; border:0; border-top:8px solid #0B0B0D; }
.style-creative-magazine .preset-note { background:#FF2E72; color:#fff; border:0; }
.style-creative-magazine .preset-stage::after { content:""; position:absolute; width:340px; height:22px; right:4%; bottom:8%; background:#FF2E72; transform:rotate(-7deg); z-index:-1; }
""",
    ),
    "e-ink-magazine": HtmlStylePreset(
        id="e-ink-magazine",
        name="E-Ink Magazine",
        best_for="Keynotes, opinion pieces, AI/technology launches, and nonfiction storytelling.",
        visual_direction="Paper-and-ink editorial rhythm with serif heroes, monospace metadata, and quiet graphic texture.",
        density="alternating low-density heroes and medium-density editorial pages",
        palette={
            "paper": "#F7F4EA",
            "ink": "#111111",
            "primary": "#1E2A78",
            "accent": "#B5422C",
            "muted": "#69665F",
        },
        typography="Large editorial serif headlines, neutral sans body, and monospace metadata.",
        archetypes=(
            "editorial-hero",
            "typographic-statement",
            "metric-story",
            "comparison",
            "claim-evidence",
        ),
        avoid=(
            "template cards",
            "shiny gradients",
            "cute illustration",
            "dashboard overload",
        ),
        css=r"""
.slide.style-e-ink-magazine { --paper:#F7F4EA; --ink:#111111; --muted:#69665F; --primary:#1E2A78; --accent:#B5422C; --line:rgba(17,17,17,.34); --font-display:Georgia,"Times New Roman",serif; background:repeating-linear-gradient(0deg,rgba(17,17,17,.018) 0 1px,transparent 1px 5px),#F7F4EA; }
.style-e-ink-magazine .title { font-family:Georgia,"Times New Roman",serif; font-weight:650; letter-spacing:-.045em; }
.style-e-ink-magazine .preset-display { font-family:Georgia,"Times New Roman",serif; font-weight:600; }
.style-e-ink-magazine .preset-micro,.style-e-ink-magazine .preset-tag { font-family:"Courier New",monospace; }
.style-e-ink-magazine .preset-tag { border-left:0; border-right:0; padding-left:0; padding-right:0; }
.style-e-ink-magazine .preset-panel { background:rgba(247,244,234,.82); border-color:#111; }
""",
    ),
    "data-dashboard": HtmlStylePreset(
        id="data-dashboard",
        name="Data Dashboard",
        best_for="KPI reviews, operational analytics, business intelligence, and metric-heavy reporting.",
        visual_direction="Bright modern analytics surface with precise charts, lightweight panels, and one central insight.",
        density="high but rigorously grouped",
        palette={
            "paper": "#F5F8FC",
            "ink": "#0F172A",
            "primary": "#2563EB",
            "accent": "#06B6D4",
            "muted": "#64748B",
        },
        typography="Compact sans-serif hierarchy with large metrics and restrained labels.",
        archetypes=("metric-story", "dashboard-grid", "claim-evidence", "comparison"),
        avoid=(
            "dark monitoring wall",
            "cyberpunk glow",
            "tiny labels",
            "numbers without a decision narrative",
        ),
        css=r"""
.slide.style-data-dashboard { --paper:#F5F8FC; --ink:#0F172A; --muted:#64748B; --primary:#2563EB; --accent:#06B6D4; --line:#DCE6F2; background:#F5F8FC; }
.style-data-dashboard .title { font-size:54px; letter-spacing:-.03em; }
.style-data-dashboard .preset-panel,.style-data-dashboard .panel { background:#fff; border-color:#DCE6F2; border-radius:14px; box-shadow:0 8px 28px rgba(15,23,42,.06); }
.style-data-dashboard .preset-number,.style-data-dashboard .metric { color:#2563EB; }
.style-data-dashboard .preset-tag { color:#2563EB; background:#EAF2FF; border-color:#CFE0FF; border-radius:999px; }
.style-data-dashboard .preset-stage { background-image:linear-gradient(#E6EDF6 1px,transparent 1px),linear-gradient(90deg,#E6EDF6 1px,transparent 1px); background-size:48px 48px; }
""",
    ),
    "retro-flat-illustration": HtmlStylePreset(
        id="retro-flat-illustration",
        name="Retro Flat Illustration",
        best_for="Brand stories, cultural projects, travel, lifestyle, and narrative-led presentations.",
        visual_direction="Cream-paper vintage poster with flat fills, monoline outlines, and playful panoramic scenes.",
        density="medium and decorative",
        palette={
            "paper": "#F5F3E8",
            "ink": "#34495E",
            "primary": "#E17055",
            "accent": "#F9CA24",
            "muted": "#6C7A89",
        },
        typography="Chunky vintage display paired with friendly geometric sans-serif.",
        archetypes=(
            "editorial-hero",
            "process-ribbon",
            "claim-evidence",
            "architecture",
        ),
        avoid=("photorealism", "glossy 3D", "neon", "inconsistent outline weight"),
        css=r"""
.slide.style-retro-flat-illustration { --paper:#F5F3E8; --ink:#34495E; --muted:#6C7A89; --primary:#E17055; --accent:#F9CA24; --line:#34495E; background:radial-gradient(circle at 15% 18%,rgba(249,202,36,.16),transparent 23%),repeating-linear-gradient(0deg,rgba(52,73,94,.025) 0 1px,transparent 1px 4px),#F5F3E8; }
.style-retro-flat-illustration .title,.style-retro-flat-illustration .preset-display { color:#E17055; text-shadow:3px 3px 0 #F9CA24; }
.style-retro-flat-illustration .preset-panel,.style-retro-flat-illustration .panel { background:#FFF9E7; border:3px solid #34495E; border-radius:8px; box-shadow:7px 7px 0 #95E1D3; }
.style-retro-flat-illustration .preset-tag { background:#F9CA24; color:#34495E; border:2px solid #34495E; border-radius:999px; }
.style-retro-flat-illustration .preset-note { background:#95E1D3; border:2px solid #34495E; }
""",
    ),
    "handdrawn-technical": HtmlStylePreset(
        id="handdrawn-technical",
        name="Hand-Drawn Technical Explanation",
        best_for="Technical concepts, AI/software explanations, knowledge cards, and calm educational diagrams.",
        visual_direction="Near-white paper, thin graphite sketch lines, small precise diagrams, pastel marker emphasis, generous whitespace.",
        density="low-to-medium; one core idea",
        palette={
            "paper": "#FCFBF7",
            "ink": "#2F3437",
            "primary": "#557DA5",
            "accent": "#F4C7B8",
            "muted": "#6D7478",
        },
        typography="Restrained handwriting-like display with exact, sparse sans-serif labels.",
        archetypes=("concept-map", "comparison", "process-ribbon", "architecture"),
        avoid=(
            "messy whiteboard frame",
            "large cartoons",
            "dense handwriting",
            "digital UI cards",
        ),
        css=r"""
.slide.style-handdrawn-technical { --paper:#FCFBF7; --ink:#2F3437; --muted:#6D7478; --primary:#557DA5; --accent:#F4C7B8; --line:rgba(47,52,55,.45); --font-display:"Bradley Hand","Comic Sans MS",Arial,sans-serif; background:repeating-linear-gradient(-2deg,rgba(47,52,55,.018) 0 1px,transparent 1px 8px),#FCFBF7; }
.style-handdrawn-technical .title { font-family:var(--font-display); font-weight:700; letter-spacing:-.025em; }
.style-handdrawn-technical .preset-panel { background:rgba(255,255,255,.72); border:2px dashed rgba(47,52,55,.58); border-radius:46% 54% 48% 52% / 8% 10% 7% 9%; }
.style-handdrawn-technical .preset-tag { background:#BFD7F1; color:#2F3437; border:0; transform:rotate(-1deg); }
.style-handdrawn-technical .preset-note { background:#CFE2D1; border:0; transform:rotate(.6deg); }
.style-handdrawn-technical .preset-rule { height:3px; background:repeating-linear-gradient(90deg,#2F3437 0 18px,transparent 18px 26px); }
""",
    ),
    "handdrawn-whiteboard": HtmlStylePreset(
        id="handdrawn-whiteboard",
        name="Hand-Drawn Whiteboard",
        best_for="Training, workshops, concept breakdowns, and approachable technical sharing.",
        visual_direction="Authentic organized whiteboard with marker lines, arrows, simple boxes, and teaching annotations.",
        density="medium and freeform but ordered",
        palette={
            "paper": "#FAFAF5",
            "ink": "#202428",
            "primary": "#3498DB",
            "accent": "#E74C3C",
            "muted": "#62686D",
        },
        typography="Marker-like headings and clear compact labels.",
        archetypes=("concept-map", "process-ribbon", "comparison", "architecture"),
        avoid=(
            "illegible handwriting",
            "childish clutter",
            "photoreal people",
            "polished digital cards",
        ),
        css=r"""
.slide.style-handdrawn-whiteboard { --paper:#FAFAF5; --ink:#202428; --muted:#62686D; --primary:#3498DB; --accent:#E74C3C; --line:rgba(32,36,40,.55); --font-display:"Bradley Hand","Comic Sans MS",Arial,sans-serif; background:radial-gradient(circle at 80% 12%,rgba(52,152,219,.05),transparent 22%),repeating-linear-gradient(0deg,rgba(32,36,40,.018) 0 1px,transparent 1px 7px),#FAFAF5; }
.style-handdrawn-whiteboard .title { font-family:var(--font-display); text-decoration:underline 4px #3498DB; text-underline-offset:10px; }
.style-handdrawn-whiteboard .preset-panel { background:transparent; border:3px solid #202428; border-radius:18px 10px 22px 12px; transform:rotate(-.25deg); }
.style-handdrawn-whiteboard .preset-panel:nth-child(even) { transform:rotate(.35deg); }
.style-handdrawn-whiteboard .preset-tag { color:#E74C3C; border-color:#E74C3C; transform:rotate(-2deg); }
.style-handdrawn-whiteboard .preset-note { background:#FFF9C4; border:0; box-shadow:2px 5px 12px rgba(32,36,40,.12); transform:rotate(1deg); }
""",
    ),
    "warm-handmade": HtmlStylePreset(
        id="warm-handmade",
        name="Warm Handmade",
        best_for="Education, community, culture, public-interest work, and human-centered stories.",
        visual_direction="Soft paper collage with tactile notes, gentle color, and restrained scrapbook warmth.",
        density="medium, intimate, and tactile",
        palette={
            "paper": "#F5F1E8",
            "ink": "#5C4033",
            "primary": "#A67C52",
            "accent": "#FFA574",
            "muted": "#7B695D",
        },
        typography="Warm rounded or handwritten display paired with readable soft-brown body text.",
        archetypes=(
            "editorial-hero",
            "claim-evidence",
            "process-ribbon",
            "concept-map",
        ),
        avoid=(
            "glossy plastic",
            "hard corporate edges",
            "neon",
            "childish sticker overload",
        ),
        css=r"""
.slide.style-warm-handmade { --paper:#F5F1E8; --ink:#5C4033; --muted:#7B695D; --primary:#A67C52; --accent:#FFA574; --line:rgba(92,64,51,.25); --font-display:"Bradley Hand","Aptos Display",Arial,sans-serif; background:repeating-linear-gradient(93deg,rgba(92,64,51,.018) 0 1px,transparent 1px 5px),linear-gradient(135deg,#F8F3E9,#E8DCC8); }
.style-warm-handmade .title { font-family:var(--font-display); color:#5C4033; }
.style-warm-handmade .preset-panel,.style-warm-handmade .panel { background:#FFF9EA; border:0; box-shadow:0 10px 18px rgba(92,64,51,.16); transform:rotate(-.45deg); }
.style-warm-handmade .preset-panel:nth-child(even) { background:#EAF2E2; transform:rotate(.6deg); }
.style-warm-handmade .preset-panel::before { content:""; position:absolute; top:-12px; left:40%; width:82px; height:24px; background:rgba(255,236,183,.72); transform:rotate(-3deg); }
.style-warm-handmade .preset-tag { background:#F5C4B8; color:#5C4033; border:0; border-radius:4px; }
""",
    ),
    "scientific-defense": HtmlStylePreset(
        id="scientific-defense",
        name="Scientific Defense",
        best_for="Research proposals, thesis defenses, lab reviews, and evidence-heavy academic reporting.",
        visual_direction="Formal research-defense system with crisp navy structure, restrained red conclusions, numbered reasoning, dense evidence, and disciplined technical diagrams and tables.",
        density="medium-to-high with strict grouping",
        palette={
            "paper": "#FFFFFF",
            "ink": "#111111",
            "primary": "#003F8F",
            "accent": "#B5121B",
            "muted": "#4B5563",
        },
        typography="Authoritative sans-serif hierarchy optimized for Chinese/English academic material.",
        archetypes=(
            "claim-evidence",
            "architecture",
            "matrix",
            "comparison",
            "evidence-grid",
        ),
        avoid=(
            "empty marketing heroes",
            "cartoons",
            "decorative gradients",
            "random icons",
            "unrelated stock imagery",
        ),
        css=r"""
.slide.style-scientific-defense { --paper:#FFFFFF; --ink:#111111; --muted:#4B5563; --primary:#003F8F; --accent:#B5121B; --line:#D8DEE8; background:#fff; }
.style-scientific-defense .safe::before { content:""; position:absolute; left:0; right:0; top:-20px; height:6px; background:#003F8F; }
.style-scientific-defense .title { font-size:50px; color:#003F8F; letter-spacing:-.025em; }
.style-scientific-defense .preset-panel,.style-scientific-defense .panel { background:#F8FAFD; border:1px solid #C9D5E5; border-top:7px solid #0B5CAD; border-radius:2px; box-shadow:none; }
.style-scientific-defense .preset-tag { background:#003F8F; color:#fff; border-color:#003F8F; }
.style-scientific-defense .preset-note { color:#B5121B; background:#FFF4F4; border-color:#B5121B; font-weight:700; }
.style-scientific-defense table th { background:#003F8F; color:#fff; }
.style-scientific-defense .tpl-title { color:#003F8F; font-size:48px; letter-spacing:-.02em; }
.style-scientific-defense .tpl-kicker { color:#0B5CAD; }
.style-scientific-defense .tpl-card,.style-scientific-defense .tpl-cell { border-radius:2px; background:#FAFCFF; border-color:#C9D5E5; box-shadow:none; }
.style-scientific-defense .tpl-card { border-top:5px solid #0B5CAD; }
.style-scientific-defense .tpl-cell.header { background:#003F8F; border-color:#003F8F; }
.style-scientific-defense .tpl-research-takeaway { background:#EDF4FC; border-color:#9CBCE0; color:#003F8F; }
.style-scientific-defense .tpl-research-number { background:#003F8F; color:#fff; }
.style-scientific-defense .tpl-research-emphasis { color:#B5121B; }
""",
    ),
    "mckinsey": HtmlStylePreset(
        id="mckinsey",
        name="McKinsey-Style Consulting",
        best_for="Executive strategy, transformation, operating models, frameworks, roadmaps, and recommendations.",
        visual_direction="Light Swiss-grid consulting editorial with engineered typography, one business metaphor, and precise annotations.",
        density="low on key-message slides; medium on analytical slides",
        palette={
            "paper": "#F6F8FA",
            "ink": "#111827",
            "primary": "#243447",
            "accent": "#4F75A3",
            "muted": "#6B7280",
        },
        typography="Modern report sans-serif, reconstructed display words, micro labels, and precise hierarchy.",
        archetypes=(
            "typographic-statement",
            "matrix",
            "architecture",
            "process-ribbon",
            "claim-evidence",
        ),
        avoid=(
            "generic card grid",
            "icon rows",
            "large navy blocks",
            "orange-led palette",
            "multiple metaphors",
        ),
        css=r"""
.slide.style-mckinsey { --paper:#F6F8FA; --ink:#111827; --muted:#6B7280; --primary:#243447; --accent:#4F75A3; --line:#D8DEE8; background-color:#F6F8FA; background-image:linear-gradient(rgba(79,117,163,.10) 1px,transparent 1px),linear-gradient(90deg,rgba(79,117,163,.10) 1px,transparent 1px); background-size:80px 80px; }
.style-mckinsey .title { font-weight:620; letter-spacing:-.045em; }
.style-mckinsey .preset-display { color:transparent; -webkit-text-stroke:2px #243447; letter-spacing:-.08em; }
.style-mckinsey .preset-tag { padding:0; border:0; color:#4F75A3; }
.style-mckinsey .preset-panel { background:rgba(246,248,250,.88); border:1px solid #AAB8C8; }
.style-mckinsey .preset-note { border-left:2px solid #243447; background:rgba(255,255,255,.66); }
.style-mckinsey .preset-rule { height:1px; }
""",
    ),
    "party-government-red": HtmlStylePreset(
        id="party-government-red",
        name="Party and Government Red",
        best_for="Formal public-sector reports, policy communication, annual summaries, and institutional plans.",
        visual_direction="Solemn Chinese-red identity with warm ivory, restrained matte gold, and disciplined formal hierarchy.",
        density="medium and balanced",
        palette={
            "paper": "#FFF9F2",
            "ink": "#262626",
            "primary": "#C41E3A",
            "accent": "#D6A84B",
            "muted": "#5F514B",
        },
        typography="Large dignified Chinese/Latin sans-serif with formal alignment.",
        archetypes=(
            "editorial-hero",
            "process-ribbon",
            "claim-evidence",
            "metric-story",
            "closing",
        ),
        avoid=(
            "invented official symbols",
            "festival decoration",
            "glitter",
            "glossy gold",
            "cartoon styling",
        ),
        css=r"""
.slide.style-party-government-red { --paper:#FFF9F2; --ink:#262626; --muted:#5F514B; --primary:#C41E3A; --accent:#D6A84B; --line:rgba(158,21,48,.28); background:radial-gradient(circle at 88% 5%,rgba(214,168,75,.20),transparent 24%),linear-gradient(150deg,#FFF9F2 0 72%,#F5E5DD 100%); }
.style-party-government-red .title,.style-party-government-red .preset-display { color:#9E1530; }
.style-party-government-red .preset-tag { background:#C41E3A; color:#fff; border-color:#C41E3A; }
.style-party-government-red .preset-panel { background:#fff; border:1px solid rgba(158,21,48,.25); border-top:6px solid #C41E3A; }
.style-party-government-red .preset-note { color:#9E1530; background:#FFF0E7; border-color:#D6A84B; }
.style-party-government-red .eyebrow-rule { background:#D6A84B; }
""",
    ),
    "teaching-courseware": HtmlStylePreset(
        id="teaching-courseware",
        name="Teaching Courseware",
        best_for="University courses, technical training, concept explanation, cases, and learning synthesis.",
        visual_direction="Credible academic courseware with a clear teaching sequence and content-appropriate evidence.",
        density="medium with strong instructional grouping",
        palette={
            "paper": "#FFFFFF",
            "ink": "#1F2937",
            "primary": "#0B2E6D",
            "accent": "#1769AA",
            "muted": "#4B5563",
        },
        typography="Clear academic sans-serif with explicit hierarchy for concepts, evidence, and takeaways.",
        archetypes=(
            "claim-evidence",
            "process-ribbon",
            "comparison",
            "architecture",
            "evidence-grid",
        ),
        avoid=(
            "text-only pages",
            "repeated three-column cards",
            "generic AI imagery",
            "playful stickers",
            "heavy shadows",
        ),
        css=r"""
.slide.style-teaching-courseware { --paper:#FFFFFF; --ink:#1F2937; --muted:#4B5563; --primary:#0B2E6D; --accent:#1769AA; --line:#D7E0EA; background:linear-gradient(180deg,#EAF3FB 0 16px,#fff 16px); }
.style-teaching-courseware .title { color:#0B2E6D; font-size:56px; }
.style-teaching-courseware .preset-tag { background:#0B2E6D; color:#fff; border-color:#0B2E6D; }
.style-teaching-courseware .preset-panel,.style-teaching-courseware .panel { background:#F7FAFD; border:1px solid #D7E0EA; }
.style-teaching-courseware .preset-panel h3 { color:#1769AA; }
.style-teaching-courseware .preset-note { background:#EAF3FB; color:#0B2E6D; border-color:#1769AA; }
""",
    ),
}


LAYOUT_ARCHETYPES: dict[str, dict[str, Any]] = {
    "editorial-hero": {
        "use_for": "cover, section divider, or image-led key message",
        "composition": "40/60 or 55/45 split with one dominant title and one visual field",
        "skeleton": '<div class="safe hero"><section data-box>...title...</section><figure class="preset-stage" data-box>...visual...</figure></div>',
    },
    "hero-split": {
        "use_for": "cover or high-level proposition",
        "composition": "asymmetric hero with concise claim, supporting sentence, and one CSS/SVG visual",
        "skeleton": '<div class="safe hero"><div data-box>...claim...</div><div class="preset-stage" data-box>...diagram...</div></div>',
    },
    "typographic-statement": {
        "use_for": "key message or section divider",
        "composition": "small complete claim plus one oversized engineered core word and sparse annotations",
        "skeleton": '<div class="safe"><p class="preset-tag">...</p><h1 class="preset-display" data-box>...</h1><div class="preset-note" data-box>...</div></div>',
    },
    "claim-evidence": {
        "use_for": "argument, recommendation, or evidence explanation",
        "composition": "takeaway title over one primary evidence field and one implication rail",
        "skeleton": '<div class="safe"><h1 class="title">...</h1><div class="split"><section class="preset-stage" data-box>...evidence...</section><aside class="preset-note" data-box>...meaning...</aside></div></div>',
    },
    "process-ribbon": {
        "use_for": "process, roadmap, chronology, or causal chain",
        "composition": "single left-to-right reading path with 3-6 stages; connectors remain behind nodes",
        "skeleton": '<div class="safe"><h1 class="title">...</h1><div class="process">...step nodes...</div></div>',
    },
    "comparison": {
        "use_for": "before/after, option comparison, or paired concepts",
        "composition": "two contrasting fields with one explicit comparison axis and one synthesis",
        "skeleton": '<div class="safe"><h1 class="title">...</h1><div class="split"><section data-box>...A...</section><section data-box>...B...</section></div><div class="preset-note" data-box>...synthesis...</div></div>',
    },
    "metric-story": {
        "use_for": "one major metric with supporting context",
        "composition": "one oversized number, one visual trend/evidence area, and concise interpretation",
        "skeleton": '<div class="safe hero"><section data-box><div class="preset-number">...</div>...meaning...</section><div class="preset-stage" data-box>...chart...</div></div>',
    },
    "dashboard-grid": {
        "use_for": "genuinely multi-metric operational dashboard only",
        "composition": "3-4 KPI strip plus one dominant chart and one secondary evidence area",
        "skeleton": '<div class="safe"><h1 class="title">...</h1><div class="preset-grid">...KPI strip + dominant chart...</div></div>',
    },
    "matrix": {
        "use_for": "2x2, prioritization, positioning, or decision guide",
        "composition": "one dominant coordinate field with 2-4 plotted items and a narrow methodology rail",
        "skeleton": '<div class="safe"><h1 class="title">...</h1><div class="split"><div class="preset-stage" data-box>...axes...</div><aside data-box>...legend...</aside></div></div>',
    },
    "architecture": {
        "use_for": "system, operating model, technical architecture, or concept map",
        "composition": "one dominant relationship diagram with concise labels and minimal side notes",
        "skeleton": '<div class="safe"><h1 class="title">...</h1><div class="preset-stage" data-box>...SVG/CSS diagram...</div></div>',
    },
    "concept-map": {
        "use_for": "teaching a single idea with surrounding annotations",
        "composition": "small central concept with 3-4 sparse notes and ample whitespace",
        "skeleton": '<div class="safe"><h1 class="title">...</h1><div class="preset-stage" data-box>...central node + notes...</div></div>',
    },
    "evidence-grid": {
        "use_for": "academic/source evidence, cases, figures, or experiments",
        "composition": "2-3 aligned evidence zones with captions and one explicit conclusion",
        "skeleton": '<div class="safe"><h1 class="title">...</h1><div class="three">...evidence...</div><div class="preset-note">...conclusion...</div></div>',
    },
    "closing": {
        "use_for": "recommendation, call to action, or synthesis",
        "composition": "one resolved statement, one next action, and one restrained visual conclusion",
        "skeleton": '<div class="safe hero"><section data-box>...resolved statement...</section><div class="preset-stage" data-box>...visual conclusion...</div></div>',
    },
}


def get_style_preset(style_id: str) -> HtmlStylePreset:
    try:
        return STYLE_PRESETS[style_id]
    except KeyError as exc:
        choices = ", ".join(sorted(STYLE_PRESETS))
        raise ValueError(
            f"unknown style_preset {style_id!r}; choose one of: {choices}"
        ) from exc


def style_catalog(style_id: str | None = None) -> dict[str, Any]:
    if style_id is not None:
        preset = get_style_preset(style_id)
        return {
            "selected_style": preset.to_catalog(),
            "layout_archetypes": {
                name: LAYOUT_ARCHETYPES[name]
                for name in preset.archetypes
                if name in LAYOUT_ARCHETYPES
            },
            "shared_classes": [
                "preset-tag",
                "preset-display",
                "preset-micro",
                "preset-stage",
                "preset-panel",
                "preset-note",
                "preset-number",
                "preset-rule",
                "preset-grid",
                "preset-axis",
            ],
        }
    return {
        "styles": [STYLE_PRESETS[name].to_catalog() for name in STYLE_PRESETS],
        "layout_archetype_ids": list(LAYOUT_ARCHETYPES),
        "selection_gate": {
            "must_confirm_with_user": True,
            "silent_default": None,
            "recommended_first_option": "scientific-defense",
            "recommended_by_job": {
                "research_or_thesis": "scientific-defense",
                "general_business": "clean-professional",
                "strategy_consulting": "mckinsey",
                "data_or_operations": "data-dashboard",
                "course_or_training": "teaching-courseware",
                "creative_editorial": "creative-magazine",
                "technical_explainer": "handdrawn-technical",
            },
        },
        "selection_rule": (
            "Ask the user to confirm one deck-level style before authoring, then vary "
            "slide archetypes by narrative role. Do not repeat the same silhouette "
            "on adjacent slides unless it is an intentional sequence."
        ),
    }


__all__ = [
    "COMMON_PRESET_CSS",
    "HtmlStylePreset",
    "LAYOUT_ARCHETYPES",
    "STYLE_PRESETS",
    "get_style_preset",
    "style_catalog",
]
