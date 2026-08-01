"""Deterministic, editable-first HTML templates for presentation slides."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape
import json
from typing import Any


MAX_TEMPLATE_CONTENT_CHARS = 80_000


EDITABLE_TEMPLATE_CSS = r"""
.tpl-safe { position:absolute; inset:64px 84px; }
.tpl-kicker { margin:0 0 16px; color:var(--primary); font-size:20px; line-height:1.1; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.tpl-title { margin:0; max-width:1320px; font-family:var(--font-display); font-size:58px; line-height:1.04; letter-spacing:-.035em; font-weight:760; }
.tpl-subtitle { margin:20px 0 0; max-width:1080px; color:var(--muted); font-size:26px; line-height:1.34; }
.tpl-label { margin:0; color:var(--muted); font-size:18px; line-height:1.2; font-weight:760; letter-spacing:.055em; text-transform:uppercase; }
.tpl-body { margin:0; color:var(--muted); font-size:21px; line-height:1.38; }
.tpl-card { border:1.5px solid var(--line); border-radius:16px; background:rgba(255,255,255,.86); }
.tpl-cover-side { position:absolute; right:84px; top:145px; width:440px; height:520px; padding:42px; border:2px solid var(--primary); border-radius:22px; background:rgba(255,255,255,.9); }
.tpl-cover-value { margin:72px 0 14px; color:var(--primary); font-family:var(--font-display); font-size:92px; line-height:.9; font-weight:800; letter-spacing:-.055em; }
.tpl-section-number { position:absolute; right:84px; top:95px; color:var(--accent); font-family:var(--font-display); font-size:190px; line-height:.8; font-weight:800; opacity:.18; }
.tpl-statement { position:absolute; left:84px; right:84px; top:185px; }
.tpl-statement .tpl-title { max-width:1450px; font-size:78px; line-height:1; }
.tpl-evidence { position:absolute; left:84px; bottom:92px; width:680px; padding-top:18px; border-top:4px solid var(--accent); }
.tpl-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:26px; margin-top:48px; }
.tpl-metric { min-height:220px; padding:28px; }
.tpl-metric-value { margin:30px 0 10px; color:var(--primary); font-family:var(--font-display); font-size:68px; line-height:.9; font-weight:800; letter-spacing:-.04em; }
.tpl-insight { margin-top:28px; padding:20px 26px; border-left:6px solid var(--accent); background:rgba(255,255,255,.58); }
.tpl-process { display:flex; align-items:center; margin-top:54px; }
.tpl-step { flex:1 1 0; min-height:260px; padding:28px; }
.tpl-step h2 { margin:30px 0 12px; font-size:29px; line-height:1.1; }
.tpl-connector { flex:0 0 44px; height:5px; background:var(--accent); }
.tpl-comparison { display:grid; grid-template-columns:1fr 1fr; gap:42px; margin-top:46px; }
.tpl-side { min-height:420px; padding:34px; }
.tpl-side h2 { margin:16px 0 26px; font-size:34px; }
.tpl-side p { margin:0 0 18px; font-size:21px; line-height:1.35; }
.tpl-timeline { position:relative; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:26px; margin-top:80px; }
.tpl-timeline-line { position:absolute; left:6%; right:6%; top:31px; height:5px; background:var(--primary); }
.tpl-event { position:relative; padding-top:72px; }
.tpl-event-dot { position:absolute; left:20px; top:11px; width:44px; height:44px; border:5px solid var(--primary); border-radius:50%; background:var(--paper); }
.tpl-event h2 { margin:10px 0 10px; font-size:26px; }
.tpl-architecture { width:980px; margin:42px auto 0; }
.tpl-layer { min-height:88px; padding:20px 28px; display:flex; align-items:center; justify-content:space-between; }
.tpl-layer h2 { margin:0; font-size:27px; }
.tpl-layer p { margin:0; max-width:650px; text-align:right; }
.tpl-layer-link { width:5px; height:22px; margin:0 auto; background:var(--accent); }
.tpl-matrix { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-top:38px; }
.tpl-quadrant { min-height:205px; padding:26px 30px; }
.tpl-quadrant h2 { margin:10px 0 10px; font-size:29px; }
.tpl-bars { margin-top:42px; display:flex; flex-direction:column; gap:20px; }
.tpl-bar-row { display:grid; grid-template-columns:230px 1fr 110px; gap:18px; align-items:center; }
.tpl-bar-track { position:relative; height:38px; border:1px solid var(--line); border-radius:8px; background:rgba(255,255,255,.62); }
.tpl-bar-fill { position:absolute; left:0; top:0; bottom:0; border-radius:7px; background:var(--primary); }
.tpl-bar-value { margin:0; color:var(--ink); font-size:24px; font-weight:780; text-align:right; }
.tpl-table { display:grid; gap:8px; margin-top:38px; }
.tpl-cell { min-height:64px; padding:16px 18px; border:1px solid var(--line); border-radius:8px; background:rgba(255,255,255,.82); }
.tpl-cell.header { border-color:var(--primary); background:var(--primary); }
.tpl-cell p { margin:0; font-size:19px; line-height:1.25; }
.tpl-cell.header p { color:white; font-weight:760; }
.tpl-quote-mark { position:absolute; left:74px; top:115px; color:var(--accent); font-family:Georgia,serif; font-size:210px; line-height:.7; opacity:.25; }
.tpl-quote { position:absolute; left:190px; right:140px; top:185px; margin:0; font-family:var(--font-display); font-size:56px; line-height:1.16; letter-spacing:-.025em; }
.tpl-attribution { position:absolute; left:195px; bottom:125px; }
.tpl-image-frame { position:absolute; right:84px; top:160px; width:650px; height:570px; object-fit:cover; border-radius:20px; }
.tpl-image-copy { position:absolute; left:84px; top:150px; width:690px; }
.tpl-image-copy .tpl-title { font-size:54px; }
.tpl-caption { position:absolute; right:84px; bottom:80px; width:650px; margin:0; color:var(--muted); font-size:18px; }
.tpl-actions { display:flex; gap:24px; margin-top:55px; }
.tpl-action { flex:1 1 0; min-height:150px; padding:25px; }
.tpl-action h2 { margin:14px 0 0; font-size:27px; }
.tpl-research-header { padding-bottom:16px; border-bottom:4px solid var(--primary); }
.tpl-research-header .tpl-title { font-size:48px; }
.tpl-research-number { display:flex; align-items:center; justify-content:center; flex:0 0 42px; width:42px; height:42px; border-radius:50%; background:var(--primary); color:white; font-size:21px; font-weight:800; }
.tpl-research-number p { margin:0; color:white; font-size:21px; line-height:1; font-weight:800; text-align:center; }
.tpl-research-takeaway { display:flex; align-items:center; gap:18px; min-height:68px; padding:14px 22px; border:1.5px solid var(--line); background:rgba(237,244,252,.78); color:var(--primary); }
.tpl-research-takeaway p { margin:0; font-size:22px; line-height:1.25; font-weight:720; }
.tpl-research-emphasis { color:var(--accent); font-weight:800; }
.tpl-research-overview { display:grid; grid-template-columns:.82fr 1.18fr; gap:28px; margin-top:24px; }
.tpl-research-paper { min-height:355px; padding:26px; }
.tpl-research-paper h2 { margin:16px 0 12px; color:var(--primary); font-size:28px; }
.tpl-research-diagram { display:flex; flex-direction:column; justify-content:center; gap:10px; min-height:355px; padding:24px; }
.tpl-research-diagram-node { display:flex; align-items:center; justify-content:space-between; min-height:56px; padding:12px 18px; }
.tpl-research-diagram-node h3 { margin:0; font-size:21px; }
.tpl-research-diagram-node p { margin:0; max-width:420px; text-align:right; font-size:17px; line-height:1.22; }
.tpl-research-contribs { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; margin-top:18px; }
.tpl-research-contrib { min-height:125px; padding:18px 20px; }
.tpl-research-contrib h3 { margin:10px 0 0; font-size:22px; line-height:1.15; }
.tpl-research-chain { display:grid; grid-template-columns:260px 1fr 330px; gap:22px; margin-top:24px; }
.tpl-research-chain-column { display:flex; flex-direction:column; gap:14px; }
.tpl-research-chain-card { display:flex; gap:14px; min-height:92px; padding:15px; }
.tpl-research-chain-card h3 { margin:0 0 6px; font-size:21px; color:var(--primary); }
.tpl-research-chain-card p { margin:0; font-size:17px; line-height:1.25; }
.tpl-research-evidence-card { min-height:145px; padding:18px 20px; }
.tpl-research-evidence-card h3 { margin:10px 0 8px; font-size:23px; color:var(--primary); }
.tpl-research-conclusion { min-height:304px; padding:24px; border:2px solid var(--primary); }
.tpl-research-conclusion h2 { margin:18px 0; font-size:29px; line-height:1.12; color:var(--accent); }
.tpl-research-grid3 { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; margin-top:24px; }
.tpl-research-column { min-height:390px; padding:22px; }
.tpl-research-column h2 { margin:14px 0; color:var(--primary); font-size:26px; }
.tpl-research-column p { margin:0 0 13px; font-size:18px; line-height:1.3; }
.tpl-research-architecture { display:grid; grid-template-columns:1.08fr .92fr; gap:28px; margin-top:22px; }
.tpl-research-layers { display:flex; flex-direction:column; gap:8px; padding:20px; }
.tpl-research-layer { min-height:61px; padding:13px 18px; display:flex; align-items:center; justify-content:space-between; }
.tpl-research-layer h3 { margin:0; font-size:22px; color:var(--primary); }
.tpl-research-layer p { margin:0; max-width:410px; text-align:right; font-size:17px; }
.tpl-research-annotations { display:flex; flex-direction:column; gap:10px; }
.tpl-research-annotation { display:flex; gap:14px; min-height:78px; padding:13px 15px; }
.tpl-research-annotation h3 { margin:0 0 5px; color:var(--primary); font-size:20px; }
.tpl-research-annotation p { margin:0; font-size:16px; line-height:1.22; }
.tpl-research-mechanism { display:grid; grid-template-columns:1fr 1fr 310px; gap:20px; margin-top:22px; }
.tpl-research-mechanism-panel { min-height:395px; padding:20px; }
.tpl-research-mechanism-panel h2 { margin:12px 0 18px; color:var(--primary); font-size:25px; }
.tpl-research-step-row { display:flex; align-items:center; gap:10px; margin-bottom:12px; }
.tpl-research-step-box { flex:1 1 0; min-height:58px; padding:13px 15px; text-align:center; font-size:18px; font-weight:700; }
.tpl-research-step-line { flex:0 0 18px; height:4px; background:var(--accent); }
.tpl-research-explain { min-height:395px; padding:20px; }
.tpl-research-explain p { margin:0 0 17px; font-size:17px; line-height:1.28; }
.tpl-research-equation-layout { display:grid; grid-template-columns:1.18fr .82fr; gap:26px; margin-top:24px; }
.tpl-research-equations { display:flex; flex-direction:column; gap:18px; }
.tpl-research-equation { min-height:145px; padding:20px 24px; }
.tpl-research-formula { margin:18px 0 10px; color:var(--primary); font-family:Georgia,"Times New Roman",serif; font-size:34px; line-height:1.12; text-align:center; }
.tpl-research-terms { min-height:308px; padding:20px; }
.tpl-research-term { display:flex; gap:14px; margin-bottom:14px; }
.tpl-research-term h3 { margin:0 0 4px; color:var(--primary); font-size:20px; }
.tpl-research-term p { margin:0; font-size:16px; line-height:1.2; }
.tpl-research-results-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; margin-top:22px; }
.tpl-research-result-metric { min-height:122px; padding:17px 20px; text-align:center; }
.tpl-research-result-value { margin:12px 0 5px; color:var(--primary); font-size:48px; line-height:.9; font-weight:820; }
.tpl-research-results-table { display:grid; gap:6px; margin-top:18px; }
.tpl-research-results-table .tpl-cell { min-height:48px; padding:11px 14px; }
.tpl-research-results-table .tpl-cell p { font-size:16px; }
"""


@dataclass(frozen=True)
class EditableBaseTemplate:
    id: str
    name: str
    kind: str
    description: str
    best_for: tuple[str, ...]
    editable_features: tuple[str, ...]
    content_schema: dict[str, Any]
    renderer: Callable[[str, dict[str, Any]], str]
    style_affinity: tuple[str, ...] = ()

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "best_for": list(self.best_for),
            "editable_features": list(self.editable_features),
            "content_schema": self.content_schema,
            "style_affinity": list(self.style_affinity),
        }


def _value(content: dict[str, Any], key: str, default: str = "") -> str:
    raw = content.get(key, default)
    if not isinstance(raw, str):
        raise ValueError(f"template content.{key} must be a string")
    if len(raw) > 1_000:
        raise ValueError(f"template content.{key} is too long")
    return escape(raw)


def _items(
    content: dict[str, Any], key: str, *, minimum: int, maximum: int
) -> list[dict[str, Any]]:
    raw = content.get(key)
    if not isinstance(raw, list) or not minimum <= len(raw) <= maximum:
        raise ValueError(
            f"template content.{key} must contain {minimum}–{maximum} items"
        )
    if not all(isinstance(item, dict) for item in raw):
        raise ValueError(f"template content.{key} items must be objects")
    return raw


def _check_content(content: dict[str, Any], allowed: set[str]) -> None:
    if len(json.dumps(content, ensure_ascii=False)) > MAX_TEMPLATE_CONTENT_CHARS:
        raise ValueError("template content is too large")
    unknown = sorted(set(content) - allowed)
    if unknown:
        raise ValueError(f"unsupported template content fields: {', '.join(unknown)}")


def _header(title: str, content: dict[str, Any]) -> str:
    kicker = _value(content, "kicker", "")
    subtitle = _value(content, "subtitle", "")
    return (
        f'<p class="tpl-kicker">{kicker}</p>'
        f'<h1 class="tpl-title" data-pptx-role="title">{escape(title)}</h1>'
        + (f'<p class="tpl-subtitle">{subtitle}</p>' if subtitle else "")
    )


def _cover_split(title: str, content: dict[str, Any]) -> str:
    _check_content(
        content, {"kicker", "subtitle", "side_label", "side_value", "side_note"}
    )
    return (
        f'<div class="tpl-safe" style="width:850px;right:auto;display:flex;flex-direction:column;justify-content:center">{_header(title, content)}</div>'
        f'<div class="tpl-cover-side" data-box data-pptx-shape="roundRect"><p class="tpl-label">{_value(content, "side_label")}</p>'
        f'<p class="tpl-cover-value">{_value(content, "side_value")}</p><p class="tpl-body">{_value(content, "side_note")}</p></div>'
    )


def _section_divider(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "section"})
    return (
        f'<div class="tpl-section-number" data-pptx-native="text">{_value(content, "section", "01")}</div>'
        f'<div class="tpl-safe" style="width:1050px;right:auto;display:flex;flex-direction:column;justify-content:center">{_header(title, content)}</div>'
    )


def _statement(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "support", "evidence"})
    support = _value(content, "support")
    return (
        f'<div class="tpl-statement"><p class="tpl-kicker">{_value(content, "kicker")}</p><h1 class="tpl-title" data-pptx-role="title">{escape(title)}</h1>'
        f'<p class="tpl-subtitle">{support}</p></div><div class="tpl-evidence"><p class="tpl-label">Evidence</p><p class="tpl-body">{_value(content, "evidence")}</p></div>'
    )


def _metric_story(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "metrics", "insight"})
    metrics = _items(content, "metrics", minimum=2, maximum=4)
    cards = "".join(
        '<div class="tpl-card tpl-metric" data-box data-pptx-shape="roundRect">'
        f'<p class="tpl-label">{_value(item, "label")}</p><p class="tpl-metric-value">{_value(item, "value")}</p><p class="tpl-body">{_value(item, "detail")}</p></div>'
        for item in metrics
    )
    return (
        f'<div class="tpl-safe">{_header(title, content)}<div class="tpl-metrics" style="grid-template-columns:repeat({len(metrics)},minmax(0,1fr))">{cards}</div>'
        f'<div class="tpl-insight"><p class="tpl-body">{_value(content, "insight")}</p></div></div>'
    )


def _process_flow(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "steps"})
    steps = _items(content, "steps", minimum=3, maximum=5)
    parts: list[str] = []
    for index, item in enumerate(steps):
        if index:
            parts.append('<div class="tpl-connector" data-pptx-native="line"></div>')
        parts.append(
            '<div class="tpl-card tpl-step" data-box data-pptx-shape="roundRect">'
            f'<p class="tpl-label">{index + 1:02d}</p><h2>{_value(item, "title")}</h2><p class="tpl-body">{_value(item, "body")}</p></div>'
        )
    return f'<div class="tpl-safe">{_header(title, content)}<div class="tpl-process">{"".join(parts)}</div></div>'


def _comparison(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "left", "right"})
    sides = []
    for key in ("left", "right"):
        item = content.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"template content.{key} must be an object")
        bullets = _items(item, "points", minimum=2, maximum=5)
        body = "".join(f"<p>• {_value(point, 'text')}</p>" for point in bullets)
        sides.append(
            '<div class="tpl-card tpl-side" data-box data-pptx-shape="roundRect">'
            f'<p class="tpl-label">{_value(item, "label")}</p><h2>{_value(item, "title")}</h2>{body}</div>'
        )
    return f'<div class="tpl-safe">{_header(title, content)}<div class="tpl-comparison">{"".join(sides)}</div></div>'


def _timeline(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "events"})
    events = _items(content, "events", minimum=3, maximum=5)
    rendered = "".join(
        '<div class="tpl-event"><div class="tpl-event-dot" data-box data-pptx-shape="ellipse"></div>'
        f'<p class="tpl-label">{_value(item, "when")}</p><h2>{_value(item, "title")}</h2><p class="tpl-body">{_value(item, "body")}</p></div>'
        for item in events
    )
    return (
        f'<div class="tpl-safe">{_header(title, content)}<div class="tpl-timeline" style="grid-template-columns:repeat({len(events)},minmax(0,1fr))">'
        f'<div class="tpl-timeline-line" data-pptx-native="line"></div>{rendered}</div></div>'
    )


def _architecture(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "layers"})
    layers = _items(content, "layers", minimum=3, maximum=5)
    parts: list[str] = []
    for index, item in enumerate(layers):
        if index:
            parts.append('<div class="tpl-layer-link" data-pptx-native="line"></div>')
        parts.append(
            '<div class="tpl-card tpl-layer" data-box data-pptx-shape="roundRect">'
            f'<h2>{_value(item, "title")}</h2><p class="tpl-body">{_value(item, "body")}</p></div>'
        )
    return f'<div class="tpl-safe">{_header(title, content)}<div class="tpl-architecture">{"".join(parts)}</div></div>'


def _matrix(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "quadrants"})
    quadrants = _items(content, "quadrants", minimum=4, maximum=4)
    rendered = "".join(
        '<div class="tpl-card tpl-quadrant" data-box data-pptx-shape="roundRect">'
        f'<p class="tpl-label">{_value(item, "label")}</p><h2>{_value(item, "title")}</h2><p class="tpl-body">{_value(item, "body")}</p></div>'
        for item in quadrants
    )
    return f'<div class="tpl-safe">{_header(title, content)}<div class="tpl-matrix">{rendered}</div></div>'


def _bar_chart(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "series", "unit"})
    series = _items(content, "series", minimum=3, maximum=7)
    values: list[float] = []
    for item in series:
        value = item.get("value")
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError("bar chart values must be non-negative numbers")
        values.append(float(value))
    maximum = max(values) or 1
    unit = _value(content, "unit")
    rows = "".join(
        '<div class="tpl-bar-row">'
        f'<p class="tpl-body">{_value(item, "label")}</p><div class="tpl-bar-track" data-box data-pptx-shape="roundRect"><div class="tpl-bar-fill" data-box data-pptx-shape="roundRect" style="width:{value / maximum * 100:.2f}%"></div></div>'
        f'<p class="tpl-bar-value">{value:g}{unit}</p></div>'
        for item, value in zip(series, values, strict=True)
    )
    return f'<div class="tpl-safe">{_header(title, content)}<div class="tpl-bars">{rows}</div></div>'


def _data_table(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "headers", "rows"})
    headers = content.get("headers")
    rows = content.get("rows")
    if (
        not isinstance(headers, list)
        or not 2 <= len(headers) <= 5
        or not all(isinstance(value, str) for value in headers)
    ):
        raise ValueError("table headers must contain 2–5 strings")
    if not isinstance(rows, list) or not 2 <= len(rows) <= 6:
        raise ValueError("table rows must contain 2–6 rows")
    cells: list[str] = []
    for value in headers:
        cells.append(
            f'<div class="tpl-cell header" data-box data-pptx-shape="roundRect"><p>{escape(value)}</p></div>'
        )
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != len(headers)
            or not all(isinstance(value, str) for value in row)
        ):
            raise ValueError(
                "every table row must match the header width and contain strings"
            )
        cells.extend(
            f'<div class="tpl-cell" data-box data-pptx-shape="roundRect"><p>{escape(value)}</p></div>'
            for value in row
        )
    return (
        f'<div class="tpl-safe">{_header(title, content)}<div class="tpl-table" data-qa-density="allow" style="grid-template-columns:repeat({len(headers)},minmax(0,1fr))">'
        f"{''.join(cells)}</div></div>"
    )


def _quote(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"quote", "attribution", "context"})
    return (
        '<div class="tpl-quote-mark" data-pptx-raster>“</div>'
        f'<blockquote class="tpl-quote">{_value(content, "quote", title)}</blockquote>'
        f'<div class="tpl-attribution"><p class="tpl-label">{_value(content, "attribution")}</p><p class="tpl-body">{_value(content, "context")}</p></div>'
    )


def _image_story(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "body", "image", "caption"})
    image = _value(content, "image")
    if not image:
        raise ValueError("template content.image is required")
    return (
        f'<div class="tpl-image-copy">{_header(title, content)}<p class="tpl-body" style="margin-top:34px">{_value(content, "body")}</p></div>'
        f'<img class="tpl-image-frame" data-pptx-native="image" src="{image}" alt=""><p class="tpl-caption">{_value(content, "caption")}</p>'
    )


def _closing(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "actions"})
    actions = _items(content, "actions", minimum=1, maximum=3)
    rendered = "".join(
        '<div class="tpl-card tpl-action" data-box data-pptx-shape="roundRect">'
        f'<p class="tpl-label">{index + 1:02d}</p><h2>{_value(item, "text")}</h2></div>'
        for index, item in enumerate(actions)
    )
    return f'<div class="tpl-safe" style="display:flex;flex-direction:column;justify-content:center">{_header(title, content)}<div class="tpl-actions">{rendered}</div></div>'


def _balanced_title(title: str, *, threshold: int = 56) -> str:
    if len(title) <= threshold or " " not in title:
        return escape(title)
    candidates = [index for index, char in enumerate(title) if char == " "]
    split_at = min(candidates, key=lambda index: abs(index - len(title) / 2))
    return f"{escape(title[:split_at])}<br>{escape(title[split_at + 1 :])}"


def _research_header(title: str, content: dict[str, Any]) -> str:
    kicker = _value(content, "kicker", "")
    subtitle = _value(content, "subtitle", "")
    return (
        '<div class="tpl-research-header">'
        f'<p class="tpl-kicker">{kicker}</p>'
        f'<h1 class="tpl-title" data-pptx-role="title">{_balanced_title(title)}</h1>'
        + (f'<p class="tpl-subtitle">{subtitle}</p>' if subtitle else "")
        + "</div>"
    )


def _research_takeaway(content: dict[str, Any]) -> str:
    return (
        '<div class="tpl-research-takeaway" data-box data-pptx-name="Research takeaway">'
        '<div class="tpl-research-number" data-box data-pptx-shape="ellipse" data-pptx-name="Takeaway marker"><p>→</p></div>'
        f"<p>{_value(content, 'takeaway')}</p></div>"
    )


def _research_paper_overview(title: str, content: dict[str, Any]) -> str:
    _check_content(
        content,
        {
            "kicker",
            "subtitle",
            "citation",
            "summary",
            "architecture",
            "contributions",
        },
    )
    architecture = _items(content, "architecture", minimum=3, maximum=5)
    contributions = _items(content, "contributions", minimum=3, maximum=3)
    nodes = "".join(
        '<div class="tpl-card tpl-research-diagram-node" data-box data-pptx-name="Architecture node">'
        f"<h3>{_value(item, 'title')}</h3><p>{_value(item, 'body')}</p></div>"
        for item in architecture
    )
    contribution_cards = "".join(
        '<div class="tpl-card tpl-research-contrib" data-box data-pptx-name="Research contribution">'
        f'<p class="tpl-label">{index + 1:02d}</p><h3>{_value(item, "title")}</h3></div>'
        for index, item in enumerate(contributions)
    )
    return (
        f'<div class="tpl-safe" data-qa-density="allow">{_research_header(title, content)}'
        '<div class="tpl-research-overview">'
        '<section class="tpl-card tpl-research-paper" data-box data-pptx-name="Paper summary">'
        f'<p class="tpl-label">Source</p><h2>{_value(content, "citation")}</h2>'
        f'<p class="tpl-body">{_value(content, "summary")}</p></section>'
        f'<section class="tpl-research-diagram" data-box data-pptx-name="Paper architecture">{nodes}</section>'
        f'</div><div class="tpl-research-contribs">{contribution_cards}</div></div>'
    )


def _research_problem_chain(title: str, content: dict[str, Any]) -> str:
    _check_content(
        content,
        {"kicker", "subtitle", "problems", "evidence", "conclusion", "takeaway"},
    )
    problems = _items(content, "problems", minimum=3, maximum=3)
    evidence = _items(content, "evidence", minimum=2, maximum=3)
    problem_cards = "".join(
        '<div class="tpl-card tpl-research-chain-card" data-box data-pptx-name="Problem step">'
        f'<div class="tpl-research-number" data-box data-pptx-shape="ellipse"><p>{index + 1}</p></div>'
        f"<div><h3>{_value(item, 'title')}</h3><p>{_value(item, 'body')}</p></div></div>"
        for index, item in enumerate(problems)
    )
    evidence_cards = "".join(
        '<div class="tpl-card tpl-research-evidence-card" data-box data-pptx-name="Evidence block">'
        f'<p class="tpl-label">{_value(item, "label")}</p><h3>{_value(item, "title")}</h3>'
        f'<p class="tpl-body">{_value(item, "body")}</p></div>'
        for item in evidence
    )
    return (
        f'<div class="tpl-safe" data-qa-density="allow">{_research_header(title, content)}'
        '<div class="tpl-research-chain">'
        f'<div class="tpl-research-chain-column">{problem_cards}</div>'
        f'<div class="tpl-research-chain-column">{evidence_cards}</div>'
        '<aside class="tpl-research-conclusion" data-box data-pptx-name="Research conclusion">'
        '<p class="tpl-label">Core question</p>'
        f'<h2>{_value(content, "conclusion")}</h2><p class="tpl-body">What must change?</p></aside>'
        f"</div>{_research_takeaway(content)}</div>"
    )


def _research_contribution_grid(title: str, content: dict[str, Any]) -> str:
    _check_content(content, {"kicker", "subtitle", "contributions", "takeaway"})
    contributions = _items(content, "contributions", minimum=3, maximum=3)
    columns = "".join(
        '<section class="tpl-card tpl-research-column" data-box data-pptx-name="Contribution evidence column">'
        f'<div class="tpl-research-number" data-box data-pptx-shape="ellipse"><p>{index + 1}</p></div>'
        f"<h2>{_value(item, 'title')}</h2><p>{_value(item, 'claim')}</p>"
        f'<p class="tpl-label">Evidence</p><p>{_value(item, "evidence")}</p></section>'
        for index, item in enumerate(contributions)
    )
    return (
        f'<div class="tpl-safe" data-qa-density="allow">{_research_header(title, content)}'
        f'<div class="tpl-research-grid3">{columns}</div>{_research_takeaway(content)}</div>'
    )


def _research_architecture_annotated(title: str, content: dict[str, Any]) -> str:
    _check_content(
        content,
        {"kicker", "subtitle", "layers", "annotations", "takeaway"},
    )
    layers = _items(content, "layers", minimum=3, maximum=5)
    annotations = _items(content, "annotations", minimum=3, maximum=4)
    layer_nodes = "".join(
        '<div class="tpl-card tpl-research-layer" data-box data-pptx-name="Architecture layer">'
        f"<h3>{_value(item, 'title')}</h3><p>{_value(item, 'body')}</p></div>"
        for item in layers
    )
    notes = "".join(
        '<div class="tpl-card tpl-research-annotation" data-box data-pptx-name="Architecture annotation">'
        f'<div class="tpl-research-number" data-box data-pptx-shape="ellipse"><p>{index + 1}</p></div>'
        f"<div><h3>{_value(item, 'title')}</h3><p>{_value(item, 'body')}</p></div></div>"
        for index, item in enumerate(annotations)
    )
    return (
        f'<div class="tpl-safe" data-qa-density="allow">{_research_header(title, content)}'
        '<div class="tpl-research-architecture">'
        f'<section class="tpl-research-layers" data-box data-pptx-name="Architecture diagram">{layer_nodes}</section>'
        f'<aside class="tpl-research-annotations">{notes}</aside>'
        f"</div>{_research_takeaway(content)}</div>"
    )


def _research_mechanism(title: str, content: dict[str, Any]) -> str:
    _check_content(
        content,
        {"kicker", "subtitle", "mechanisms", "explanations", "takeaway"},
    )
    mechanisms = _items(content, "mechanisms", minimum=2, maximum=2)
    explanations = _items(content, "explanations", minimum=3, maximum=4)
    mechanism_panels: list[str] = []
    for mechanism in mechanisms:
        steps = _items(mechanism, "steps", minimum=2, maximum=4)
        step_parts: list[str] = []
        for index, step in enumerate(steps):
            if index:
                step_parts.append(
                    '<div class="tpl-research-step-line" data-pptx-native="line"></div>'
                )
            step_parts.append(
                '<div class="tpl-card tpl-research-step-box" data-box data-pptx-name="Mechanism step">'
                f"{_value(step, 'text')}</div>"
            )
        mechanism_panels.append(
            '<section class="tpl-card tpl-research-mechanism-panel" data-box data-pptx-name="Mechanism panel">'
            f'<p class="tpl-label">{_value(mechanism, "label")}</p><h2>{_value(mechanism, "title")}</h2>'
            f'<div class="tpl-research-step-row">{"".join(step_parts)}</div>'
            f'<p class="tpl-body">{_value(mechanism, "body")}</p></section>'
        )
    explanation_points = "".join(
        f'<p><span class="tpl-research-emphasis">{index + 1}.</span> {_value(item, "text")}</p>'
        for index, item in enumerate(explanations)
    )
    return (
        f'<div class="tpl-safe" data-qa-density="allow">{_research_header(title, content)}'
        '<div class="tpl-research-mechanism">'
        f'{"".join(mechanism_panels)}<aside class="tpl-card tpl-research-explain" data-box data-pptx-name="Mechanism explanation">'
        f'<p class="tpl-label">Key explanation</p>{explanation_points}</aside>'
        f"</div>{_research_takeaway(content)}</div>"
    )


def _research_equation_explainer(title: str, content: dict[str, Any]) -> str:
    _check_content(
        content,
        {"kicker", "subtitle", "equations", "terms", "takeaway"},
    )
    equations = _items(content, "equations", minimum=1, maximum=2)
    terms = _items(content, "terms", minimum=3, maximum=5)
    equation_cards = "".join(
        '<section class="tpl-card tpl-research-equation" data-box data-pptx-name="Editable equation">'
        f'<p class="tpl-label">{_value(item, "label")}</p><p class="tpl-research-formula">{_value(item, "formula")}</p>'
        f'<p class="tpl-body">{_value(item, "meaning")}</p></section>'
        for item in equations
    )
    term_rows = "".join(
        '<div class="tpl-research-term">'
        f'<div class="tpl-research-number" data-box data-pptx-shape="ellipse"><p>{index + 1}</p></div>'
        f"<div><h3>{_value(item, 'term')}</h3><p>{_value(item, 'meaning')}</p></div></div>"
        for index, item in enumerate(terms)
    )
    return (
        f'<div class="tpl-safe" data-qa-density="allow">{_research_header(title, content)}'
        '<div class="tpl-research-equation-layout">'
        f'<div class="tpl-research-equations">{equation_cards}</div>'
        f'<aside class="tpl-card tpl-research-terms" data-box data-pptx-name="Equation terms">{term_rows}</aside>'
        f"</div>{_research_takeaway(content)}</div>"
    )


def _research_results_summary(title: str, content: dict[str, Any]) -> str:
    _check_content(
        content,
        {"kicker", "subtitle", "metrics", "headers", "rows", "takeaway"},
    )
    metrics = _items(content, "metrics", minimum=3, maximum=3)
    headers = content.get("headers")
    rows = content.get("rows")
    if (
        not isinstance(headers, list)
        or not 2 <= len(headers) <= 4
        or not all(isinstance(value, str) for value in headers)
    ):
        raise ValueError("research result headers must contain 2–4 strings")
    if not isinstance(rows, list) or not 2 <= len(rows) <= 4:
        raise ValueError("research result rows must contain 2–4 rows")
    metric_cards = "".join(
        '<div class="tpl-card tpl-research-result-metric" data-box data-pptx-name="Research metric">'
        f'<p class="tpl-label">{_value(item, "label")}</p><p class="tpl-research-result-value">{_value(item, "value")}</p>'
        f'<p class="tpl-body">{_value(item, "detail")}</p></div>'
        for item in metrics
    )
    cells = [
        f'<div class="tpl-cell header" data-box><p>{escape(value)}</p></div>'
        for value in headers
    ]
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != len(headers)
            or not all(isinstance(value, str) for value in row)
        ):
            raise ValueError("every research result row must match the headers")
        cells.extend(
            f'<div class="tpl-cell" data-box><p>{escape(value)}</p></div>'
            for value in row
        )
    return (
        f'<div class="tpl-safe" data-qa-density="allow">{_research_header(title, content)}'
        f'<div class="tpl-research-results-metrics">{metric_cards}</div>'
        f'<div class="tpl-research-results-table" style="grid-template-columns:repeat({len(headers)},minmax(0,1fr))">{"".join(cells)}</div>'
        f"{_research_takeaway(content)}</div>"
    )


def _schema(
    required: list[str], optional: list[str], repeating: str | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {"required": required, "optional": optional}
    if repeating:
        result["repeating_field"] = repeating
    return result


BASE_TEMPLATES: dict[str, EditableBaseTemplate] = {
    item.id: item
    for item in (
        EditableBaseTemplate(
            "cover-split",
            "Cover split",
            "cover",
            "Minimal cover with one proof-point panel.",
            ("opening", "proposal", "pitch"),
            ("text", "rounded shape"),
            _schema(["side_label", "side_value", "side_note"], ["kicker", "subtitle"]),
            _cover_split,
        ),
        EditableBaseTemplate(
            "section-divider",
            "Section divider",
            "content",
            "Strong chapter transition with oversized section number.",
            ("chapter break", "narrative transition"),
            ("text",),
            _schema(["section"], ["kicker", "subtitle"]),
            _section_divider,
        ),
        EditableBaseTemplate(
            "typographic-statement",
            "Typographic statement",
            "content",
            "One claim with a compact evidence anchor.",
            ("executive takeaway", "recommendation"),
            ("text", "line"),
            _schema(["support", "evidence"], ["kicker"]),
            _statement,
        ),
        EditableBaseTemplate(
            "metric-story",
            "Metric story",
            "data",
            "Two to four metrics tied to one implication.",
            ("KPI", "performance", "evidence"),
            ("text", "rounded shapes"),
            _schema(["metrics", "insight"], ["kicker", "subtitle"], "metrics: 2–4"),
            _metric_story,
        ),
        EditableBaseTemplate(
            "process-flow",
            "Process flow",
            "process",
            "Three to five stages with editable connectors.",
            ("workflow", "operating model", "method"),
            ("text", "rounded shapes", "lines"),
            _schema(["steps"], ["kicker", "subtitle"], "steps: 3–5"),
            _process_flow,
        ),
        EditableBaseTemplate(
            "comparison",
            "Comparison",
            "comparison",
            "Two balanced alternatives or states.",
            ("before/after", "option comparison", "trade-offs"),
            ("text", "rounded shapes"),
            _schema(["left", "right"], ["kicker", "subtitle"]),
            _comparison,
        ),
        EditableBaseTemplate(
            "timeline",
            "Timeline",
            "process",
            "Three to five milestones on a single time axis.",
            ("roadmap", "history", "delivery plan"),
            ("text", "ellipses", "line"),
            _schema(["events"], ["kicker", "subtitle"], "events: 3–5"),
            _timeline,
        ),
        EditableBaseTemplate(
            "architecture-layers",
            "Architecture layers",
            "architecture",
            "Stacked system layers with editable nodes and links.",
            ("architecture", "operating model", "capability stack"),
            ("text", "rounded shapes", "lines"),
            _schema(["layers"], ["kicker", "subtitle"], "layers: 3–5"),
            _architecture,
        ),
        EditableBaseTemplate(
            "decision-matrix",
            "Decision matrix",
            "comparison",
            "Four editable quadrants for a 2×2 decision frame.",
            ("prioritization", "portfolio", "risk/value"),
            ("text", "rounded shapes"),
            _schema(["quadrants"], ["kicker", "subtitle"], "quadrants: exactly 4"),
            _matrix,
        ),
        EditableBaseTemplate(
            "bar-chart",
            "Editable bar chart",
            "data",
            "Three to seven native bars with labels and values.",
            ("ranking", "category comparison", "progress"),
            ("text", "rounded shapes"),
            _schema(["series"], ["kicker", "subtitle", "unit"], "series: 3–7"),
            _bar_chart,
        ),
        EditableBaseTemplate(
            "data-table",
            "Editable data table",
            "data",
            "Compact 2–5 column table built from editable cells.",
            ("comparison table", "status", "plan"),
            ("text", "rounded shapes"),
            _schema(["headers", "rows"], ["kicker", "subtitle"]),
            _data_table,
        ),
        EditableBaseTemplate(
            "quote",
            "Quote",
            "content",
            "Editorial quote with attribution and context.",
            ("testimonial", "voice", "principle"),
            ("text",),
            _schema(["quote", "attribution"], ["context"]),
            _quote,
        ),
        EditableBaseTemplate(
            "image-story",
            "Image story",
            "content",
            "Text-led story paired with one movable image or SVG.",
            ("case study", "product", "visual evidence"),
            ("text", "picture"),
            _schema(["image", "body"], ["kicker", "subtitle", "caption"]),
            _image_story,
        ),
        EditableBaseTemplate(
            "closing-actions",
            "Closing actions",
            "closing",
            "Resolution slide with one to three explicit next actions.",
            ("decision", "next steps", "close"),
            ("text", "rounded shapes"),
            _schema(["actions"], ["kicker", "subtitle"], "actions: 1–3"),
            _closing,
        ),
        EditableBaseTemplate(
            "research-paper-overview",
            "Research paper overview",
            "architecture",
            "Paper identity, source summary, editable architecture stack, and three contribution anchors.",
            ("paper introduction", "literature review", "method overview"),
            ("text", "rectangular shapes"),
            _schema(
                ["citation", "summary", "architecture", "contributions"],
                ["kicker", "subtitle"],
                "architecture: 3–5; contributions: exactly 3",
            ),
            _research_paper_overview,
            ("scientific-defense", "teaching-courseware"),
        ),
        EditableBaseTemplate(
            "research-problem-chain",
            "Research problem chain",
            "process",
            "Three numbered limitations linked to evidence, a core question, and an objective ribbon.",
            ("research background", "problem framing", "motivation"),
            ("text", "rectangular shapes", "ellipses"),
            _schema(
                ["problems", "evidence", "conclusion", "takeaway"],
                ["kicker", "subtitle"],
                "problems: exactly 3; evidence: 2–3",
            ),
            _research_problem_chain,
            ("scientific-defense", "teaching-courseware"),
        ),
        EditableBaseTemplate(
            "research-contribution-grid",
            "Research contribution grid",
            "content",
            "Three disciplined evidence columns with numbered contributions and one synthesis.",
            ("paper contributions", "experiment findings", "novelty"),
            ("text", "rectangular shapes", "ellipses"),
            _schema(
                ["contributions", "takeaway"],
                ["kicker", "subtitle"],
                "contributions: exactly 3",
            ),
            _research_contribution_grid,
            ("scientific-defense",),
        ),
        EditableBaseTemplate(
            "research-architecture-annotated",
            "Annotated research architecture",
            "architecture",
            "Editable technical layer stack paired with three or four numbered explanations.",
            ("model architecture", "system stack", "method structure"),
            ("text", "rectangular shapes", "ellipses"),
            _schema(
                ["layers", "annotations", "takeaway"],
                ["kicker", "subtitle"],
                "layers: 3–5; annotations: 3–4",
            ),
            _research_architecture_annotated,
            ("scientific-defense", "teaching-courseware"),
        ),
        EditableBaseTemplate(
            "research-mechanism",
            "Research mechanism",
            "architecture",
            "Two editable mechanisms, ordered steps, an explanation rail, and a central conclusion.",
            ("algorithm explanation", "model mechanism", "technical comparison"),
            ("text", "rectangular shapes", "lines"),
            _schema(
                ["mechanisms", "explanations", "takeaway"],
                ["kicker", "subtitle"],
                "mechanisms: exactly 2; steps: 2–4 each; explanations: 3–4",
            ),
            _research_mechanism,
            ("scientific-defense", "handdrawn-technical"),
        ),
        EditableBaseTemplate(
            "research-equation-explainer",
            "Research equation explainer",
            "content",
            "One or two editable equations with a compact term-by-term interpretation rail.",
            ("formula explanation", "method derivation", "technical teaching"),
            ("text", "rectangular shapes", "ellipses"),
            _schema(
                ["equations", "terms", "takeaway"],
                ["kicker", "subtitle"],
                "equations: 1–2; terms: 3–5",
            ),
            _research_equation_explainer,
            ("scientific-defense", "teaching-courseware"),
        ),
        EditableBaseTemplate(
            "research-results-summary",
            "Research results summary",
            "data",
            "Three headline results above an editable comparison table and evidence-based takeaway.",
            ("experiment results", "benchmark", "research conclusion"),
            ("text", "rectangular shapes", "editable cells"),
            _schema(
                ["metrics", "headers", "rows", "takeaway"],
                ["kicker", "subtitle"],
                "metrics: exactly 3; headers: 2–4; rows: 2–4",
            ),
            _research_results_summary,
            ("scientific-defense", "data-dashboard"),
        ),
    )
}


def get_base_template(template_id: str) -> EditableBaseTemplate:
    try:
        return BASE_TEMPLATES[template_id]
    except KeyError as exc:
        choices = ", ".join(BASE_TEMPLATES)
        raise ValueError(
            f"unknown base template '{template_id}'; choose one of: {choices}"
        ) from exc


def render_base_template(template_id: str, title: str, content: dict[str, Any]) -> str:
    template = get_base_template(template_id)
    return template.renderer(title, content)


def template_catalog(template_id: str | None = None) -> dict[str, Any]:
    if template_id is not None:
        return {"selected_template": get_base_template(template_id).catalog_entry()}
    return {
        "templates": [template.catalog_entry() for template in BASE_TEMPLATES.values()],
        "families": {
            "general": 14,
            "scientific_research": {
                "count": 7,
                "recommended_style": "scientific-defense",
                "templates": [
                    template.id
                    for template in BASE_TEMPLATES.values()
                    if "scientific-defense" in template.style_affinity
                ],
            },
        },
        "authoring": {
            "slide_contract": "Set template + content instead of html.",
            "editability": "Templates use semantic text and native shape/image markers; use editable_mode=max.",
            "fallback": "Use raw html only when no base template fits the narrative job.",
        },
    }


__all__ = [
    "BASE_TEMPLATES",
    "EDITABLE_TEMPLATE_CSS",
    "EditableBaseTemplate",
    "get_base_template",
    "render_base_template",
    "template_catalog",
]
